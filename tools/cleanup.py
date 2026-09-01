"""Bersihkan file/folder yang tidak terpakai di proyek Clipper.

DUA TINGKAT, sengaja dibedakan:

  HAPUS       - benar-benar sampah yang dibuat ulang otomatis atau hasil sementara
                (pycache, m4a temp WhisperX, log kosong, log rotasi).
  KARANTINA   - file yang TIDAK dirujuk kode mana pun tapi mungkin masih kamu
                anggap berharga (backup lama, sketsa UI yang tak dipakai, PNG duplikat).
                Dipindah ke `_trash_<tanggal>/` supaya bisa dibalikkan. Hapus sendiri
                kalau sudah yakin.

`final/` dan `output/` TIDAK DISENTUH (permintaan user).

Cara pakai:
    .venv/Scripts/python.exe tools/cleanup.py --dry-run    # lihat dulu
    .venv/Scripts/python.exe tools/cleanup.py              # kerjakan
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ----------------------------------------------------------------------
# HAPUS: dibuat ulang otomatis / hasil sementara
# ----------------------------------------------------------------------
HAPUS_GLOB = [
    "**/__pycache__",
    ".pytest_cache",
    "temp/*.m4a",           # salinan audio WhisperX, ~250MB/berkas
    "logs/*.log.[0-9]",     # log rotasi
]

# ----------------------------------------------------------------------
# KARANTINA: tidak dirujuk kode (sudah diperiksa dengan grep), tapi bukan sampah jelas
# ----------------------------------------------------------------------
KARANTINA = [
    # backup manual di root
    "config.STABLE.py",
    "main.py.backup",
    "stage5_error.txt",
    "stage5_errornew.txt",
    # backup manual di stages/
    "stages/Backup",
    "stages/stage1_curate.STABLE.py",
    "stages/stage2_download back.py",
    "stages/main.py",                 # entry point lama; yang dipakai adalah ./main.py
    # sketsa UI yang tidak pernah ditanam di GUI
    "sketches/clipper-operator-console",
    "sketches/clipper-review-studio",
    "sketches/clipper-ui-mockup/index.dashboard-backup.html",
    "sketches/clipper-ui-mockup/index.pre-v2-backup.html",
    # PNG duplikat / tak dirujuk
    "assets/Frame 1.png",             # sama byte-per-byte dgn frames/frame-1/frame.png
    "assets/overlays/kelap kelip.png",  # sama dgn kelap-kelip.png (yang dipakai preset)
    "assets/overlays/2.png",
    "assets/overlays/820d6a6ac0a0f9c19dc6c63b1e2d0e2f.png",
]

# JANGAN disentuh walau kelihatan menganggur — ada kode yang merujuknya:
#   assets/frame.png, assets/framesf.png   -> frame_library._SEED_SPEC (seed kalau
#                                             library kosong)
#   assets/stage5_layout_reference.png     -> stage5_fonts.LAYOUT_REFERENCE
#   assets/gui_settings.json               -> pilihan bahasa UI
#   logs/clipper.log                       -> log aktif, dibaca tab Run
#   logs/gui_run*.log                      -> 0 byte tapi dipakai run_clipper_gui.ps1


def ukuran(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def fmt(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    total_hapus = 0
    print("=== HAPUS (dibuat ulang otomatis / sementara) ===")
    for pola in HAPUS_GLOB:
        for p in sorted(ROOT.glob(pola)):
            # jaring pengaman: jangan pernah menyentuh final/ atau output/
            rel = p.relative_to(ROOT)
            if rel.parts and rel.parts[0] in ("final", "output", ".venv", ".whisperx-venv"):
                continue
            n = ukuran(p)
            total_hapus += n
            print(f"  {fmt(n):>8s}  {rel}")
            if not args.dry_run:
                shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)

    trash = ROOT / f"_trash_{datetime.now():%Y%m%d}"
    total_k = 0
    print(f"\n=== KARANTINA -> {trash.name}/ (bisa dibalikkan) ===")
    for nama in KARANTINA:
        p = ROOT / nama
        if not p.exists():
            print(f"  (tidak ada)  {nama}")
            continue
        n = ukuran(p)
        total_k += n
        print(f"  {fmt(n):>8s}  {nama}")
        if not args.dry_run:
            tujuan = trash / nama
            tujuan.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(tujuan))

    print(f"\nDihapus    : {fmt(total_hapus)}")
    print(f"Dikarantina: {fmt(total_k)}  -> {trash}")
    if args.dry_run:
        print("\n(dry-run: belum ada yang diubah)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
