"""
Clipper Stage 5 — SUBTITLE sebagai LAPISAN PNG (bukan ASS/libass lagi).

Kenapa modul ini ada
--------------------
Headline dan watermark sudah digambar `stages/text_engine.py`, jadi preview dan hasil
render literal gambar yang sama. Subtitle masih ketinggalan: ia digambar libass lewat
file .ass, sementara preview menggambarnya dengan CSS. Itu artinya subtitle TIDAK
punya jaminan "preview == output", dan perbedaannya nyata:

- libass `Outline` bukan piksel: dengan `ScaledBorderAndShadow: yes` ketebalannya
  diskalakan relatif PlayRes, sedangkan preview memakai `-webkit-text-stroke` yang
  selalu terpusat di tepi glyph (jadi separuh tebalnya "masuk" ke dalam huruf).
- Shadow libass = offset tanpa blur dan selalu satu warna, tidak bisa ditumpuk
  sebagai lapisan sendiri. Panel Shadow (geser X/Y, blur, warna, urutan lapisan)
  yang sudah ada untuk headline mustahil dipakai subtitle.
- Pemecahan baris libass memakai pengukur font sendiri, bukan pengukur yang dipakai
  auto-fit. Titik pecah baris tidak pernah persis sama.
- Perataan libass lewat `\\an` + margin, bukan zona 7% yang dipakai elemen lain.

Cara kerja
----------
Tiap potongan waktu subtitle digambar jadi satu PNG RGBA seukuran kanvas oleh
`text_engine.render_block()` — fungsi yang sama dengan headline/watermark dan
preview. Deretan PNG itu disusun sebagai SATU input ffmpeg lewat concat demuxer
(`file`/`duration`), lalu di-overlay ke video. Celah antar subtitle diisi PNG
transparan.

    [1:v] video ... -> [framed]
    -f concat -i list.txt  ->  [sub]
    [framed][sub]overlay=0:0

Animasi
-------
- none                : satu lapisan statis sepanjang durasi entri.
- pop / fade / up      : lapisan dasar ditransformasi per langkah (skala / opasitas /
                        geser Y) memakai operasi PIL murni — tidak menggambar teks
                        ulang, jadi murah.
- word / karaoke       : satu lapisan per kata aktif. Kata aktif diberi warna
                        `active_color` dan (mode word) skala `active_scale`, sisanya
                        `inactive_scale`. Ini digambar `text_engine` lewat `word_specs`,
                        jadi preview bisa meminta gambar yang sama persis.

Biaya terukur (klip 137s, 106 entri, kanvas 1080x1920): 3.4s untuk 106 lapisan,
~10 MB PNG di folder temp. Lapisan identik di-cache berdasar hash parameter, jadi
teks yang berulang tidak digambar dua kali.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

from PIL import Image

try:  # dipakai sebagai modul paket (stages.subtitle_engine)
    from . import text_engine as TE
except ImportError:  # dipakai sebagai skrip (sys.path berisi folder stages/)
    import text_engine as TE


# Animasi masuk (pop/fade/up) dibagi jadi beberapa langkah gambar. 6 langkah pada
# ~180ms sudah terlihat mulus di 30fps tanpa membanjiri disk dengan PNG.
ANIM_STEPS = 6
ANIM_DURATION = 0.18
# Pergeseran awal animasi "up" (piksel pada kanvas 1080x1920, diskalakan ke kanvas lain).
UP_TRAVEL = 30


def _sig(*parts: Any) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]


def _transform(base: Image.Image, *, kind: str, t: float, canvas_h: int) -> Image.Image:
    """
    Terapkan animasi masuk pada LAPISAN yang sudah digambar (tanpa menggambar teks ulang).

    t: 0..1 progres animasi (1 = posisi/ukuran akhir).
    pop  : skala 0.80 -> 1.00, dipusatkan pada bounding box tinta supaya teks tidak
           bergeser ke sudut kanvas saat mengecil.
    fade : opasitas 0 -> 1.
    up   : digeser dari UP_TRAVEL px di bawah posisi akhir, sekaligus fade.
    """
    t = max(0.0, min(1.0, float(t)))
    if kind == "fade":
        out = base.copy()
        out.putalpha(base.split()[3].point(lambda a: int(a * t)))
        return out

    if kind == "up":
        dy = int(round(UP_TRAVEL * (canvas_h / 1920.0) * (1.0 - t)))
        out = Image.new("RGBA", base.size, (0, 0, 0, 0))
        out.paste(base, (0, dy))
        if t < 1.0:
            out.putalpha(out.split()[3].point(lambda a: int(a * t)))
        return out

    if kind == "pop":
        s = 0.80 + 0.20 * t
        if s >= 0.999:
            return base
        bbox = base.getbbox()
        if not bbox:
            return base
        cx = (bbox[0] + bbox[2]) / 2.0
        cy = (bbox[1] + bbox[3]) / 2.0
        w, h = base.size
        small = base.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)
        out = Image.new("RGBA", base.size, (0, 0, 0, 0))
        # titik pusat tinta harus tetap di tempatnya setelah diperkecil
        out.paste(small, (int(round(cx - cx * s)), int(round(cy - cy * s))))
        return out

    return base


def word_specs_for(
    words: list[str],
    active_index: int,
    *,
    color: str,
    active_color: str,
    inactive_scale: float,
    active_scale: float,
    colorize_only: bool,
) -> list[dict]:
    """
    Bangun spec per kata untuk satu momen (kata ke-`active_index` sedang aktif).

    colorize_only=True (karaoke): hanya warna yang berubah, ukuran tetap.
    colorize_only=False (word)   : warna + skala (kesan pop per kata).
    """
    out: list[dict] = []
    for i, w in enumerate(words):
        act = (i == active_index)
        out.append({
            "t": w,
            "color": (active_color if act else color),
            "scale": 1.0 if colorize_only else (active_scale if act else inactive_scale),
        })
    return out


def subtitle_block(sub: dict[str, Any]) -> dict[str, Any]:
    """
    Ubah `preset.subtitle` menjadi blok yang dimengerti `text_engine.render_block`.

    Subtitle memakai kunci yang sama dengan headline/watermark supaya SEMUA elemen
    teks lewat jalur kode yang identik. Nilai `x` diisi base (45 pada kanvas 1080)
    kalau preset tidak punya, artinya tanpa geseran halus.
    """
    blk = dict(sub)
    blk.setdefault("align", "center")
    blk.setdefault("max_lines", 2)
    blk.setdefault("line_spacing", -0.15)
    # Skema shadow lama subtitle: satu angka = offset x DAN y, warna hitam.
    if "shadow_x" not in blk and "shadow_y" not in blk:
        legacy = int(blk.get("shadow", 0) or 0)
        blk["shadow_x"] = legacy
        blk["shadow_y"] = legacy
    return blk


def build_layers(
    entries: Iterable[tuple[float, float, str]],
    sub: dict[str, Any],
    *,
    canvas_w: int,
    canvas_h: int,
    out_dir: Path,
    total_duration: float,
    auto_stroke_color: str | None = None,
) -> tuple[Path, int]:
    """
    Gambar semua lapisan subtitle + tulis daftar concat ffmpeg.

    Return (path list.txt, jumlah segmen). Segmen kosong diisi PNG transparan supaya
    stream lapisan selalu menutupi seluruh durasi video (kalau ada celah, concat
    demuxer akan memajukan timestamp dan subtitle muncul di waktu yang salah).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    blk = subtitle_block(sub)
    anim = str(sub.get("animation", "none") or "none").lower()
    color = str(sub.get("color") or "#FFFFFF")
    active_color = str(sub.get("active_color") or "#FFA500")
    inactive_scale = float(sub.get("inactive_scale", 0.80) or 0.80)
    active_scale = float(sub.get("active_scale", 1.00) or 1.00)
    per_word = anim in {"word", "karaoke"}

    blank = out_dir / "blank.png"
    if not blank.exists():
        Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0)).save(
            blank, compress_level=1
        )

    cache: dict[str, Path] = {}

    def layer(text: str, specs: list[dict] | None, tag: str) -> Path:
        key = _sig(canvas_w, canvas_h, text, tag,
                   repr(sorted(blk.items(), key=lambda kv: kv[0])),
                   repr(specs))
        hit = cache.get(key)
        if hit is not None:
            return hit
        path = out_dir / f"s_{key}.png"
        if not path.exists():
            img, _, _ = TE.render_block(
                blk, canvas_w=canvas_w, canvas_h=canvas_h, text=text,
                default_font="subtitle.ttf", auto_stroke_color=auto_stroke_color,
                word_specs=specs,
            )
            img.save(path, compress_level=1)
        cache[key] = path
        return path

    def anim_layer(base_text: str, kind: str, step: int) -> Path:
        """Lapisan animasi masuk: transformasi PIL atas lapisan dasar (tanpa gambar ulang)."""
        key = _sig(canvas_w, canvas_h, base_text, kind, step,
                   repr(sorted(blk.items(), key=lambda kv: kv[0])))
        hit = cache.get(key)
        if hit is not None:
            return hit
        path = out_dir / f"a_{key}.png"
        if not path.exists():
            base = Image.open(layer(base_text, None, "static")).convert("RGBA")
            t = (step + 1) / float(ANIM_STEPS)
            _transform(base, kind=kind, t=t, canvas_h=canvas_h).save(
                path, compress_level=1
            )
        cache[key] = path
        return path

    # ---- bangun timeline (waktu absolut, urut) ----
    segments: list[tuple[float, float, Path]] = []
    for start, end, text in entries:
        text = " ".join(str(text or "").split())
        if not text or end <= start:
            continue
        dur = end - start
        if per_word:
            words = text.split()
            slot = dur / len(words)
            for i in range(len(words)):
                specs = word_specs_for(
                    words, i, color=color, active_color=active_color,
                    inactive_scale=inactive_scale, active_scale=active_scale,
                    colorize_only=(anim == "karaoke"),
                )
                segments.append((start + i * slot, start + (i + 1) * slot,
                                 layer(text, specs, f"w{i}")))
        elif anim in {"pop", "fade", "up"}:
            adur = min(ANIM_DURATION, dur * 0.5)
            step = adur / ANIM_STEPS
            for i in range(ANIM_STEPS):
                segments.append((start + i * step, start + (i + 1) * step,
                                 anim_layer(text, anim, i)))
            segments.append((start + adur, end, layer(text, None, "static")))
        else:
            segments.append((start, end, layer(text, None, "static")))

    segments.sort(key=lambda s: s[0])

    # ---- isi celah dengan blank, tulis list concat ----
    lines: list[str] = []
    cursor = 0.0
    written = 0

    def emit(path: Path, dur: float) -> None:
        nonlocal written
        if dur <= 0.0005:
            return
        lines.append(f"file '{path.as_posix()}'")
        lines.append(f"duration {dur:.4f}")
        written += 1

    for start, end, path in segments:
        if start > cursor + 0.0005:
            emit(blank, start - cursor)
        if end <= cursor:
            continue
        emit(path, end - max(cursor, start))
        cursor = max(cursor, end)

    tail = float(total_duration) - cursor
    # +1s sengaja: concat demuxer menghentikan stream di akhir daftar. Kalau lebih
    # pendek dari video, overlay=shortest=1 akan MEMOTONG video di situ.
    emit(blank, max(1.0, tail + 1.0))
    if lines:
        # concat demuxer mengabaikan `duration` file TERAKHIR, jadi file itu ditulis
        # ulang sebagai penutup daftar.
        lines.append(f"file '{blank.as_posix()}'")

    list_path = out_dir / "sublayers.txt"
    list_path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return list_path, written


def preview_spec_layers(
    sub: dict[str, Any],
    text: str,
    *,
    canvas_w: int,
    canvas_h: int,
    auto_stroke_color: str | None = None,
    active_index: int = 0,
    ink_out: dict[str, Any] | None = None,
) -> tuple[Image.Image, int, list[str], int]:
    """
    Gambar SATU momen subtitle untuk preview: keadaan yang benar-benar terlihat di MP4.

    Kembalikan (layer, ukuran font terpakai, baris, jumlah kata).
    `active_index` = kata mana yang sedang aktif (mode word/karaoke); preview bisa
    memanggil ini per indeks lalu memutar hasilnya sebagai animasi nyata.

    Catatan penting soal `words_per_line`: di render, N kata per baris berarti entri
    SRT DIPECAH jadi beberapa potongan WAKTU, bukan beberapa baris yang muncul
    bersamaan. Jadi preview hanya boleh menampilkan potongan PERTAMA — kalau semua
    potongan ditumpuk sebagai baris, preview akan memperlihatkan sesuatu yang tidak
    pernah ada di video.
    """
    blk = subtitle_block(sub)
    words = str(text or "").split()
    wpl = int(sub.get("words_per_line", 0) or 0)
    if wpl > 0:
        words = words[:wpl]
    shown = " ".join(words)
    anim = str(sub.get("animation", "none") or "none").lower()
    specs = None
    if anim in {"word", "karaoke"} and words:
        specs = word_specs_for(
            words, max(0, min(int(active_index), len(words) - 1)),
            color=str(sub.get("color") or "#FFFFFF"),
            active_color=str(sub.get("active_color") or "#FFA500"),
            inactive_scale=float(sub.get("inactive_scale", 0.80) or 0.80),
            active_scale=float(sub.get("active_scale", 1.00) or 1.00),
            colorize_only=(anim == "karaoke"),
        )
    img, size, lines = TE.render_block(
        blk, canvas_w=canvas_w, canvas_h=canvas_h, text=shown,
        default_font="subtitle.ttf", auto_stroke_color=auto_stroke_color,
        word_specs=specs, ink_out=ink_out,
    )
    return img, size, lines, len(words)
