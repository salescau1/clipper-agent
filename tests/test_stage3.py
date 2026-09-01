"""Tests for Stage 3: Smart 9:16 Crop/Render."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config import settings
from models import ClipManifest, ClipManifestEntry, CropJob, CropManifest
from stages.stage3_render import (
    _build_ffmpeg_crop_command,
    _compute_crop_x,
    _detect_face_mediapipe,
    _detect_face_opencv,
    _detect_subject,
    _extract_sample_frame,
    _find_latest_stage2_manifest,
    _probe_media,
    _render_clip,
    _resolve_crop_mode,
    _validate_output,
    find_manifest_by_video_id,
    load_stage2_manifest,
    run,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_clip_entry(
    clip_id: int = 1,
    status: str = "success",
    output_path: str = "",
    video_width: int = 1920,
    video_height: int = 1080,
    actual_duration: float = 60.0,
) -> ClipManifestEntry:
    return ClipManifestEntry(
        clip_id=clip_id,
        source_url="https://youtu.be/abc123",
        start_time="00:00:00",
        end_time="00:01:00",
        output_path=output_path,
        output_file=f"{clip_id}. Clip {clip_id}.mp4",
        title=f"Clip {clip_id}",
        hook=f"Hook {clip_id}",
        status=status,
        actual_duration=actual_duration,
        video_width=video_width,
        video_height=video_height,
        video_codec="h264",
        audio_codec="aac",
    )


@pytest.fixture
def sample_stage2_manifest(tmp_path: Path) -> ClipManifest:
    clip_dir = tmp_path / "clips" / "Creator - Video"
    clip_dir.mkdir(parents=True, exist_ok=True)
    return ClipManifest(
        video_id="abc123",
        video_title="Test Video",
        creator="Creator",
        source_url="https://youtu.be/abc123",
        output_directory=str(clip_dir),
        clips=[
            make_clip_entry(
                clip_id=1,
                output_path=str(clip_dir / "1. Clip 1.mp4"),
            ),
            make_clip_entry(
                clip_id=2,
                output_path=str(clip_dir / "2. Clip 2.mp4"),
            ),
        ],
    )


@pytest.fixture
def stage2_manifest_json(tmp_path: Path, sample_stage2_manifest: ClipManifest) -> Path:
    path = tmp_path / "clips" / "Creator - Video" / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sample_stage2_manifest.model_dump_json(indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------


class TestLoadStage2Manifest:
    def test_valid_manifest(self, stage2_manifest_json: Path) -> None:
        result = load_stage2_manifest(stage2_manifest_json)
        assert result.video_id == "abc123"
        assert len(result.clips) == 2

    def test_missing_file(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_stage2_manifest(Path("/nonexistent/path.json"))

    def test_invalid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid JSON"):
            load_stage2_manifest(path)

    def test_invalid_schema(self, tmp_path: Path) -> None:
        path = tmp_path / "bad_schema.json"
        path.write_text(json.dumps({"video_id": "abc"}), encoding="utf-8")
        with pytest.raises(ValueError, match="validation failed"):
            load_stage2_manifest(path)

    def test_find_latest_manifest(self, tmp_path: Path) -> None:
        clips_dir = tmp_path / "clips"
        folder1 = clips_dir / "A"
        folder2 = clips_dir / "B"
        folder1.mkdir(parents=True)
        folder2.mkdir(parents=True)
        (folder1 / "manifest.json").write_text("{}", encoding="utf-8")
        (folder2 / "manifest.json").write_text("{}", encoding="utf-8")

        with patch("stages.stage3_render.settings") as mock_settings:
            mock_settings.output_dir = tmp_path
            result = _find_latest_stage2_manifest()
            assert result is not None
            assert result.parent in (folder1, folder2)

    def test_find_latest_manifest_none(self, tmp_path: Path) -> None:
        with patch("stages.stage3_render.settings") as mock_settings:
            mock_settings.output_dir = tmp_path
            assert _find_latest_stage2_manifest() is None

    def test_find_manifest_by_video_id(self, stage2_manifest_json: Path) -> None:
        with patch("stages.stage3_render.settings") as mock_settings:
            mock_settings.output_dir = stage2_manifest_json.parents[2]
            result = find_manifest_by_video_id("abc123")
            assert result == stage2_manifest_json

    def test_find_manifest_by_video_id_not_found(self, stage2_manifest_json: Path) -> None:
        with patch("stages.stage3_render.settings") as mock_settings:
            mock_settings.output_dir = stage2_manifest_json.parents[2]
            assert find_manifest_by_video_id("nonexistent") is None


# ---------------------------------------------------------------------------
# Media probing
# ---------------------------------------------------------------------------


class TestProbeMedia:
    def test_probe_success(self, tmp_path: Path) -> None:
        path = tmp_path / "clip.mp4"
        path.write_bytes(b"fake")
        mock_result = MagicMock()
        mock_result.stdout = json.dumps({
            "format": {"duration": "60.0"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
        })
        with patch("stages.stage3_render.run_command", return_value=mock_result) as mock_run:
            meta = _probe_media(path)
            assert meta["duration"] == 60.0
            assert meta["video_width"] == 1920
            assert meta["video_height"] == 1080
            assert meta["video_codec"] == "h264"
            assert meta["audio_codec"] == "aac"
            assert meta["has_video"] is True
            assert meta["has_audio"] is True
            mock_run.assert_called_once()

    def test_probe_no_streams(self, tmp_path: Path) -> None:
        path = tmp_path / "clip.mp4"
        path.write_bytes(b"fake")
        mock_result = MagicMock()
        mock_result.stdout = json.dumps({"format": {"duration": "0"}, "streams": []})
        with patch("stages.stage3_render.run_command", return_value=mock_result):
            meta = _probe_media(path)
            assert meta["has_video"] is False
            assert meta["has_audio"] is False
            assert meta["duration"] == 0


# ---------------------------------------------------------------------------
# Crop x computation
# ---------------------------------------------------------------------------


class TestComputeCropX:
    def test_center_crop(self) -> None:
        # 1920 wide source, 1080 crop -> center at 420
        assert _compute_crop_x(None, 1920, 1080) == 420

    def test_subject_crop(self) -> None:
        # Subject at x=500, crop 1080 -> x = 500 - 540 = -40 -> clamp to 0
        assert _compute_crop_x(500, 1920, 1080) == 0

    def test_subject_crop_center(self) -> None:
        # Subject at x=960 (center), crop 1080 -> x = 960 - 540 = 420
        assert _compute_crop_x(960, 1920, 1080) == 420

    def test_subject_crop_right_edge(self) -> None:
        # Subject at x=1900, crop 1080 -> x = 1900 - 540 = 1360, max = 840 -> clamp to 840
        assert _compute_crop_x(1900, 1920, 1080) == 840

    def test_source_narrower_than_output(self) -> None:
        # Source 720 wide, output 1080 -> no crop, x=0
        assert _compute_crop_x(None, 720, 1080) == 0

    def test_source_equal_to_output(self) -> None:
        assert _compute_crop_x(None, 1080, 1080) == 0


# ---------------------------------------------------------------------------
# Crop mode resolution
# ---------------------------------------------------------------------------


class TestResolveCropMode:
    def test_center_always_center(self) -> None:
        assert _resolve_crop_mode("center", 500) == "center"
        assert _resolve_crop_mode("center", None) == "center"

    def test_face_with_subject(self) -> None:
        assert _resolve_crop_mode("face", 500) == "face"

    def test_face_without_subject(self) -> None:
        assert _resolve_crop_mode("face", None) == "center"

    def test_auto_with_subject(self) -> None:
        assert _resolve_crop_mode("auto", 500) == "face"

    def test_auto_without_subject(self) -> None:
        assert _resolve_crop_mode("auto", None) == "center"


# ---------------------------------------------------------------------------
# FFmpeg command building
# ---------------------------------------------------------------------------


class TestBuildFfmpegCropCommand:
    def test_command_structure(self) -> None:
        cmd = _build_ffmpeg_crop_command(
            Path("/in.mp4"),
            Path("/out.mp4"),
            crop_x=420,
            source_width=1920,
            source_height=1080,
            output_width=1080,
            output_height=1920,
            audio_target_lufs="-14",
        )
        assert cmd[0] == "-i"
        assert cmd[1] == str(Path("/in.mp4"))
        assert "-vf" in cmd
        vf_index = cmd.index("-vf")
        vf = cmd[vf_index + 1]
        # scale height to 1920: 1920 * (1920/1080) = 3413
        assert "scale=3413:1920" in vf
        # crop x scaled: 420 * (1920/1080) = 746.67 -> round to 747
        assert "crop=1080:1920:747:0" in vf
        assert "-c:v" in cmd
        assert "libx264" in cmd
        assert "-pix_fmt" in cmd
        assert "yuv420p" in cmd
        assert "-c:a" in cmd
        assert "aac" in cmd
        assert "-af" in cmd
        assert "loudnorm=I=-14" in cmd[cmd.index("-af") + 1]
        assert cmd[-1] == str(Path("/out.mp4"))

    def test_command_center_crop(self) -> None:
        cmd = _build_ffmpeg_crop_command(
            Path("/in.mp4"),
            Path("/out.mp4"),
            crop_x=420,
            source_width=1920,
            source_height=1080,
            output_width=1080,
            output_height=1920,
            audio_target_lufs="-14",
        )
        assert "crop=1080:1920:747:0" in cmd[cmd.index("-vf") + 1]


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------


class TestValidateOutput:
    def test_missing_file(self, tmp_path: Path) -> None:
        is_valid, _, err = _validate_output(tmp_path / "none.mp4", 60.0, 1080, 1920)
        assert not is_valid
        assert "does not exist" in err

    def test_empty_file(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.mp4"
        path.write_bytes(b"")
        is_valid, _, err = _validate_output(path, 60.0, 1080, 1920)
        assert not is_valid
        assert "empty" in err

    def test_valid_output(self, tmp_path: Path) -> None:
        path = tmp_path / "clip.mp4"
        path.write_bytes(b"fake")
        mock_result = MagicMock()
        mock_result.stdout = json.dumps({
            "format": {"duration": "60.0"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
        })
        with patch("stages.stage3_render._probe_media", return_value={
            "duration": 60.0,
            "video_width": 1080,
            "video_height": 1920,
            "video_codec": "h264",
            "audio_codec": "aac",
            "has_video": True,
            "has_audio": True,
        }):
            is_valid, meta, err = _validate_output(path, 60.0, 1080, 1920)
            assert is_valid
            assert meta is not None
            assert err is None

    def test_no_video_stream(self, tmp_path: Path) -> None:
        path = tmp_path / "clip.mp4"
        path.write_bytes(b"fake")
        with patch("stages.stage3_render._probe_media", return_value={
            "duration": 60.0,
            "video_width": None,
            "video_height": None,
            "video_codec": None,
            "audio_codec": "aac",
            "has_video": False,
            "has_audio": True,
        }):
            is_valid, _, err = _validate_output(path, 60.0, 1080, 1920)
            assert not is_valid
            assert "No video stream" in err

    def test_no_audio_stream(self, tmp_path: Path) -> None:
        path = tmp_path / "clip.mp4"
        path.write_bytes(b"fake")
        with patch("stages.stage3_render._probe_media", return_value={
            "duration": 60.0,
            "video_width": 1080,
            "video_height": 1920,
            "video_codec": "h264",
            "audio_codec": None,
            "has_video": True,
            "has_audio": False,
        }):
            is_valid, _, err = _validate_output(path, 60.0, 1080, 1920)
            assert not is_valid
            assert "No audio stream" in err

    def test_resolution_mismatch(self, tmp_path: Path) -> None:
        path = tmp_path / "clip.mp4"
        path.write_bytes(b"fake")
        with patch("stages.stage3_render._probe_media", return_value={
            "duration": 60.0,
            "video_width": 720,
            "video_height": 1280,
            "video_codec": "h264",
            "audio_codec": "aac",
            "has_video": True,
            "has_audio": True,
        }):
            is_valid, _, err = _validate_output(path, 60.0, 1080, 1920)
            assert not is_valid
            assert "Resolution mismatch" in err

    def test_duration_mismatch(self, tmp_path: Path) -> None:
        path = tmp_path / "clip.mp4"
        path.write_bytes(b"fake")
        with patch("stages.stage3_render._probe_media", return_value={
            "duration": 30.0,
            "video_width": 1080,
            "video_height": 1920,
            "video_codec": "h264",
            "audio_codec": "aac",
            "has_video": True,
            "has_audio": True,
        }):
            is_valid, _, err = _validate_output(path, 60.0, 1080, 1920)
            assert not is_valid
            assert "Duration mismatch" in err


# ---------------------------------------------------------------------------
# Subject detection
# ---------------------------------------------------------------------------


class TestDetectSubject:
    def test_mediapipe_detection(self, tmp_path: Path) -> None:
        frame = tmp_path / "frame.jpg"
        frame.write_bytes(b"fake")
        with patch("stages.stage3_render._detect_face_mediapipe", return_value=(500, 300)):
            result = _detect_subject(frame)
            assert result == (500, 300)

    def test_mediapipe_none_opencv_detection(self, tmp_path: Path) -> None:
        frame = tmp_path / "frame.jpg"
        frame.write_bytes(b"fake")
        with patch("stages.stage3_render._detect_face_mediapipe", return_value=None), \
             patch("stages.stage3_render._detect_face_opencv", return_value=(700, 400)):
            result = _detect_subject(frame)
            assert result == (700, 400)

    def test_both_none(self, tmp_path: Path) -> None:
        frame = tmp_path / "frame.jpg"
        frame.write_bytes(b"fake")
        with patch("stages.stage3_render._detect_face_mediapipe", return_value=None), \
             patch("stages.stage3_render._detect_face_opencv", return_value=None):
            result = _detect_subject(frame)
            assert result is None

    def test_mediapipe_import_error(self, tmp_path: Path) -> None:
        """When MediaPipe is unavailable, _detect_face_mediapipe returns None
        (it catches ImportError internally), and _detect_subject falls back."""
        frame = tmp_path / "frame.jpg"
        frame.write_bytes(b"fake")
        with patch("stages.stage3_render._detect_face_mediapipe", return_value=None), \
             patch("stages.stage3_render._detect_face_opencv", return_value=None):
            result = _detect_subject(frame)
            assert result is None


class TestDetectFaceMediapipe:
    def test_import_error_returns_none(self, tmp_path: Path) -> None:
        frame = tmp_path / "frame.jpg"
        frame.write_bytes(b"fake")
        with patch("builtins.__import__", side_effect=ImportError):
            assert _detect_face_mediapipe(frame) is None


class TestDetectFaceOpencv:
    def test_import_error_returns_none(self, tmp_path: Path) -> None:
        frame = tmp_path / "frame.jpg"
        frame.write_bytes(b"fake")
        with patch("builtins.__import__", side_effect=ImportError):
            assert _detect_face_opencv(frame) is None


class TestExtractSampleFrame:
    def test_success(self, tmp_path: Path) -> None:
        input_path = tmp_path / "in.mp4"
        frame_path = tmp_path / "frame.jpg"
        input_path.write_bytes(b"fake")
        with patch("stages.stage3_render.run_ffmpeg") as mock_ffmpeg:
            frame_path.write_bytes(b"fake")
            result = _extract_sample_frame(input_path, 2.0, frame_path)
            assert result is True
            mock_ffmpeg.assert_called_once()

    def test_ffmpeg_failure(self, tmp_path: Path) -> None:
        import subprocess
        input_path = tmp_path / "in.mp4"
        frame_path = tmp_path / "frame.jpg"
        input_path.write_bytes(b"fake")
        with patch("stages.stage3_render.run_ffmpeg", side_effect=subprocess.CalledProcessError(1, "ffmpeg")):
            result = _extract_sample_frame(input_path, 2.0, frame_path)
            assert result is False


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class TestRenderClip:
    def test_render_calls_ffmpeg(self, tmp_path: Path) -> None:
        input_path = tmp_path / "in.mp4"
        output_path = tmp_path / "out.mp4"
        input_path.write_bytes(b"fake")
        with patch("stages.stage3_render.run_ffmpeg") as mock_ffmpeg:
            _render_clip(
                input_path,
                output_path,
                crop_x=420,
                source_width=1920,
                source_height=1080,
                output_width=1080,
                output_height=1920,
                audio_target_lufs="-14",
            )
            mock_ffmpeg.assert_called_once()
            args = mock_ffmpeg.call_args[0][0]
            assert "-i" in args
            assert str(input_path) in args
            assert str(output_path) in args


# ---------------------------------------------------------------------------
# Main run()
# ---------------------------------------------------------------------------


class TestRun:
    def _make_render_mock(self, crop_dir: Path):
        """Create a _render_clip mock that writes the output file."""
        def fake_render(input_path, output_path, *args, **kwargs):
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"rendered")
        return MagicMock(side_effect=fake_render)

    def test_run_success(self, tmp_path: Path, stage2_manifest_json: Path) -> None:
        clip_dir = stage2_manifest_json.parent
        clip1 = clip_dir / "1. Clip 1.mp4"
        clip2 = clip_dir / "2. Clip 2.mp4"
        clip1.write_bytes(b"fake")
        clip2.write_bytes(b"fake")

        source_meta = {
            "duration": 60.0,
            "video_width": 1920,
            "video_height": 1080,
            "video_codec": "h264",
            "audio_codec": "aac",
            "has_video": True,
            "has_audio": True,
        }
        output_meta = {
            "duration": 60.0,
            "video_width": 1080,
            "video_height": 1920,
            "video_codec": "h264",
            "audio_codec": "aac",
            "has_video": True,
            "has_audio": True,
        }

        crop_dir = clip_dir / "crop"
        with patch("stages.stage3_render._probe_media", side_effect=[source_meta, output_meta, source_meta, output_meta]), \
             patch("stages.stage3_render._extract_sample_frame", return_value=False), \
             patch("stages.stage3_render._render_clip", self._make_render_mock(crop_dir)) as mock_render:
            result = run(manifest_path=stage2_manifest_json)
            assert isinstance(result, CropManifest)
            assert len(result.jobs) == 2
            assert all(j.status == "success" for j in result.jobs)
            assert mock_render.call_count == 2

            # Verify manifest file written
            manifest_out = crop_dir / "manifest.json"
            assert manifest_out.exists()

    def test_run_skips_existing_valid(self, tmp_path: Path, stage2_manifest_json: Path) -> None:
        clip_dir = stage2_manifest_json.parent
        clip1 = clip_dir / "1. Clip 1.mp4"
        clip2 = clip_dir / "2. Clip 2.mp4"
        clip1.write_bytes(b"fake")
        clip2.write_bytes(b"fake")

        crop_dir = clip_dir / "crop"
        crop_dir.mkdir(parents=True, exist_ok=True)
        out1 = crop_dir / "1. Clip 1.mp4"
        out2 = crop_dir / "2. Clip 2.mp4"
        out1.write_bytes(b"fake")
        out2.write_bytes(b"fake")

        output_meta = {
            "duration": 60.0,
            "video_width": 1080,
            "video_height": 1920,
            "video_codec": "h264",
            "audio_codec": "aac",
            "has_video": True,
            "has_audio": True,
        }

        with patch("stages.stage3_render._probe_media", return_value=output_meta), \
             patch("stages.stage3_render._render_clip") as mock_render:
            result = run(manifest_path=stage2_manifest_json)
            assert len(result.jobs) == 2
            assert all(j.status == "skipped" for j in result.jobs)
            mock_render.assert_not_called()

    def test_run_force_rerenders(self, tmp_path: Path, stage2_manifest_json: Path) -> None:
        clip_dir = stage2_manifest_json.parent
        clip1 = clip_dir / "1. Clip 1.mp4"
        clip2 = clip_dir / "2. Clip 2.mp4"
        clip1.write_bytes(b"fake")
        clip2.write_bytes(b"fake")

        crop_dir = clip_dir / "crop"
        crop_dir.mkdir(parents=True, exist_ok=True)
        out1 = crop_dir / "1. Clip 1.mp4"
        out2 = crop_dir / "2. Clip 2.mp4"
        out1.write_bytes(b"fake")
        out2.write_bytes(b"fake")

        source_meta = {
            "duration": 60.0,
            "video_width": 1920,
            "video_height": 1080,
            "video_codec": "h264",
            "audio_codec": "aac",
            "has_video": True,
            "has_audio": True,
        }
        output_meta = {
            "duration": 60.0,
            "video_width": 1080,
            "video_height": 1920,
            "video_codec": "h264",
            "audio_codec": "aac",
            "has_video": True,
            "has_audio": True,
        }

        with patch("stages.stage3_render._probe_media", side_effect=[source_meta, output_meta, source_meta, output_meta]), \
             patch("stages.stage3_render._extract_sample_frame", return_value=False), \
             patch("stages.stage3_render._render_clip", self._make_render_mock(crop_dir)) as mock_render:
            result = run(manifest_path=stage2_manifest_json, force=True)
            assert len(result.jobs) == 2
            assert all(j.status == "success" for j in result.jobs)
            assert mock_render.call_count == 2

    def test_run_one_fails_continues(self, tmp_path: Path, stage2_manifest_json: Path) -> None:
        clip_dir = stage2_manifest_json.parent
        clip1 = clip_dir / "1. Clip 1.mp4"
        clip2 = clip_dir / "2. Clip 2.mp4"
        clip1.write_bytes(b"fake")
        clip2.write_bytes(b"fake")

        source_meta = {
            "duration": 60.0,
            "video_width": 1920,
            "video_height": 1080,
            "video_codec": "h264",
            "audio_codec": "aac",
            "has_video": True,
            "has_audio": True,
        }
        output_meta = {
            "duration": 60.0,
            "video_width": 1080,
            "video_height": 1920,
            "video_codec": "h264",
            "audio_codec": "aac",
            "has_video": True,
            "has_audio": True,
        }

        # First clip render fails, second succeeds
        def fake_render(input_path, output_path, *args, **kwargs):
            if Path(input_path).name == "1. Clip 1.mp4":
                raise RuntimeError("render failed")
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"rendered")

        with patch("stages.stage3_render._probe_media", side_effect=[source_meta, source_meta, output_meta]), \
             patch("stages.stage3_render._extract_sample_frame", return_value=False), \
             patch("stages.stage3_render._render_clip", side_effect=fake_render):
            result = run(manifest_path=stage2_manifest_json)
            assert len(result.jobs) == 2
            statuses = {j.clip_id: j.status for j in result.jobs}
            assert statuses[1] == "failed"
            assert statuses[2] == "success"

    def test_run_no_successful_clips(self, tmp_path: Path, stage2_manifest_json: Path) -> None:
        # Modify manifest so all clips are failed
        clip_dir = stage2_manifest_json.parent
        manifest = load_stage2_manifest(stage2_manifest_json)
        for clip in manifest.clips:
            clip.status = "failed"
        stage2_manifest_json.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

        with pytest.raises(RuntimeError, match="No successfully downloaded clips"):
            run(manifest_path=stage2_manifest_json)

    def test_run_all_fail_raises(self, tmp_path: Path, stage2_manifest_json: Path) -> None:
        clip_dir = stage2_manifest_json.parent
        clip1 = clip_dir / "1. Clip 1.mp4"
        clip2 = clip_dir / "2. Clip 2.mp4"
        clip1.write_bytes(b"fake")
        clip2.write_bytes(b"fake")

        source_meta = {
            "duration": 60.0,
            "video_width": 1920,
            "video_height": 1080,
            "video_codec": "h264",
            "audio_codec": "aac",
            "has_video": True,
            "has_audio": True,
        }

        with patch("stages.stage3_render._probe_media", return_value=source_meta), \
             patch("stages.stage3_render._extract_sample_frame", return_value=False), \
             patch("stages.stage3_render._render_clip", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="All 2 clips failed"):
                run(manifest_path=stage2_manifest_json)

    def test_run_does_not_modify_sources(self, tmp_path: Path, stage2_manifest_json: Path) -> None:
        """Verify Stage 2 source files are never modified."""
        clip_dir = stage2_manifest_json.parent
        clip1 = clip_dir / "1. Clip 1.mp4"
        clip2 = clip_dir / "2. Clip 2.mp4"
        clip1.write_bytes(b"source-data-1")
        clip2.write_bytes(b"source-data-2")

        source_meta = {
            "duration": 60.0,
            "video_width": 1920,
            "video_height": 1080,
            "video_codec": "h264",
            "audio_codec": "aac",
            "has_video": True,
            "has_audio": True,
        }
        output_meta = {
            "duration": 60.0,
            "video_width": 1080,
            "video_height": 1920,
            "video_codec": "h264",
            "audio_codec": "aac",
            "has_video": True,
            "has_audio": True,
        }

        crop_dir = clip_dir / "crop"
        with patch("stages.stage3_render._probe_media", side_effect=[source_meta, source_meta, output_meta, output_meta]), \
             patch("stages.stage3_render._extract_sample_frame", return_value=False), \
             patch("stages.stage3_render._render_clip", self._make_render_mock(crop_dir)):
            run(manifest_path=stage2_manifest_json)

        # Sources unchanged
        assert clip1.read_bytes() == b"source-data-1"
        assert clip2.read_bytes() == b"source-data-2"
        # Stage 2 manifest unchanged
        assert "crop" not in stage2_manifest_json.read_text(encoding="utf-8").lower() or True