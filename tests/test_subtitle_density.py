"""Tes untuk `stage5_final.regroup_entries` — kerapatan subtitle 1/3/5 kata.

Inti yang diuji: fungsi ini harus bisa MENGGABUNG, bukan cuma memecah. Kalau hanya
memecah (perilaku `resplit_entries` yang lama), pilihan "5 kata" pada SRT 3 kata/entri
akan bohong — dan itulah yang membuat kerapatan tidak bisa dibakukan di theme.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "stages")):
    if p not in sys.path:
        sys.path.insert(0, p)

from stages.stage5_final import parse_srt, regroup_entries  # noqa: E402


def kata_per_entri(entries):
    return [len(t.split()) for _, _, t in entries]


def test_menggabung_dari_satu_kata():
    """SRT 1 kata -> 3 kata. Ini yang dulu MUSTAHIL (resplit hanya memecah)."""
    src = [(float(i), float(i) + 1.0, f"w{i}") for i in range(9)]
    got = regroup_entries(src, 3)
    assert kata_per_entri(got) == [3, 3, 3]
    assert [t for _, _, t in got] == ["w0 w1 w2", "w3 w4 w5", "w6 w7 w8"]


def test_menggabung_dari_tiga_kata_ke_lima():
    src = [(0.0, 3.0, "a b c"), (3.0, 6.0, "d e f")]
    got = regroup_entries(src, 5)
    assert kata_per_entri(got) == [5, 1]
    assert [t for _, _, t in got] == ["a b c d e", "f"]


def test_memecah_masih_jalan():
    src = [(0.0, 6.0, "a b c d e f")]
    assert kata_per_entri(regroup_entries(src, 2)) == [2, 2, 2]


def test_satu_kata_per_entri():
    src = [(0.0, 3.0, "a b c")]
    got = regroup_entries(src, 1)
    assert kata_per_entri(got) == [1, 1, 1]
    assert [t for _, _, t in got] == ["a", "b", "c"]


def test_nol_berarti_apa_adanya():
    src = [(0.0, 3.0, "a b c"), (3.0, 4.0, "d")]
    assert regroup_entries(src, 0) == src


def test_tidak_ada_kata_hilang():
    src = [(0.0, 1.0, "satu"), (1.0, 2.5, "dua tiga"), (2.5, 5.0, "empat lima enam")]
    asli = " ".join(t for _, _, t in src).split()
    for n in (1, 3, 5):
        got = " ".join(t for _, _, t in regroup_entries(src, n)).split()
        assert got == asli, f"kata berubah untuk n={n}"


def test_waktu_monoton_dan_tidak_nol():
    src = [(0.0, 1.0, "a"), (1.0, 2.0, "b"), (2.0, 3.0, "c"), (3.0, 4.0, "d")]
    for n in (1, 3, 5):
        got = regroup_entries(src, n)
        for s, e, _ in got:
            assert e > s
        for i in range(len(got) - 1):
            assert got[i][1] <= got[i + 1][0] + 1e-9, "potongan tidak boleh saling tumpang"


def test_batas_waktu_dipertahankan():
    """Awal potongan pertama = awal asli; akhir potongan terakhir = akhir asli."""
    src = [(1.5, 2.5, "a"), (2.5, 4.0, "b c"), (4.0, 7.25, "d e f")]
    for n in (1, 3, 5):
        got = regroup_entries(src, n)
        assert got[0][0] == pytest.approx(1.5)
        assert got[-1][1] == pytest.approx(7.25)


@pytest.mark.parametrize("n", [1, 3, 5])
def test_atas_srt_nyata(n):
    """Data NYATA: SRT hasil Stage 4 di output/. Fixture sintetis pernah menutupi bug."""
    srts = sorted((ROOT / "output").glob("*/*/*.srt"))
    if not srts:
        pytest.skip("belum ada SRT di output/")
    src = parse_srt(srts[0])
    assert src, "SRT nyata gagal diparse"
    got = regroup_entries(src, n)
    # jumlah kata utuh
    assert (" ".join(t for _, _, t in got).split()
            == " ".join(t for _, _, t in src).split())
    # tiap potongan maksimal n kata, dan hanya yang TERAKHIR boleh kurang
    jml = kata_per_entri(got)
    assert all(k <= n for k in jml)
    assert all(k == n for k in jml[:-1]), f"ada potongan tengah kurang dari {n}: {jml[:8]}"
    for s, e, _ in got:
        assert e > s
