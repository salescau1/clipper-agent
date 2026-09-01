"""
Clipper Stage 5 — MESIN TEKS TUNGGAL (single source of truth).

Modul ini adalah SATU-SATUNYA tempat teks digambar di seluruh proyek. Baik preview di
tab Customize maupun hasil render MP4 memanggil fungsi yang sama, jadi keduanya bukan
"didekatkan" — mereka literal gambar yang sama.

Kenapa modul ini ada
--------------------
Sebelumnya preview memakai CSS (`-webkit-text-stroke`, `text-shadow`, `paint-order`)
sedangkan render memakai ffmpeg `drawtext` (`borderw`, `shadowx/y`). Tiga perbedaan
mendasar membuat hasilnya tidak akan pernah sama:

1. Auto-fit hanya ada di render. Preview memakai ukuran font apa adanya dan membungkus
   teks sebanyak apa pun baris; render mengecilkan font agar muat `max_lines`. Preset
   minta 117px -> render pakai 86px, dan user melihatnya sebagai "output tidak sesuai".
2. Urutan lapisan tidak bisa diatur di drawtext. Shadow selalu digambar paling bawah
   mengikuti siluet luar (fill + border), sementara CSS memakai `paint-order`. Efek 3D
   yang user inginkan (fill, lalu shadow, lalu outline sebagai lapisan terpisah)
   mustahil dari drawtext.
3. Pengukur lebar teks berbeda (mesin layout browser vs fontTools), jadi titik pecah
   baris selalu selisih beberapa piksel.

Alternatif yang DICOBA dan GAGAL: merender lapisan teks lewat QWebEngine supaya
mesin gambarnya benar-benar browser. `view.render(QImage)`, `view.grab()`, dan
software-rendering (`QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu`) semuanya menghasilkan
gambar 100% transparan — isi QWebEngine dikomposisi GPU di proses terpisah dan tidak
tersedia bagi widget. Jadi mesin tunggalnya adalah Pillow.

Model lapisan
-------------
Satu elemen teks digambar sebagai tumpukan, dari bawah ke atas:

    SHADOW  -> siluet teks digeser (shadow_x, shadow_y), warna sendiri, blur opsional
    STROKE  -> outline; outer = melebar keluar, inner = mengikis fill ke dalam
    FILL    -> isi huruf

`layer_order` mengizinkan menukar urutan STROKE dan FILL:
    "shadow-stroke-fill" (default, seperti sticker biasa)
    "shadow-fill-stroke" (fill dulu, stroke menimpa -> outline terlihat penuh di atas isi)

Catatan penting soal efek 3D: kalau warna shadow SAMA dengan warna stroke, keduanya
menyatu jadi satu massa dan kesan timbulnya hilang. Beri shadow warna berbeda
(mis. outline hitam + shadow abu tua) atau offset lebih besar.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = ROOT / "assets" / "fonts"

# Cache font agar tidak membaca file berulang saat preview digeser-geser.
_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}
# Cache pengukuran lebar teks: auto-fit memanggil ini puluhan kali per perubahan.
_WIDTH_CACHE: dict[tuple[str, str, int], float] = {}


def font_path(name: str | None) -> Path:
    """Resolusi nama file font ke path absolut di assets/fonts/."""
    n = str(name or "title.ttf").strip() or "title.ttf"
    p = FONTS_DIR / n
    if p.exists():
        return p
    fallback = FONTS_DIR / "title.ttf"
    return fallback if fallback.exists() else p


def load_font(name: str | None, size: int) -> ImageFont.FreeTypeFont:
    p = font_path(name)
    key = (str(p), int(size))
    hit = _FONT_CACHE.get(key)
    if hit is None:
        hit = ImageFont.truetype(str(p), int(size))
        _FONT_CACHE[key] = hit
    return hit


def text_width(text: str, font_name: str | None, size: int) -> float:
    key = (str(text), str(font_name or ""), int(size))
    hit = _WIDTH_CACHE.get(key)
    if hit is None:
        font = load_font(font_name, size)
        hit = _MEASURE.textlength(text, font=font)
        _WIDTH_CACHE[key] = hit
    return hit


# Kanvas 1x1 khusus untuk mengukur; membuat ImageDraw baru tiap panggil itu mahal.
_MEASURE = ImageDraw.Draw(Image.new("RGBA", (1, 1)))


def line_advance(font_name: str | None, size: int, gap_ratio: float) -> int:
    """
    Jarak antar baris dalam piksel.

    gap_ratio adalah RASIO terhadap tinggi baris natural font (negatif = merapat).
    Memakai rasio, bukan piksel absolut, supaya nilai tetap benar setelah auto-fit
    mengubah ukuran font — nilai absolut lama (-50 px) menjadi 2px saat font turun ke
    52px dan membuat baris saling menimpa.
    """
    font = load_font(font_name, size)
    asc, desc = font.getmetrics()
    natural = asc + desc
    adv = int(round(natural * (1.0 + float(gap_ratio))))
    # Jangan pernah kurang dari 45% tinggi natural: di bawah itu baris pasti bertumpuk.
    return max(int(round(natural * 0.45)), adv)


def wrap_to_lines(
    text: str, font_name: str | None, size: int, max_width: float, max_lines: int
) -> list[str] | None:
    """
    Bungkus teks ke maksimal `max_lines` baris selebar `max_width`.

    Return None kalau tidak muat (pemanggil harus mengecilkan font).
    Kata yang lebih lebar dari max_width tidak bisa dipecah -> None.
    """
    words = str(text or "").split()
    if not words:
        return []
    lines: list[str] = []
    cur = ""
    for w in words:
        if text_width(w, font_name, size) > max_width and not cur:
            return None
        cand = f"{cur} {w}".strip()
        if text_width(cand, font_name, size) <= max_width:
            cur = cand
        else:
            lines.append(cur)
            cur = w
            if len(lines) >= max_lines:
                return None
    if cur:
        lines.append(cur)
    return lines if len(lines) <= max_lines else None


def fit_text(
    text: str,
    font_name: str | None,
    *,
    max_size: int,
    min_size: int,
    max_width: float,
    max_lines: int,
) -> tuple[int, list[str]]:
    """
    Cari ukuran font TERBESAR (<= max_size) yang membuat teks muat.

    Ini pengukur yang SAMA dengan penggambar, jadi hasil fit selalu konsisten dengan
    hasil gambar. Kalau sampai min_size masih tidak muat, pakai min_size dan potong
    ke max_lines.
    """
    hi = max(1, int(max_size))
    lo = max(1, min(int(min_size), hi))
    for size in range(hi, lo - 1, -1):
        lines = wrap_to_lines(text, font_name, size, max_width, max_lines)
        if lines is not None:
            return size, lines
    # paksa di min_size
    words = str(text or "").split()
    lines: list[str] = []
    cur = ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if cur and text_width(cand, font_name, lo) > max_width:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lo, lines[: max(1, int(max_lines))]


def _norm_word_specs(specs: Iterable[dict] | None) -> list[dict] | None:
    """
    Normalkan daftar spesifikasi PER KATA.

    Dipakai animasi subtitle `word` / `karaoke`: setiap kata bisa punya warna dan
    skala sendiri (kata aktif dibesarkan / diberi warna lain). Bentuk tiap item:
        {"t": "KATA", "color": "#RRGGBB" | None, "scale": 1.0}
    """
    if specs is None:
        return None
    out: list[dict] = []
    for s in specs:
        if not isinstance(s, dict):
            out.append({"t": str(s), "color": None, "scale": 1.0})
            continue
        out.append({
            "t": str(s.get("t", "")),
            "color": s.get("color") or None,
            "scale": max(0.05, float(s.get("scale", 1.0) or 1.0)),
        })
    return out


def map_specs_to_lines(
    lines: list[str], specs: list[dict] | None
) -> list[list[dict]] | None:
    """
    Petakan daftar spec kata (urutan baca) ke baris hasil pembungkusan.

    Pembungkusan baris dihitung dari teks polos (fit_text), jadi spec per kata harus
    dipotong mengikuti jumlah kata tiap baris. Kalau jumlah kata tidak cocok,
    kembalikan None supaya pemanggil jatuh ke penggambaran biasa (lebih baik teks
    benar tanpa highlight daripada teks rusak).
    """
    if not specs:
        return None
    per_line = [len(str(ln).split()) for ln in lines]
    if sum(per_line) != len(specs):
        return None
    out: list[list[dict]] = []
    i = 0
    for n in per_line:
        out.append(specs[i:i + n])
        i += n
    return out


def _rgba(color: str | tuple, alpha: int = 255) -> tuple[int, int, int, int]:
    """Terima '#RRGGBB', '#RGB', atau tuple. Selalu kembalikan RGBA."""
    if isinstance(color, (tuple, list)):
        vals = list(color) + [alpha]
        return (int(vals[0]), int(vals[1]), int(vals[2]), int(vals[3]))
    s = str(color or "#FFFFFF").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        s = "FFFFFF"
    try:
        r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError:
        r, g, b = 255, 255, 255
    return (r, g, b, int(alpha))


# ---------------------------------------------------------------------------
# Penggambar lapisan
# ---------------------------------------------------------------------------
def _draw_lines(
    target: Image.Image,
    lines: Iterable[str],
    *,
    font: ImageFont.FreeTypeFont,
    canvas_w: int,
    x: int,
    y: int,
    advance: int,
    align: str,
    fill: tuple,
    stroke_w: int = 0,
    stroke_fill: tuple | None = None,
    margin: int = 0,
    font_name: str | None = None,
    size: int = 0,
    word_specs: list[list[dict]] | None = None,
    force_color: tuple | None = None,
) -> None:
    """
    Gambar tiap baris pada posisi yang sama seperti yang dihitung auto-fit.

    align: "left" | "center" | "right" — perataan TIAP BARIS di dalam zona teks
    (zona = margin .. canvas_w - margin). `x` adalah geseran halus (nudge) yang
    ditambahkan setelah perataan, jadi slider Geser X tetap berfungsi di semua mode.

    Stroke melebar keluar glyph, jadi untuk left/right zona dikurangi `stroke_w`
    supaya garis tepi tidak terpotong tepi kanvas.

    word_specs: kalau diisi (satu list per baris), tiap kata digambar sendiri dengan
    warna dan skala ukurannya masing-masing — inilah cara subtitle `word`/`karaoke`
    membesarkan + mewarnai kata aktif. Baseline semua kata disejajarkan (tipografi
    normal) supaya kata yang diperbesar tidak melompat ke atas/bawah.
    force_color: paksa semua kata memakai warna ini (dipakai lapisan SHADOW, yang
    hanya butuh siluet).
    """
    d = ImageDraw.Draw(target)
    a = str(align or "center").lower()
    pad = int(stroke_w)
    left_edge = int(margin) + pad
    right_edge = int(canvas_w) - int(margin) - pad
    lines = list(lines)
    base_ascent = font.getmetrics()[0]

    def word_font(scale: float) -> ImageFont.FreeTypeFont:
        if not size or abs(scale - 1.0) < 1e-3:
            return font
        return load_font(font_name, max(4, int(round(size * scale))))

    for i, ln in enumerate(lines):
        ly = y + i * advance
        specs = word_specs[i] if (word_specs and i < len(word_specs)) else None
        if not specs:
            lw = d.textlength(ln, font=font)
            if a == "left":
                lx = left_edge
            elif a == "right":
                lx = right_edge - lw
            else:
                lx = (canvas_w - lw) / 2.0
            d.text((lx + x, ly), ln, font=font, fill=fill,
                   stroke_width=int(stroke_w), stroke_fill=stroke_fill)
            continue

        # ---- per kata: ukur dulu total lebar agar perataan tetap benar ----
        space_w = d.textlength(" ", font=font)
        widths = [d.textlength(sp["t"], font=word_font(sp["scale"])) for sp in specs]
        lw = sum(widths) + space_w * max(0, len(specs) - 1)
        if a == "left":
            lx = left_edge
        elif a == "right":
            lx = right_edge - lw
        else:
            lx = (canvas_w - lw) / 2.0
        cx = lx + x
        for sp, wpx in zip(specs, widths):
            wf = word_font(sp["scale"])
            col = force_color if force_color is not None else (
                _rgba(sp["color"], fill[3]) if sp["color"] else fill
            )
            # anchor "ls" = kiri, BASELINE. Perlu supaya kata berskala berbeda tetap
            # duduk di garis yang sama; anchor default ("la") menyejajarkan ascender,
            # jadi kata yang diperbesar akan turun.
            d.text((cx, ly + base_ascent), sp["t"], font=wf, fill=col, anchor="ls",
                   stroke_width=int(stroke_w), stroke_fill=stroke_fill)
            cx += wpx + space_w


def render_text_layer(
    *,
    canvas_w: int,
    canvas_h: int,
    text: str,
    font_name: str | None,
    size: int,
    lines: list[str] | None = None,
    x: int = 0,
    y: int = 0,
    align: str = "center",
    line_gap: float = -0.25,
    color: str | tuple = "#FFFFFF",
    stroke_w: int = 0,
    stroke_color: str | tuple = "#000000",
    stroke_mode: str = "outer",
    shadow_x: int = 0,
    shadow_y: int = 0,
    shadow_color: str | tuple = "#000000",
    shadow_opacity: int = 255,
    shadow_blur: float = 0.0,
    layer_order: str = "shadow-stroke-fill",
    margin: int = 0,
    word_specs: list[list[dict]] | None = None,
) -> Image.Image:
    """
    Gambar satu elemen teks ke PNG RGBA transparan seukuran kanvas.

    Dipakai IDENTIK oleh preview (dikirim ke UI sebagai data URL) dan oleh render
    (dioverlay ke video lewat ffmpeg). Itulah inti jaminan "preview == output".

    lines: kalau None, teks dipakai apa adanya (dipecah pada '\\n'). Pemanggil yang
    ingin auto-fit harus memanggil fit_text() lebih dulu dan meneruskan hasilnya,
    supaya ukuran & pemecahan baris dihitung sekali saja.
    """
    if lines is None:
        lines = [ln for ln in str(text or "").splitlines()] or [""]
    font = load_font(font_name, size)
    adv = line_advance(font_name, size, line_gap)
    fill = _rgba(color)
    scol = _rgba(stroke_color)
    inner = str(stroke_mode).lower() == "inner" and int(stroke_w) > 0

    img = Image.new("RGBA", (int(canvas_w), int(canvas_h)), (0, 0, 0, 0))

    def blank() -> Image.Image:
        return Image.new("RGBA", (int(canvas_w), int(canvas_h)), (0, 0, 0, 0))

    # Argumen yang identik untuk setiap lapisan — supaya SHADOW, STROKE dan FILL
    # tidak mungkin memakai layout/perataan yang berbeda.
    common = dict(font=font, canvas_w=canvas_w, advance=adv, align=align,
                  margin=margin, font_name=font_name, size=size,
                  word_specs=word_specs)

    # ---- SHADOW: siluet penuh digeser. Selalu lapisan paling bawah. ----
    if int(shadow_x) or int(shadow_y):
        sh = blank()
        shc = _rgba(shadow_color, max(0, min(255, int(shadow_opacity))))
        # Siluet shadow mengikuti bentuk TERLUAR: untuk outer stroke berarti
        # fill+stroke, untuk inner stroke siluetnya sama dengan fill saja.
        # force_color: shadow adalah SILUET, jadi warna per kata diabaikan —
        # kalau tidak, bayangan kata aktif ikut berwarna dan efek 3D-nya rusak.
        _draw_lines(sh, lines, x=int(x) + int(shadow_x), y=int(y) + int(shadow_y),
                    fill=shc, force_color=shc,
                    stroke_w=0 if inner else int(stroke_w), stroke_fill=shc, **common)
        if float(shadow_blur) > 0:
            sh = sh.filter(ImageFilter.GaussianBlur(float(shadow_blur)))
        img = Image.alpha_composite(img, sh)

    # ---- STROKE + FILL ----
    if inner:
        # Inner stroke: siluet penuh berwarna stroke, lalu fill dikikis ke dalam
        # sebanyak stroke_w px (MinFilter mengecilkan area opak alpha).
        st = blank()
        _draw_lines(st, lines, x=int(x), y=int(y), fill=scol, force_color=scol, **common)
        img = Image.alpha_composite(img, st)

        fl = blank()
        _draw_lines(fl, lines, x=int(x), y=int(y), fill=fill, **common)
        k = max(1, min(int(stroke_w), 25))
        alpha = fl.split()[3].filter(ImageFilter.MinFilter(k * 2 + 1))
        fl.putalpha(alpha)
        img = Image.alpha_composite(img, fl)
    elif str(layer_order) == "shadow-fill-stroke" and int(stroke_w) > 0:
        # fill dulu, stroke MENIMPA di atasnya -> outline terlihat utuh penuh lebar
        # (ini yang membuat kesan "sticker tebal" / 3D lebih tegas).
        fl = blank()
        _draw_lines(fl, lines, x=int(x), y=int(y), fill=fill, **common)
        img = Image.alpha_composite(img, fl)

        st = blank()
        _draw_lines(st, lines, x=int(x), y=int(y), fill=(0, 0, 0, 0),
                    force_color=(0, 0, 0, 0),
                    stroke_w=int(stroke_w), stroke_fill=scol, **common)
        img = Image.alpha_composite(img, st)
    else:
        # default: stroke di bawah fill, satu operasi (paling cepat)
        ly = blank()
        _draw_lines(ly, lines, x=int(x), y=int(y), fill=fill,
                    stroke_w=int(stroke_w), stroke_fill=scol, **common)
        img = Image.alpha_composite(img, ly)

    return img


# ---------------------------------------------------------------------------
# Jembatan preset -> parameter mesin
# ---------------------------------------------------------------------------
# Zona horizontal elemen teks: 7% margin kiri/kanan, sama untuk preview dan render.
ZONE_MARGIN_RATIO = 0.07

# Versi tanda tangan cache layer preview. Naikkan kalau bentuk metadata berubah.
_SIG_VERSION = 2


def zone_width(canvas_w: int) -> int:
    return max(120, int(canvas_w) - int(round(canvas_w * ZONE_MARGIN_RATIO)) * 2)


def _norm_align(value: Any) -> str:
    """Terima 'left'/'center'/'right' (juga 'l'/'c'/'r'); default center."""
    a = str(value or "center").strip().lower()
    if a in ("left", "l", "start"):
        return "left"
    if a in ("right", "r", "end"):
        return "right"
    return "center"


def block_params(
    block: dict[str, Any], canvas_w: int, *, default_font: str = "title.ttf"
) -> dict[str, Any]:
    """
    Ubah satu blok preset (headline / watermark) menjadi argumen render_text_layer.

    Menerima skema BARU (shadow_x/shadow_y/shadow_color/layer_order) maupun LAMA
    (shadow: int) supaya preset lama tetap terbaca:
      - `shadow` int lama dipakai sebagai offset x DAN y (itu perilaku drawtext dulu).
      - `line_spacing` bernilai absolut (|v| > 1) dikonversi ke rasio.
    """
    font_name = str(block.get("font") or default_font)
    max_size = int(block.get("size", 86))
    min_size = max(20, int(block.get("min_size", max(28, max_size // 2))))
    max_lines = max(1, int(block.get("max_lines", 1)))

    raw_gap = block.get("line_spacing", -0.25)
    try:
        gap = float(raw_gap)
    except (TypeError, ValueError):
        gap = -0.25
    if abs(gap) > 1.0:                     # nilai absolut lama (px pada font ~86)
        gap = gap / 86.0
    gap = max(-0.55, min(1.0, gap))

    shadow_on = bool(block.get("shadow_enabled", True))
    legacy = int(block.get("shadow", 0) or 0)
    sx = int(block.get("shadow_x", legacy))
    sy = int(block.get("shadow_y", legacy))
    if not shadow_on:
        sx = sy = 0

    return {
        "font_name": font_name,
        "max_size": max_size,
        "min_size": min_size,
        "max_lines": max_lines,
        "line_gap": gap,
        "color": str(block.get("color") or "#FFFFFF"),
        "stroke_w": abs(int(block.get("outline", 0) or 0)),
        "stroke_color": str(block.get("outline_color") or "") or None,
        "stroke_mode": str(block.get("outline_mode", "outer")),
        "shadow_x": sx,
        "shadow_y": sy,
        "shadow_color": str(block.get("shadow_color") or "#000000"),
        "shadow_opacity": int(block.get("shadow_opacity", 255)),
        "shadow_blur": float(block.get("shadow_blur", 0) or 0),
        "layer_order": str(block.get("layer_order") or "shadow-stroke-fill"),
        "align": _norm_align(block.get("align")),
    }


def render_block(
    block: dict[str, Any],
    *,
    canvas_w: int,
    canvas_h: int,
    text: str,
    default_font: str = "title.ttf",
    auto_stroke_color: str | None = None,
    word_specs: Iterable[dict] | None = None,
    ink_out: dict[str, Any] | None = None,
) -> tuple[Image.Image, int, list[str]]:
    """
    Auto-fit + gambar satu blok preset. Return (layer PNG, ukuran terpakai, baris).

    Titik masuk tunggal yang dipakai BAIK preview MAUPUN render.

    word_specs: opsional, satu item per kata (`{"t","color","scale"}`) untuk animasi
    subtitle per-kata. Auto-fit tetap memakai teks polos, lalu spec dipetakan ke baris
    hasil pembungkusan. Kalau jumlah kata tidak cocok, spec diabaikan (teks tetap
    benar, hanya tanpa highlight).

    ink_out: kalau diberi dict, diisi pengukuran KOTAK TINTA teks (fill+stroke, TANPA
    shadow) beserta dua angka yang dibutuhkan UI untuk slider zero-center:
      dy_top = jarak tepi atas tinta dari nilai `y` yang diminta
      dcx    = simpangan pusat tinta dari (tengah kanvas + geseran x)
    Keduanya TIDAK bergantung pada `x`/`y`, hanya pada font/ukuran/isi teks — jadi UI
    bisa menghitung posisi tengah dalam SEKALI jalan, tanpa umpan balik berulang.
    """
    p = block_params(block, canvas_w, default_font=default_font)
    margin = int(round(canvas_w * ZONE_MARGIN_RATIO))
    zone = zone_width(canvas_w)
    # Stroke melebar keluar glyph; kurangi zona agar garis tepi tidak terpotong.
    fit_zone = max(60, zone - p["stroke_w"] * 2)
    specs = _norm_word_specs(list(word_specs) if word_specs is not None else None)
    # Kata aktif bisa DIBESARKAN (scale > 1) sehingga baris jadi lebih lebar daripada
    # teks polos. Kecilkan zona fit sesuai skala terbesar supaya kata yang membesar
    # tetap tidak keluar zona / terpotong.
    if specs:
        mx = max((s["scale"] for s in specs), default=1.0)
        if mx > 1.0:
            fit_zone = max(60, int(fit_zone / mx))
    size, lines = fit_text(text, p["font_name"], max_size=p["max_size"],
                           min_size=p["min_size"], max_width=fit_zone,
                           max_lines=p["max_lines"])
    stroke_color = p["stroke_color"] or auto_stroke_color or "#000000"
    line_specs = map_specs_to_lines(lines, specs) if specs else None

    # `x` preset diperlakukan sebagai GESERAN HALUS dari margin kiri baku (45px pada
    # kanvas 1080), bukan posisi absolut. Dengan begitu perataan left/center/right yang
    # menentukan posisi dasar, dan slider Geser X tetap bisa menggeser dari situ.
    base_x = int(round(45 * (canvas_w / 1080.0)))
    x_off = int(block.get("x", base_x)) - base_x

    layer = render_text_layer(
        canvas_w=canvas_w, canvas_h=canvas_h, text=text, lines=lines,
        font_name=p["font_name"], size=size,
        x=x_off, y=int(block.get("y", 55)), align=p["align"],
        line_gap=p["line_gap"], color=p["color"],
        stroke_w=p["stroke_w"], stroke_color=stroke_color,
        stroke_mode=p["stroke_mode"],
        shadow_x=p["shadow_x"], shadow_y=p["shadow_y"],
        shadow_color=p["shadow_color"], shadow_opacity=p["shadow_opacity"],
        shadow_blur=p["shadow_blur"], layer_order=p["layer_order"],
        margin=margin, word_specs=line_specs,
    )
    if ink_out is not None:
        ink_out.update(
            measure_ink(
                lines=lines, font_name=p["font_name"], size=size,
                canvas_w=canvas_w, canvas_h=canvas_h, align=p["align"],
                line_gap=p["line_gap"], stroke_w=p["stroke_w"], margin=margin,
                x_off=x_off, y=int(block.get("y", 55)), word_specs=line_specs,
            )
        )
    return layer, size, lines


def measure_ink(
    *,
    lines: list[str],
    font_name: str | None,
    size: int,
    canvas_w: int,
    canvas_h: int,
    align: str,
    line_gap: float,
    stroke_w: int,
    margin: int,
    x_off: int,
    y: int,
    word_specs: list[list[dict]] | None = None,
) -> dict[str, Any]:
    """
    Ukur kotak tinta teks (fill + stroke, TANPA shadow) tanpa menggambar lapisan penuh.

    Kenapa perlu terpisah dari `layer.getbbox()`: bbox lapisan jadi ikut melebar oleh
    shadow dan blur, jadi memakai bbox untuk memusatkan teks akan menggeser teks
    sebesar offset shadow — persis kelas bug "preview tidak sama dengan render".

    Mengembalikan juga `dy_top` dan `dcx`, dua angka yang membuat pemusatan bisa
    dihitung dalam SEKALI jalan:
        y  yang memusatkan vertikal = (canvas_h - h) // 2 - dy_top
        x_off yang memusatkan horizontal = x_off_sekarang - dcx
    """
    img = Image.new("RGBA", (int(canvas_w), int(canvas_h)), (0, 0, 0, 0))
    font = load_font(font_name, size)
    adv = line_advance(font_name, size, line_gap)
    _draw_lines(
        img, lines, font=font, canvas_w=canvas_w, x=int(x_off), y=int(y),
        advance=adv, align=align, fill=(255, 255, 255, 255),
        stroke_w=int(stroke_w), stroke_fill=(255, 255, 255, 255),
        margin=int(margin), font_name=font_name, size=size,
        word_specs=word_specs, force_color=(255, 255, 255, 255),
    )
    bbox = img.getbbox()
    if not bbox:
        return {}
    x0, y0, x1, y1 = (int(v) for v in bbox)
    w, h = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    return {
        "x": x0, "y": y0, "w": w, "h": h, "cx": cx, "cy": cy,
        # jarak tepi atas tinta dari `y` yang diminta (ascender/leading font)
        "dy_top": y0 - int(y),
        # simpangan pusat tinta dari tengah kanvas setelah geseran x diterapkan
        "dcx": cx - (int(canvas_w) // 2 + int(x_off)),
    }


def layer_signature(*parts: Any) -> str:
    """Hash pendek untuk nama file cache layer preview.

    `_SIG_VERSION` HARUS dinaikkan setiap kali METADATA yang disimpan bersama PNG
    bertambah/berubah bentuk. Tanpa itu, cache dari versi lama tetap dipakai
    (`png.exists()` true) dan field baru — mis. `ink` untuk slider zero-center — akan
    selamanya hilang di mesin yang pernah menjalankan versi sebelumnya. Ini bukan
    hipotesis: pemusatan teks terbaca melenceng 8-24px justru karena hal ini.
    """
    h = hashlib.sha1(
        ("|".join(str(p) for p in parts) + f"|v{_SIG_VERSION}").encode("utf-8")
    )
    return h.hexdigest()[:16]
