"""
Clipper Stage 5 - Render preset (Fase A).

Satu file JSON (render_preset.json) adalah SATU-SATUNYA kontrak antara mockup UI
dan renderer Stage 5. Modul ini:

    * mendefinisikan DEFAULT_PRESET yang meniru PERSIS perilaku hardcoded lama,
    * memuat preset JSON dari disk dan meng-*merge* di atas default (deep merge),
    * menyediakan helper konversi warna hex -> ASS (&HAABBGGRR) dan -> drawtext (0xRRGGBB),
    * menurunkan geometri video (scale relatif lebar canvas, center horizontal).

Kalau preset tidak ada / field kosong -> nilai default lama dipakai, jadi render
lama tetap identik (tidak ada regresi).

Mapping UI <-> engine (dikunci 2026-08-27):
    UI "Headline"  -> menggantikan penuh "hook" lama (teks bisa dari Gemini sebagai default)
    UI "Watermark" -> "creator" (nama kreator)
    video.scale    -> relatif LEBAR canvas; 1.0 = penuh 1080px, center horizontal
    subtitle.animation -> none|pop|fade|up|word|karaoke
    custom_png     -> layer overlay baru (path,x,y,width)
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


# ------------------------------------------------------------------
# DEFAULT PRESET — meniru konstanta hardcoded lama di stage5_final.py
# ------------------------------------------------------------------
# Canvas & video default disamakan dengan stage5_final.py:
#   CANVAS 1080x1920, VIDEO 1080x608 @ Y=675  => video.scale = 1.0
#   SUBTITLE size 80 @ Y=1190, animasi word-pop, outline 6
DEFAULT_PRESET: dict[str, Any] = {
    "canvas": {"w": 1080, "h": 1920},
    "frame": {
        # id = frame di assets/frames/<id>/ (Frame Library). Kosong => pakai
        # frame_path yang diteruskan Stage 5 (default assets/frame.png = perilaku lama).
        "id": "",
        "path": "",
    },
    "video": {
        "scale": 1.0,      # 1.0 = penuh lebar canvas (1080px), center horizontal
        "x": 0,            # GESERAN dari tengah (0 = center) — slider zero-center
        "y": 675,          # top-left Y video di canvas
        "radius": 0,       # sudut membulat (belum dipakai render, disiapkan)
        "aspect": "16/9",  # rasio sumber Stage 2 (fixed)
        "blur_background": False,
        "blur_radius": 40,
    },
    "subtitle": {
        "font": "subtitle.ttf",
        "size": 80,
        "y": 1190,
        # Subtitle digambar stages/text_engine.py (mesin yang SAMA dengan preview dan
        # headline/watermark), bukan libass. Karena itu ia punya kunci yang sama:
        # perataan, maks baris, jarak baris rasio, dan shadow sebagai lapisan sendiri.
        "align": "center",
        "max_lines": 2,
        "line_spacing": -0.15,     # rasio tinggi baris natural (bukan piksel)
        "outline": 6,
        "outline_mode": "outer",    # outer = stroke di luar glyph, inner = mengikis ke dalam
        "outline_color": "",        # kosong -> auto kontras (lihat auto_border_color)
        "shadow": 3,                # legacy: dibaca sebagai shadow_x = shadow_y
        "shadow_enabled": True,     # False -> shadow dipaksa 0
        "shadow_x": 3,
        "shadow_y": 3,
        "shadow_color": "#000000",
        "shadow_blur": 0,
        "layer_order": "shadow-stroke-fill",
        "color": "#FFFFFF",         # warna normal
        "active_color": "#FFA500",  # warna kata aktif (oranye) untuk word/karaoke
        "animation": "word",        # none|pop|fade|up|word|karaoke
        # Kerapatan subtitle: 1 / 3 / 5 kata (dibakukan di theme 2026-08-30).
        # 0 masih diterima demi preset lama = "pakai baris SRT apa adanya", tapi UI
        # tidak lagi menawarkannya. `regroup_entries()` bisa MEMECAH maupun
        # MENGGABUNGKAN, jadi mengubah nilai ini tidak butuh Stage 4 ulang.
        "words_per_line": 3,
        # parameter word-pop lama
        "inactive_scale": 0.80,
        "active_scale": 1.00,
        "pop_duration": 0.18,
    },
    # headline & watermark digambar oleh stages/text_engine.py (mesin yang SAMA dengan
    # preview). Shadow adalah LAPISAN sendiri: offset x/y terpisah, warna sendiri, blur,
    # dan urutan lapisan bisa ditukar. Field `shadow` (satu int) dari preset lama tetap
    # dibaca dan dipakai sebagai offset x=y.
    "headline": {                    # dulu "hook"
        "enabled": True,
        "text": "",                  # kosong -> diisi Gemini sbagai default
        "gemini_default": True,      # True: Gemini menulis default text ke preset
        "font": "title.ttf",
        "size": 86,
        "x": 45,
        "y": 55,
        "color": "#D94B0A",
        "outline": 6,
        "outline_mode": "outer",
        "outline_color": "",        # kosong -> auto kontras
        "align": "center",          # left | center | right (per baris, dalam zona 86%)
        "shadow_enabled": True,
        "shadow_x": 8,
        "shadow_y": 8,
        "shadow_color": "#000000",  # BEDAKAN dari outline_color kalau mau efek 3D
        "shadow_blur": 0,           # 0 = bayangan keras (paling tegas untuk 3D)
        "layer_order": "shadow-stroke-fill",   # atau "shadow-fill-stroke"
        "line_spacing": -0.25,   # RASIO thd tinggi baris font (negatif = merapat);
                                 # nilai absolut lama (mis. -50) otomatis dikonversi
        "max_lines": 2,
    },
    "watermark": {                   # dulu "creator"
        "enabled": True,
        # "Creator!" = PENANDA, bukan teks harfiah: dipakai sebagai contoh di preview,
        # lalu diganti nama kreator dari manifest saat render. Kosong juga otomatis.
        # Daftar penanda lengkap: stage5_final.AUTO_WATERMARK_TOKENS.
        "text": "Creator!",
        "font": "title.ttf",
        "size": 130,
        "x": 45,
        "y": 55,
        "color": "#D94B0A",
        "outline": 7,
        "outline_mode": "outer",
        "outline_color": "",        # kosong -> auto kontras
        "align": "center",          # left | center | right
        "shadow_enabled": True,
        "shadow_x": 6,
        "shadow_y": 6,
        "shadow_color": "#000000",
        "shadow_blur": 0,
        "layer_order": "shadow-stroke-fill",
        "max_lines": 1,
    },
    "custom_png": {                  # elemen BARU
        "enabled": False,
        "path": "",
        "x": 16,
        "y": 84,
        "width": 220,
        # 0..1 (1 = opak). Ditambahkan 2026-08-30 atas permintaan user; preset lama
        # tanpa field ini otomatis dianggap 1.0.
        "opacity": 1.0,
    },
    # Intro Cover (bug.txt item 12): lapisan penutup di detik-detik AWAL video, untuk
    # feed TikTok/Shorts yang memakai frame pertama sebagai thumbnail.
    #
    # Yang membuatnya berbeda dari "video diawali gambar": video dan audio utama TETAP
    # BERJALAN dari detik ke-0 di latar. Cover hanya lapisan di atasnya yang memudar.
    # Kalau video di-freeze/di-geser, durasi klip berubah dan subtitle jadi meleset —
    # itu sebabnya pendekatan overlay yang dipakai, bukan concat.
    "intro": {
        "enabled": False,
        # Durasi tampil cover, DETIK. 0.3-0.5 = rentang yang diminta user: cukup untuk
        # ditangkap sebagai thumbnail feed, tapi nyaris tak terasa saat ditonton.
        "duration": 0.4,
        # Lama fade out, detik. Dibatasi <= duration saat render.
        "fade": 0.15,
        # Gambar latar cover, relatif ke root proyek (mis. assets/intro/cover.png).
        # Kosong -> pakai latar gelap polos supaya teks tetap terbaca.
        "background": "",
        # Teks di cover memakai blok `headline` dan `watermark` yang SAMA (font, warna,
        # outline, shadow), tapi selalu di-center di kanvas — bukan mengikuti x/y-nya.
        # Alasannya: cover adalah komposisi terpisah, dan menaruh teksnya di posisi
        # layout video justru membuatnya tampak salah tempat.
        "show_headline": True,
        "show_creator": True,
    },
    "export": {"w": 1080, "h": 1920, "crf": 18, "preset": "medium"},
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge `override` di atas `base` secara rekursif (non-destruktif)."""
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if (
            key in out
            and isinstance(out[key], dict)
            and isinstance(value, dict)
        ):
            out[key] = _deep_merge(out[key], value)
        elif value is not None:
            out[key] = value
    return out


def load_preset(path: str | Path | None) -> dict[str, Any]:
    """
    Muat preset JSON dan merge di atas DEFAULT_PRESET.

    path None / tidak ada -> kembalikan default penuh (perilaku lama).
    """
    if not path:
        return copy.deepcopy(DEFAULT_PRESET)
    p = Path(path)
    if not p.exists():
        return copy.deepcopy(DEFAULT_PRESET)
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # preset korup -> jangan bikin render gagal
        raise ValueError(f"Preset JSON tidak bisa dibaca: {p}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Preset harus objek JSON: {p}")
    return _deep_merge(DEFAULT_PRESET, data)


# ------------------------------------------------------------------
# KONVERSI WARNA
# ------------------------------------------------------------------
def _hex_rgb(value: str) -> tuple[int, int, int]:
    s = str(value or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        raise ValueError(f"Warna hex tidak valid: {value!r}")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def hex_to_ass(value: str) -> str:
    """#RRGGBB -> &H00BBGGRR (ASS: alpha=00 opaque, urutan BGR)."""
    # nilai yang sudah format ASS dibiarkan
    if str(value or "").startswith("&H"):
        return value
    r, g, b = _hex_rgb(value)
    return f"&H00{b:02X}{g:02X}{r:02X}"


def hex_to_drawtext(value: str) -> str:
    """#RRGGBB -> 0xRRGGBB (untuk ffmpeg drawtext fontcolor)."""
    if str(value or "").startswith("0x"):
        return value
    r, g, b = _hex_rgb(value)
    return f"0x{r:02X}{g:02X}{b:02X}"


def auto_border_color(fill: str, override: str | None = None) -> str:
    """
    Warna garis tepi (drawtext bordercolor) yang selalu kontras dengan fill.

    Kenapa perlu: default lama selalu `bordercolor=white`. Kalau teksnya juga
    putih, border melebarkan setiap glyph tanpa memberi pemisah sehingga
    huruf-huruf menyatu jadi gumpalan (headline jadi tidak terbaca).

    `override` (preset.<blok>.outline_color) selalu menang bila diisi.
    Selain itu: fill terang -> border hitam, fill gelap -> border putih.
    """
    if override:
        return hex_to_drawtext(override)
    try:
        r, g, b = _hex_rgb(fill)
    except Exception:
        return "black"
    # Luminansi relatif (Rec. 709) — ambang 0.6 supaya kuning/oranye terang
    # (yang umum dipakai di sini) tetap dapat border hitam.
    lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
    return "black" if lum > 0.6 else "white"


def ratio_label(w: int, h: int) -> str:
    """Label rasio manusiawi dari ukuran canvas (mis. 9:16, 1:1, 4:5)."""
    from math import gcd
    if int(w) <= 0 or int(h) <= 0:
        return "?"
    g = gcd(int(w), int(h))
    rw, rh = int(w) // g, int(h) // g
    known = {
        (9, 16): "9:16", (1, 1): "1:1", (4, 5): "4:5", (16, 9): "16:9",
        (4, 3): "4:3", (3, 4): "3:4", (2, 3): "2:3", (21, 9): "21:9",
    }
    return known.get((rw, rh), f"{rw}:{rh}")


# ------------------------------------------------------------------
# UKURAN CANVAS / EXPORT UMUM
# ------------------------------------------------------------------
# Dipakai UI untuk dropdown rasio. `id` disimpan di preset.canvas.id supaya
# pilihan user bisa dipulihkan; renderer sendiri hanya butuh w/h.
CANVAS_PRESETS: list[dict[str, Any]] = [
    {"id": "9x16",     "w": 1080, "h": 1920, "ratio": "9:16",
     "label": "9:16 Vertical", "use": "Shorts / Reels / TikTok"},
    {"id": "9x16-hd",  "w": 720,  "h": 1280, "ratio": "9:16",
     "label": "9:16 Vertical (720p)", "use": "Vertical ringan"},
    {"id": "4x5",      "w": 1080, "h": 1350, "ratio": "4:5",
     "label": "4:5 Portrait", "use": "Feed Instagram"},
    {"id": "1x1",      "w": 1080, "h": 1080, "ratio": "1:1",
     "label": "1:1 Square", "use": "Feed / carousel"},
    {"id": "16x9",     "w": 1920, "h": 1080, "ratio": "16:9",
     "label": "16:9 Landscape", "use": "YouTube biasa"},
    {"id": "16x9-hd",  "w": 1280, "h": 720,  "ratio": "16:9",
     "label": "16:9 Landscape (720p)", "use": "Landscape ringan"},
    {"id": "4x3",      "w": 1440, "h": 1080, "ratio": "4:3",
     "label": "4:3 Classic", "use": "Klasik / presentasi"},
]


def canvas_preset(preset_id: str) -> dict[str, Any] | None:
    for c in CANVAS_PRESETS:
        if c["id"] == preset_id:
            return c
    return None


def scale_preset_canvas(preset: dict[str, Any], new_w: int, new_h: int) -> dict[str, Any]:
    """
    Ubah ukuran canvas preset dan SKALAKAN semua koordinat/ukuran ikut serta.

    Tanpa ini, mengganti 1080x1920 -> 1080x1080 akan meninggalkan subtitle di
    y=1190 (di luar frame). Skala X pakai rasio lebar, skala Y pakai rasio tinggi,
    ukuran font pakai rasio yang lebih kecil supaya tidak meluber.
    """
    out = copy.deepcopy(preset)
    old = out.get("canvas") or {}
    ow, oh = int(old.get("w", 1080) or 1080), int(old.get("h", 1920) or 1920)
    nw, nh = int(new_w), int(new_h)
    if ow <= 0 or oh <= 0 or nw <= 0 or nh <= 0:
        return out
    sx, sy = nw / ow, nh / oh
    ss = min(sx, sy)

    def r(v: float) -> int:
        return int(round(v))

    out["canvas"] = {"w": nw, "h": nh}
    exp = out.get("export") or {}
    exp["w"], exp["h"] = nw, nh
    out["export"] = exp

    vid = out.get("video") or {}
    if "x" in vid:
        vid["x"] = r(float(vid.get("x", 0)) * sx)
    if "y" in vid:
        vid["y"] = r(float(vid.get("y", 0)) * sy)
    if "radius" in vid:
        vid["radius"] = r(float(vid.get("radius", 0)) * ss)
    out["video"] = vid

    for key, sxk, syk in (("subtitle", sx, sy), ("headline", sx, sy), ("watermark", sx, sy)):
        blk = out.get(key) or {}
        for f, mul in (("x", sxk), ("y", syk)):
            if f in blk:
                blk[f] = r(float(blk.get(f, 0)) * mul)
        # Nilai PIKSEL diskalakan. `line_spacing` SENGAJA tidak ada di daftar ini:
        # ia sudah rasio terhadap tinggi baris font, jadi mengalikannya dengan ss
        # akan merusak jarak baris setiap kali rasio kanvas diubah.
        for f in ("size", "outline", "shadow", "shadow_x", "shadow_y", "shadow_blur"):
            if f in blk and blk.get(f) is not None:
                blk[f] = r(float(blk.get(f, 0)) * ss)
        if "max_x" in blk:
            blk["max_x"] = r(float(blk["max_x"]) * sx)
        out[key] = blk

    png = out.get("custom_png") or {}
    for f, mul in (("x", sx), ("y", sy), ("width", ss)):
        if f in png:
            png[f] = r(float(png.get(f, 0)) * mul)
    out["custom_png"] = png
    return out


# ------------------------------------------------------------------
# GEOMETRI VIDEO (scale relatif lebar canvas, center horizontal)
# ------------------------------------------------------------------
def video_geometry(preset: dict[str, Any]) -> dict[str, int]:
    """
    Turunkan geometri video dari preset.

    scale 1.0 => lebar video = lebar canvas (center horizontal).
    Tinggi mengikuti rasio sumber (aspect "W/H").
    Kembalikan dict: w, h, x, y (semua int, top-left based).
    """
    canvas = preset["canvas"]
    video = preset["video"]
    cw = int(canvas["w"])
    ch = int(canvas["h"])
    scale = float(video.get("scale", 1.0))

    vw = max(2, int(round(cw * scale)))
    # rasio sumber
    aspect = str(video.get("aspect", "16/9"))
    try:
        num, den = aspect.split("/")
        ratio = float(num) / float(den)
    except Exception:
        ratio = 16 / 9
    vh = max(2, int(round(vw / ratio)))

    # lebar genap (libx264 butuh genap); tinggi genap
    if vw % 2:
        vw -= 1
    if vh % 2:
        vh -= 1

    x = (cw - vw) // 2            # center horizontal
    # `video.x` adalah GESERAN dari tengah (0 = center), sejalan dengan slider
    # zero-center di Customize. Absennya field ini dulu membuat slider X video tidak
    # mungkin ada: renderer selalu memaksa center dan preview jadi berbeda.
    x += int(video.get("x", 0) or 0)
    y = int(video.get("y", (ch - vh) // 2))
    return {"w": vw, "h": vh, "x": x, "y": y}


if __name__ == "__main__":
    # smoke test manual
    d = load_preset(None)
    print("default subtitle:", d["subtitle"]["size"], d["subtitle"]["animation"])
    print("video geom:", video_geometry(d))
    print("ass white:", hex_to_ass("#FFFFFF"), "ass orange:", hex_to_ass("#FFA500"))
    print("drawtext:", hex_to_drawtext("#D94B0A"))
