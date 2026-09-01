"""
Clipper Stage 5 - Preset Library (theme tersimpan).

Satu "theme" = satu file preset JSON lengkap di:

    assets/presets/library/<id>.json

Berbeda dari `render_preset.active.json` (preset yang SEDANG dipakai render),
library ini menyimpan banyak theme bernama supaya user bisa gonta-ganti gaya
tanpa mengatur ulang semua slider.

API:
    list_presets()              -> daftar theme (id, name, ratio, updated, ringkasan)
    save_preset(preset, name)   -> simpan/overwrite theme
    load_preset_entry(id)       -> isi preset JSON theme
    delete_preset(id)           -> hapus theme
    rename_preset(id, name)     -> ubah nama tampilan
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LIBRARY_DIR = ROOT / "assets" / "presets" / "library"

# Field meta yang kita sisipkan ke dalam file theme (di luar skema render).
META_KEY = "_meta"


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", str(text or "").strip().lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "theme"


def _unique_id(base: str) -> str:
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    pid, n = base, 2
    while (LIBRARY_DIR / f"{pid}.json").exists():
        pid = f"{base}-{n}"
        n += 1
    return pid


def _summary(preset: dict[str, Any]) -> dict[str, Any]:
    """Ringkasan singkat untuk ditampilkan di kartu library."""
    canvas = preset.get("canvas") or {}
    sub = preset.get("subtitle") or {}
    frame = preset.get("frame") or {}
    w, h = int(canvas.get("w", 1080) or 1080), int(canvas.get("h", 1920) or 1920)
    return {
        "canvas": f"{w}x{h}",
        "ratio": ratio_label(w, h),
        "frame_id": str(frame.get("id") or ""),
        "subtitle_font": str(sub.get("font") or ""),
        "animation": str(sub.get("animation") or ""),
        "words_per_line": int(sub.get("words_per_line", 0) or 0),
    }


def ratio_label(w: int, h: int) -> str:
    """Label rasio yang manusiawi (mis. 9:16, 1:1, 4:5, 16:9)."""
    from math import gcd
    if w <= 0 or h <= 0:
        return "?"
    g = gcd(w, h)
    rw, rh = w // g, h // g
    known = {
        (9, 16): "9:16", (1, 1): "1:1", (4, 5): "4:5",
        (16, 9): "16:9", (4, 3): "4:3", (3, 4): "3:4",
        (2, 3): "2:3", (21, 9): "21:9",
    }
    return known.get((rw, rh), f"{rw}:{rh}")


def _entry(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    meta = data.get(META_KEY) or {}
    return {
        "id": path.stem,
        "name": str(meta.get("name") or path.stem.replace("-", " ").title()),
        "updated": float(meta.get("updated") or path.stat().st_mtime),
        "updated_text": time.strftime(
            "%d %b %Y %H:%M", time.localtime(float(meta.get("updated") or path.stat().st_mtime))
        ),
        "path": str(path.resolve()),
        **_summary(data),
    }


def list_presets() -> list[dict[str, Any]]:
    """Semua theme, terbaru dulu."""
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    items = [e for p in LIBRARY_DIR.glob("*.json") if (e := _entry(p))]
    items.sort(key=lambda e: e["updated"], reverse=True)
    return items


def load_preset_entry(preset_id: str) -> dict[str, Any]:
    """Isi preset sebuah theme (tanpa blok _meta)."""
    pid = Path(str(preset_id or "")).name
    path = LIBRARY_DIR / f"{pid}.json"
    if not path.is_file():
        return {"error": f"theme tidak ditemukan: {pid}"}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"gagal membaca theme: {exc}"}
    if not isinstance(data, dict):
        return {"error": "isi theme bukan objek JSON"}
    data.pop(META_KEY, None)
    return {"id": pid, "preset": data}


def find_by_name(name: str) -> dict[str, Any] | None:
    """Theme dengan nama tampilan yang sama (tidak peka huruf besar/kecil).

    Dipakai untuk menolak nama ganda: dua theme bernama sama membuat daftar di panel
    kiri mustahil dibedakan, dan user tidak punya cara tahu mana yang ia muat.
    """
    target = str(name or "").strip().lower()
    if not target:
        return None
    for e in list_presets():
        if str(e.get("name") or "").strip().lower() == target:
            return e
    return None


def save_preset(preset: dict[str, Any], name: str,
                preset_id: str | None = None,
                overwrite: bool = False) -> dict[str, Any]:
    """
    Simpan theme. `preset_id` diisi -> overwrite theme itu.
    Kosong -> buat id baru dari `name` (auto-suffix kalau bentrok).

    Nama HARUS unik (permintaan user 2026-08-30). Kalau nama sudah dipakai theme lain
    dan `overwrite` False, kembalikan {"error":..., "exists": <id>} supaya UI bisa
    menawarkan "timpa atau ganti nama" — bukan diam-diam membuat "Theme-2" yang
    tampak identik di daftar.
    """
    if not isinstance(preset, dict) or not preset:
        return {"error": "preset kosong"}
    display = str(name or "").strip() or "Theme"

    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    bentrok = find_by_name(display)
    if bentrok and bentrok["id"] != (Path(str(preset_id)).name if preset_id else None):
        if not overwrite:
            return {"error": f'nama "{display}" sudah dipakai', "exists": bentrok["id"],
                    "exists_name": bentrok["name"]}
        preset_id = bentrok["id"]

    if preset_id:
        pid = Path(str(preset_id)).name
    else:
        pid = _unique_id(_slug(display))

    data = dict(preset)
    data.pop(META_KEY, None)
    data[META_KEY] = {"name": display, "updated": time.time()}

    path = LIBRARY_DIR / f"{pid}.json"
    try:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return {"error": f"gagal menyimpan: {exc}"}
    return _entry(path) or {"error": "gagal membaca kembali theme"}


def delete_preset(preset_id: str) -> dict[str, Any]:
    """Hapus theme. Menolak id ber-separator / di luar LIBRARY_DIR."""
    raw = str(preset_id or "").strip()
    if not raw:
        return {"error": "id theme kosong"}
    if "/" in raw or "\\" in raw or raw in (".", ".."):
        return {"error": f"id tidak valid: {raw}"}
    path = (LIBRARY_DIR / f"{raw}.json").resolve()
    try:
        path.relative_to(LIBRARY_DIR.resolve())
    except Exception:
        return {"error": "file di luar library"}
    if not path.is_file():
        return {"error": f"theme tidak ditemukan: {raw}"}
    try:
        path.unlink()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"gagal menghapus: {exc}"}
    return {"deleted": raw}


def rename_preset(preset_id: str, name: str) -> dict[str, Any]:
    """Ubah nama tampilan theme (id/file tetap)."""
    got = load_preset_entry(preset_id)
    if got.get("error"):
        return got
    return save_preset(got["preset"], name, preset_id=got["id"])


if __name__ == "__main__":
    items = list_presets()
    print(f"{len(items)} theme di {LIBRARY_DIR}:")
    for e in items:
        print(f"  - {e['id']:24s} {e['name']:24s} {e['ratio']:6s} {e['updated_text']}")
