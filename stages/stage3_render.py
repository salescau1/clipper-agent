"""Stage 3: Smart 9:16 Crop/Render.

Consumes Stage 2 raw clips (READ-ONLY — never modified) and produces
1080x1920 vertical videos with smart subject-aware cropping.

Crop modes:
    - auto:   Detect the main subject (face first, then saliency) and crop
              around it. Falls back to center crop if detection fails.
    - face:   Force face detection. Falls back to center crop if no face found.
    - center: Always crop the horizontal center of the frame.

Subject detection fallback hierarchy:
    MediaPipe Face Detection -> OpenCV (Haar cascade) -> center crop.

Output layout:
    output/clips/<stage2-folder>/crop/<clip>.mp4
    output/clips/<stage2-folder>/crop/manifest.json
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from config import settings
from models import ClipManifest, CropJob, CropManifest
from utils import (
    ensure_dirs,
    format_time,
    get_logger,
    run_command,
    run_ffmpeg,
    safe_remove,
    setup_logging,
)

logger = get_logger("stage3")

# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------


def _find_latest_stage2_manifest() -> Path | None:
    """Return the most recently modified Stage 2 manifest, if any."""
    clips_dir = settings.output_dir / "clips"
    if not clips_dir.exists():
        return None
    manifests = sorted(
        clips_dir.glob("*/manifest.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return manifests[0] if manifests else None


def find_manifest_by_video_id(video_id: str) -> Path | None:
    """Find a Stage 2 manifest matching the given video ID.

    Searches all ``output/clips/*/manifest.json`` files for one whose
    ``video_id`` field matches.

    Returns:
        The matching manifest path, or None if not found.
    """
    clips_dir = settings.output_dir / "clips"
    if not clips_dir.exists():
        return None
    for manifest_path in clips_dir.glob("*/manifest.json"):
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            if raw.get("video_id") == video_id:
                return manifest_path
        except (json.JSONDecodeError, OSError):
            continue
    return None


def load_stage2_manifest(path: Path | None = None) -> ClipManifest:
    """Load and validate a Stage 2 manifest.

    Args:
        path: Explicit path to Stage 2 manifest.json. If None, uses latest.

    Returns:
        Validated ClipManifest.

    Raises:
        FileNotFoundError: If no manifest is found.
        ValueError: If manifest is malformed.
    """
    if path is None:
        path = _find_latest_stage2_manifest()
        if path is None:
            raise FileNotFoundError(
                "No Stage 2 manifest found. Run Stage 2 first or provide --manifest-path."
            )

    if not path.exists():
        raise FileNotFoundError(f"Stage 2 manifest not found: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in manifest: {path}") from exc

    try:
        return ClipManifest.model_validate(raw)
    except Exception as exc:
        raise ValueError(f"Stage 2 manifest validation failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Media probing
# ---------------------------------------------------------------------------


def _probe_media(path: Path) -> dict[str, Any]:
    """Probe a media file with ffprobe and return stream metadata.

    Returns a dict with keys: duration, video_width, video_height,
    video_codec, audio_codec, has_video, has_audio.
    """
    result = run_command(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-show_entries", "stream=codec_type,codec_name,width,height",
            "-of", "json",
            str(path),
        ],
        check=True,
        capture=True,
        logger=logger,
    )
    data = json.loads(result.stdout)

    streams = data.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

    video = video_streams[0] if video_streams else {}
    audio = audio_streams[0] if audio_streams else {}

    duration = float(data.get("format", {}).get("duration") or 0)
    if duration <= 0 and video:
        duration = float(video.get("duration") or 0)

    return {
        "duration": duration,
        "video_width": video.get("width"),
        "video_height": video.get("height"),
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "has_video": bool(video_streams),
        "has_audio": bool(audio_streams),
    }


# ---------------------------------------------------------------------------
# Subject detection
# ---------------------------------------------------------------------------


def _detect_face_mediapipe(frame_path: Path) -> tuple[int, int] | None:
    """Detect a face using MediaPipe Face Detection.

    Returns (center_x, center_y) in pixels, or None if no face found or
    MediaPipe is unavailable.
    """
    try:
        import mediapipe as mp  # type: ignore
        import cv2  # type: ignore
    except ImportError:
        logger.debug("MediaPipe/OpenCV not installed; skipping face detection.")
        return None

    try:
        img = cv2.imread(str(frame_path))
        if img is None:
            return None
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]

        mp_face = mp.solutions.face_detection
        with mp_face.FaceDetection(model_selection=1, min_detection_confidence=0.5) as detector:
            results = detector.process(rgb)
            if not results.detections:
                return None
            # Use the highest-confidence detection
            best = max(
                results.detections,
                key=lambda d: d.score[0] if d.score else 0,
            )
            bbox = best.location_data.relative_bounding_box
            cx = int((bbox.xmin + bbox.width / 2) * w)
            cy = int((bbox.ymin + bbox.height / 2) * h)
            return cx, cy
    except Exception as exc:
        logger.debug("MediaPipe face detection failed: %s", exc)
        return None


def _detect_face_opencv(frame_path: Path) -> tuple[int, int] | None:
    """Detect a face using OpenCV Haar cascade.

    Returns (center_x, center_y) in pixels, or None if no face found.
    """
    try:
        import cv2  # type: ignore
    except ImportError:
        logger.debug("OpenCV not installed; skipping Haar cascade detection.")
        return None

    try:
        img = cv2.imread(str(frame_path))
        if img is None:
            return None
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape[:2]

        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(cascade_path)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        if len(faces) == 0:
            return None

        # Use the largest face
        best = max(faces, key=lambda f: f[2] * f[3])
        x, y, fw, fh = best
        return x + fw // 2, y + fh // 2
    except Exception as exc:
        logger.debug("OpenCV face detection failed: %s", exc)
        return None


def _detect_subject(frame_path: Path) -> tuple[int, int] | None:
    """Detect the main subject in a frame.

    Fallback hierarchy: MediaPipe -> OpenCV -> None (center crop).

    Returns (center_x, center_y) in pixels, or None if no subject found.
    """
    # 1. MediaPipe
    result = _detect_face_mediapipe(frame_path)
    if result is not None:
        logger.debug("Subject detected via MediaPipe: %s", result)
        return result

    # 2. OpenCV Haar cascade
    result = _detect_face_opencv(frame_path)
    if result is not None:
        logger.debug("Subject detected via OpenCV: %s", result)
        return result

    logger.debug("No subject detected; will use center crop.")
    return None


def _extract_sample_frame(
    input_path: Path,
    sample_time: float,
    frame_path: Path,
) -> bool:
    """Extract a single frame at the given time for subject detection."""
    try:
        run_ffmpeg(
            [
                "-ss", str(sample_time),
                "-i", str(input_path),
                "-frames:v", "1",
                "-q:v", "2",
                "-y",
                str(frame_path),
            ],
            logger=logger,
        )
        return frame_path.exists() and frame_path.stat().st_size > 0
    except subprocess.CalledProcessError:
        return False


def _compute_crop_x(
    subject_x: int | None,
    source_width: int,
    output_width: int,
) -> int:
    """Compute the horizontal crop offset (x) for a 9:16 crop.

    Centers the crop on the subject if detected, otherwise centers the frame.
    Clamps the offset so the crop window stays within the source frame.
    """
    if source_width <= output_width:
        return 0

    max_x = source_width - output_width

    if subject_x is None:
        return max_x // 2

    # Center the crop window on the subject
    x = subject_x - output_width // 2
    return max(0, min(x, max_x))


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _build_ffmpeg_crop_command(
    input_path: Path,
    output_path: Path,
    crop_x: int,
    source_width: int,
    source_height: int,
    output_width: int,
    output_height: int,
    audio_target_lufs: str,
) -> list[str]:
    """Build the FFmpeg command for a 9:16 crop + audio normalize render.

    Strategy:
        1. Scale the source so its height matches the output height (1920),
           preserving aspect ratio. This makes the source width >= 1080.
        2. Crop a 1080x1920 window at the computed x offset.
        3. Normalize audio to the target LUFS.
        4. Encode H.264 + AAC, yuv420p.
    """
    # Scale height to output_height, keep aspect ratio.
    scaled_width = int(round(source_width * output_height / source_height))

    # The crop x must be scaled to the scaled coordinate space.
    scale_factor = output_height / source_height
    scaled_crop_x = int(round(crop_x * scale_factor))

    # Clamp scaled crop x to valid range.
    max_scaled_x = max(0, scaled_width - output_width)
    scaled_crop_x = max(0, min(scaled_crop_x, max_scaled_x))

    return [
        "-i", str(input_path),
        "-vf",
        f"scale={scaled_width}:{output_height},crop={output_width}:{output_height}:{scaled_crop_x}:0",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-af", f"loudnorm=I={audio_target_lufs}:TP=-1.5:LRA=11",
        "-movflags", "+faststart",
        "-y",
        str(output_path),
    ]


def _render_clip(
    input_path: Path,
    output_path: Path,
    crop_x: int,
    source_width: int,
    source_height: int,
    output_width: int,
    output_height: int,
    audio_target_lufs: str,
) -> None:
    """Render a single clip with the given crop parameters."""
    cmd = _build_ffmpeg_crop_command(
        input_path,
        output_path,
        crop_x,
        source_width,
        source_height,
        output_width,
        output_height,
        audio_target_lufs,
    )
    run_ffmpeg(cmd, logger=logger)


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------


def _validate_output(
    path: Path,
    expected_duration: float,
    output_width: int,
    output_height: int,
) -> tuple[bool, dict[str, Any] | None, str | None]:
    """Validate a rendered clip file.

    Returns:
        (is_valid, metadata_dict, error_message)
    """
    if not path.exists():
        return False, None, "File does not exist."
    if path.stat().st_size == 0:
        return False, None, "File is empty."

    try:
        meta = _probe_media(path)
    except Exception as exc:
        return False, None, f"ffprobe failed: {exc}"

    if not meta["has_video"]:
        return False, None, "No video stream found."
    if not meta["has_audio"]:
        return False, None, "No audio stream found."

    if meta["video_width"] != output_width or meta["video_height"] != output_height:
        return (
            False,
            None,
            f"Resolution mismatch: expected {output_width}x{output_height}, "
            f"got {meta['video_width']}x{meta['video_height']}.",
        )

    if meta["duration"] <= 0:
        return False, None, "Invalid duration reported by ffprobe."

    # Allow 10% tolerance for duration mismatch
    tolerance = max(1.0, expected_duration * 0.1)
    if abs(meta["duration"] - expected_duration) > tolerance:
        return (
            False,
            None,
            f"Duration mismatch: expected ~{expected_duration:.1f}s, got {meta['duration']:.1f}s.",
        )

    return True, meta, None


# ---------------------------------------------------------------------------
# Crop mode resolution
# ---------------------------------------------------------------------------


def _resolve_crop_mode(
    requested: str,
    subject_x: int | None,
) -> str:
    """Resolve the actual crop mode used based on detection results.

    - center: always center.
    - face:   face if subject found, else center.
    - auto:   face if subject found, else center.
    """
    if requested == "center":
        return "center"
    if subject_x is not None:
        return "face"
    return "center"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run(
    manifest_path: Path | None = None,
    force: bool = False,
) -> CropManifest:
    """Render 9:16 vertical clips from Stage 2 raw clips.

    Stage 2 source files are READ-ONLY and never modified.

    Args:
        manifest_path: Explicit path to Stage 2 manifest.json. If None, uses latest.
        force: If True, re-render clips even if valid output exists.

    Returns:
        CropManifest with render results.

    Raises:
        RuntimeError: If all clips fail to render.
    """
    setup_logging()
    ensure_dirs()

    logger.info("=" * 60)
    logger.info("[3/5] STAGE 3: SMART 9:16 CROP/RENDER")
    logger.info("=" * 60)

    # Load Stage 2 manifest
    logger.info("Loading Stage 2 manifest...")
    stage2 = load_stage2_manifest(manifest_path)
    video_id = stage2.video_id
    video_title = stage2.video_title
    creator = stage2.creator
    source_dir = Path(stage2.output_directory)

    # Only process clips that downloaded successfully
    source_clips = [c for c in stage2.clips if c.status in ("success", "skipped") and c.output_path]
    if not source_clips:
        raise RuntimeError("No successfully downloaded clips found in Stage 2 manifest.")

    logger.info(
        "Video ID: %s | Title: %s | Creator: %s | Clips to render: %d",
        video_id, video_title, creator or "(unknown)", len(source_clips),
    )

    # Prepare crop output directory (sibling of Stage 2 sources, never touching them)
    crop_dir = source_dir / "crop"
    crop_dir.mkdir(parents=True, exist_ok=True)

    output_width = settings.output_width
    output_height = settings.output_height
    crop_mode_requested = settings.crop_mode
    sample_seconds = settings.face_detection_sample_seconds
    audio_target_lufs = settings.audio_target_lufs

    jobs: list[CropJob] = []
    successful = 0
    failed = 0
    skipped = 0

    for idx, clip in enumerate(source_clips, start=1):
        input_path = Path(clip.output_path)
        output_path = crop_dir / clip.output_file

        logger.info(
            "[%d/%d] Processing Clip %d / Source: %s / Output: %s",
            idx, len(source_clips), clip.clip_id, input_path, output_path,
        )

        # Skip if valid output already exists (resume)
        if not force and output_path.exists() and output_path.stat().st_size > 0:
            is_valid, meta, err = _validate_output(
                output_path,
                clip.actual_duration or 0,
                output_width,
                output_height,
            )
            if is_valid:
                logger.info(
                    "Clip %d already rendered and valid, skipping. / Status: skipped",
                    clip.clip_id,
                )
                jobs.append(CropJob(
                    clip_id=clip.clip_id,
                    input_file=str(input_path),
                    output_file=str(output_path),
                    source_width=clip.video_width,
                    source_height=clip.video_height,
                    output_width=output_width,
                    output_height=output_height,
                    crop_mode_requested=crop_mode_requested,
                    crop_mode_used="center",
                    crop_x=0,
                    duration=meta["duration"] if meta else None,
                    video_codec=meta.get("video_codec") if meta else None,
                    audio_codec=meta.get("audio_codec") if meta else None,
                    status="skipped",
                ))
                skipped += 1
                continue
            else:
                logger.warning(
                    "Clip %d output exists but is invalid (%s), re-rendering.",
                    clip.clip_id, err,
                )
                safe_remove(output_path)

        # Probe source to get dimensions
        try:
            source_meta = _probe_media(input_path)
        except Exception as exc:
            logger.error("Clip %d: failed to probe source: %s", clip.clip_id, exc)
            jobs.append(CropJob(
                clip_id=clip.clip_id,
                input_file=str(input_path),
                output_file=str(output_path),
                source_width=clip.video_width,
                source_height=clip.video_height,
                output_width=output_width,
                output_height=output_height,
                crop_mode_requested=crop_mode_requested,
                status="failed",
                error_message=f"Failed to probe source: {exc}",
            ))
            failed += 1
            continue

        source_width = source_meta.get("video_width") or clip.video_width or 0
        source_height = source_meta.get("video_height") or clip.video_height or 0

        if source_width <= 0 or source_height <= 0:
            logger.error("Clip %d: invalid source dimensions %dx%d.", clip.clip_id, source_width, source_height)
            jobs.append(CropJob(
                clip_id=clip.clip_id,
                input_file=str(input_path),
                output_file=str(output_path),
                source_width=source_width,
                source_height=source_height,
                output_width=output_width,
                output_height=output_height,
                crop_mode_requested=crop_mode_requested,
                status="failed",
                error_message=f"Invalid source dimensions {source_width}x{source_height}.",
            ))
            failed += 1
            continue

        # Subject detection (unless center mode)
        subject_x: int | None = None
        detection_mode = "center"
        if crop_mode_requested != "center":
            # Sample a frame near the start of the clip for subject detection
            sample_time = min(sample_seconds, max(0.0, (source_meta.get("duration") or 0) / 2))
            frame_path = crop_dir / f"_detect_{clip.clip_id}.jpg"
            try:
                if _extract_sample_frame(input_path, sample_time, frame_path):
                    subject = _detect_subject(frame_path)
                    if subject is not None:
                        subject_x = subject[0]
                        detection_mode = "face"
                safe_remove(frame_path)
            except Exception as exc:
                logger.debug("Clip %d: subject detection failed: %s", clip.clip_id, exc)
                safe_remove(frame_path)

        # Compute crop x
        crop_x = _compute_crop_x(subject_x, source_width, output_width)
        crop_mode_used = _resolve_crop_mode(crop_mode_requested, subject_x)

        logger.info(
            "Clip %d / Detection: %s / Crop X: %d / Output: %dx%d",
            clip.clip_id, detection_mode, crop_x, output_width, output_height,
        )

        # Render
        try:
            _render_clip(
                input_path,
                output_path,
                crop_x,
                source_width,
                source_height,
                output_width,
                output_height,
                audio_target_lufs,
            )
        except Exception as exc:
            logger.error("Clip %d: render failed: %s", clip.clip_id, exc)
            jobs.append(CropJob(
                clip_id=clip.clip_id,
                input_file=str(input_path),
                output_file=str(output_path),
                source_width=source_width,
                source_height=source_height,
                output_width=output_width,
                output_height=output_height,
                crop_mode_requested=crop_mode_requested,
                crop_mode_used=crop_mode_used,
                crop_x=crop_x,
                status="failed",
                error_message=str(exc),
            ))
            failed += 1
            continue

        # Validate output
        expected_duration = source_meta.get("duration") or clip.actual_duration or 0
        is_valid, meta, err = _validate_output(
            output_path,
            expected_duration,
            output_width,
            output_height,
        )
        if not is_valid:
            logger.error("Clip %d: output validation failed: %s", clip.clip_id, err)
            safe_remove(output_path)
            jobs.append(CropJob(
                clip_id=clip.clip_id,
                input_file=str(input_path),
                output_file=str(output_path),
                source_width=source_width,
                source_height=source_height,
                output_width=output_width,
                output_height=output_height,
                crop_mode_requested=crop_mode_requested,
                crop_mode_used=crop_mode_used,
                crop_x=crop_x,
                status="failed",
                error_message=f"Output validation failed: {err}",
            ))
            failed += 1
            continue

        logger.info("Clip %d / Status: success", clip.clip_id)
        jobs.append(CropJob(
            clip_id=clip.clip_id,
            input_file=str(input_path),
            output_file=str(output_path),
            source_width=source_width,
            source_height=source_height,
            output_width=output_width,
            output_height=output_height,
            crop_mode_requested=crop_mode_requested,
            crop_mode_used=crop_mode_used,
            crop_x=crop_x,
            duration=meta["duration"] if meta else None,
            video_codec=meta.get("video_codec") if meta else None,
            audio_codec=meta.get("audio_codec") if meta else None,
            status="success",
        ))
        successful += 1

    # Summary
    logger.info("=" * 60)
    logger.info("STAGE 3 COMPLETE")
    logger.info("Successful: %d | Skipped: %d | Failed: %d", successful, skipped, failed)
    logger.info("Output directory: %s", crop_dir)
    logger.info("=" * 60)

    if successful == 0 and failed > 0:
        raise RuntimeError(f"All {failed} clips failed to render. Check logs for details.")

    # Build and save manifest
    manifest = CropManifest(
        video_id=video_id,
        video_title=video_title,
        creator=creator,
        source_directory=str(source_dir),
        output_directory=str(crop_dir),
        jobs=jobs,
    )
    manifest_path_out = crop_dir / "manifest.json"
    manifest_path_out.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Manifest saved: %s", manifest_path_out)

    return manifest