"""Bandingkan frame baru dengan frame-1 pada metrik yang BISA diukur.

Dipakai karena penilaian mata (termasuk model vision) tidak konsisten: satu putaran
bilang "tidak ada anti-alias" padahal mask sudah pakai clip 1px, dan bilang "tidak ada
bayangan" padahal alpha di luar kertas > 0. frame-1 adalah acuan yang user sudah
terima, jadi patokannya: metrik frame baru harus SEBANDING dengan frame-1.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
FRAMES = ROOT / "assets" / "frames"


def metrics(png: Path) -> dict[str, float]:
    im = np.array(Image.open(png).convert("RGBA")).astype(np.float32)
    a = im[:, :, 3]
    H, W = a.shape

    # profil tepi: baris pertama tembus (alpha<128); kalau rata, pakai baris terakhir
    tembus = a < 128
    atas, bawah = [], []
    for x in range(W):
        idx = np.where(tembus[:, x])[0]
        atas.append(int(idx[0]) if len(idx) else -1)
        bawah.append(int(idx[-1]) if len(idx) else -1)
    pa = np.array(atas)[1:-1]
    pa = pa[pa >= 0]
    prof = pa if (len(pa) > 10 and pa.std() >= 1.0) else np.array(bawah)[1:-1]
    prof = prof[prof >= 0]

    # WANDER lambat: setelah dihaluskan kuat, berapa lebar lenggokannya
    ker = np.ones(120) / 120.0
    lambat = np.convolve(prof.astype(np.float32), ker, mode="valid")
    wander = float(lambat.max() - lambat.min())

    # ANTI-ALIAS: piksel alpha di tengah (bukan 0/255) sebagai rasio panjang tepi
    tengah = ((a > 12) & (a < 243)).sum()
    aa = float(tengah / max(1, len(prof)))

    # BAYANGAN: piksel di sisi jendela yang alpha kecil tapi bukan nol
    # (kertas = alpha 255; bayangan = alpha 1..200)
    bayang = float(((a > 2) & (a < 200)).sum() / max(1, len(prof)))

    d = np.diff(prof.astype(np.float32))
    return {
        "rentang": float(prof.max() - prof.min()),
        "wander_lambat": wander,
        "std_lonjakan": float(d.std()),
        "aa_per_kolom": aa,
        "bayang_per_kolom": bayang,
    }


def main() -> int:
    nama = ["frame-1"] + sorted(
        d.name for d in FRAMES.iterdir()
        if (d / "frame.png").exists() and d.name not in ("frame-1", "framesf"))
    rows = [(n, metrics(FRAMES / n / "frame.png")) for n in nama]

    kunci = ["rentang", "wander_lambat", "std_lonjakan", "aa_per_kolom", "bayang_per_kolom"]
    print(f"{'frame':20s}" + "".join(f"{k:>17s}" for k in kunci))
    for n, m in rows:
        print(f"{n:20s}" + "".join(f"{m[k]:17.1f}" for k in kunci))

    acuan = rows[0][1]
    # `strip-kraft` hanya punya SATU tepi robek (strip bawah), jadi jumlah piksel
    # anti-alias dan bayangan per kolom wajar sekitar setengah frame dua-tepi.
    # Ini bukan cacat — jangan "diperbaiki" dengan menaikkan blur.
    SATU_TEPI = {"strip-kraft"}
    print("\nPatokan = frame-1. Frame baru yang di bawah 40% acuan:")
    ada = False
    for n, m in rows[1:]:
        batas = 0.4 * (0.5 if n in SATU_TEPI else 1.0)
        kurang = [k for k in ("wander_lambat", "std_lonjakan", "aa_per_kolom",
                              "bayang_per_kolom")
                  if m[k] < acuan[k] * batas]
        if kurang:
            ada = True
            print(f"  {n:20s} kurang: {', '.join(kurang)}")
    if not ada:
        print("  (tidak ada)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
