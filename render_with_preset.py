"""
Jembatan UI -> render (Fase D).

Mockup meng-*download* render_preset.json (biasanya ke folder Downloads).
Skrip ini mengambil preset itu lalu menjalankan Stage 5.

Pemakaian:
    # pakai preset terbaru di ~/Downloads (default):
    python render_with_preset.py

    # atau tunjuk preset eksplisit:
    python render_with_preset.py --preset "C:/path/render_preset.json"

    # opsi lain diteruskan ke Stage 5:
    python render_with_preset.py --manifest-path <m.json> --frame assets/frame.png --force

Preset disalin ke assets/presets/render_preset.active.json sebagai arsip
'preset aktif terakhir', lalu Stage 5 dijalankan dengan preset tsb.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "stages"))


def find_latest_preset() -> Path | None:
    """Cari render_preset.json terbaru di lokasi umum."""
    candidates: list[Path] = []
    search_dirs = [
        Path.home() / "Downloads",
        Path.home() / "Desktop",
        ROOT,
        ROOT / "assets" / "presets",
    ]
    for d in search_dirs:
        if d.exists():
            # render_preset.json dan varian render_preset (1).json dst.
            candidates.extend(d.glob("render_preset*.json"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render Stage 5 memakai preset dari UI.")
    parser.add_argument("--preset", type=Path, default=None,
                        help="Path preset. Default: render_preset.json terbaru di Downloads/Desktop/proyek.")
    parser.add_argument("--manifest-path", type=Path, default=None)
    parser.add_argument("--frame", type=Path, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--only-clip", type=int, default=None,
                        help="Render HANYA klip nomor N (1-based), timpa hasil lama. Uji cepat.")
    args = parser.parse_args()

    preset_path = args.preset or find_latest_preset()
    if preset_path is None or not Path(preset_path).exists():
        print("[ERROR] Tidak menemukan render_preset.json.")
        print("        Klik 'Save preset (JSON)' di mockup dulu, atau beri --preset <path>.")
        sys.exit(1)

    preset_path = Path(preset_path).resolve()
    print(f"[preset] pakai: {preset_path}")

    # Arsipkan sebagai preset aktif.
    presets_dir = ROOT / "assets" / "presets"
    presets_dir.mkdir(parents=True, exist_ok=True)
    active = presets_dir / "render_preset.active.json"
    try:
        shutil.copyfile(preset_path, active)
        print(f"[preset] arsip aktif: {active}")
    except Exception as exc:
        print(f"[warn] gagal arsip preset: {exc}")
        active = preset_path

    import stage5_final

    frame_path = args.frame.resolve() if args.frame else None
    print("[render] menjalankan Stage 5...\n")
    stage5_final.run(
        manifest_path=args.manifest_path,
        frame_path=frame_path,
        force=args.force,
        preset_path=active,
        only_clip=args.only_clip,
    )
    print("\n[render] selesai. Cek folder final/<creator>/<title>/")


if __name__ == "__main__":
    main()
