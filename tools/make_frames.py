"""Pembuat frame 'kertas robek' untuk Frame Library Clipper.

Sistemnya diambil dari `assets/frames/frame-1/frame.png` yang sudah dipakai user:
kanvas 1080x1920 RGBA, dua bidang kertas (atas & bawah) dengan tepi ROBEK, serat
vertikal halus, bibir terang di tepi robekan, dan bayangan lembut yang jatuh KE ARAH
jendela. Jendela (alpha 0) itu tempat video muncul.

Dijalankan: .venv/Scripts/python.exe tools/make_frames.py
Hasil: assets/frames/<id>/{frame.png,thumbnail.png,frame.json}

CATATAN KENAPA KODENYA BEGINI (versi pertama gagal di empat hal ini, semuanya
ketemu saat memeriksa PNG hasilnya, bukan saat membaca kode):

1. Tepi robek butuh lapis frekuensi LAMBAT yang besar. Kalau hanya getaran halus,
   tepinya bergerak beberapa piksel saja melintasi 1080px -> terlihat seperti garis
   lurus ber-EKG. Sekarang lapis lambatnya ±31px.
2. Gigi jangan selebar 1px. Paku 1px membaca sebagai noise digital. Sekarang benjolan
   6-22px yang ditapis lagi.
3. Bibir tepi harus BERUBAH-UBAH lebarnya dan tidak putih murni. Stroke lebar-tetap
   yang mengikuti jalur persis adalah ciri paling jelas gambar vektor. Lebar bibir di
   sini dikendalikan noise per kolom, kadang 0 (robekan bersih), kadang 3x rata-rata.
4. Bayangan harus DITURUNKAN DARI MASK yang digeser, bukan gradien linear. Gradien
   linear tidak ikut melenggok mengikuti tepi — itu ketidakcocokan yang paling mudah
   terlihat. Sekarang: mask digeser ke arah jendela lalu di-blur 16px, dan warnanya
   ditarik ke arah warna kertas (bukan abu netral).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
FRAMES = ROOT / "assets" / "frames"
W, H = 1080, 1920


# ----------------------------------------------------------------------
# Bentuk tepi robek
# ----------------------------------------------------------------------
def _smooth_noise(n_out: int, scale: int, r: np.random.Generator) -> np.ndarray:
    """Noise 1D halus dalam -1..1 dengan panjang gelombang ~`scale` piksel."""
    n = r.normal(0, 1, max(3, n_out // scale + 3))
    xp = np.linspace(0, n_out - 1, len(n))
    v = np.interp(np.arange(n_out), xp, n)
    return v / (np.abs(v).max() or 1)


def torn_edge(width: int, amp: float, seed: int) -> np.ndarray:
    """Offset per kolom untuk satu tepi robek (rata-rata 0).

    Empat komponen. Yang keempat (kekasaran lokal) baru ditambahkan setelah MENGUKUR
    frame-1: profil tepinya punya lonjakan antar-kolom sampai 204px dengan
    std_lonjakan 7.9, sedangkan versi halus buatan saya hanya 3px / 0.6. Tanpa itu
    tepinya mulus seperti kurva — bukan kertas. Ukur ulang dengan
    `tools/check_frames.py` kalau mengubah angka di sini.
    """
    r = np.random.default_rng(seed)
    lambat = _smooth_noise(width, 430, r) * amp * 2.4     # bentuk keseluruhan
    sedang = _smooth_noise(width, 120, r) * amp * 0.9     # lekuk
    halus = _smooth_noise(width, 26, r) * amp * 0.25      # serat

    gigi = np.zeros(width)
    for _ in range(int(width / 70)):
        c = int(r.integers(0, width))
        lebar = int(r.integers(6, 23))
        tinggi = r.uniform(0.35, 1.15) * amp * float(r.choice([-1, 1]))
        lo, hi = max(0, c - lebar), min(width, c + lebar)
        if hi > lo:
            gigi[lo:hi] += (1 - np.abs(np.linspace(-1, 1, hi - lo))) * tinggi
    gigi = np.convolve(gigi, np.ones(5) / 5.0, mode="same")

    # --- kekasaran lokal: getar per kolom + sobekan serat yang dalam ---
    getar = r.normal(0, amp * 0.16, width)
    serat = np.zeros(width)
    for _ in range(int(width / 26)):
        c = int(r.integers(1, width - 1))
        lebar = int(r.integers(1, 5))
        dalam = r.uniform(0.6, 3.0) * amp * float(r.choice([-1, 1]))
        serat[c:c + lebar] += dalam

    # --- sobekan DALAM yang jarang ---
    # frame-1 punya rentang profil 417px dengan lonjakan tunggal 204px: ada beberapa
    # tempat di mana robekan menganga jauh. Tanpa ini rentang frame baru cuma ~85px
    # dan tepinya terasa terlalu "tertib" walau kekasaran haluznya sudah pas.
    for _ in range(int(r.integers(2, 5))):
        c = int(r.integers(0, width))
        lebar = int(r.integers(30, 130))
        dalam = r.uniform(2.5, 7.0) * amp * float(r.choice([-1, 1]))
        lo, hi = max(0, c - lebar), min(width, c + lebar)
        if hi > lo:
            ramp = np.cos(np.linspace(-np.pi / 2, np.pi / 2, hi - lo)) ** 2
            serat[lo:hi] += ramp * dalam

    e = lambat + sedang + halus + gigi + getar + serat
    return e - e.mean()


def lip_width(width: int, seed: int, rata: float = 9.0) -> np.ndarray:
    """Lebar bibir tepi per kolom (px). Kadang 0 = robekan bersih, kadang ~3x rata-rata.

    Lebar-tetap adalah ciri stroke vektor; ini yang membuat versi pertama tidak
    meyakinkan (catatan 3).
    """
    r = np.random.default_rng(seed)
    v = _smooth_noise(width, 90, r) * 0.65 + _smooth_noise(width, 22, r) * 0.35
    w = rata * (1.0 + v * 1.5)
    return np.clip(w, 0.0, rata * 3.2)


# ----------------------------------------------------------------------
# Bidang kertas
# ----------------------------------------------------------------------
def build_masks(bands: list[tuple[str, float, float]], seed: int):
    """(mask_kertas, mask_bibir) untuk daftar band.

    bands: (sisi, mulai_frac, selesai_frac). `sisi` = tepi yang ROBEK (menghadap
    jendela): 'top' = kertas di atas, robek di bawahnya; dst.

    Mask dihitung sebagai jarak bertanda ke garis tepi lalu di-clip 0..1 pada rentang
    1 piksel — itu memberi ANTI-ALIAS. Mask boolean keras membuat tepinya bergerigi
    (terlihat jelas begitu thumbnail diperkecil), dan itu salah satu keluhan pada
    batch pertama.

    Serpih (fleck) kecil yang TERLEPAS dari badan kertas ditambahkan di dekat tepi:
    robekan asli meninggalkan serpihan, dan tanpa itu tepinya selalu berupa satu
    fungsi y(x) yang tidak pernah punya bagian lepas.
    """
    m = np.zeros((H, W), dtype=np.float32)
    lip = np.zeros((H, W), dtype=np.float32)
    yy = np.arange(H, dtype=np.float32)[:, None]
    xx = np.arange(W, dtype=np.float32)[None, :]

    for i, (sisi, a, b) in enumerate(bands):
        s = seed + i * 977
        r = np.random.default_rng(s + 11)

        if sisi in ("top", "bottom"):
            e = torn_edge(W, amp=13.0, seed=s)
            lw = lip_width(W, seed=s + 5)
            batas = (H * (b if sisi == "top" else a)) + e             # (W,)
            jarak = (batas[None, :] - yy) if sisi == "top" else (yy - batas[None, :])
            kertas = np.clip(jarak + 0.5, 0.0, 1.0)
            pinggir = kertas * np.clip(lw[None, :] - jarak, 0.0, 1.0)
            # serpih lepas di sisi jendela
            for _ in range(int(W / 150)):
                cx = int(r.integers(20, W - 20))
                cy = float(batas[cx]) + r.uniform(6, 26) * (1 if sisi == "top" else -1)
                rad = r.uniform(2.0, 5.5)
                blob = np.clip(rad - np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2), 0, 1)
                m = np.maximum(m, blob)
        else:
            e = torn_edge(H, amp=13.0, seed=s)
            lw = lip_width(H, seed=s + 5)
            batas = (W * (b if sisi == "left" else a)) + e             # (H,)
            kol = batas[:, None]
            jarak = (kol - xx) if sisi == "left" else (xx - kol)
            kertas = np.clip(jarak + 0.5, 0.0, 1.0)
            pinggir = kertas * np.clip(lw[:, None] - jarak, 0.0, 1.0)

        m = np.maximum(m, kertas)
        lip = np.maximum(lip, pinggir)

    return np.clip(m, 0, 1), np.clip(lip, 0, 1)


def paper_surface(warna: tuple[int, int, int], seed: int) -> np.ndarray:
    """Warna permukaan kertas: serat vertikal + butiran isotropik + bercak lembut."""
    r = np.random.default_rng(seed)

    # serat vertikal (ciri khas frame-1) + silang halus supaya tidak seperti garis mesin
    kolom = np.convolve(r.normal(0, 1, W), np.array([0.25, 0.5, 0.25]), mode="same")
    kolom = (kolom - kolom.min()) / (np.ptp(kolom) or 1)
    serat_v = np.tile(kolom, (H, 1))
    baris_n = np.convolve(r.normal(0, 1, H), np.array([0.25, 0.5, 0.25]), mode="same")
    baris_n = (baris_n - baris_n.min()) / (np.ptp(baris_n) or 1)
    serat_h = np.tile(baris_n[:, None], (1, W))
    serat = np.clip(serat_v * 0.72 + serat_h * 0.28, 0, 1)

    # butiran isotropik (bukan garis) supaya bidangnya tidak rata sempurna
    butir = np.array(
        Image.fromarray(r.integers(0, 256, (H, W), dtype=np.uint8))
        .filter(ImageFilter.GaussianBlur(0.7)), dtype=np.float32) / 255.0

    # bercak besar: variasi terang-gelap seperti kertas asli
    kecil = r.normal(0, 1, (H // 60 + 2, W // 60 + 2))
    bercak = np.array(
        Image.fromarray(((kecil - kecil.min()) / (np.ptp(kecil) or 1) * 255)
                        .astype(np.uint8)).resize((W, H), Image.BICUBIC),
        dtype=np.float32) / 255.0

    base = np.zeros((H, W, 3), dtype=np.float32)
    base[:] = np.array(warna, dtype=np.float32)
    # serat mencerahkan ke putih (maks 15%), butiran ±5%, bercak ±6%
    base = base * (1 - serat[..., None] * 0.15) + 255.0 * (serat[..., None] * 0.15)
    base *= (0.95 + butir[..., None] * 0.10)
    base *= (0.94 + bercak[..., None] * 0.12)
    return np.clip(base, 0, 255)


def build_frame(warna: tuple[int, int, int], bands: list, seed: int) -> Image.Image:
    mask, lip = build_masks(bands, seed)
    base = paper_surface(warna, seed + 31)

    # --- bibir tepi: inti kertas yang tersingkap, krem bukan putih murni ---
    lip_soft = np.array(
        Image.fromarray((lip * 255).astype(np.uint8))
        .filter(ImageFilter.GaussianBlur(1.6)), dtype=np.float32) / 255.0
    krem = np.array([252.0, 246.0, 238.0])
    base = base * (1 - lip_soft[..., None] * 0.92) + krem * (lip_soft[..., None] * 0.92)

    # --- bayangan: mask DIGESER ke arah jendela lalu di-blur ---
    # Menggeser itu yang membuat bayangan ikut melenggok mengikuti tepi (catatan 4).
    # Radius blur DIKECILKAN jadi 9px setelah mengukur frame-1: di sana alpha turun
    # dari 125 ke 0 dalam ~24px, sedangkan blur 26px membuat kabut abu selebar ~60px
    # yang terlihat sebagai gradien lembut, bukan bayangan kontak.
    m_img = Image.fromarray((mask * 255).astype(np.uint8))
    geser = 7
    ofs = np.array(m_img.transform(
        (W, H), Image.AFFINE, (1, 0, 0, 0, 1, -geser), resample=Image.BILINEAR),
        dtype=np.float32) / 255.0
    ofs2 = np.array(m_img.transform(
        (W, H), Image.AFFINE, (1, 0, 0, 0, 1, geser), resample=Image.BILINEAR),
        dtype=np.float32) / 255.0
    src = np.maximum(ofs, ofs2)
    blur = np.array(
        Image.fromarray((src * 255).astype(np.uint8))
        .filter(ImageFilter.GaussianBlur(9)), dtype=np.float32) / 255.0
    bayang = np.clip(blur - mask, 0, 1) * 0.72

    # warna bayangan ditarik ke arah warna kertas (bounce), bukan abu netral
    warna_bayang = np.array(warna, dtype=np.float32) * 0.28 + np.array([26.0, 26.0, 30.0])

    rgba = np.zeros((H, W, 4), dtype=np.float32)
    rgba[..., :3] = base * mask[..., None]
    rgba[..., :3] += warna_bayang * bayang[..., None] * (1 - mask[..., None])
    rgba[..., 3] = np.clip(mask * 255 + bayang * 255, 0, 255)
    return Image.fromarray(rgba.round().astype(np.uint8), mode="RGBA")


# ----------------------------------------------------------------------
# Katalog
# ----------------------------------------------------------------------
PALET = {
    "apricot": (255, 189, 124),      # sama dengan frame-1
    "blush": (245, 180, 180),
    "sage": (185, 205, 166),
    "sky": (169, 200, 228),
    "butter": (245, 222, 150),
    "lilac": (201, 182, 222),
    "terracotta": (227, 155, 120),
    "mint": (168, 214, 200),
    "kraft": (217, 188, 150),
}

# (id, nama, warna, bands, kategori)
KATALOG = [
    ("paper-blush",      "Kertas Blush",       "blush",
     [("top", 0.0, 0.26), ("bottom", 0.72, 1.0)], "kertas"),
    ("paper-sage",       "Kertas Sage",        "sage",
     [("top", 0.0, 0.26), ("bottom", 0.72, 1.0)], "kertas"),
    ("paper-sky",        "Kertas Sky",         "sky",
     [("top", 0.0, 0.26), ("bottom", 0.72, 1.0)], "kertas"),
    ("paper-butter",     "Kertas Butter",      "butter",
     [("top", 0.0, 0.26), ("bottom", 0.72, 1.0)], "kertas"),
    ("wide-terracotta",  "Lebar Terracotta",   "terracotta",
     [("top", 0.0, 0.15), ("bottom", 0.85, 1.0)], "lebar"),
    ("wide-mint",        "Lebar Mint",         "mint",
     [("top", 0.0, 0.15), ("bottom", 0.85, 1.0)], "lebar"),
    ("headline-apricot", "Headline Apricot",   "apricot",
     [("top", 0.0, 0.38), ("bottom", 0.80, 1.0)], "headline"),
    ("headline-lilac",   "Headline Lilac",     "lilac",
     [("top", 0.0, 0.38), ("bottom", 0.80, 1.0)], "headline"),
    ("strip-kraft",      "Strip Kraft",        "kraft",
     [("bottom", 0.74, 1.0)], "strip"),
]


def window_of(png: Path) -> dict[str, int]:
    """Batas jendela dengan aturan SAMA seperti frame_library.window_bounds."""
    al = np.array(Image.open(png).convert("RGBA"))[:, :, 3]
    rows = np.where((al < 250).sum(axis=1) > al.shape[1] * 0.5)[0]
    return {"top": int(rows[0]), "bottom": int(rows[-1])}


def main() -> int:
    dibuat = []
    for i, (fid, nama, warna_key, bands, kategori) in enumerate(KATALOG):
        d = FRAMES / fid
        d.mkdir(parents=True, exist_ok=True)
        img = build_frame(PALET[warna_key], bands, seed=1000 + i * 313)
        png = d / "frame.png"
        img.save(png)

        thumb = img.copy()
        thumb.thumbnail((240, 427))
        bg = Image.new("RGB", thumb.size, (12, 16, 24))
        bg.paste(thumb, (0, 0), thumb)
        bg.save(d / "thumbnail.png")

        win = window_of(png)
        meta = {
            "id": fid,
            "name": nama,
            "category": kategori,
            "tags": [warna_key],
            "ratio": "9:16",
            "canvas": {"w": W, "h": H},
            "video_slot": {"scale": 1.0, "y": (win["top"] + win["bottom"]) // 2,
                           "radius": 0, "aspect": "16/9"},
            "subtitle_slot": {"y": min(H - 120, win["bottom"] - 180), "size": 80},
            "headline_slot": {"x": 45, "y": 55, "size": 86},
            "recommended_subtitle": {"animation": "word", "color": "#FFFFFF",
                                     "active_color": "#FFA500"},
            "window": win,
        }
        (d / "frame.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        dibuat.append((fid, win))

    print(f"{len(dibuat)} frame dibuat:")
    for fid, win in dibuat:
        print(f"  {fid:20s} window {win['top']:4d}..{win['bottom']:4d}"
              f"  tinggi {win['bottom'] - win['top']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
