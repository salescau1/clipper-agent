"""
Clipper Stage 5 - Font Library.

Folder khusus font milik user:

    assets/fonts/
        subtitle.ttf     # bawaan (dilindungi, tidak bisa dihapus dari UI)
        title.ttf        # bawaan (dilindungi)
        <apa pun>.ttf    # font tambahan yang dimasukkan user
        <apa pun>.otf

Modul ini:
    * mendaftar semua font yang ada (list_fonts) + nama family aslinya,
    * mengimpor file font baru ke folder (import_font),
    * menghapus font tambahan (delete_font) — font bawaan dilindungi.

Dipakai oleh:
    * GUI (clipper_gui.PresetBridge.list_fonts / import_font_dialog / delete_font)
      untuk mengisi dropdown font di Customizer sekaligus @font-face preview,
    * Stage 5 (stage5_final) yang sudah membaca `preset.subtitle.font`,
      `preset.headline.font`, `preset.watermark.font` sebagai NAMA FILE
      di dalam folder ini.

Catatan penting: preset menyimpan NAMA FILE (mis. "Anton-Regular.ttf"),
bukan nama family CSS. Renderer ffmpeg butuh file, bukan family.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FONTS_DIR = ASSETS / "fonts"

# Ekstensi yang diterima. .ttc (collection) tidak dipakai: ffmpeg/libass
# butuh index face, bikin ribet — tolak saja supaya tidak gagal saat render.
ALLOWED_EXT = {".ttf", ".otf"}

# Font bawaan pipeline: dipakai sebagai fallback di stage5_fonts.py.
# Jangan biarkan user menghapusnya dari UI, nanti render gagal.
PROTECTED = {"subtitle.ttf", "title.ttf"}


# ------------------------------------------------------------------
# Nama family asli dari file font
# ------------------------------------------------------------------
def family_name(font_path: Path, fallback: str | None = None) -> str:
    """
    Ambil nama family dari tabel 'name' font (nameID 1, lalu 4).

    Dipakai untuk label dropdown di UI dan untuk Style ASS di Stage 5
    (libass mencocokkan berdasarkan family, bukan nama file).
    """
    fb = fallback or font_path.stem
    try:
        from fontTools.ttLib import TTFont
    except Exception:
        return fb
    try:
        font = TTFont(str(font_path), lazy=True, fontNumber=0)
        names = font["name"].names
        for name_id in (1, 4):
            for rec in names:
                if rec.nameID != name_id:
                    continue
                try:
                    value = rec.toUnicode().strip()
                except Exception:
                    continue
                if value:
                    return value
    except Exception:
        pass
    return fb


def _css_family(file_name: str) -> str:
    """
    Family CSS unik untuk preview di WebEngine.

    Sengaja diturunkan dari NAMA FILE (bukan family asli) supaya dua font
    dengan family sama tidak saling menimpa di preview.
    """
    stem = Path(file_name).stem
    safe = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in stem)
    return f"cf_{safe}"


# ------------------------------------------------------------------
# Query
# ------------------------------------------------------------------
def _entry(path: Path) -> dict[str, Any]:
    file_name = path.name
    return {
        "file": file_name,                      # yang masuk ke preset
        "path": str(path.resolve()),
        "family": family_name(path),            # nama asli, untuk label
        "css_family": _css_family(file_name),   # untuk @font-face preview
        "ext": path.suffix.lower(),
        "size_kb": round(path.stat().st_size / 1024, 1),
        "protected": file_name.lower() in PROTECTED,
    }


def list_fonts() -> list[dict[str, Any]]:
    """Semua font di assets/fonts/, terurut: bawaan dulu, lalu alfabetis."""
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    items = [
        _entry(p)
        for p in FONTS_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in ALLOWED_EXT
    ]
    items.sort(key=lambda f: (not f["protected"], f["family"].lower()))
    return items


def font_path(file_name: str) -> Path | None:
    """Path absolut sebuah font by nama file (None kalau tidak ada)."""
    name = Path(str(file_name or "")).name  # buang komponen direktori
    if not name:
        return None
    p = FONTS_DIR / name
    return p if p.is_file() else None


# ------------------------------------------------------------------
# Mutasi
# ------------------------------------------------------------------
def import_font(source: str | Path, new_name: str | None = None) -> dict[str, Any]:
    """
    Salin file font ke assets/fonts/.

    Return metadata font, atau {"error": "..."} kalau gagal.
    Nama file bentrok -> otomatis diberi sufiks -2, -3, dst.
    """
    src = Path(source)
    if not src.is_file():
        return {"error": f"File font tidak ada: {src}"}
    if src.suffix.lower() not in ALLOWED_EXT:
        return {"error": f"Format tidak didukung: {src.suffix} (pakai .ttf atau .otf)"}

    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    target = FONTS_DIR / (new_name or src.name)
    if target.resolve() == src.resolve():
        return _entry(target)  # sudah di folder font

    stem, suffix = target.stem, target.suffix
    n = 2
    while target.exists():
        target = FONTS_DIR / f"{stem}-{n}{suffix}"
        n += 1

    from shutil import copyfile
    try:
        copyfile(src, target)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Gagal menyalin: {exc}"}

    # Validasi: harus benar-benar bisa dibaca sebagai font.
    try:
        from fontTools.ttLib import TTFont
        TTFont(str(target), lazy=True, fontNumber=0)
    except Exception as exc:  # noqa: BLE001
        target.unlink(missing_ok=True)
        return {"error": f"File bukan font yang valid: {exc}"}

    return _entry(target)


def delete_font(file_name: str) -> dict[str, Any]:
    """
    Hapus font tambahan dari assets/fonts/.

    Menolak: nama kosong, path separator, font bawaan (subtitle.ttf/title.ttf),
    dan file di luar FONTS_DIR.
    """
    raw = str(file_name or "").strip()
    if not raw:
        return {"error": "nama font kosong"}
    if "/" in raw or "\\" in raw:
        return {"error": f"nama font tidak valid: {raw}"}
    if raw.lower() in PROTECTED:
        return {"error": f"{raw} adalah font bawaan pipeline, tidak bisa dihapus"}

    target = (FONTS_DIR / raw).resolve()
    try:
        target.relative_to(FONTS_DIR.resolve())
    except Exception:
        return {"error": "file di luar folder font"}
    if not target.is_file():
        return {"error": f"font tidak ditemukan: {raw}"}

    try:
        target.unlink()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"gagal menghapus: {exc}"}
    return {"deleted": raw}


if __name__ == "__main__":
    fonts = list_fonts()
    print(f"{len(fonts)} font di {FONTS_DIR}:")
    for f in fonts:
        tag = " [bawaan]" if f["protected"] else ""
        print(f"  - {f['file']:30s} {f['family']:28s} {f['size_kb']:8.1f} KB{tag}")
