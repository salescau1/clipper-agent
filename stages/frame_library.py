"""
Clipper Stage 5 - Frame Library.

Sebuah "frame" adalah overlay PNG 9:16 (transparan di jendela video) plus metadata.
Setiap frame hidup di folder sendiri:

    assets/frames/<id>/
        frame.png       # overlay 1080x1920 (RGBA)
        thumbnail.png    # thumbnail kecil untuk grid UI
        frame.json       # metadata (id, name, category, tags, slot default, dst.)

Modul ini:
    * menemukan semua frame (list_frames),
    * meresolusi 1 frame by id (get_frame / frame_png_path),
    * menyemai frame awal dari aset lama (assets/frame.png, assets/framesf.png)
      bila folder assets/frames masih kosong (ensure_seed_frames).

Dipakai oleh:
    * GUI (clipper_gui.PresetBridge.list_frames) untuk mengisi grid Frame Library,
    * Stage 5 (stage5_final.run) untuk memilih frame.png yang benar dari preset.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FRAMES_DIR = ASSETS / "frames"

CANVAS_W, CANVAS_H = 1080, 1920
THUMB_W = 240  # lebar thumbnail (tinggi mengikuti rasio 9:16 -> 426)


# ------------------------------------------------------------------
# Metadata default (dipakai untuk melengkapi frame.json yang tak lengkap)
# ------------------------------------------------------------------
def _default_meta(frame_id: str) -> dict[str, Any]:
    return {
        "id": frame_id,
        "name": frame_id.replace("-", " ").replace("_", " ").title(),
        "category": "general",
        "tags": [],
        "ratio": "9:16",
        "canvas": {"w": CANVAS_W, "h": CANVAS_H},
        # slot default meniru geometri hardcoded lama Stage 5
        "video_slot": {"scale": 1.0, "y": 675, "radius": 0, "aspect": "16/9"},
        "subtitle_slot": {"y": 1190, "size": 80},
        "headline_slot": {"x": 45, "y": 55, "size": 86},
        "recommended_subtitle": {
            "animation": "word",
            "color": "#FFFFFF",
            "active_color": "#FFA500",
        },
    }


def _read_meta(frame_dir: Path) -> dict[str, Any]:
    """Baca frame.json + isi default yang hilang. Selalu paksa id = nama folder."""
    meta = _default_meta(frame_dir.name)
    fj = frame_dir / "frame.json"
    if fj.exists():
        try:
            data = json.loads(fj.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                meta.update({k: v for k, v in data.items() if v is not None})
        except Exception:
            pass
    meta["id"] = frame_dir.name  # id selalu = folder (sumber kebenaran)
    return meta


# ------------------------------------------------------------------
# Thumbnail
# ------------------------------------------------------------------
def _make_thumbnail(src_png: Path, dst_png: Path, width: int = THUMB_W) -> bool:
    """Buat thumbnail dari frame.png. Return True kalau berhasil."""
    try:
        from PIL import Image
    except Exception:
        return False
    try:
        im = Image.open(src_png).convert("RGBA")
        ratio = im.height / im.width if im.width else CANVAS_H / CANVAS_W
        height = max(1, int(round(width * ratio)))
        thumb = im.resize((width, height), Image.LANCZOS)
        # Latar putih supaya jendela transparan tetap terbaca di grid gelap/terang.
        bg = Image.new("RGBA", thumb.size, (255, 255, 255, 255))
        bg.alpha_composite(thumb)
        dst_png.parent.mkdir(parents=True, exist_ok=True)
        bg.convert("RGB").save(dst_png, "PNG")
        return True
    except Exception:
        return False


# ------------------------------------------------------------------
# Seeding: bikin frame awal dari aset lama kalau folder frames kosong
# ------------------------------------------------------------------
_SEED_SPEC = [
    # (source png relatif ke assets, id, name, category, tags)
    ("frame.png", "torn-paper-branded", "Torn Paper — Branded",
     "review", ["review", "viral"]),
    ("framesf.png", "torn-paper-plain", "Torn Paper — Plain",
     "clean", ["clean", "review"]),
]


def ensure_seed_frames() -> None:
    """Kalau assets/frames belum punya frame apa pun, seed dari aset lama."""
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    existing = [d for d in FRAMES_DIR.iterdir() if d.is_dir() and (d / "frame.png").exists()]
    if existing:
        return
    for src_name, fid, name, category, tags in _SEED_SPEC:
        src = ASSETS / src_name
        if not src.exists():
            continue
        _create_frame_dir(fid, src, name=name, category=category, tags=tags)


def _create_frame_dir(
    frame_id: str,
    source_png: Path,
    *,
    name: str | None = None,
    category: str = "general",
    tags: list[str] | None = None,
) -> Path:
    """Bikin assets/frames/<id>/ dari sebuah PNG sumber. Return folder frame."""
    frame_dir = FRAMES_DIR / frame_id
    frame_dir.mkdir(parents=True, exist_ok=True)
    dst_png = frame_dir / "frame.png"

    from shutil import copyfile
    copyfile(source_png, dst_png)

    _make_thumbnail(dst_png, frame_dir / "thumbnail.png")

    meta = _default_meta(frame_id)
    meta["name"] = name or meta["name"]
    meta["category"] = category
    meta["tags"] = tags or []
    (frame_dir / "frame.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return frame_dir


def import_frame(source_png: str | Path, frame_id: str | None = None,
                 **meta_kwargs: Any) -> dict[str, Any]:
    """Impor PNG jadi frame baru di library. Return metadata frame."""
    src = Path(source_png)
    if not src.exists():
        raise FileNotFoundError(f"Source PNG tidak ada: {src}")
    fid = frame_id or src.stem.lower().replace(" ", "-")
    _create_frame_dir(fid, src, **meta_kwargs)
    return _read_meta(FRAMES_DIR / fid)


def delete_frame(frame_id: str) -> dict[str, Any]:
    """
    Hapus satu frame dari library (buang seluruh folder assets/frames/<id>/).

    Aman: menolak id kosong, id ber-path separator, dan folder di luar FRAMES_DIR.
    Return {"deleted": id} atau {"error": "..."}.
    """
    fid = str(frame_id or "").strip()
    if not fid:
        return {"error": "id frame kosong"}
    if "/" in fid or "\\" in fid or fid in (".", ".."):
        return {"error": f"id frame tidak valid: {fid}"}

    frame_dir = (FRAMES_DIR / fid).resolve()
    try:
        # pastikan benar-benar di dalam FRAMES_DIR (cegah path traversal)
        frame_dir.relative_to(FRAMES_DIR.resolve())
    except Exception:
        return {"error": f"folder di luar library: {frame_dir}"}
    if not frame_dir.is_dir():
        return {"error": f"frame tidak ditemukan: {fid}"}

    from shutil import rmtree
    try:
        rmtree(frame_dir)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"gagal menghapus: {exc}"}
    return {"deleted": fid}



# ------------------------------------------------------------------
# Query API
# ------------------------------------------------------------------
def frame_png_path(frame_id: str) -> Path | None:
    """Path ke frame.png untuk sebuah id (None kalau tidak ada)."""
    if not frame_id:
        return None
    p = FRAMES_DIR / frame_id / "frame.png"
    return p if p.exists() else None


def get_frame(frame_id: str) -> dict[str, Any] | None:
    """Metadata satu frame (+ path absolut) atau None."""
    frame_dir = FRAMES_DIR / (frame_id or "")
    if not (frame_dir / "frame.png").exists():
        return None
    return _entry(frame_dir)


def window_bounds(frame_png: Path) -> dict[str, int] | None:
    """
    Batas atas/bawah jendela frame (baris yang MAYORITAS lebarnya tembus cahaya).

    Ambang mayoritas (>50% piksel alpha < 250) wajib: tekstur/anti-alias artwork bikin
    hampir setiap baris punya beberapa piksel semi-transparan, jadi kriteria "ada satu
    piksel tembus" akan melaporkan seluruh kanvas sebagai jendela.

    Dipakai oleh preview UI dan Stage 5 supaya kotak video dijamin menutup jendela;
    kalau lebih pendek, latar hitam bocor sebagai strip gelap di tepi robekan.
    """
    try:
        from PIL import Image
        import numpy as np
    except Exception:
        return None
    try:
        alpha = np.array(Image.open(frame_png).convert("RGBA"))[:, :, 3]
    except Exception:
        return None
    width = alpha.shape[1]
    rows = np.where((alpha < 250).sum(axis=1) > width * 0.5)[0]
    if not len(rows):
        return None
    return {"top": int(rows[0]), "bottom": int(rows[-1])}


def _entry(frame_dir: Path) -> dict[str, Any]:
    meta = _read_meta(frame_dir)
    frame_png = frame_dir / "frame.png"
    thumb = frame_dir / "thumbnail.png"
    if not thumb.exists():
        _make_thumbnail(frame_png, thumb)
    meta["frame_path"] = str(frame_png.resolve())
    meta["thumbnail_path"] = str(thumb.resolve()) if thumb.exists() else ""
    # batas jendela video (di-cache ke frame.json agar tak menghitung alpha tiap kali)
    win = meta.get("window")
    if not (isinstance(win, dict) and "top" in win and "bottom" in win):
        win = window_bounds(frame_png)
        if win:
            meta["window"] = win
            try:
                fj = frame_dir / "frame.json"
                data = json.loads(fj.read_text(encoding="utf-8-sig")) if fj.exists() else {}
                if isinstance(data, dict):
                    data["window"] = win
                    fj.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                  encoding="utf-8")
            except Exception:
                pass
    # path relatif proyek (dipakai di preset agar portabel)
    try:
        meta["rel_path"] = str(frame_png.resolve().relative_to(ROOT)).replace("\\", "/")
    except Exception:
        meta["rel_path"] = str(frame_png.resolve()).replace("\\", "/")
    return meta


def list_frames(seed: bool = True) -> list[dict[str, Any]]:
    """Semua frame di library (seed dari aset lama bila kosong)."""
    if seed:
        ensure_seed_frames()
    if not FRAMES_DIR.exists():
        return []
    out: list[dict[str, Any]] = []
    for frame_dir in sorted(FRAMES_DIR.iterdir()):
        if frame_dir.is_dir() and (frame_dir / "frame.png").exists():
            out.append(_entry(frame_dir))
    return out


def resolve_frame_from_preset(preset: dict[str, Any] | None) -> Path | None:
    """
    Tentukan frame.png dari preset.

    Prioritas: preset.frame.id (library) > preset.frame.path (rel/abs) > None.
    """
    if not preset:
        return None
    frame = preset.get("frame") or {}
    if not isinstance(frame, dict):
        return None
    fid = str(frame.get("id") or "").strip()
    if fid:
        p = frame_png_path(fid)
        if p:
            return p
    raw = str(frame.get("path") or "").strip()
    if raw:
        p = Path(raw)
        if not p.is_absolute():
            p = (ROOT / p).resolve()
        if p.exists():
            return p
    return None


if __name__ == "__main__":
    frames = list_frames()
    print(f"{len(frames)} frame:")
    for f in frames:
        print(f"  - {f['id']:24s} {f['name']:28s} tags={f['tags']} thumb={bool(f['thumbnail_path'])}")
