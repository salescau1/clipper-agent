"""Resolver berkas bawaan paket (untuk installer portabel) — TANPA dependensi pihak ketiga.

Modul ini SENGAJA hanya memakai pustaka standar (`os`, `sys`, `shutil`, `pathlib`)
supaya bisa diimpor dari SEMUA jalur eksekusi proyek ini:

  * `.venv`               -> GUI, CLI, Stage 1/2/3/5
  * `.whisperx-venv`      -> Stage 4 (dijalankan sebagai subprocess oleh main.py)
  * `python-embed`        -> Python embeddable yang dibawa installer (tanpa pydantic)

Kalau logika ini ditaruh langsung di `utils.py`, ia ikut menarik `config` +
pydantic-settings, dan jalur `.whisperx-venv` / `python-embed` bisa gagal impor.
Karena itu implementasinya di sini, lalu `utils.py` MENG-EKSPOR ULANG fungsi-fungsinya
supaya pemakaian lama (`from utils import check_ffmpeg`) tetap jalan. Tetap SATU sumber
kebenaran — bukan logika kembar (proyek ini sudah pernah kena bug 'logika kembar' yang
perbaikannya cuma sampai ke satu jalur).

POLA WAJIB di semua resolver di bawah:
    kalau berkas bawaan paket ADA -> pakai itu;
    kalau TIDAK ADA               -> pakai perilaku lama (venv pengembangan / PATH /
                                     cache HuggingFace default di ~/.cache).
Jadi menjalankan aplikasi dari folder pengembangan (`.venv`) berperilaku persis
seperti sebelum modul ini ada.

Tata letak yang diharapkan di hasil installer (C:\\Clipper Agent\\):
    python-embed/python.exe            interpreter utama (GUI, CLI, Stage 1/2/3/5)
    python-embed-whisperx/python.exe   interpreter Stage 4 (dependensinya bentrok)
    ffmpeg/bin/ffmpeg.exe              ffmpeg bawaan paket
    ffmpeg/bin/ffprobe.exe             ffprobe bawaan paket
    models/hub/models--...             cache HuggingFace bawaan (bundel installer ke-2)
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# Root proyek = folder yang memuat berkas ini.
PROJECT_ROOT = Path(__file__).resolve().parent

# --- Nama folder bawaan installer (satu tempat, jangan ditulis ulang di file lain) ---
EMBED_PYTHON_DIR = "python-embed"
EMBED_PYTHON_WHISPERX_DIR = "python-embed-whisperx"
BUNDLED_FFMPEG_DIR = "ffmpeg"          # + /bin/ffmpeg.exe
BUNDLED_MODELS_DIR = "models"          # dipakai sebagai HF_HOME

# Nama repo HuggingFace (nama folder cache) untuk pemeriksaan model Stage 4.
ALIGN_MODEL_REPO = "cahya/wav2vec2-large-xlsr-indonesian"
TRANSCRIBE_MODEL_REPO_FMT = "Systran/faster-whisper-{model}"


def _root(root: str | Path | None = None) -> Path:
    """Root yang dipakai resolver. Argumen `root` hanya untuk pengujian."""
    return Path(root).resolve() if root is not None else PROJECT_ROOT


def _repo_folder_name(repo_id: str) -> str:
    """`org/nama` -> `models--org--nama` (tata nama folder cache HuggingFace)."""
    return "models--" + repo_id.replace("/", "--")


# ---------------------------------------------------------------------------
# TUGAS 1: interpreter Python
# ---------------------------------------------------------------------------


def python_exe_candidates(root: str | Path | None = None) -> list[Path]:
    """Kandidat interpreter utama, urut prioritas.

    1. `python-embed/python.exe`        -> dibawa installer
    2. `.venv/Scripts/python.exe`       -> perilaku sekarang di folder pengembangan
    (jaring terakhir `sys.executable` ditambahkan di `resolve_python_exe`)
    """
    base = _root(root)
    return [
        base / EMBED_PYTHON_DIR / "python.exe",
        base / ".venv" / "Scripts" / "python.exe",
    ]


def resolve_python_exe(root: str | Path | None = None) -> Path:
    """Interpreter untuk menjalankan `main.py` / `render_with_preset.py`.

    Tidak pernah melempar error: kalau kedua kandidat tidak ada, jatuh ke
    `sys.executable` (proses yang sedang jalan) — itu jaring terakhir yang diminta.
    """
    for candidate in python_exe_candidates(root):
        if candidate.exists():
            return candidate
    return Path(sys.executable)


def whisperx_python_candidates(root: str | Path | None = None) -> list[Path]:
    """Kandidat interpreter Stage 4 (WhisperX), urut prioritas.

    1. `python-embed-whisperx/python.exe` -> dibawa installer
    2. `.whisperx-venv/Scripts/python.exe` -> perilaku sekarang di folder pengembangan

    TIDAK ada fallback `sys.executable` di sini: dependensi Stage 4 bentrok dengan
    `.venv` (torch/httpx), jadi menjalankannya dengan interpreter utama akan gagal
    dengan pesan yang menyesatkan. Lebih baik gagal jelas menyebut kedua path.
    """
    base = _root(root)
    return [
        base / EMBED_PYTHON_WHISPERX_DIR / "python.exe",
        base / ".whisperx-venv" / "Scripts" / "python.exe",
    ]


def resolve_whisperx_python(root: str | Path | None = None) -> Path:
    """Interpreter Stage 4. Melempar RuntimeError yang MENYEBUT kedua path yang dicari."""
    candidates = whisperx_python_candidates(root)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    dicari = "\n".join(f"  - {c}" for c in candidates)
    raise RuntimeError(
        "Interpreter WhisperX (Stage 4) tidak ditemukan. Dua lokasi yang dicari:\n"
        f"{dicari}\n"
        "Pasang ulang aplikasi (installer membawa 'python-embed-whisperx'), atau buat "
        "'.whisperx-venv' di folder proyek untuk mode pengembangan."
    )


# ---------------------------------------------------------------------------
# TUGAS 2: ffmpeg & ffprobe
# ---------------------------------------------------------------------------


def bundled_ffmpeg_bin(root: str | Path | None = None) -> Path:
    """Folder `ffmpeg/bin` bawaan paket (belum tentu ada)."""
    return _root(root) / BUNDLED_FFMPEG_DIR / "bin"


def _bundled_tool(name: str, root: str | Path | None = None) -> Path | None:
    """Path `ffmpeg/bin/<name>.exe` kalau BENAR-BENAR ada, kalau tidak None."""
    candidate = bundled_ffmpeg_bin(root) / f"{name}.exe"
    return candidate if candidate.is_file() else None


def ffmpeg_path(root: str | Path | None = None) -> Path | None:
    """Path ffmpeg yang benar-benar akan dipakai, atau None kalau tidak ada.

    1. `ffmpeg/bin/ffmpeg.exe` (bawaan installer)
    2. hasil `shutil.which("ffmpeg")` (perilaku lama: mengandalkan PATH)
    """
    bundled = _bundled_tool("ffmpeg", root)
    if bundled is not None:
        return bundled
    found = shutil.which("ffmpeg")
    return Path(found) if found else None


def ffprobe_path(root: str | Path | None = None) -> Path | None:
    """Sama seperti `ffmpeg_path()` untuk ffprobe."""
    bundled = _bundled_tool("ffprobe", root)
    if bundled is not None:
        return bundled
    found = shutil.which("ffprobe")
    return Path(found) if found else None


def ffmpeg_exe(root: str | Path | None = None) -> str:
    """Argumen pertama untuk subprocess ffmpeg.

    Mengembalikan path ABSOLUT kalau ffmpeg bawaan paket ada; kalau tidak, nama
    telanjang `"ffmpeg"` — persis perilaku lama, termasuk pesan error `FileNotFoundError`
    yang sama kalau ffmpeg tidak terpasang.
    """
    bundled = _bundled_tool("ffmpeg", root)
    return str(bundled) if bundled is not None else "ffmpeg"


def ffprobe_exe(root: str | Path | None = None) -> str:
    """Sama seperti `ffmpeg_exe()` untuk ffprobe."""
    bundled = _bundled_tool("ffprobe", root)
    return str(bundled) if bundled is not None else "ffprobe"


def ffmpeg_source(root: str | Path | None = None) -> str:
    """Asal ffmpeg yang dipakai: 'bawaan paket', 'PATH', atau 'tidak ditemukan'.

    Dipakai `main.py doctor` supaya orang bisa mendiagnosis di komputer lain.
    """
    if _bundled_tool("ffmpeg", root) is not None:
        return "bawaan paket"
    return "PATH" if shutil.which("ffmpeg") else "tidak ditemukan"


def check_ffmpeg(root: str | Path | None = None) -> bool:
    """True kalau ffmpeg tersedia (bawaan paket ATAU di PATH)."""
    return ffmpeg_path(root) is not None


# ---------------------------------------------------------------------------
# TUGAS 3: HF_HOME — cache model WhisperX di dalam folder aplikasi
# ---------------------------------------------------------------------------


def bundled_models_dir(root: str | Path | None = None) -> Path:
    """Folder `models/` bawaan paket (belum tentu ada)."""
    return _root(root) / BUNDLED_MODELS_DIR


def apply_bundled_hf_home(root: str | Path | None = None) -> Path | None:
    """Setel `HF_HOME` ke `<root>/models` KALAU folder itu ada.

    Kalau folder `models/` TIDAK ada, TIDAK menyetel apa pun — cache HuggingFace
    tetap di `~/.cache/huggingface` (perilaku lama). Ini penting supaya komputer
    pengembangan yang modelnya sudah ada di `~/.cache` tidak mengunduh ulang ~4 GB.

    `HF_HOME` yang sudah diset dari luar DIHORMATI (tidak ditimpa) — kalau orang
    sengaja mengarahkan cache ke disk lain, itu keputusannya.

    WAJIB dipanggil SEBELUM `whisperx` / `faster_whisper` diimpor atau dimuat:
    kedua pustaka membaca HF_HOME saat menghitung lokasi cache.

    Returns:
        Path cache yang diset, atau None kalau tidak menyetel apa pun.
    """
    models = bundled_models_dir(root)
    if not models.is_dir():
        return None
    sudah = os.environ.get("HF_HOME")
    if sudah:
        return Path(sudah)
    os.environ["HF_HOME"] = str(models)
    return models


def effective_hf_cache_dir(root: str | Path | None = None) -> Path:
    """Folder cache hub HuggingFace yang BENAR-BENAR akan dipakai Stage 4.

    Urutannya sama dengan yang dipakai huggingface_hub, ditambah folder bawaan paket:
    1. `HF_HUB_CACHE` (kalau diset)
    2. `HF_HOME/hub` (kalau diset — termasuk hasil `apply_bundled_hf_home()`)
    3. `<root>/models/hub` kalau folder `models/` ada (yang AKAN diset Stage 4)
    4. `~/.cache/huggingface/hub` (default HuggingFace)

    Fungsi ini MURNI (tidak mengubah os.environ), jadi aman dipanggil dari GUI dan
    dari `main.py doctor` untuk melaporkan status tanpa efek samping.
    """
    hub = os.environ.get("HF_HUB_CACHE")
    if hub:
        return Path(hub)
    home = os.environ.get("HF_HOME")
    if home:
        return Path(home) / "hub"
    models = bundled_models_dir(root)
    if models.is_dir():
        return models / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


# ---------------------------------------------------------------------------
# TUGAS 4: deteksi bundel model WhisperX
# ---------------------------------------------------------------------------

# Berkas bobot yang harus ADA supaya sebuah repo dianggap terpasang lengkap.
# Repo yang baru separuh terunduh punya folder + config.json tapi TIDAK punya ini,
# dan itu tetap berarti "belum terpasang" — pemeriksaan folder saja akan bohong.
_WEIGHT_FILES = ("model.bin", "pytorch_model.bin", "model.safetensors")


def _repo_installed(cache_dir: Path, repo_id: str) -> tuple[bool, Path]:
    """Apakah repo HuggingFace ada LENGKAP di `cache_dir`.

    Syaratnya: folder `models--org--nama/snapshots/<rev>/` memuat salah satu berkas
    bobot di `_WEIGHT_FILES`. Symlink dihitung ada kalau target blob-nya ada
    (`Path.is_file()` sudah mengikuti symlink, yaitu bentuk normal cache HuggingFace
    di Windows dengan Developer Mode).
    """
    repo_dir = cache_dir / _repo_folder_name(repo_id)
    snapshots = repo_dir / "snapshots"
    if not snapshots.is_dir():
        return False, repo_dir
    for revisi in snapshots.iterdir():
        if not revisi.is_dir():
            continue
        for nama in _WEIGHT_FILES:
            if (revisi / nama).is_file():
                return True, repo_dir
    return False, repo_dir


def model_bundle_status(
    whisper_model: str = "medium",
    root: str | Path | None = None,
) -> dict:
    """Periksa keberadaan NYATA model Stage 4 di cache yang aktif.

    Args:
        whisper_model: ukuran model faster-whisper (`small` / `medium` / ...),
            biasanya `settings.whisper_model`.
        root: hanya untuk pengujian.

    Returns:
        dict berisi:
            cache_dir  : Path cache yang diperiksa (bawaan paket atau ~/.cache)
            bundled    : True kalau cache itu ada di dalam folder aplikasi
            transcribe : {"repo", "folder", "ok"}  -> mesin ASR faster-whisper
            align      : {"repo", "folder", "ok"}  -> penyelaras wav2vec2 Indonesia
            ok         : True kalau KEDUANYA ada
            missing    : daftar nama folder yang belum ada
    """
    cache_dir = effective_hf_cache_dir(root)
    transcribe_repo = TRANSCRIBE_MODEL_REPO_FMT.format(model=whisper_model)

    t_ok, t_dir = _repo_installed(cache_dir, transcribe_repo)
    a_ok, a_dir = _repo_installed(cache_dir, ALIGN_MODEL_REPO)

    missing = [d.name for ok, d in ((t_ok, t_dir), (a_ok, a_dir)) if not ok]
    return {
        "cache_dir": cache_dir,
        "bundled": bundled_models_dir(root) in cache_dir.parents
        or cache_dir == bundled_models_dir(root),
        "transcribe": {"repo": transcribe_repo, "folder": t_dir.name, "ok": t_ok},
        "align": {"repo": ALIGN_MODEL_REPO, "folder": a_dir.name, "ok": a_ok},
        "ok": t_ok and a_ok,
        "missing": missing,
    }


# Pesan peringatan model. SATU tempat supaya GUI dan `main.py doctor` tidak bisa
# berbeda bunyi. Ini PERINGATAN, bukan larangan: WhisperX memang bisa mengunduh
# sendiri kalau ada internet, jadi tombol Jalankan TIDAK boleh dimatikan karenanya.
MODEL_BUNDLE_WARNING = (
    "Bundel model WhisperX belum terpasang — pasang Clipper-Models terlebih dahulu, "
    "atau biarkan aplikasi mengunduhnya otomatis (butuh internet, ~3,9 GB)."
)


def model_bundle_message(status: dict | None = None, whisper_model: str = "medium") -> str:
    """Pesan siap-tampil untuk status model. String kosong kalau model sudah lengkap."""
    st = status if status is not None else model_bundle_status(whisper_model)
    if st["ok"]:
        return ""
    return (
        f"{MODEL_BUNDLE_WARNING}\n"
        f"Belum ada: {', '.join(st['missing'])}\n"
        f"Cache yang diperiksa: {st['cache_dir']}"
    )


__all__ = [
    "PROJECT_ROOT",
    "EMBED_PYTHON_DIR",
    "EMBED_PYTHON_WHISPERX_DIR",
    "BUNDLED_FFMPEG_DIR",
    "BUNDLED_MODELS_DIR",
    "ALIGN_MODEL_REPO",
    "TRANSCRIBE_MODEL_REPO_FMT",
    "MODEL_BUNDLE_WARNING",
    "python_exe_candidates",
    "resolve_python_exe",
    "whisperx_python_candidates",
    "resolve_whisperx_python",
    "bundled_ffmpeg_bin",
    "ffmpeg_path",
    "ffprobe_path",
    "ffmpeg_exe",
    "ffprobe_exe",
    "ffmpeg_source",
    "check_ffmpeg",
    "bundled_models_dir",
    "apply_bundled_hf_home",
    "effective_hf_cache_dir",
    "model_bundle_status",
    "model_bundle_message",
]
