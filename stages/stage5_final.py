"""
Clipper Stage 5 - Final composition (Mockup #1 / paper).

Pipeline:
    Stage 2 MP4 (16:9 H.264)
        + Stage 4 SRT
        + assets/frame.png (1080x1920)
        -> 1080x1920 final MP4

Stage 5 deliberately does NOT do face tracking yet.
It composes the original 16:9 clip onto the supplied frame and burns
the Stage 4 subtitle at the global lower edge of the video area.

Expected frame:
    <project_root>/assets/frame.png
    1080x1920 recommended.

Output:
    <project_root>/final/<creator>/<video_title>/<clip>.mp4
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

try:
    from .stage5_design import refine_hook
    from .stage5_layout import build_layout, fit_text
    from .caption_txt import write_caption_file
except ImportError:
    from stage5_design import refine_hook
    from stage5_layout import build_layout, fit_text
    from caption_txt import write_caption_file

try:
    from .stage5_fonts import (
        CREATOR_FONT, HOOK_FONT, SUBTITLE_FONT,
        CREATOR_MIN_SIZE, CREATOR_MAX_SIZE,
        HOOK_MIN_SIZE, HOOK_MAX_SIZE, HOOK_MAX_LINES, HOOK_LINE_SPACING,
        HOOK_SHADOW, HOOK_BORDER,
        SUBTITLE_SIZE, SUBTITLE_Y, SUBTITLE_BORDER, SUBTITLE_SHADOW,
        SUBTITLE_INACTIVE_SCALE, SUBTITLE_ACTIVE_SCALE, SUBTITLE_POP_DURATION,
        SUBTITLE_NORMAL_COLOR, SUBTITLE_ACTIVE_COLOR,
        CREATOR_SHADOW, CREATOR_BORDER,
        LAYOUT_REFERENCE, HEADLINE_LEFT, HEADLINE_RIGHT, HEADLINE_TOP, HEADLINE_BOTTOM,
        GEMINI_DESIGN_ENABLED, GEMINI_MODEL, GEMINI_TEMPERATURE,
        GEMINI_HOOK_MAX_LINES, GEMINI_HOOK_MIN_CHARS, GEMINI_HOOK_MAX_CHARS,
    )
except ImportError:
    from stage5_fonts import (
        CREATOR_FONT, HOOK_FONT, SUBTITLE_FONT,
        CREATOR_MIN_SIZE, CREATOR_MAX_SIZE,
        HOOK_MIN_SIZE, HOOK_MAX_SIZE, HOOK_MAX_LINES, HOOK_LINE_SPACING,
        HOOK_SHADOW, HOOK_BORDER,
        SUBTITLE_SIZE, SUBTITLE_Y, SUBTITLE_BORDER, SUBTITLE_SHADOW,
        SUBTITLE_INACTIVE_SCALE, SUBTITLE_ACTIVE_SCALE, SUBTITLE_POP_DURATION,
        SUBTITLE_NORMAL_COLOR, SUBTITLE_ACTIVE_COLOR,
        CREATOR_SHADOW, CREATOR_BORDER,
        LAYOUT_REFERENCE, HEADLINE_LEFT, HEADLINE_RIGHT, HEADLINE_TOP, HEADLINE_BOTTOM,
        GEMINI_DESIGN_ENABLED, GEMINI_MODEL, GEMINI_TEMPERATURE,
        GEMINI_HOOK_MAX_LINES, GEMINI_HOOK_MIN_CHARS, GEMINI_HOOK_MAX_CHARS,
    )

try:
    from .stage5_preset import (
        load_preset as _load_preset_safe,
        hex_to_ass as _hex_to_ass,
        hex_to_drawtext as _hex_to_drawtext,
        auto_border_color as _auto_border_color,
        video_geometry as _video_geometry,
    )
except ImportError:
    from stage5_preset import (
        load_preset as _load_preset_safe,
        hex_to_ass as _hex_to_ass,
        hex_to_drawtext as _hex_to_drawtext,
        auto_border_color as _auto_border_color,
        video_geometry as _video_geometry,
    )

try:
    from .frame_library import resolve_frame_from_preset as _resolve_frame_from_preset
except ImportError:
    from frame_library import resolve_frame_from_preset as _resolve_frame_from_preset

# Mesin teks TUNGGAL: dipakai render (di sini) DAN preview (lewat bridge GUI).
try:
    from . import text_engine as _text_engine
except ImportError:
    import text_engine as _text_engine

# Subtitle juga digambar mesin yang sama (lapisan PNG + concat demuxer), bukan libass.
try:
    from . import subtitle_engine as _subtitle_engine
except ImportError:
    import subtitle_engine as _subtitle_engine


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FRAME = ROOT / "assets" / "frame.png"
DEFAULT_CLIPS_ROOT = ROOT / "output"
DEFAULT_FINAL_ROOT = ROOT / "final"
# Preset yang terakhir di-"Terapkan" dari GUI Customize. Dipakai otomatis kalau
# pemanggil tidak memberi --preset, supaya tab Run menghasilkan gaya yang sama
# dengan yang dilihat user di Customize.
ACTIVE_PRESET = ROOT / "assets" / "presets" / "render_preset.active.json"


def resolve_preset_path(preset_path: Path | None) -> Path | None:
    """Preset eksplisit > preset aktif dari GUI > None (default lama)."""
    if preset_path is not None:
        return Path(preset_path)
    if ACTIVE_PRESET.exists():
        print(f"      preset:    {ACTIVE_PRESET.name} (dari Customize)")
        return ACTIVE_PRESET
    return None

# Mockup #1 geometry, based on a 1080x1920 canvas.
# The 16:9 video is full-width and centered vertically in the composition.
CANVAS_W = 1080
CANVAS_H = 1920
VIDEO_W = 1080
VIDEO_H = 608
VIDEO_Y = 675

# Subtitle baseline is intentionally near the lower edge of the video,
# matching the supplied mockup. ASS coordinates are top-left based.
SUBTITLE_Y = 1190


def sanitize_component(value: str, fallback: str = "untitled") -> str:
    value = str(value or "").strip()
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", value)
    value = re.sub(r"\s+", " ", value).strip().rstrip(".")
    return value[:180] or fallback


def run_ffmpeg(args: list[str]) -> None:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-y", *args],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"FFmpeg failed ({proc.returncode}):\n{detail[-5000:]}")


def probe_duration(path: Path) -> float:
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {proc.stderr}")
    return float(proc.stdout.strip())


def srt_timestamp_to_seconds(value: str) -> float:
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    if len(parts) != 3:
        raise ValueError(value)
    h, m, s = parts
    return int(h) * 3600 + int(m) * 60 + float(s)


def parse_srt(path: Path) -> list[tuple[float, float, str]]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    blocks = re.split(r"\r?\n\s*\r?\n", text.strip())
    items: list[tuple[float, float, str]] = []

    for block in blocks:
        lines = [line.rstrip() for line in block.splitlines()]
        if not lines:
            continue

        timing_index = next(
            (i for i, line in enumerate(lines) if "-->" in line),
            None,
        )
        if timing_index is None:
            continue

        timing = lines[timing_index]
        left, right = [x.strip() for x in timing.split("-->", 1)]
        # Strip optional SRT settings after end timestamp.
        right = right.split()[0]

        start = srt_timestamp_to_seconds(left)
        end = srt_timestamp_to_seconds(right)
        subtitle = " ".join(
            x.strip() for x in lines[timing_index + 1:] if x.strip()
        )
        subtitle = re.sub(r"<[^>]+>", "", subtitle)
        subtitle = re.sub(r"\s+", " ", subtitle).strip()

        if subtitle and end > start:
            items.append((start, end, subtitle))

    return items


def regroup_entries(
    entries: list[tuple[float, float, str]], words_per_line: int
) -> list[tuple[float, float, str]]:
    """
    Susun ulang entri SRT menjadi potongan berisi TEPAT `words_per_line` kata.

    Bisa MEMECAH (entri lebih panjang dari target) maupun MENGGABUNG (entri lebih
    pendek). Kemampuan menggabung itu yang membuat `words_per_line` bisa dibakukan di
    theme: pendahulunya (`resplit_entries`) hanya memecah, jadi SRT 3 kata mustahil
    ditampilkan 5 kata dan pilihan itu akan bohong.

    Caranya: semua kata di-flatten dulu bersama perkiraan waktunya (durasi entri dibagi
    proporsional per kata), lalu dikelompokkan ulang. Awal potongan = start kata pertama,
    akhir potongan = end kata terakhir, jadi batas asli entri tetap dihormati.

    Presisinya bergantung kehalusan SRT: SRT 1 kata/entri memberi waktu per kata yang
    NYATA (dari alignment WhisperX), sedangkan SRT 3 kata/entri hanya punya batas per
    entri sehingga waktu di dalamnya adalah perkiraan. Karena itu Stage 4 sekarang
    menulis SRT sehalus mungkin (1 kata) — lihat `config.subtitle_target_words`.

    words_per_line <= 0 -> kembalikan apa adanya (pakai baris SRT dari Stage 4).
    """
    n = int(words_per_line or 0)
    if n <= 0:
        return entries

    # 1) flatten: (start, end, kata)
    kata: list[tuple[float, float, str]] = []
    for start, end, text in entries:
        words = str(text or "").split()
        if not words:
            continue
        durasi = max(0.01, float(end) - float(start))
        per = durasi / len(words)
        for i, w in enumerate(words):
            ws = start + per * i
            we = end if i == len(words) - 1 else start + per * (i + 1)
            if we <= ws:
                we = ws + 0.01
            kata.append((ws, we, w))

    # 2) kelompokkan ulang per n kata
    out: list[tuple[float, float, str]] = []
    for i in range(0, len(kata), n):
        grup = kata[i:i + n]
        mulai = grup[0][0]
        akhir = grup[-1][1]
        if akhir <= mulai:
            akhir = mulai + 0.01
        out.append((mulai, akhir, " ".join(w for _, _, w in grup)))
    return out


# Nama lama dipertahankan sebagai alias supaya pemanggil/tes lama tidak pecah.
resplit_entries = regroup_entries


# CATATAN 2026-08-30 — frame_window_bounds() dan cover_frame_window() DIHAPUS.
#
# Keduanya memaksa kotak video membesar sampai menutup "jendela" frame, alasannya
# mencegah base HITAM bocor sebagai strip gelap di tepi robekan. Alasan itu sudah tidak
# berlaku: base kanvas sekarang VIDEO yang di-cover penuh ([vbg]scale=...,crop=...),
# jadi yang tembus di tepi semi-transparan adalah gambar, bukan hitam.
#
# Yang tersisa hanya efek merugikannya: nilai video.scale pilihan user ditimpa diam-diam,
# sehingga slider Skala terasa tidak berpengaruh (dilaporkan user). Sekarang slider jujur:
# 0% = video utuh (tidak terpotong), 300% = kanvas terisi penuh.
#
# frame.json masih menyimpan `window` (dipakai stages/frame_library.py untuk info);
# yang dibuang adalah PEMAKSAAN geometri di jalur render.


AUTO_WATERMARK_TOKENS = {
    "creator!", "creator", "nama creator", "nama kreator",
    "kreator!", "kreator", "<creator>", "{creator}",
}


def resolve_watermark_text(preset_text: object, creator: str) -> str:
    """Tentukan teks watermark akhir untuk satu video.

    Aturan (2026-08-30, permintaan user): kotak watermark di Customize memuat contoh
    `Creator!` supaya preview tidak kosong; saat render, penanda itu DIGANTI nama creator
    video yang sedang diproses. Teks lain dipakai harfiah, jadi user tetap bisa memaksa
    satu nama tetap untuk semua video.

    Kenapa penanda dan bukan "kosong = otomatis": default mockup selalu mengisi kotak itu,
    jadi menyimpan preset akan terus "membakar" teks contoh ke preset (inilah sebabnya
    watermark tetap "AD REVIEW" setelah dua perbaikan). Penanda membuat contoh preview dan
    perilaku otomatis jadi satu hal yang sama, bukan dua yang bisa berbeda.
    """
    teks = str(preset_text or "").strip()
    nama = str(creator or "").strip().upper()
    if not teks or teks.lower() in AUTO_WATERMARK_TOKENS:
        return nama
    return teks


def build_intro_cover(
    intro: dict[str, Any],
    *,
    canvas_w: int,
    canvas_h: int,
    headline_block: dict[str, Any],
    watermark_block: dict[str, Any],
    headline_text: str,
    creator_text: str,
    out_path: Path,
) -> Path | None:
    """Gambar SATU PNG RGBA seukuran kanvas: latar cover + headline + nama creator.

    Ini lapisan untuk Intro Cover (bug.txt item 12). Dipakai sebagai thumbnail feed
    TikTok/Shorts, yang mengambil frame paling awal video sebagai gambar sampul.

    Yang penting dan mudah salah:
      * Video & audio utama TIDAK disentuh — cover cuma dioverlay di detik-detik awal
        lalu memudar. Pendekatan lain (freeze frame / concat gambar) menggeser seluruh
        timeline sehingga subtitle dan durasi klip jadi meleset.
      * Teks memakai blok `headline`/`watermark` yang SAMA dengan video (font, warna,
        outline, shadow) supaya cover terasa satu keluarga dengan isinya, tapi selalu
        dipusatkan di kanvas — bukan mengikuti x/y layout video, karena di komposisi
        cover posisi itu tampak salah tempat.
      * Latar wajib OPAK. Cover yang tembus pandang tidak berguna sebagai sampul.

    Return path PNG, atau None kalau tidak ada yang bisa digambar.
    """
    from PIL import Image

    headline_text = str(headline_text or "").strip()
    creator_text = str(creator_text or "").strip()
    show_head = bool(intro.get("show_headline", True)) and bool(headline_text)
    show_wm = bool(intro.get("show_creator", True)) and bool(creator_text)

    bg_rel = str(intro.get("background") or "").strip()
    bg_path = (ROOT / bg_rel) if bg_rel else None
    has_bg = bool(bg_path and bg_path.exists())

    if not (has_bg or show_head or show_wm):
        return None

    # ---- latar ----
    if has_bg:
        # COVER + center-crop, bukan stretch: gambar sampul user tidak boleh gepeng
        # kalau rasionya beda dari kanvas.
        base = Image.open(bg_path).convert("RGBA")
        scale = max(canvas_w / base.width, canvas_h / base.height)
        new_w = max(1, int(round(base.width * scale)))
        new_h = max(1, int(round(base.height * scale)))
        base = base.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - canvas_w) // 2
        top = (new_h - canvas_h) // 2
        cover = base.crop((left, top, left + canvas_w, top + canvas_h))
    else:
        # Tanpa gambar impor: latar gelap pekat. Bukan transparan — lihat docstring.
        cover = Image.new("RGBA", (canvas_w, canvas_h), (7, 12, 22, 255))

    # ---- teks, dipusatkan lewat measure_ink (mesin yang sama dengan preview) ----
    def _centered(
        block: dict[str, Any], text: str, default_font: str, y_shift: int = 0,
    ) -> "Image.Image | None":
        blk = dict(block)
        blk["enabled"] = True
        blk["align"] = "center"
        auto = str(_auto_border_color(str(blk.get("color") or "#FFFFFF"))).lower()
        auto_hex = "#FFFFFF" if "white" in auto or auto.startswith("#fff") else "#000000"
        # Dua tahap: gambar sekali untuk MENGUKUR kotak tinta, lalu gambar ulang di
        # posisi yang benar-benar memusatkannya. `measure_ink` mengabaikan shadow, jadi
        # teks tidak tergeser sebesar offset shadow — masalah yang pernah muncul saat
        # pemusatan memakai bbox lapisan. `y_shift` menggeser dari titik tengah itu,
        # dipakai saat headline dan creator tampil bersamaan supaya tidak bertumpuk.
        ink: dict[str, Any] = {}
        _text_engine.render_block(
            blk, canvas_w=canvas_w, canvas_h=canvas_h, text=text,
            default_font=default_font, auto_stroke_color=auto_hex, ink_out=ink,
        )
        h = int(ink.get("h") or 0)
        if h:
            blk["y"] = (canvas_h - h) // 2 - int(ink.get("dy_top") or 0) + int(y_shift)
            base_x = int(round(45 * (canvas_w / 1080.0)))
            blk["x"] = base_x - int(ink.get("dcx") or 0)
        layer, _size, _lines = _text_engine.render_block(
            blk, canvas_w=canvas_w, canvas_h=canvas_h, text=text,
            default_font=default_font, auto_stroke_color=auto_hex,
        )
        return layer

    if show_head and show_wm:
        # Dua teks: headline di ATAS titik tengah, nama creator di BAWAHNYA.
        gap = int(round(canvas_h * 0.06))
        head_layer = _centered(headline_block, headline_text, HOOK_FONT, -gap)
        wm_layer = _centered(watermark_block, creator_text, CREATOR_FONT, gap)
        if head_layer is not None:
            cover.alpha_composite(head_layer)
        if wm_layer is not None:
            cover.alpha_composite(wm_layer)
    elif show_head:
        layer = _centered(headline_block, headline_text, HOOK_FONT)
        if layer is not None:
            cover.alpha_composite(layer)
    elif show_wm:
        layer = _centered(watermark_block, creator_text, CREATOR_FONT)
        if layer is not None:
            cover.alpha_composite(layer)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cover.save(out_path, compress_level=1)
    return out_path


def render_clip(
    video_path: Path,
    srt_path: Path,
    frame_path: Path,
    output_path: Path,
    creator: str,
    hook: str,
    video_title: str,
    preset: dict[str, Any] | None = None,
    headline: str = "",
) -> None:
    """
    Render satu klip.

    headline: teks headline SPESIFIK untuk klip ini (dari manifest Stage 2, yang asalnya
    dari keputusan user di tahap review). Kalau kosong, jatuh ke `preset.headline.text`
    lalu ke Gemini. Sengaja parameter terpisah dari `hook`: `hook` adalah kutipan
    transkrip mentah yang dipakai Gemini sebagai bahan, bukan teks yang mau ditampilkan.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if preset is None:
        preset = _load_preset_safe(None)

    canvas = preset["canvas"]
    cw, ch = int(canvas["w"]), int(canvas["h"])
    sub = preset["subtitle"]
    head = preset["headline"]
    wm = preset["watermark"]
    png = preset["custom_png"]
    export = preset["export"]

    geom = _video_geometry(preset)

    # CATATAN 2026-08-30: pemaksaan `cover_frame_window()` DIBUANG.
    # Dulu geometri video dinaikkan otomatis supaya menutup penuh jendela frame, dengan
    # alasan mencegah base hitam bocor di tepi robekan. Tapi base kanvas sekarang adalah
    # VIDEO yang di-cover penuh (lihat filter graph di bawah), jadi tidak ada hitam yang
    # bisa bocor — sementara pemaksaan itu MENIMPA nilai skala pilihan user, sehingga
    # slider Skala terasa tidak berpengaruh (bug yang dilaporkan user). Slider sekarang
    # jujur: 0% = video utuh, 300% = kanvas terisi penuh.

    with tempfile.TemporaryDirectory(prefix="clipper_stage5_") as td:
        fonts_dir = Path(__file__).resolve().parents[1] / "assets" / "fonts"
        subtitle_font = fonts_dir / str(sub.get("font") or SUBTITLE_FONT)
        head_font = fonts_dir / str(head.get("font") or HOOK_FONT)
        wm_font = fonts_dir / str(wm.get("font") or CREATOR_FONT)

        for f in (subtitle_font, head_font, wm_font):
            if not f.exists():
                raise FileNotFoundError(f"Missing font: {f}")

        # CATATAN: nama family font tidak lagi diperlukan. Dulu libass mencocokkan font
        # lewat NAMA family dari fontsdir; text_engine memuat FILE font langsung.

        # -------- SUBTITLE: lapisan PNG dari text_engine, BUKAN ASS/libass --------
        # Dulu subtitle dibakar libass dari file .ass sementara preview menggambarnya
        # dengan CSS — dua mesin berbeda, jadi subtitle adalah satu-satunya elemen
        # yang tidak punya jaminan "preview == output" (tebal outline, blur/warna
        # shadow, titik pecah baris, dan zona perataan semuanya beda). Sekarang
        # subtitle memakai `text_engine.render_block()` yang sama dengan headline,
        # watermark, dan preview; deretan PNG-nya disusun jadi satu input ffmpeg
        # lewat concat demuxer.
        sub_entries = regroup_entries(
            parse_srt(srt_path), int(sub.get("words_per_line", 0) or 0)
        )
        if not sub_entries:
            raise RuntimeError(f"No usable subtitle entries found in {srt_path}")
        sub_auto = str(_auto_border_color(str(sub.get("color") or "#FFFFFF"))).lower()
        sub_auto_hex = "#FFFFFF" if "white" in sub_auto else "#000000"
        sub_list_path, sub_segments = _subtitle_engine.build_layers(
            sub_entries, sub,
            canvas_w=cw, canvas_h=ch,
            out_dir=Path(td) / "sublayers",
            total_duration=probe_duration(video_path),
            auto_stroke_color=sub_auto_hex,
        )
        count = len(sub_entries)
        print(f"      subtitle: {count} entri -> {sub_segments} lapisan PNG"
              f" (mesin sama dengan preview)")

        # -------- Headline text: per klip > preset > Gemini --------
        # URUTAN INI PENTING. `headline` datang dari manifest Stage 2 (asalnya dari
        # keputusan user di tahap review, atau `judul_relevan` hasil kurasi Gemini),
        # jadi ia SPESIFIK per klip dan harus menang. `preset.headline.text` bersifat
        # GLOBAL untuk semua klip — kalau preset menang, headline per klip TIDAK AKAN
        # PERNAH terpakai, karena preset user praktis selalu terisi (mis. "HEADLINE1
        # HEADLINE2 HEADLINE3"). Preset tetap dipakai kalau manifest tidak membawa
        # headline, supaya tombol "Uji 1 klip" dari Customize dan preset lama tidak
        # berubah perilakunya.
        headline_text = str(headline or "").strip() or str(head.get("text") or "").strip()
        design = None
        if not headline_text and head.get("gemini_default", True):
            reference_path = (ROOT / LAYOUT_REFERENCE).resolve()
            cache_path = output_path.with_suffix(".design.v3.json")
            layout_context = {
                "canvas": f"{cw}x{ch}",
                "headline_zone": {
                    "left": HEADLINE_LEFT, "right": HEADLINE_RIGHT,
                    "top": HEADLINE_TOP, "bottom": HEADLINE_BOTTOM,
                },
                "subtitle_y": int(sub.get("y", SUBTITLE_Y)),
            }
            subtitle_entries = parse_srt(srt_path)
            subtitle_sample = subtitle_entries[0][2] if subtitle_entries else ""
            design = refine_hook(
                creator=creator, title=video_title, current_hook=hook,
                cache_path=cache_path, reference_path=reference_path,
                enabled=GEMINI_DESIGN_ENABLED, model=GEMINI_MODEL,
                temperature=GEMINI_TEMPERATURE, max_lines=GEMINI_HOOK_MAX_LINES,
                min_chars=GEMINI_HOOK_MIN_CHARS, max_chars=GEMINI_HOOK_MAX_CHARS,
                layout_context=layout_context, subtitle_sample=subtitle_sample,
            )
            headline_text = design.hook

        # -------- Watermark text: penanda otomatis > teks preset > nama creator --------
        # "Creator!" (dan variannya) adalah PENANDA, bukan teks harfiah: dipakai sebagai
        # contoh di preview Customize, lalu diganti nama creator video saat render. Teks
        # lain apa pun dipakai apa adanya, jadi user tetap bisa memaksa satu nama tetap.
        watermark_text = resolve_watermark_text(wm.get("text"), creator)

        # CATATAN: auto-fit + pemecahan baris headline/watermark TIDAK lagi dihitung di
        # sini. Keduanya dilakukan oleh `text_engine.render_block()` yang JUGA dipanggil
        # preview, sehingga ukuran font dan titik pecah baris dijamin sama. Perhitungan
        # ganda di dua tempat itulah sumber "output tidak sesuai preview" sebelumnya.

        # Tidak ada lagi path yang perlu di-escape ke dalam string filter_complex:
        # frame, overlay PNG, dan lapisan teks semuanya masuk sebagai INPUT ffmpeg
        # biasa (`-i`), dan filter `ass` (yang dulu butuh fontsdir) sudah dibuang.
        # Itu sekaligus menghilangkan kelas bug escaping path Windows di filter.

        vw, vh, vx, vy = geom["w"], geom["h"], geom["x"], geom["y"]

        # -------- Lapisan teks: digambar text_engine, jadi PNG RGBA seukuran kanvas --------
        # Preview memanggil fungsi yang SAMA (`text_engine.render_block`), jadi hasilnya
        # bukan "didekatkan" tapi literal gambar yang sama. Auto-fit, pemecahan baris,
        # urutan lapisan (shadow/stroke/fill), warna shadow, blur — semua di satu tempat.
        text_layer_paths: list[Path] = []
        for label, blk, txt, default_font in (
            ("wm", wm, watermark_text, CREATOR_FONT),
            ("head", head, headline_text, HOOK_FONT),
        ):
            if not blk.get("enabled", True) or not str(txt or "").strip():
                continue
            auto = str(_auto_border_color(str(blk.get("color") or "#FFFFFF"))).lower()
            auto_hex = "#FFFFFF" if "white" in auto or auto.startswith("#fff") else "#000000"
            layer_img, used_size, used_lines = _text_engine.render_block(
                blk, canvas_w=cw, canvas_h=ch, text=str(txt),
                default_font=str(default_font), auto_stroke_color=auto_hex,
            )
            lp = Path(td) / f"layer_{label}.png"
            # compress_level=1 sama dengan yang dipakai preview (bridge) dan
            # subtitle_engine, supaya PNG kedua sisi identik BYTE — itu bukti
            # terkuat bahwa preview dan render memakai gambar yang sama.
            layer_img.save(lp, compress_level=1)
            text_layer_paths.append(lp)
            print(f"      {label}: {used_size}px, {len(used_lines)} baris")

        # -------- Intro Cover (item 12): PNG penutup di detik-detik awal --------
        # Digambar SEBELUM daftar input disusun karena ia menambah satu input ffmpeg.
        intro = preset.get("intro", {}) or {}
        intro_path: Path | None = None
        intro_dur = 0.0
        intro_fade = 0.0
        if bool(intro.get("enabled")):
            try:
                intro_dur = max(0.05, float(intro.get("duration", 0.4)))
            except (TypeError, ValueError):
                intro_dur = 0.4
            try:
                intro_fade = max(0.0, float(intro.get("fade", 0.15)))
            except (TypeError, ValueError):
                intro_fade = 0.15
            # Fade tidak boleh lebih lama dari tampilnya cover: kalau lebih, cover
            # mulai memudar sebelum sempat terlihat penuh dan thumbnail feed jadi
            # setengah transparan.
            intro_fade = min(intro_fade, intro_dur)
            intro_path = build_intro_cover(
                intro,
                canvas_w=cw, canvas_h=ch,
                headline_block=head, watermark_block=wm,
                headline_text=headline_text, creator_text=watermark_text,
                out_path=Path(td) / "intro_cover.png",
            )
            if intro_path is not None:
                print(f"      intro cover: {intro_dur:.2f}s (fade {intro_fade:.2f}s)")

        # -------- Inputs: frame(0), video(1), [png], [subtitle concat], [layer teks...] --------
        inputs = ["-loop", "1", "-i", str(frame_path), "-i", str(video_path)]
        next_index = 2
        png_enabled = bool(png.get("enabled")) and str(png.get("path") or "").strip()
        if png_enabled and Path(str(png["path"])).exists():
            inputs += ["-loop", "1", "-i", str(png["path"])]
            png_index = next_index
            next_index += 1
        else:
            png_index = None
        # Subtitle = SATU input bertimestamp berisi deretan PNG (concat demuxer).
        # `-safe 0` diperlukan karena daftar memuat path absolut.
        inputs += ["-f", "concat", "-safe", "0", "-i", str(sub_list_path)]
        sub_index = next_index
        next_index += 1
        text_layer_index = next_index
        for lp in text_layer_paths:
            inputs += ["-loop", "1", "-i", str(lp)]
            next_index += 1
        # Intro cover masuk PALING AKHIR supaya ia jadi lapisan teratas di filter graph.
        if intro_path is not None:
            inputs += ["-loop", "1", "-i", str(intro_path)]
            intro_index = next_index
            next_index += 1
        else:
            intro_index = None

        # -------- filter graph --------
        # Rounded corners video (opsional): mask alpha via geq bila radius > 0.
        vradius = int(preset["video"].get("radius", 0))
        vradius = max(0, min(vradius, min(vw, vh) // 2))
        if vradius > 0:
            # Preserve alpha=255 di tengah; hanya cek 4 sudut membulat.
            round_a = (
                f"if(gt(abs(X-({vw}/2)),({vw}/2-{vradius}))*"
                f"gt(abs(Y-({vh}/2)),({vh}/2-{vradius})),"
                f"if(lte(hypot(abs(X-({vw}/2))-({vw}/2-{vradius}),"
                f"abs(Y-({vh}/2))-({vh}/2-{vradius})),{vradius}),255,0),255)"
            )
            # comma menyambung geq ke rantai scale/pad/format sebelumnya
            clip_round = (
                f",geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='{round_a}'[clip];"
            )
        else:
            clip_round = "[clip];"
        fg = (
            # Base kanvas = VIDEO yang di-cover ke seluruh kanvas, BUKAN hitam.
            # Kenapa: tepi robekan frame semi-transparan (alpha memudar 0->255 sepanjang
            # ~20px). Apa pun yang ada di base ikut tembus di tepi itu. Dengan base hitam,
            # strip gelap tetap terlihat di tepi walau kotak video sudah menutup jendela.
            # Base video membuat yang tembus adalah gambar, bukan hitam.
            f"[1:v]split=2[vsrc][vbg];"
        )
        vid_blur = preset.get("video", {}).get("blur_background", False)
        blur_rad = preset.get("video", {}).get("blur_radius", 40)
        if vid_blur:
            fg += (
                f"[vbg]scale={cw}:{ch}:force_original_aspect_ratio=increase,"
                f"crop={cw}:{ch},setsar=1,boxblur={blur_rad}:1,colorchannelmixer=r=0.6:g=0.6:b=0.6:a=1,format=rgba[base];"
            )
        else:
            fg += (
                f"[vbg]scale={cw}:{ch}:force_original_aspect_ratio=increase,"
                f"crop={cw}:{ch},setsar=1,format=rgba[base];"
            )
        fg += (
            # COVER, bukan letterbox. Dulu `decrease` + `pad=...:color=black` mengisi
            # sisa kotak dengan HITAM: klip 1920x884 (rasio 2.17) di kotak rasio 1.78
            # menghasilkan bar hitam ~78px di atas & bawah, dan bar itulah yang terlihat
            # sebagai strip gelap di tepi robekan frame. `increase` + `crop` membuat
            # video selalu MENGISI kotak; kelebihannya dipotong (sesuai model
            # "input adjustment vs output" — luberan memang dibuang).
            f"[vsrc]scale={vw}:{vh}:force_original_aspect_ratio=increase,"
            f"crop={vw}:{vh},setsar=1,format=rgba"
            + clip_round +
            f"[base][clip]overlay={vx}:{vy}:shortest=1[video];"
            # Frame di-fit ke canvas. Aset frame umumnya 1080x1920; canvas bisa
            # 1:1 / 4:5 / 16:9. Pakai COVER + center-crop (bukan stretch) supaya
            # desain torn-paper tidak gepeng saat rasio berbeda.
            f"[0:v]scale={cw}:{ch}:force_original_aspect_ratio=increase,"
            f"crop={cw}:{ch},setsar=1[frm];"
            f"[video][frm]overlay=0:0:shortest=1[framed];"
        )
        stream = "framed"
        if png_index is not None:
            pw = int(png.get("width", 220))
            # Opacity PNG: kalikan channel alpha. `colorchannelmixer=aa=` bekerja pada
            # alpha yang SUDAH ada, jadi PNG dengan tepi lembut tetap lembut.
            try:
                pop = float(png.get("opacity", 1.0))
            except (TypeError, ValueError):
                pop = 1.0
            pop = max(0.0, min(1.0, pop))
            alpha_f = "" if pop >= 0.999 else f",format=rgba,colorchannelmixer=aa={pop:.3f}"
            fg += (
                f"[{png_index}:v]scale={pw}:-1{alpha_f}[png];"
                f"[{stream}][png]overlay={int(png.get('x',16))}:{int(png.get('y',84))}:shortest=1[pngd];"
            )
            stream = "pngd"
        # ---- subtitle: overlay lapisan PNG (mesin sama dengan preview) ----
        # `fps=30` + `format=rgba` menyeragamkan stream concat (tiap PNG punya durasi
        # berbeda) menjadi laju frame tetap sebelum di-overlay.
        fg += (
            f"[{sub_index}:v]format=rgba,fps=30[subl];"
            f"[{stream}][subl]overlay=0:0:shortest=1[subbed];"
        )
        stream = "subbed"
        # ---- overlay lapisan teks (sudah digambar text_engine di atas) ----
        if text_layer_paths:
            for i in range(len(text_layer_paths)):
                src = f"{text_layer_index + i}:v"
                last = (i == len(text_layer_paths) - 1)
                out_lbl = ("vtxt" if intro_index is not None else "v") if last else f"txt{i}"
                fg += f"[{stream}][{src}]overlay=0:0:shortest=1[{out_lbl}];"
                stream = out_lbl
            if intro_index is None:
                fg = fg.rstrip(";")
        else:
            fg += f"[{stream}]null[{'vtxt' if intro_index is not None else 'v'}];"
            stream = "vtxt" if intro_index is not None else "v"
            if intro_index is None:
                fg = fg.rstrip(";")

        # ---- Intro Cover: lapisan TERATAS, hanya tampil di detik-detik awal ----
        # Cara kerjanya:
        #   fade=out  -> alpha cover turun dari 1 ke 0, mulai (durasi - fade).
        #   overlay enable='lte(t,durasi)' -> setelah itu cover berhenti dikomposit
        #     sama sekali, jadi tidak ada beban dan tidak ada sisa lapisan samar.
        # Video dan audio utama tidak disentuh: keduanya tetap berjalan dari detik 0,
        # sesuai permintaan (cover BUKAN freeze frame / bukan klip yang disambung).
        if intro_index is not None:
            fade_st = max(0.0, intro_dur - intro_fade)
            fade_f = (
                f",fade=t=out:st={fade_st:.3f}:d={intro_fade:.3f}:alpha=1"
                if intro_fade > 0 else ""
            )
            fg += (
                f"[{intro_index}:v]format=rgba,fps=30{fade_f}[intro];"
                f"[{stream}][intro]overlay=0:0:enable='lte(t,{intro_dur:.3f})':"
                f"shortest=1[v]"
            )

        run_ffmpeg(
            inputs + [
                "-filter_complex", fg,
                "-map", "[v]", "-map", "1:a?",
                "-c:v", "libx264", "-preset", str(export.get("preset", "medium")),
                "-crf", str(export.get("crf", 18)),
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest", "-movflags", "+faststart",
                "-metadata", f"title={headline_text or hook or video_path.stem}",
                "-metadata", f"artist={creator}",
                str(output_path),
            ]
        )

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError(f"Stage 5 produced no output: {output_path}")

        print(f"      subtitles: {count}")
        print(f"      output:    {output_path}")


def find_stage2_manifests(clips_root: Path) -> list[Path]:
    return sorted(clips_root.glob("**/manifest.json"))


def load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def creator_watermark_from_curation(folder: Path) -> str:
    """Baca `creator_watermark` dari file kurasi Stage 1 di `folder`, kalau ada.

    Kenapa perlu: manifest Stage 2 hanya ditulis ulang saat Download dijalankan. Kalau
    user mengubah kotak Kreator di panel Review lalu HANYA me-render ulang (jalur
    `render_with_preset.py`, tanpa unduh lagi), `manifest.json` masih memuat nilai lama —
    dan user akan melihat watermark tidak berubah walau sudah menyimpan. File kurasi
    adalah sumber yang baru saja ia edit, jadi itu yang dimenangkan.

    File kurasi selalu `<video_id>.json` di folder yang sama; nama ber-"manifest" ditolak
    (lihat `gui_review.is_curation_file` — aturannya disamakan, jangan dilonggarkan).
    """
    folder = Path(folder)
    if not folder.is_dir():
        return ""
    for p in sorted(folder.glob("*.json")):
        nama = p.name.lower()
        if "manifest" in nama or nama.endswith((".subtitle.json", ".design.v3.json")):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(data, dict) and isinstance(data.get("daftar_klip"), list):
            return str(data.get("creator_watermark") or "").strip()
    return ""


def render_manifest(
    manifest_path: Path,
    *,
    frame_path: Path,
    final_root: Path,
    force: bool,
    preset: dict[str, Any] | None = None,
    only_clip: int | None = None,
) -> None:
    """
    Render semua klip di manifest.

    only_clip: nomor klip (1-based, urutan di manifest). Kalau diisi, hanya klip itu
    yang dirender dan file lama-nya ditimpa (force otomatis) — dipakai untuk uji cepat
    satu klip dari GUI tanpa menunggu semuanya.
    """
    manifest = load_manifest(manifest_path)

    creator = str(manifest.get("creator") or "").strip()
    # WATERMARK memakai ketikan user kalau ada; nama FOLDER di bawah tetap `creator` asli.
    # Dua nilai yang berbeda dengan sengaja: user boleh menulis "AD REVIEW" di watermark
    # tanpa memindahkan hasil ke folder baru (yang akan memutus jejak klip Stage 2).
    creator_watermark = (
        creator_watermark_from_curation(manifest_path.parent)
        or str(manifest.get("creator_watermark") or "").strip()
        or creator
    )
    video_title = str(
        manifest.get("video_title")
        or manifest.get("judul_video")
        or manifest_path.parent.name
    ).strip()

    creator_dir = sanitize_component(creator, "Unknown Creator")
    title_dir = sanitize_component(video_title, "Untitled Video")
    output_dir = final_root / creator_dir / title_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    clips = manifest.get("clips") or manifest.get("daftar_klip") or []
    if not isinstance(clips, list):
        raise RuntimeError(f"Invalid clips in {manifest_path}")

    print("=" * 72)
    print("STAGE 5 â€” FINAL COMPOSITION / PAPER")
    print(f"Manifest : {manifest_path}")
    print(f"Frame    : {frame_path}")
    print(f"Output   : {output_dir}")
    print("=" * 72)

    rendered = 0
    skipped = 0
    failed = 0

    for idx, clip in enumerate(clips, 1):
        if not isinstance(clip, dict):
            continue

        # Nomor klip yang BERARTI bagi user adalah `clip_id` (berasal dari `id_klip`
        # Gemini di Stage 1), BUKAN nomor urut entri di manifest. Keduanya kebetulan
        # sama ketika semua klip diunduh, tapi begitu user men-skip klip di tahap
        # review, manifest hanya memuat klip terpilih (mis. clip_id 1, 2, 5) — dan
        # `idx` untuk clip_id 5 menjadi 3. Mencocokkan `idx` berarti "Uji 1 klip"
        # nomor 3 merender klip 5 tanpa peringatan. Fallback ke `idx` dipertahankan
        # untuk manifest lama yang tidak punya `clip_id`.
        try:
            clip_no = int(clip.get("clip_id") or idx)
        except (TypeError, ValueError):
            clip_no = idx

        if only_clip is not None and clip_no != int(only_clip):
            continue

        # Prefiks log memuat NOMOR KLIP (clip_no), bukan hanya posisi entri, supaya
        # ketika ada klip yang di-skip user tetap bisa mencocokkan log dengan nama file.
        tag = f"[{idx}/{len(clips)} klip {clip_no}]"

        status = str(clip.get("status") or "").lower()
        if status and status not in {"success", "skipped", "complete", "completed"}:
            print(f"{tag} skip failed clip entry")
            continue

        video_raw = clip.get("output_path") or ""
        if not video_raw:
            print(f"{tag} skip: no output_path")
            continue

        video_path = Path(video_raw)
        if not video_path.is_absolute():
            video_path = (ROOT / video_path).resolve()

        if not video_path.exists():
            print(f"{tag} missing video: {video_path}")
            failed += 1
            continue

        srt_path = video_path.with_suffix(".srt")
        if not srt_path.exists():
            print(f"{tag} missing SRT: {srt_path}")
            failed += 1
            continue

        output_path = output_dir / video_path.name
        # Uji satu klip selalu menimpa, supaya perubahan preset benar-benar terlihat.
        if (output_path.exists() and output_path.stat().st_size > 0
                and not force and only_clip is None):
            print(f"{tag} skip existing: {output_path.name}")
            skipped += 1
            continue

        hook = str(clip.get("hook") or clip.get("title") or "").strip()
        # Headline SPESIFIK klip ini, diisi Stage 2 dari hasil review user.
        # SENGAJA tidak ada fallback ke `title`: manifest lama tidak punya field
        # `headline`, dan kalau `title` dipakai sebagai fallback maka semua render
        # lama akan tiba-tiba memakai judul klip dan MENGABAIKAN preset.headline.text
        # yang selama ini terpakai. Manifest lama harus berperilaku sama seperti dulu.
        clip_headline = str(clip.get("headline") or "").strip()

        print(f"{tag} {video_path.name}")
        try:
            render_clip(
                video_path=video_path,
                srt_path=srt_path,
                frame_path=frame_path,
                output_path=output_path,
                # Nama untuk WATERMARK, bukan untuk folder.
                creator=creator_watermark,
                hook=hook,
                video_title=video_title,
                preset=preset,
                headline=clip_headline,
            )
            rendered += 1
        except Exception as exc:
            failed += 1
            print(f"      ERROR: {exc}")

    # caption.txt untuk copy-paste. Ditulis SELALU (bukan hanya kalau ada render baru):
    # user bisa merender ulang satu klip saja, dan caption tetap harus lengkap.
    # Kegagalannya tidak boleh menjatuhkan render yang sudah jadi.
    try:
        caption_path = write_caption_file(
            output_dir,
            manifest,
            curation_folder=manifest_path.parent,
            creator=creator,
            video_title=video_title,
        )
        if caption_path is not None:
            print(f"Caption:  {caption_path}")
    except Exception as exc:  # noqa: BLE001
        print(f"      WARNING: caption.txt gagal ditulis: {exc}")

    print("-" * 72)
    print(f"Rendered: {rendered} | Skipped: {skipped} | Failed: {failed}")
    print(f"Final:    {output_dir}")

    if failed:
        raise RuntimeError(f"Stage 5 finished with {failed} failed clip(s).")


def run(
    manifest_path: Path | None = None,
    frame_path: Path | None = None,
    force: bool = False,
    preset_path: Path | None = None,
    only_clip: int | None = None,
) -> None:
    """Run Stage 5 from Python/main.py."""
    resolved_frame = (frame_path or DEFAULT_FRAME).resolve()
    if not resolved_frame.exists():
        raise FileNotFoundError(
            f"Frame not found: {resolved_frame}. "
            "Put the template at assets/frame.png."
        )

    preset = _load_preset_safe(resolve_preset_path(preset_path))

    # Frame Library: kalau preset menunjuk frame (id/path), pakai itu.
    # Kalau tidak, pakai frame_path argumen (default assets/frame.png = perilaku lama).
    frame_from_preset = _resolve_frame_from_preset(preset)
    if frame_from_preset is not None:
        resolved_frame = frame_from_preset.resolve()
        if not resolved_frame.exists():
            raise FileNotFoundError(f"Frame dari preset tidak ada: {resolved_frame}")

    if manifest_path is not None:
        manifests = [Path(manifest_path).resolve()]
    else:
        manifests = find_stage2_manifests(DEFAULT_CLIPS_ROOT)

    if not manifests:
        raise FileNotFoundError(
            f"No Stage 2 manifest.json found below {DEFAULT_CLIPS_ROOT}"
        )

    selected = (
        manifests[0]
        if len(manifests) == 1
        else max(manifests, key=lambda p: p.stat().st_mtime)
    )

    render_manifest(
        selected,
        frame_path=resolved_frame,
        final_root=DEFAULT_FINAL_ROOT,
        force=force,
        preset=preset,
        only_clip=only_clip,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clipper Stage 5: paper-frame portrait composition + burned subtitles."
    )
    parser.add_argument("--manifest-path", type=Path)
    parser.add_argument("--frame", type=Path, default=DEFAULT_FRAME)
    parser.add_argument("--final-root", type=Path, default=DEFAULT_FINAL_ROOT)
    parser.add_argument("--preset", type=Path, default=None,
                        help="Path ke render_preset.json (opsional; default = perilaku lama).")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--only-clip", type=int, default=None,
                        help="Render HANYA klip nomor N (1-based) dan timpa hasil lama. Untuk uji cepat.")
    args = parser.parse_args()

    frame_path = args.frame.resolve()
    if not frame_path.exists():
        raise FileNotFoundError(
            f"Frame not found: {frame_path}\n"
            "Put the Stage 5 template at assets/frame.png."
        )

    if frame_path.suffix.lower() != ".png":
        raise ValueError("Stage 5 frame must be a PNG.")

    preset = _load_preset_safe(resolve_preset_path(args.preset))

    # Frame Library: preset bisa menimpa pilihan frame CLI.
    frame_from_preset = _resolve_frame_from_preset(preset)
    if frame_from_preset is not None and frame_from_preset.exists():
        frame_path = frame_from_preset.resolve()

    if args.manifest_path:
        manifests = [args.manifest_path.resolve()]
    else:
        manifests = find_stage2_manifests(DEFAULT_CLIPS_ROOT)

    if not manifests:
        raise FileNotFoundError(
            f"No Stage 2 manifest.json found below {DEFAULT_CLIPS_ROOT}"
        )

    # Without an explicit manifest, use the newest Stage 2 manifest.
    manifest_path = max(manifests, key=lambda p: p.stat().st_mtime)

    render_manifest(
        manifest_path,
        frame_path=frame_path,
        final_root=args.final_root.resolve(),
        force=args.force,
        preset=preset,
        only_clip=args.only_clip,
    )


if __name__ == "__main__":
    main()

