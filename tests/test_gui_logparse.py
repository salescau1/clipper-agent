"""Tes untuk gui_logparse — parsing baris log tab Run.

Dijalankan atas baris log NYATA dari `logs/clipper.log` (Stage 2 lewat `logging`,
Stage 4/5 lewat `print`). Fixture sintetis sudah pernah membuat masalah di proyek ini:
tes lulus karena hanya memuat bentuk yang sudah terpikirkan. Karena itu file log asli
juga dipindai di akhir (`test_atas_log_nyata`).
"""
from __future__ import annotations

from pathlib import Path

import pytest

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui_logparse import (  # noqa: E402
    classify_log_line,
    extract_output_dir,
    normalize_youtube_url,
    parse_clip_progress,
    parse_clip_total,
    strip_log_prefix,
)

PREFIX = "2026-08-30 04:02:44 [INFO] [clipper.stage2] "
PREFIX_ERR = "2026-08-30 04:02:44 [ERROR] [clipper.stage2] "
PREFIX_WARN = "2026-08-30 04:02:44 [WARNING] [clipper.stage2] "


# ---------------------------------------------------------------- klasifikasi
@pytest.mark.parametrize("line", [
    # INTI BUG: ringkasan SUKSES memuat kata "Failed" dan dulu memerahkan kartu stage.
    PREFIX + "Successful: 1 | Skipped: 1 | Failed: 0",
    "Rendered: 1 | Skipped: 0 | Failed: 0",
    "Failed:    0",
    PREFIX + "Clips to download: 1 dari 5 (4 di-skip user)",
    "[OK] C:/x/1. judul.srt",
    "STAGE 4 BATCH PASS",
    PREFIX + "[3/5] Processing clip 3: Judul [00:05:46 -> 00:07:37]",
])
def test_baris_normal_tidak_error(line):
    assert classify_log_line(line) == "info"


@pytest.mark.parametrize("line", [
    "Failed:    3",
    "Rendered: 2 | Skipped: 0 | Failed: 1",
    PREFIX_ERR + "Clip 4 timestamp validation failed: end < start",
    "[FAIL] MP4 not found: C:/x/2.mp4",
    "Traceback (most recent call last):",
    "RuntimeError: FFmpeg failed (1)",
    "Stage 4 batch failed with exit code 1.",
])
def test_kegagalan_nyata_error(line):
    assert classify_log_line(line) == "error"


@pytest.mark.parametrize("line", [
    PREFIX_WARN + "Could not fetch video metadata: timeout",
    "WARNING: [youtube] Retrying (1/3)...",
    "ERROR: unable to download video data: HTTP Error 403",   # yt-dlp, ada pemulihan
    "deprecated pixel format used",
])
def test_peringatan_bukan_error(line):
    assert classify_log_line(line) == "warn"


def test_prefiks_logger_dibuang():
    assert strip_log_prefix(PREFIX + "Halo") == "Halo"
    assert strip_log_prefix("Halo") == "Halo"


# ---------------------------------------------------------------- folder hasil
def test_folder_hasil_dengan_spasi_dan_emoji():
    """Ini bug yang dilaporkan user: judul folder berspasi -> tombol jatuh ke root."""
    line = ("      output:    C:\\Clipper Agent\\clipper\\final\\Qorygore\\"
            "2026 Isinya Klarif 🔥\\1. Ambulans Udara vs Logika.mp4")
    got = extract_output_dir(line)
    assert got is not None
    assert got.name == "2026 Isinya Klarif 🔥"


def test_folder_hasil_dari_stage2_dengan_prefiks_logger():
    line = PREFIX + "Output directory: C:\\Clipper Agent\\clipper\\output\\ErikDoesVFX\\Did_AI"
    got = extract_output_dir(line)
    assert got is not None and got.name == "Did_AI"


def test_folder_hasil_baris_final():
    got = extract_output_dir("Final:    C:/Clipper Agent/clipper/final/Qorygore/Judul Panjang")
    assert got is not None and got.name == "Judul Panjang"


@pytest.mark.parametrize("line", [
    "Manifest: C:/x/manifest.json",          # bukan prefiks output
    PREFIX + "[3/5] Processing clip 3: x",
    "",
])
def test_bukan_folder_hasil(line):
    assert extract_output_dir(line) is None


# ---------------------------------------------------------------- progres klip
def test_progres_stage2():
    assert parse_clip_progress(PREFIX + "[3/5] Processing clip 3: x") == (3, 5)
    assert parse_clip_progress(PREFIX + "[4/5] Clip 4 SKIP: tidak dipilih user (y)") == (4, 5)


def test_judul_stage_bukan_progres_klip():
    """"[2/5] STAGE 2: DOWNLOAD CLIPS" = stage ke-2 dari 5, BUKAN klip 2 dari 5."""
    assert parse_clip_progress(PREFIX + "[2/5] STAGE 2: DOWNLOAD CLIPS") is None


def test_progres_stage5():
    assert parse_clip_progress("[2/5 klip 3] namafile.mp4") == (2, 5)


def test_progres_stage4():
    assert parse_clip_total("Clips:    5") == 5
    assert parse_clip_progress("CLIP 3: Judul Klip") == (3, 0)
    assert parse_clip_total("Manifest: C:/x/manifest.json") is None


# ---------------------------------------------------------------- URL
@pytest.mark.parametrize("url,vid", [
    ("https://www.youtube.com/watch?v=MFl-hJdwdzE", "MFl-hJdwdzE"),
    ("https://youtu.be/BRESQ8NX-us", "BRESQ8NX-us"),
    ("https://www.youtube.com/shorts/Ad5s_0VLi7o", "Ad5s_0VLi7o"),
    ("https://m.youtube.com/watch?v=Ad5s_0VLi7o&t=30s", "Ad5s_0VLi7o"),
    ("  https://youtu.be/Ad5s_0VLi7o?si=abc  ", "Ad5s_0VLi7o"),
    ("Ad5s_0VLi7o", "Ad5s_0VLi7o"),
])
def test_url_valid(url, vid):
    got, alasan = normalize_youtube_url(url)
    assert (got, alasan) == (vid, "")


@pytest.mark.parametrize("url", [
    "",
    "https://www.youtube.com/",
    "https://youtu.be/",
    "https://vimeo.com/123456",
    "bukan url",
    "https://www.youtube.com/watch?v=terlalupendek",
])
def test_url_tidak_valid(url):
    vid, alasan = normalize_youtube_url(url)
    assert vid == ""
    assert alasan  # harus ada penjelasan yang bisa ditampilkan


def test_regex_gui_sama_dengan_main():
    """URL yang lolos di GUI HARUS lolos juga di main.py, kalau tidak validasinya bohong."""
    import re
    main_re = re.compile(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})")
    for url in ("https://www.youtube.com/watch?v=MFl-hJdwdzE",
                "https://youtu.be/BRESQ8NX-us",
                "https://www.youtube.com/shorts/Ad5s_0VLi7o"):
        vid, _ = normalize_youtube_url(url)
        m = main_re.search(url)
        assert m and m.group(1) == vid


# ---------------------------------------------------------------- data NYATA
def test_atas_log_nyata():
    """Pindai logs/clipper.log yang asli.

    Yang diperiksa: (1) tidak ada baris INFO biasa yang salah dikategorikan error,
    (2) baris "Output directory:" benar-benar terparse jadi folder yang ADA di disk.
    """
    log = ROOT / "logs" / "clipper.log"
    if not log.exists():
        pytest.skip("logs/clipper.log belum ada")
    salah_merah: list[str] = []
    folder_ok = 0
    for raw in log.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip():
            continue
        kat = classify_log_line(raw)
        if kat == "error" and "[INFO]" in raw[:40]:
            # INFO yang dikategorikan error hanya boleh kalau memang "Failed: N>0"
            if not any(t in raw for t in ("Failed: 1", "Failed: 2", "Failed: 3",
                                          "Failed:    1", "Failed:    2", "Failed:    3")):
                salah_merah.append(raw[:140])
        d = extract_output_dir(raw)
        if d is not None and d.is_dir():
            folder_ok += 1
    assert not salah_merah, f"baris INFO salah dianggap error: {salah_merah[:5]}"
    assert folder_ok > 0, "tidak satu pun baris folder hasil yang terparse ke folder nyata"
