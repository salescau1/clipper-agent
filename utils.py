"""Generic shared helpers for the Clipper pipeline.

This module intentionally contains NO domain-specific logic for YouTube,
Whisper, Gemini, OpenCV, or subtitles. It only provides generic utilities:
logging, directory creation, time parsing/formatting, safe filenames,
subprocess/FFmpeg execution, and retry logic.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import time
from functools import wraps
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, TypeVar

from config import settings

# Resolver berkas bawaan paket (installer portabel). Diimpor dari `bundled_paths`
# supaya SATU implementasi dipakai bersama oleh GUI, CLI, dan Stage 4 di
# `.whisperx-venv` — modul itu sengaja tanpa dependensi pihak ketiga sedangkan
# `utils` menarik pydantic lewat `config`. Nama-nama ini di-EKSPOR ULANG di sini
# supaya `from utils import check_ffmpeg` (pemakaian lama) tetap bekerja.
from bundled_paths import (  # noqa: F401  (re-export untuk kompatibilitas)
    apply_bundled_hf_home,
    effective_hf_cache_dir,
    ffmpeg_exe,
    ffmpeg_path,
    ffmpeg_source,
    ffprobe_exe,
    ffprobe_path,
    model_bundle_message,
    model_bundle_status,
    resolve_python_exe,
    resolve_whisperx_python,
    ytdlp_cmd,
    ytdlp_source,
)
from bundled_paths import check_ffmpeg as _check_ffmpeg_bundled

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def setup_logging() -> logging.Logger:
    """Configure and return the root application logger.

    Writes DEBUG to a rotating file in ``settings.logs_dir`` and INFO to the
    console. Each record is prefixed with the stage name via the logger name.
    """
    logger = logging.getLogger("clipper")
    if logger.handlers:  # already configured
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        settings.logs_dir / "clipper.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(fmt)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


def get_logger(stage: str) -> logging.Logger:
    """Return a logger scoped to a stage name (e.g. 'stage1')."""
    return logging.getLogger(f"clipper.{stage}")


# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------


def ensure_dirs() -> None:
    """Create all runtime directories required by the pipeline."""
    for directory in settings.runtime_dirs:
        directory.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Time parsing / formatting
# ---------------------------------------------------------------------------

_TIME_RE = re.compile(r"^(\d+):(\d+):(\d+(?:\.\d+)?)$")
_MMSS_RE = re.compile(r"^(\d+):(\d+(?:\.\d+)?)$")
_SIMPLE_RE = re.compile(r"^(\d+(?:\.\d+)?)$")


def parse_time(value: str | int | float) -> float:
    """Parse a time string into seconds.

    Accepts ``HH:MM:SS``, ``MM:SS``, ``SS``, or a bare number of seconds.
    Raises ``ValueError`` on malformed input.
    """
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()

    # Bare number (seconds)
    if _SIMPLE_RE.match(text):
        return float(text)

    # HH:MM:SS
    match = _TIME_RE.match(text)
    if match:
        hours, minutes, seconds = match.groups()
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    # MM:SS
    match = _MMSS_RE.match(text)
    if match:
        minutes, seconds = match.groups()
        return int(minutes) * 60 + float(seconds)

    raise ValueError(f"Invalid time format: {value!r}")


def format_time(seconds: float) -> str:
    """Format a number of seconds as ``HH:MM:SS`` (clamped to >= 0)."""
    seconds = max(0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


# ---------------------------------------------------------------------------
# Safe filenames
# ---------------------------------------------------------------------------


def safe_filename(text: str, fallback: str = "clip") -> str:
    """Sanitize a string into a filesystem-safe filename.

    Replaces illegal characters and whitespace with underscores, and falls
    back to ``fallback`` if the result is empty.
    """
    cleaned = re.sub(r'[\\/*?:"<>|]', "_", text)
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._")
    return cleaned or fallback


# ---------------------------------------------------------------------------
# Subprocess / FFmpeg
# ---------------------------------------------------------------------------


def check_ffmpeg() -> bool:
    """Return True if an ``ffmpeg`` executable is available.

    Diarahkan ke helper terpusat `bundled_paths.check_ffmpeg()`: ia memeriksa
    ffmpeg BAWAAN PAKET (`ffmpeg/bin/ffmpeg.exe`) dulu, lalu PATH. Fungsi ini
    dulunya `shutil.which("ffmpeg") is not None` — perilaku itu masih jadi
    lapisan kedua, jadi folder pengembangan tanpa `ffmpeg/` tidak berubah.

    Definisi asli disimpan sebagai baris komentar ini, bukan sebagai fungsi
    kedua, supaya tidak ada dua sumber kebenaran.
    """
    return _check_ffmpeg_bundled()


def run_command(
    cmd: list[str],
    *,
    check: bool = True,
    capture: bool = True,
    logger: logging.Logger | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess command with consistent error handling.

    Args:
        cmd: The command and arguments to run.
        check: If True, raise ``subprocess.CalledProcessError`` on non-zero exit.
        capture: If True, capture stdout/stderr; otherwise inherit the terminal.
        logger: Optional logger for debug output.

    Returns:
        The completed process result.

    Raises:
        subprocess.CalledProcessError: If ``check`` is True and exit code != 0.
    """
    log = logger or get_logger("utils")
    log.debug("Running: %s", " ".join(cmd))

    kwargs: dict[str, Any] = {}
    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.STDOUT
        kwargs["text"] = True

    result = subprocess.run(cmd, check=check, **kwargs)
    if capture and result.stdout:
        log.debug("Output:\n%s", result.stdout)
    return result


def run_ffmpeg(
    args: list[str],
    *,
    logger: logging.Logger | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run an FFmpeg command, raising a clear error on failure.

    Args:
        args: FFmpeg arguments (excluding the leading ``ffmpeg``).
        logger: Optional logger.

    Returns:
        The completed process result.

    Raises:
        RuntimeError: If FFmpeg is not installed.
        subprocess.CalledProcessError: If FFmpeg exits non-zero.
    """
    if not check_ffmpeg():
        raise RuntimeError(
            "FFmpeg is not installed or not on PATH. Install it and retry."
        )
    # `ffmpeg_exe()` = ffmpeg bawaan paket kalau ada, kalau tidak nama telanjang
    # "ffmpeg" (perilaku lama yang mengandalkan PATH).
    return run_command([ffmpeg_exe(), "-y", *args], logger=logger)


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------


def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator that retries a callable on transient failures.

    Args:
        max_attempts: Total number of attempts (including the first).
        delay: Initial delay between attempts, in seconds.
        backoff: Multiplier applied to the delay after each failure.
        exceptions: Exception types that trigger a retry.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            attempt = 0
            current_delay = delay
            while True:
                try:
                    return func(*args, **kwargs)
                except exceptions:
                    attempt += 1
                    if attempt >= max_attempts:
                        raise
                    time.sleep(current_delay)
                    current_delay *= backoff

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Temp file cleanup
# ---------------------------------------------------------------------------


def safe_remove(path: str | Path) -> None:
    """Remove a file, ignoring errors (e.g. already gone or permission denied)."""
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass