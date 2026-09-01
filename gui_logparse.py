"""
Parsing baris log pipeline untuk tab Run — fungsi MURNI, tanpa Qt.

Dipisah dari `clipper_gui.py` supaya bisa diuji tanpa membuka jendela: tiga bug yang
diperbaiki di sini semuanya soal "menebak dari string", dan tebakan hanya bisa
dibuktikan salah/benar kalau ada tes yang menjalankannya atas baris log NYATA.

Isi:
    classify_log_line(line)   -> "error" | "warn" | "info"
    extract_output_dir(line)  -> Path | None   (folder hasil, dari prefiks log)
    parse_clip_progress(line) -> (indeks, total) | None
    parse_clip_total(line)    -> int | None
    normalize_youtube_url(u)  -> (video_id, alasan_error)
"""

from __future__ import annotations

import re
from pathlib import Path

# Stage 2 memakai `logging`, jadi barisnya berawalan
#   "2026-08-30 04:02:44 [INFO] [clipper.stage2] "
# sedangkan Stage 4/5 memakai print() tanpa prefiks. TEMUAN 2026-08-30: tanpa membuang
# prefiks itu, semua regex yang menuntut awal baris (^) GAGAL untuk Stage 2 — progres
# per-klip dan deteksi folder hasil tidak akan pernah jalan di stage terpanjang.
_LOG_PREFIX_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+"      # timestamp
    r"\[[A-Z]+\]\s+"                                   # [INFO] / [ERROR] / ...
    r"(?:\[[^\]]+\]\s+)?"                              # [clipper.stage2] (opsional)
)


def strip_log_prefix(line: str) -> str:
    """Buang prefiks logger (timestamp + level + nama logger) kalau ada."""
    return _LOG_PREFIX_RE.sub("", str(line or ""), count=1)

# ---------------------------------------------------------------------------
# 1. KLASIFIKASI BARIS LOG
# ---------------------------------------------------------------------------
# Versi lama: baris apa pun ber-"ERROR"/"FAILED"/"TRACEBACK" langsung menandai kartu
# stage MERAH. Akibatnya dua hal yang dilaporkan user:
#   * Ringkasan SUKSES ikut merah — Stage 4 mencetak "Failed:    0" dan Stage 5
#     mencetak "Rendered: 1 | Skipped: 0 | Failed: 0". Keduanya memuat "FAILED",
#     jadi setiap run yang berhasil pun sempat memerah.
#   * WARNING yt-dlp/ffmpeg (retry format, codec deprecated) dianggap error padahal
#     prosesnya lanjut dan hasilnya normal.
#
# Aturan sekarang: MERAH hanya untuk kegagalan yang benar-benar terjadi, KUNING untuk
# hal yang perlu dilihat tapi tidak menghentikan proses.

# Kegagalan sungguhan.
_FATAL_SUBSTR = (
    "traceback (most recent call last)",
    "[fail]",
    "ffmpeg failed",
    "stage 4 batch failed",
    "pipeline berhenti",
    "no such file or directory",
)
_FATAL_RE = (
    # Nama exception Python, dibatasi word-boundary supaya "error_message" tidak kena.
    re.compile(r"\b(RuntimeError|ValueError|OSError|KeyError|TypeError|IndexError|"
               r"FileNotFoundError|PermissionError|JSONDecodeError|Exception)\b"),
    re.compile(r"\bstage\s*\d+\s+(gagal|failed)\b", re.I),
)
# "Failed:    3" / "| Failed: 2" -> angka DIBACA. Nol berarti tidak ada kegagalan.
_FAILED_COUNT_RE = re.compile(r"\bfailed\s*[:=]\s*(\d+)", re.I)

_WARN_SUBSTR = (
    "warning",
    "[warn]",
    "deprecated",
    "retrying",
    "fallback",
)


_LEVEL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+\[([A-Z]+)\]")


def classify_log_line(line: str) -> str:
    """Kategori satu baris log: "error" | "warn" | "info"."""
    raw = str(line or "").strip()
    if not raw:
        return "info"

    # LEVEL dari logger adalah sumber paling andal untuk Stage 2 — itu keputusan kodenya
    # sendiri, bukan tebakan kita atas isi teks. Tapi ringkasan tetap diperiksa dulu:
    # "Successful: 1 | Skipped: 1 | Failed: 0" ditulis pada level INFO dan memuat kata
    # "Failed", jadi kalau hanya mengandalkan substring ia akan memerah tanpa sebab.
    lvl = _LEVEL_RE.match(raw)
    s = strip_log_prefix(raw).strip()
    low = s.lower()

    m = _FAILED_COUNT_RE.search(s)
    if m:
        # Baris ringkasan. Angkanya yang menentukan, bukan ada/tidaknya kata "failed".
        return "error" if int(m.group(1)) > 0 else "info"

    if lvl:
        level = lvl.group(1)
        if level in {"ERROR", "CRITICAL", "FATAL"}:
            return "error"
        if level == "WARNING":
            return "warn"
        if level in {"INFO", "DEBUG"}:
            return "info"

    if any(k in low for k in _FATAL_SUBSTR):
        return "error"
    if any(r.search(s) for r in _FATAL_RE):
        return "error"

    if any(k in low for k in _WARN_SUBSTR):
        return "warn"
    # yt-dlp menulis "ERROR: ..." di awal baris untuk kegagalan SATU percobaan format;
    # Stage 2 punya jalur pemulihan per klip sesudahnya, jadi ini peringatan, bukan
    # kematian stage. Kalau memang fatal, exit code proses yang akan menandainya merah.
    if low.startswith("error:") or low.startswith("error "):
        return "warn"
    return "info"


# ---------------------------------------------------------------------------
# 2. FOLDER HASIL
# ---------------------------------------------------------------------------
# Versi lama memecah baris per SPASI lalu mencari token ber-"/final/". Judul folder
# hasil mengandung spasi (dan sering emoji), jadi token yang ketemu hanya potongan
# pertama ("C:/Clipper") -> `cand.exists()` False -> tombol "Buka folder" jatuh ke
# root `final/`. Sekarang path diambil dari PREFIKS log secara utuh sampai akhir baris.
_OUT_PREFIX_RE = re.compile(
    r"^\s*(?:output|final|output directory|folder hasil)\s*:\s*(?P<path>\S.*?)\s*$",
    re.I,
)


def extract_output_dir(line: str) -> Path | None:
    """Folder hasil dari satu baris log, atau None.

    Menerima baris Stage 5 (`      output:    <path>.mp4`, `Final:    <dir>`) dan
    Stage 2 (`Output directory: <dir>`, yang datang dengan prefiks logger). Kalau path
    menunjuk file, folder induknya yang dikembalikan. Tidak menyentuh disk — pemanggil
    yang memutuskan mau memeriksa `exists()` atau tidak (itu membuat fungsi ini bisa diuji).
    """
    m = _OUT_PREFIX_RE.match(strip_log_prefix(line))
    if not m:
        return None
    raw = m.group("path").strip().strip('"')
    if not raw:
        return None
    p = Path(raw)
    if p.suffix.lower() in {".mp4", ".mkv", ".mov", ".webm", ".srt", ".json"}:
        p = p.parent
    return p


# ---------------------------------------------------------------------------
# 3. PROGRES PER-KLIP
# ---------------------------------------------------------------------------
# Progress bar dulu hanya bergerak per STAGE. Stage 4 memakan ~2 menit PER KLIP, jadi
# bar yang diam di 60% selama 10 menit tampak menggantung. Tiga stage panjang semuanya
# sudah mencetak nomor klip; tinggal dibaca.
_CLIP_RE = (
    # Stage 2: "[3/5] Processing clip 3: ..." / "[4/5] Clip 4 SKIP: ..."
    re.compile(r"^\s*\[(\d+)/(\d+)\]"),
    # Stage 5: "[2/5 klip 3] namafile.mp4"
    re.compile(r"^\s*\[(\d+)/(\d+)\s+klip\s+\d+\]"),
)
# Stage 4 batch tidak mencetak "i/total"; totalnya di header ("Clips:    5") dan setiap
# klip dibuka dengan "CLIP 3: judul".
_CLIP_TOTAL_RE = re.compile(r"^\s*clips?\s*:\s*(\d+)\s*$", re.I)
_CLIP_HEADER_RE = re.compile(r"^\s*CLIP\s+(\d+)\s*:")


def parse_clip_total(line: str) -> int | None:
    """Total klip dari header batch Stage 4 ("Clips:    5")."""
    m = _CLIP_TOTAL_RE.match(strip_log_prefix(line))
    return int(m.group(1)) if m else None


def parse_clip_progress(line: str) -> tuple[int, int] | None:
    """(indeks_klip_ke, total) dari satu baris log, atau None.

    Stage 4 tidak memuat total di barisnya, jadi dikembalikan (indeks, 0) dan
    pemanggil memakai total yang sudah ditangkap `parse_clip_total()` sebelumnya.
    """
    s = strip_log_prefix(line)
    # "[2/5] STAGE 2: DOWNLOAD CLIPS" adalah judul STAGE (2 dari 5 stage), bukan klip.
    # Tanpa penjaga ini progres langsung melompat ke 2/5 klip begitu Stage 2 dibuka.
    if re.match(r"^\s*\[\d+/\d+\]\s*STAGE\s", s, re.I):
        return None
    for r in _CLIP_RE:
        m = r.match(s)
        if m:
            return int(m.group(1)), int(m.group(2))
    m = _CLIP_HEADER_RE.match(s)
    if m:
        return int(m.group(1)), 0
    return None


# ---------------------------------------------------------------------------
# 4. VALIDASI URL
# ---------------------------------------------------------------------------
# `main.py` mengekstrak video ID dengan regex (?:v=|youtu.be/|shorts/)([\w-]{11}).
# Kalau bentuk URL tidak cocok, kegagalannya baru muncul SETELAH Stage 1 memanggil
# Gemini — mahal dan membingungkan. Divalidasi di GUI dengan aturan yang SAMA, plus
# SATU batasan tambahan: 11 karakter itu tidak boleh diikuti karakter ID lagi.
# Alasannya (ditemukan lewat tes): `?v=terlalupendek` (14 karakter) diterima regex
# main.py sebagai "terlalupend" lalu gagal jauh di belakang saat yt-dlp menolaknya.
# Lebih baik ditolak di depan; URL yang sah selalu diakhiri `&` atau ujung string.
_ID_RE = re.compile(
    r"(?:v=|youtu\.be/|shorts/|live/|embed/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])")
_BARE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def normalize_youtube_url(url: str) -> tuple[str, str]:
    """Kembalikan (video_id, alasan_error).

    video_id kosong berarti tidak valid, dan `alasan_error` berisi penjelasan yang
    bisa ditampilkan apa adanya ke user.
    """
    s = str(url or "").strip().strip('"').strip("'")
    if not s:
        return "", "URL masih kosong."
    if _BARE_ID_RE.match(s):
        return s, ""
    m = _ID_RE.search(s)
    if m:
        return m.group(1), ""
    if "youtube.com" in s or "youtu.be" in s:
        return "", ("Link YouTube-nya tidak memuat ID video 11 karakter.\n"
                    "Pakai bentuk https://www.youtube.com/watch?v=XXXXXXXXXXX "
                    "atau https://youtu.be/XXXXXXXXXXX")
    return "", ("Ini bukan link YouTube.\n"
                "Contoh yang benar: https://www.youtube.com/watch?v=XXXXXXXXXXX")
