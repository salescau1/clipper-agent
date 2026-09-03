"""Stage 2: Download curated clip ranges.

Pipeline:
    1. Load and validate Stage 1 curation manifest.
    2. Read clip timestamps and convert to seconds.
    3. Download/extract only required ranges via yt-dlp.
    4. Write individual MP4 clips to output directory.
    5. Generate Stage 2 manifest with download results.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from config import settings
from models import CurationResult, ClipManifest, ClipManifestEntry
from utils import get_logger, parse_time, format_time, run_command, safe_remove, setup_logging, ensure_dirs
# Helper terpusat: ffmpeg/ffprobe BAWAAN PAKET (ffmpeg/bin/*.exe) kalau ada, kalau
# tidak nama telanjang "ffmpeg"/"ffprobe" seperti sebelumnya (mengandalkan PATH).
from bundled_paths import ffmpeg_exe, ffprobe_exe

logger = get_logger("stage2")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CLIP_PATTERN = re.compile(r"^clip_(\d+)\.mp4$", re.IGNORECASE)
_DEFAULT_RETRIES = settings.download_retries
_DEFAULT_RETRY_DELAY = settings.download_retry_delay
_BACKOFF_FACTOR = 2.0
_MAX_FILENAME_LENGTH = 120
_WINDOWS_INVALID_CHARS = re.compile(r'[\\/:*?"<>|]')
_RESERVED_WINDOWS_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}

# Exception types that indicate transient failures worth retrying
_TRANSIENT_EXCEPTIONS: tuple[type[Exception], ...] = (
    subprocess.CalledProcessError,
    ConnectionError,
    TimeoutError,
)


# ---------------------------------------------------------------------------
# Sanitization helpers
# ---------------------------------------------------------------------------


def _sanitize_path_component(name: str) -> str:
    """Sanitize a string for use as a Windows path component (folder name)."""
    # Remove invalid characters
    cleaned = _WINDOWS_INVALID_CHARS.sub(" ", name)
    # Collapse whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Remove trailing spaces and periods
    cleaned = cleaned.rstrip(" .")
    # Avoid reserved names
    base = cleaned.upper()
    if base in _RESERVED_WINDOWS_NAMES:
        cleaned = f"{cleaned}_clip"
    # Limit length
    if len(cleaned) > 100:
        cleaned = cleaned[:100].rstrip(" .")
    return cleaned


def _sanitize_filename(name: str, max_length: int = _MAX_FILENAME_LENGTH) -> str:
    """Sanitize a string for use as a Windows filename."""
    # Remove invalid characters
    cleaned = _WINDOWS_INVALID_CHARS.sub(" ", name)
    # Collapse whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Remove trailing spaces and periods
    cleaned = cleaned.rstrip(" .")
    # Avoid reserved names (check the stem without extension)
    stem = cleaned
    base = stem.upper()
    if base in _RESERVED_WINDOWS_NAMES:
        cleaned = f"{cleaned}_clip"
    # Limit length
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip(" .")
    return cleaned


# ---------------------------------------------------------------------------
# Manifest loading / validation
# ---------------------------------------------------------------------------


def _find_latest_manifest() -> Path | None:
    """Return the most recently modified curation manifest, if any.

    Stage 1 writes to output/<creator>/<short-title>/<video_id>.json;
    legacy locations (output/creator/..., output/curation/) are also searched.
    """
    manifests: list[Path] = []
    for pattern in ("*/*/*.json", "creator/*/*.json", "curation/*.json"):
        for p in settings.output_dir.glob(pattern):
            # Stage 2's own download manifest is named manifest.json —
            # the curation manifests we want are <video_id>.json.
            if p.name == "manifest.json" or p.stem.endswith(".subtitle"):
                continue
            manifests.append(p)
    manifests = sorted(manifests, key=lambda p: p.stat().st_mtime, reverse=True)
    return manifests[0] if manifests else None


def load_manifest(path: Path | None = None) -> CurationResult:
    """Load and validate a Stage 1 curation manifest.

    Args:
        path: Explicit path to curation JSON. If None, uses latest available.

    Returns:
        Validated CurationResult.

    Raises:
        FileNotFoundError: If no manifest is found.
        ValueError: If manifest is malformed or missing required fields.
    """
    if path is None:
        path = _find_latest_manifest()
        if path is None:
            raise FileNotFoundError(
                "No curation manifest found. Run Stage 1 first or provide --manifest-path."
            )

    if not path.exists():
        raise FileNotFoundError(f"Curation manifest not found: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in manifest: {path}") from exc

    # Validate required top-level fields before Pydantic parsing
    required_top = ["url_video", "judul_video", "video_id", "daftar_klip"]
    missing = [f for f in required_top if f not in raw]
    if missing:
        raise ValueError(f"Manifest missing required fields: {', '.join(missing)}")

    if not raw.get("daftar_klip"):
        raise ValueError("Manifest contains no clips (daftar_klip is empty).")

    try:
        return CurationResult.model_validate(raw)
    except Exception as exc:
        raise ValueError(f"Manifest validation failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------


def _validate_timestamps(clip: Any, video_duration: float) -> tuple[float, float]:
    """Convert and validate clip timestamps.

    Returns:
        (start_seconds, end_seconds)

    Raises:
        ValueError: If timestamps are invalid.
    """
    start_sec = parse_time(clip.start_klip)
    end_sec = parse_time(clip.end_klip)

    if start_sec < 0:
        raise ValueError(f"Clip {clip.id_klip}: start time {start_sec}s is negative.")
    if end_sec <= start_sec:
        raise ValueError(
            f"Clip {clip.id_klip}: end time {format_time(end_sec)} must be after start {format_time(start_sec)}."
        )
    if video_duration and end_sec > video_duration:
        raise ValueError(
            f"Clip {clip.id_klip}: end time {format_time(end_sec)} exceeds video duration {format_time(video_duration)}."
        )

    return start_sec, end_sec


# ---------------------------------------------------------------------------
# Output path helpers
# ---------------------------------------------------------------------------


def _clip_output_dir(creator: str, title: str, video_id: str = "") -> Path:
    """output/<creator>/<title>/ with the title folder capped at 30 chars."""
    creator_folder = re.sub(r"[^\w\-]+", "_", (creator or "unknown")).strip("_") or "unknown"
    safe_title = re.sub(r"[^\w\-]+", "_", title).strip("_")
    title_folder = safe_title[:30].rstrip("_") or video_id or "video"
    return settings.output_dir / creator_folder / title_folder


def _clip_filename(clip: Any) -> str:
    """Generate a human-readable filename for a clip.

    Format: <N>. <judul_relevan> - <hook>.mp4
    """
    clip_id = clip.id_klip
    judul = getattr(clip, "judul_relevan", "") or ""
    hook = getattr(clip, "hook", "") or ""

    if not judul:
        return f"{clip_id}. Clip {clip_id}.mp4"

    parts = [f"{clip_id}.", judul]
    if hook:
        parts.append(f"- {hook}")

    raw_name = " ".join(parts)
    sanitized = _sanitize_filename(raw_name)
    if not sanitized.lower().endswith(".mp4"):
        sanitized = f"{sanitized}.mp4"
    return sanitized


def _existing_clip_path(clip_dir: Path, clip_id: int, filename: str) -> Path | None:
    path = clip_dir / filename
    if path.exists() and path.stat().st_size > 0:
        return path
    return None


# ---------------------------------------------------------------------------
# yt-dlp metadata helpers
# ---------------------------------------------------------------------------


def _get_video_metadata(url: str) -> dict[str, Any]:
    """Get video metadata (title, creator, duration) from yt-dlp without downloading."""
    try:
        result = run_command(
            [
                "yt-dlp",
                "--dump-json",
                "--no-download",
                "--skip-download",
                "--no-playlist",
                url,
            ],
            check=True,
            capture=True,
            logger=logger,
        )
        data = json.loads(result.stdout)
        return {
            "title": data.get("title") or "",
            "creator": data.get("uploader") or data.get("channel") or "",
            "duration": float(data.get("duration") or 0),
        }
    except Exception as exc:
        logger.warning("Could not fetch video metadata: %s", exc)
        return {"title": "", "creator": "", "duration": 0.0}


def _get_video_duration(url: str) -> float:
    """Get video duration from yt-dlp without downloading."""
    try:
        result = run_command(
            [
                "yt-dlp",
                "--dump-json",
                "--no-download",
                "--skip-download",
                "--no-playlist",
                url,
            ],
            check=True,
            capture=True,
            logger=logger,
        )
        data = json.loads(result.stdout)
        return float(data.get("duration") or 0)
    except Exception as exc:
        logger.warning("Could not fetch video duration: %s", exc)
        return 0.0


# ---------------------------------------------------------------------------
# yt-dlp download
# ---------------------------------------------------------------------------


def _build_ytdlp_command(
    url: str,
    output_path: Path,
    start_sec: float,
    end_sec: float,
    format_selector: str | None = None,
) -> list[str]:
    """Build yt-dlp command to download a specific time range.

    Uses yt-dlp's --download-sections with postprocessor to extract the range
    without re-encoding when possible.
    """
    section = f"*{start_sec}-{end_sec}"

    if format_selector is None:
        format_selector = _default_format_selector()

    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--no-playlist",
        "-f", format_selector,
        "--merge-output-format", "mp4",
        "--download-sections", section,
        "-o", str(output_path),
        url,
    ]
    if settings.ytdlp_player_client:
        cmd.insert(3, "--extractor-args")
        cmd.insert(4, f"youtube:player_client={settings.ytdlp_player_client}")
    return cmd


def _default_format_selector() -> str:
    """Build the default high-quality format selector.

    Prioritises separate video+audio streams at highest resolution,
    falling back to pre-merged mp4 only when separate streams are unavailable.
    """
    max_height = settings.video_max_height
    return (
        f"bestvideo*[height<={max_height}]+"
        f"bestaudio[ext=m4a]/"
        f"best[height<={max_height}][ext=mp4]"
    )


def _calculate_extract_end(start_sec: float, end_sec: float, buffer_sec: float, video_duration: float) -> float:
    """Compute the physical extraction endpoint with buffer, clamped to video duration.

    Args:
        start_sec: Clip start in seconds.
        end_sec: Original clip end in seconds (from Stage 1).
        buffer_sec: Extra seconds to append after the original end.
        video_duration: Total source video duration in seconds.

    Returns:
        Clamped extraction endpoint in seconds.

    Raises:
        ValueError: If extract_end <= start_sec.
    """
    if video_duration <= 0:
        raise ValueError(f"Video duration must be positive, got {video_duration}")
    extract_end = min(end_sec + buffer_sec, video_duration)
    if extract_end <= start_sec:
        raise ValueError(
            f"Extract end {extract_end}s must be after start {start_sec}s "
            f"(clip end={end_sec}s + buffer={buffer_sec}s)"
        )
    return extract_end


def _classify_download_error(exc: Exception) -> str:
    """Classify a download exception into a category.

    Returns:
        'transient' for network/HTTP errors that may succeed on retry
        'permanent' for format errors, configuration issues, etc.
        'invalid' for bad timestamps or input
    """
    if isinstance(exc, ValueError):
        return "invalid"
    if isinstance(exc, subprocess.CalledProcessError):
        stderr = (exc.stderr or "").lower()
        if any(marker in stderr for marker in ["403", "http", "rate", "blocked", "signature"]):
            return "transient"
        if any(marker in stderr for marker in ["format", "unable to merge", "no such format"]):
            return "permanent"
        return "transient"
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return "transient"
    if isinstance(exc, RuntimeError) and "failed after" in str(exc):
        # Check if last error was transient
        cause = exc.__cause__
        if isinstance(cause, (_TRANSIENT_EXCEPTIONS,)):
            return "transient"
        return "permanent"
    if isinstance(exc, Exception):
        msg = str(exc).lower()
        if any(marker in msg for marker in ["network", "connection", "timeout", "retry"]):
            return "transient"
        return "permanent"
    return "permanent"


def _is_transient_error(exc: Exception) -> bool:
    return _classify_download_error(exc) == "transient"


def _build_batch_ytdlp_command(
    url: str,
    temp_path: Path,
    format_selector: str | None = None,
) -> list[str]:
    """Build a single yt-dlp command that downloads the full video to a temp file.

    The downloaded file is later split into individual clips using ffmpeg.
    """
    if format_selector is None:
        format_selector = _default_format_selector()

    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--no-playlist",
        "-f", format_selector,
        "--merge-output-format", "mp4",
        "-o", str(temp_path),
        url,
    ]
    if settings.ytdlp_player_client:
        cmd.insert(3, "--extractor-args")
        cmd.insert(4, f"youtube:player_client={settings.ytdlp_player_client}")
    return cmd


def _split_with_ffmpeg(
    source_path: Path,
    pending: list[tuple[Any, float, float, float, str, Path]],
) -> tuple[list[ClipManifestEntry], list[tuple[Any, float, float, float, str, Path]]]:
    """Split a downloaded video into individual clip files using ffmpeg.

    Uses stream copy (no re-encoding) for speed.

    Args:
        source_path: Path to the full downloaded video.
        pending: List of (clip, start_sec, end_sec, extract_end, filename, expected_path).

    Returns:
        (successful_entries, still_pending)
    """
    entries: list[ClipManifestEntry] = []
    still_pending: list[tuple[Any, float, float, float, str, Path]] = []

    for clip, start, end, extract_end, filename, expected_path in pending:
        duration = extract_end - start
        cmd = [
            ffmpeg_exe(),
            "-y",
            "-ss", str(start),
            "-i", str(source_path),
            "-t", str(duration),
            # Re-encode to Premiere-friendly H.264/AAC.
            # Resolution is preserved; Stage 2 already limits source
            # selection to settings.video_max_height (normally 1080p).
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            "-avoid_negative_ts", "make_zero",
            str(expected_path),
        ]

        try:
            run_command(cmd, check=True, capture=True, logger=logger)
        except Exception as exc:
            logger.warning("ffmpeg split failed for clip %d: %s", clip.id_klip, exc)
            still_pending.append((clip, start, end, extract_end, filename, expected_path))
            continue

        expected_duration = duration
        is_valid, meta, err = _validate_clip_file(
            expected_path, expected_duration, settings.video_max_height,
        )
        if is_valid:
            entries.append(ClipManifestEntry(
                clip_id=clip.id_klip,
                source_url="",
                start_time=clip.start_klip,
                end_time=clip.end_klip,
                extract_end_time=format_time(extract_end),
                buffer_seconds=settings.clip_end_buffer_seconds,
                output_path=str(expected_path),
                output_file=filename,
                title=clip.judul_relevan,
                headline=clip.headline_text(),
                hook=clip.hook,
                status="success",
                actual_duration=meta["duration"],
                video_width=meta.get("video_width"),
                video_height=meta.get("video_height"),
                video_codec=meta.get("video_codec"),
                audio_codec=meta.get("audio_codec"),
                retry_count=0,
            ))
        else:
            logger.warning("Split clip %d invalid (%s)", clip.id_klip, err)
            safe_remove(expected_path)
            still_pending.append((clip, start, end, extract_end, filename, expected_path))

    return entries, still_pending


def _run_batch_download(
    url: str,
    clip_dir: Path,
    pending: list[tuple[Any, float, float, float, str, Path]],
    format_selector: str,
    label: str = "Batch",
) -> tuple[list[ClipManifestEntry], int, list[tuple[Any, float, float, float, str, Path]]]:
    """Run one batch download: yt-dlp full video + ffmpeg split.

    Returns:
        ``(entries, yt_dlp_invocations, still_pending)``
    """
    logger.info("%s: %d clips, format: %s", label, len(pending), format_selector[:60])

    import tempfile
    invocations = 0
    entries: list[ClipManifestEntry] = []
    still_pending: list[tuple[Any, float, float, str, Path]] = []

    # Step 1: Create a unique temp file path (don't create the file yet)
    temp_path = Path(tempfile.mktemp(suffix=".mp4", prefix="clipper_batch_"))

    try:
        cmd = _build_batch_ytdlp_command(url, temp_path, format_selector)
        try:
            run_command(cmd, check=True, capture=True, logger=logger)
            invocations = 1
        except subprocess.CalledProcessError as exc:
            invocations = 1
            logger.warning(
                "%s: yt-dlp exit %s – %s",
                label, exc.returncode, (exc.stderr or "")[:200],
            )
        except Exception as exc:
            invocations = 1
            logger.warning("%s: unexpected error: %s", label, exc)

        # Step 2: Only split if download succeeded
        if invocations == 1 and temp_path.exists() and temp_path.stat().st_size > 0:
            entries, still_pending = _split_with_ffmpeg(temp_path, pending)
    finally:
        # Clean up temp file
        if temp_path.exists():
            safe_remove(temp_path)

    return entries, invocations, still_pending


def _run_individual_recovery(
    url: str,
    clip_dir: Path,
    pending: list[tuple[Any, float, float, float, str, Path]],
) -> tuple[list[ClipManifestEntry], int, list[tuple[Any, float, float, float, str, Path]]]:
    """Fall back to per-clip yt-dlp calls for truly isolated failures.

    Returns ``(entries, invocations, still_pending)``.
    """
    entries: list[ClipManifestEntry] = []
    invocations = 0
    still_pending: list[tuple[Any, float, float, float, str, Path]] = []

    for clip, start, end, extract_end, filename, expected_path in pending:
        invocations += 1
        try:
            run_command(
                _build_ytdlp_command(url, expected_path, start, extract_end),
                check=True,
                capture=True,
                logger=logger,
            )
        except Exception as exc:
            logger.error("Individual recovery failed for clip %d: %s", clip.id_klip, exc)
            still_pending.append((clip, start, end, extract_end, filename, expected_path))
            continue

        expected_duration = extract_end - start
        is_valid, meta, err = _validate_clip_file(
            expected_path, expected_duration, settings.video_max_height,
        )
        if is_valid:
            entries.append(ClipManifestEntry(
                clip_id=clip.id_klip,
                source_url=url,
                start_time=clip.start_klip,
                end_time=clip.end_klip,
                extract_end_time=format_time(extract_end),
                buffer_seconds=settings.clip_end_buffer_seconds,
                output_path=str(expected_path),
                output_file=filename,
                title=clip.judul_relevan,
                headline=clip.headline_text(),
                hook=clip.hook,
                status="success",
                actual_duration=meta["duration"],
                video_width=meta.get("video_width"),
                video_height=meta.get("video_height"),
                video_codec=meta.get("video_codec"),
                audio_codec=meta.get("audio_codec"),
                retry_count=invocations,
            ))
        else:
            logger.warning("Individual recovery: clip %d invalid – %s", clip.id_klip, err)
            safe_remove(expected_path)
            still_pending.append((clip, start, end, extract_end, filename, expected_path))

    return entries, invocations, still_pending


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------


def _validate_clip_file(path: Path, expected_duration: float, max_height: int = 1080) -> tuple[bool, dict[str, Any] | None, str | None]:
    """Validate a downloaded clip file.

    Returns:
        (is_valid, metadata_dict, error_message)
        metadata_dict contains: duration, video_width, video_height, video_codec, audio_codec
    """
    if not path.exists():
        return False, None, "File does not exist."
    if path.stat().st_size == 0:
        return False, None, "File is empty."

    # Use ffprobe to check the file
    try:
        result = run_command(
            [
                ffprobe_exe(),
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_type,codec_name,width,height,duration",
                "-of", "json",
                str(path),
            ],
            check=True,
            capture=True,
            logger=logger,
        )
        probe_video = json.loads(result.stdout)
        video_streams = [s for s in probe_video.get("streams", []) if s.get("codec_type") == "video"]
        if not video_streams:
            return False, None, "No video stream found."

        video_stream = video_streams[0]
        video_width = video_stream.get("width")
        video_height = video_stream.get("height")
        video_codec = video_stream.get("codec_name")
        actual_duration = float(video_stream.get("duration") or 0)

        # Check for audio stream
        result_audio = run_command(
            [
                ffprobe_exe(),
                "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=codec_type,codec_name",
                "-of", "json",
                str(path),
            ],
            check=True,
            capture=True,
            logger=logger,
        )
        probe_audio = json.loads(result_audio.stdout)
        audio_streams = [s for s in probe_audio.get("streams", []) if s.get("codec_type") == "audio"]
        if not audio_streams:
            return False, None, "No audio stream found."

        audio_codec = audio_streams[0].get("codec_name")

        # Validate duration
        if actual_duration <= 0:
            return False, None, "Invalid duration reported by ffprobe."

        # Allow 10% tolerance for duration mismatch
        tolerance = max(1.0, expected_duration * 0.1)
        if abs(actual_duration - expected_duration) > tolerance:
            return (
                False,
                None,
                f"Duration mismatch: expected ~{expected_duration:.1f}s, got {actual_duration:.1f}s.",
            )

        # Validate resolution does not exceed configured maximum
        if video_height and video_height > max_height:
            return False, None, f"Resolution {video_height}p exceeds configured maximum {max_height}p."

        metadata = {
            "duration": actual_duration,
            "video_width": video_width,
            "video_height": video_height,
            "video_codec": video_codec,
            "audio_codec": audio_codec,
        }
        return True, metadata, None
    except subprocess.CalledProcessError as exc:
        return False, None, f"ffprobe failed: {exc.stderr[:200] if exc.stderr else str(exc)}"
    except Exception as exc:
        return False, None, f"Validation error: {exc}"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run(manifest_path: Path | None = None, force: bool = False) -> ClipManifest:
    """Download curated clip ranges from the source video.

    Batching strategy::

        1. Skip clips with valid existing output (fast resume).
        2. Batch all pending clips into a single yt-dlp invocation per format.
        3. Retry with fallback format only for clips that still fail.
        4. Fall back to per-clip calls only for truly isolated failures.

    Args:
        manifest_path: Explicit path to curation manifest. If None, uses latest.
        force: If True, re-download clips even if they already exist.

    Returns:
        ClipManifest with download results.

    Raises:
        RuntimeError: If all clips fail to download.
    """
    setup_logging()
    ensure_dirs()

    logger.info("=" * 60)
    logger.info("[2/5] STAGE 2: DOWNLOAD CLIPS")
    logger.info("=" * 60)

    # Load manifest
    logger.info("Loading curation manifest...")
    curation = load_manifest(manifest_path)
    url = curation.url_video
    video_id = curation.video_id
    video_title = curation.judul_video

    # Fetch video metadata (creator, title, duration)
    logger.info("Fetching video metadata from yt-dlp...")
    metadata = _get_video_metadata(url)
    creator = metadata.get("creator", "") or ""
    title = metadata.get("title", "") or video_title
    video_duration = metadata.get("duration", 0.0) or curation.durasi_video

    logger.info("Video ID: %s | Title: %s | Creator: %s | Duration: %s",
                video_id, title, creator or "(unknown)", format_time(video_duration))
    # Hitung yang BENAR-BENAR akan diunduh, bukan total kandidat kurasi — kalau tidak,
    # log bilang "5 klip" padahal user hanya memilih 3.
    _total = len(curation.daftar_klip)
    _dipilih = sum(1 for k in curation.daftar_klip if getattr(k, "pilih", True))
    if _dipilih == _total:
        logger.info("Clips to download: %d", _total)
    else:
        logger.info("Clips to download: %d dari %d (%d di-skip user)",
                    _dipilih, _total, _total - _dipilih)

    # Prepare output directory using creator + title
    clip_dir = _clip_output_dir(creator, title, video_id=video_id)
    clip_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Phase 1 — classify existing / invalid / pending clips
    # ------------------------------------------------------------------
    skipped_entries: list[ClipManifestEntry] = []
    pending: list[tuple[Any, float, float, float, str, Path]] = []  # (clip, start, end, extract_end, filename, expected_path)
    failed_entries: list[ClipManifestEntry] = []

    for idx, clip in enumerate(curation.daftar_klip, start=1):
        filename = _clip_filename(clip)

        # --- Keputusan review user: klip yang tidak dipilih TIDAK diunduh ---
        # Klipnya TETAP ada di file kurasi sebagai acuan (permintaan user), hanya
        # dilewati di sini. Sengaja TIDAK dimasukkan ke manifest Stage 2 sama sekali:
        # manifest = daftar klip yang benar-benar ada di disk. Kalau klip yang di-skip
        # ikut dimasukkan (mis. status "skipped"), Stage 5 akan menerimanya — daftar
        # status yang diterima memuat "skipped" — lalu gagal dengan "missing video".
        # Penomoran file tidak terpengaruh karena _clip_filename() memakai id_klip,
        # jadi men-skip klip 3 & 4 tetap menghasilkan 1., 2., 5.
        if getattr(clip, "pilih", True) is False:
            logger.info("[%d/%d] Clip %d SKIP: tidak dipilih user (%s)",
                        idx, len(curation.daftar_klip), clip.id_klip,
                        clip.judul_relevan)
            continue

        logger.info("[%d/%d] Processing clip %d: %s [%s -> %s]",
                    idx, len(curation.daftar_klip), clip.id_klip,
                    clip.judul_relevan, clip.start_klip, clip.end_klip)

        # Validate timestamps
        try:
            start_sec, end_sec = _validate_timestamps(clip, video_duration)
        except ValueError as exc:
            logger.error("Clip %d timestamp validation failed: %s", clip.id_klip, exc)
            failed_entries.append(ClipManifestEntry(
                clip_id=clip.id_klip,
                source_url=url,
                start_time=clip.start_klip,
                end_time=clip.end_klip,
                output_path="",
                output_file=filename,
                title=clip.judul_relevan,
                headline=clip.headline_text(),
                hook=clip.hook,
                status="failed",
                error_message=str(exc),
            ))
            continue

        # Calculate buffered extraction endpoint
        buffer_sec = settings.clip_end_buffer_seconds
        try:
            extract_end = _calculate_extract_end(start_sec, end_sec, buffer_sec, video_duration)
        except ValueError as exc:
            logger.error("Clip %d buffer calculation failed: %s", clip.id_klip, exc)
            failed_entries.append(ClipManifestEntry(
                clip_id=clip.id_klip,
                source_url=url,
                start_time=clip.start_klip,
                end_time=clip.end_klip,
                output_path="",
                output_file=filename,
                title=clip.judul_relevan,
                headline=clip.headline_text(),
                hook=clip.hook,
                status="failed",
                error_message=str(exc),
            ))
            continue

        expected_duration = extract_end - start_sec
        output_path = clip_dir / filename

        # Check if already exists and is valid (must match buffered duration)
        if not force and _existing_clip_path(clip_dir, clip.id_klip, filename):
            is_valid, meta, err = _validate_clip_file(
                output_path, expected_duration, settings.video_max_height,
            )
            if is_valid:
                logger.info("Clip %d already exists and is valid, skipping.", clip.id_klip)
                skipped_entries.append(ClipManifestEntry(
                    clip_id=clip.id_klip,
                    source_url=url,
                    start_time=clip.start_klip,
                    end_time=clip.end_klip,
                    extract_end_time=format_time(extract_end),
                    buffer_seconds=buffer_sec,
                    output_path=str(output_path),
                    output_file=filename,
                    title=clip.judul_relevan,
                    headline=clip.headline_text(),
                    hook=clip.hook,
                    status="skipped",
                    actual_duration=meta["duration"] if meta else None,
                    video_width=meta.get("video_width") if meta else None,
                    video_height=meta.get("video_height") if meta else None,
                    video_codec=meta.get("video_codec") if meta else None,
                    audio_codec=meta.get("audio_codec") if meta else None,
                    retry_count=0,
                ))
                continue
            else:
                logger.warning("Clip %d exists but is invalid (%s), re-downloading.", clip.id_klip, err)
                safe_remove(output_path)

        pending.append((clip, start_sec, end_sec, extract_end, filename, output_path))

    # ------------------------------------------------------------------
    # Phase 2 — batch download (preferred format), retry with fallback format
    # ------------------------------------------------------------------
    preferred_fmt = _default_format_selector()
    fallback_fmt = "best[ext=mp4]/best"
    total_yt_dlp_invocations = 0
    format_fallback_used = False

    # Primary batch
    if pending:
        entries_batch, invocations, remaining = _run_batch_download(
            url, clip_dir, pending, preferred_fmt,
            label="Batch 1",
        )
        total_yt_dlp_invocations += invocations
        logger.info(
            "Batch 1 done: %d/%d clips succeeded (%d yt-dlp invocations).",
            len(entries_batch), len(pending), invocations,
        )

        # Retry remaining with fallback format
        if remaining:
            entries_fb, invocations, still_remaining = _run_batch_download(
                url, clip_dir, remaining, fallback_fmt,
                label="Batch retry",
            )
            total_yt_dlp_invocations += invocations
            format_fallback_used = True
            logger.info(
                "Batch retry done: %d/%d clips succeeded (%d yt-dlp invocations).",
                len(entries_fb), len(remaining), invocations,
            )
        else:
            entries_fb, still_remaining = [], []

    else:
        entries_batch, entries_fb, still_remaining = [], [], []

    # ------------------------------------------------------------------
    # Phase 3 — individual recovery for truly isolated failures
    # ------------------------------------------------------------------
    individual_entries: list[ClipManifestEntry] = []
    if still_remaining:
        individual_entries, invocations, final_pending = _run_individual_recovery(
            url, clip_dir, still_remaining,
        )
        total_yt_dlp_invocations += invocations
        logger.info(
            "Individual recovery done: %d succeeded, %d still pending.",
            len(individual_entries), len(final_pending),
        )
    else:
        final_pending = []

    # ------------------------------------------------------------------
    # Assemble final result
    # ------------------------------------------------------------------
    successful = len(entries_batch) + len(entries_fb) + len(individual_entries) + len(skipped_entries)
    failed = len(final_pending) + len(failed_entries)
    skipped = len(skipped_entries)

    entries = skipped_entries + entries_batch + entries_fb + individual_entries

    # Mark any still-pending clips as failed
    for clip, _, _, _, filename, _ in final_pending:
        entries.append(ClipManifestEntry(
            clip_id=clip.id_klip,
            source_url=url,
            start_time=clip.start_klip,
            end_time=clip.end_klip,
            output_path=str(clip_dir / filename),
            output_file=filename,
            title=clip.judul_relevan,
            headline=clip.headline_text(),
            hook=clip.hook,
            status="failed",
            error_message="Download failed after batch + individual retries.",
            retry_count=2,
        ))

    if failed_entries:
        entries.extend(failed_entries)

    # Urutkan berdasarkan clip_id supaya manifest selalu berurutan 1,2,5 — bukan
    # mengikuti urutan proses (skipped dulu, lalu batch, lalu recovery). Dengan klip
    # yang di-skip user, urutan proses jadi makin acak dan log Stage 4/5 sulit dibaca.
    entries.sort(key=lambda e: e.clip_id)

    # Summary
    logger.info("=" * 60)
    logger.info("STAGE 2 COMPLETE")
    logger.info("Successful: %d | Skipped: %d | Failed: %d", successful, skipped, failed)
    logger.info("yt-dlp invocations: %d (%s format fallback)",
                total_yt_dlp_invocations, "with" if format_fallback_used else "no")
    logger.info("Output directory: %s", clip_dir)
    logger.info("=" * 60)

    if successful == 0 and failed > 0:
        raise RuntimeError(f"All {failed} clips failed to download. Check logs for details.")

    # Build and save manifest
    manifest = ClipManifest(
        video_id=video_id,
        video_title=title,
        creator=creator,
        # Ketikan user di panel Review ikut ke manifest supaya Stage 5 memakainya untuk
        # WATERMARK. Nama folder di atas (`_clip_output_dir`) tetap dari `creator` asli:
        # kalau folder ikut berubah, klip yang sudah diunduh tidak akan ketemu lagi.
        creator_watermark=str(getattr(curation, "creator_watermark", "") or "").strip(),
        source_url=url,
        output_directory=str(clip_dir),
        clips=entries,
    )
    manifest_path_out = clip_dir / "manifest.json"
    manifest_path_out.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Manifest saved: %s", manifest_path_out)

    return manifest