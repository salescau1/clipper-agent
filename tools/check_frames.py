"""Ukur kualitas frame di Frame Library dengan membandingkannya ke frame-1 (acuan user).

Dipakai supaya penilaian "mirip kertas atau tidak" berdasarkan ANGKA, bukan kesan.
Metrik yang penting (ditemukan saat frame batch pertama terlihat seperti garis lurus):

  rentang        : selisih tertinggi-terendah profil tepi. frame-1 ~417px.
  std            : sebaran profil tepi.
  lonjakan_max   : perubahan terbesar antar kolom bersebelahan. frame-1 = 204px.
  std_lonjakan   : sebaran perubahan antar kolom. frame-1 = 7.9. Ini yang membedakan
                   tepi ROBEK (kasar) dari kurva halus (0.6).
  bibir_var      : koefisien variasi lebar bibir. 0 = stroke vektor lebar-tetap.

Jalankan: .venv/Scripts/python.exe tools/check_frames.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
FRAMES = ROOT / "assets" / "frames"


def edge_profile(png: Path) -> np.ndarray:
    """Profil tepi robekan per kolom.

    Ambang 128, BUKAN 250: pada ambang 250 tekstur dan bayangan ikut terhitung dan
    profilnya jadi tidak berhubungan dengan tepi robekan.

    Frame yang tidak punya kertas di atas (mis. `strip-kraft`, hanya strip bawah)
    membuat "baris tembus pertama" = 0 di semua kolom -> profil rata dan salah
    dilaporkan "terlalu halus". Untuk itu tepi yang diukur adalah baris tembus
    TERAKHIR (tepi bawah). Dipilih otomatis: kalau tepi atas hampir rata (std<1),
    pakai tepi bawah.
    """
    a = np.array(Image.open(png).convert("RGBA"))[:, :, 3]
    tembus = a < 128

    atas, bawah = [], []
    for x in range(a.shape[1]):
        idx = np.where(tembus[:, x])[0]
        atas.append(int(idx[0]) if len(idx) else -1)
        bawah.append(int(idx[-1]) if len(idx) else -1)

    pa = np.array(atas)[1:-1]
    pa = pa[pa >= 0]
    if len(pa) >= 10 and pa.std() >= 1.0:
        return pa
    pb = np.array(bawah)[1:-1]
    return pb[pb >= 0]


def lip_variation(png: Path) -> float:
    """Koefisien variasi lebar bibir terang di tepi atas jendela."""
    im = np.array(Image.open(png).convert("RGBA")).astype(np.float32)
    a = im[:, :, 3]
    terang = (im[:, :, 0] > 235) & (im[:, :, 1] > 228) & (im[:, :, 2] > 218) & (a > 200)
    lebar = terang.sum(axis=0).astype(np.float32)
    lebar = lebar[lebar > 0]
    if len(lebar) < 50:
        return 0.0
    return float(lebar.std() / (lebar.mean() or 1))


def main() -> int:
    baris = []
    for d in sorted(FRAMES.iterdir()):
        png = d / "frame.png"
        if not png.exists():
            continue
        p = edge_profile(png)
        if len(p) < 10:
            baris.append((d.name, 0, 0.0, 0, 0.0, 0.0))
            continue
        dd = np.diff(p)
        baris.append((d.name, int(p.max() - p.min()), float(p.std()),
                      int(np.abs(dd).max()), float(dd.std()), lip_variation(png)))

    print(f"{'frame':20s} {'rentang':>8s} {'std':>7s} {'lonjak':>7s} "
          f"{'std_lonj':>9s} {'bibir_var':>10s}")
    for n, rg, sd, lm, sl, lv in baris:
        print(f"{n:20s} {rg:8d} {sd:7.1f} {lm:7d} {sl:9.2f} {lv:10.2f}")

    acuan = {n: (rg, sl) for n, rg, sd, lm, sl, lv in baris if n == "frame-1"}
    if acuan:
        rg_a, sl_a = acuan["frame-1"]
        print(f"\nAcuan frame-1: rentang={rg_a}, std_lonjakan={sl_a:.2f}")
        kurang = [n for n, rg, sd, lm, sl, lv in baris
                  if n not in ("frame-1", "framesf") and sl < sl_a * 0.35]
        if kurang:
            print("TERLALU HALUS (tepinya tidak sekasar frame-1):", ", ".join(kurang))
        else:
            print("Semua frame baru sekasar acuan.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
