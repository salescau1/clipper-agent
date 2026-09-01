"""Tests for Stage 2 buffer functionality."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from config import settings
from models import CurationResult, ClipCandidate, ClipManifest, ClipManifestEntry
from stages.stage2_download import (
    _calculate_extract_end,
    _validate_clip_file,
    _run_batch_download,
    load_manifest,
    run,
    safe_remove,
    setup_logging,
    ensure_dirs,
    _get_video_metadata,
)
from utils import format_time


def sample_curation() -> CurationResult:
    return CurationResult(
        url_video="https://youtu.be/abc123",
        judul_video="Test Video",
        video_id="abc123",
        durasi_video=300.0,
        transcript_source="youtube_auto",
        transcript_language="id",
        total_klip=3,
        daftar_klip=[
            ClipCandidate(
                id_klip=1,
                judul_relevan="Clip 1",
                deskripsi="Description 1",
                start_klip="00:00:00",
                end_klip="00:01:00",
                tags=["#a", "#b", "#c"],
                hook="Hook 1",
                score=90.0,
            ),
            ClipCandidate(
                id_klip=2,
                judul_relevan="Clip 2",
                deskripsi="Description 2",
                start_klip="00:01:30",
                end_klip="00:02:30",
                tags=["#d", "#e", "#f"],
                hook="Hook 2",
                score=85.0,
            ),
            ClipCandidate(
                id_klip=3,
                judul_relevan="Clip 3",
                deskripsi="Description 3",
                start_klip="00:03:00",
                end_klip="00:04:00",
                tags=["#g", "#h", "#i"],
                hook="Hook 3",
                score=80.0,
            ),
        ],
    )


@pytest.fixture
def curation_json(tmp_path: Path) -> Path:
    path = tmp_path / "curation.json"
    path.write_text(sample_curation().model_dump_json(indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Buffer functionality tests
# ---------------------------------------------------------------------------


class TestCalculateExtractEnd:
    def test_basic_no_clamping(self) -> None:
        result = _calculate_extract_end(start_sec=0.0, end_sec=60.0, buffer_sec=30.0, video_duration=300.0)
        assert result == 90.0

    def test_clamped_to_video_duration(self) -> None:
        result = _calculate_extract_end(start_sec=250.0, end_sec=290.0, buffer_sec=30.0, video_duration=300.0)
        assert result == 300.0

    def test_zero_buffer(self) -> None:
        result = _calculate_extract_end(start_sec=10.0, end_sec=60.0, buffer_sec=0.0, video_duration=300.0)
        assert result == 60.0

    def test_raises_when_extract_end_not_after_start(self) -> None:
        with pytest.raises(ValueError, match="must be after start"):
            _calculate_extract_end(start_sec=60.0, end_sec=30.0, buffer_sec=10.0, video_duration=300.0)

    def test_raises_when_video_duration_zero(self) -> None:
        with pytest.raises(ValueError, match="Video duration must be positive"):
            _calculate_extract_end(start_sec=0.0, end_sec=60.0, buffer_sec=30.0, video_duration=0.0)


class TestBufferInRun:
    def test_manifest_includes_extract_end_and_buffer(self, curation_json: Path, tmp_path: Path) -> None:
        def batch_side_effect(url, clip_dir, pending, format_selector, label="Batch"):
            entries = []
            for clip, start, end, extract_end, filename, expected_path in pending:
                entries.append(ClipManifestEntry(
                    clip_id=clip.id_klip, source_url="https://youtu.be/abc123",
                    start_time=clip.start_klip, end_time=clip.end_klip,
                    extract_end_time=format_time(extract_end),
                    buffer_seconds=30.0,
                    output_path=str(expected_path), output_file=filename,
                    title=clip.judul_relevan, hook=clip.hook,
                    status="success", actual_duration=90.0, video_width=1920, video_height=1080,
                    video_codec="h264", audio_codec="aac", retry_count=0
                ))
            return entries, 1, []

        with patch("stages.stage2_download.settings") as mock_settings, \
             patch("stages.stage2_download.setup_logging"), \
             patch("stages.stage2_download.ensure_dirs"), \
             patch("stages.stage2_download._get_video_metadata", return_value={"title": "Test Video", "creator": "Test Channel", "duration": 300.0}), \
             patch("stages.stage2_download._run_batch_download", side_effect=batch_side_effect), \
             patch("stages.stage2_download._validate_clip_file", return_value=(True, {"duration": 90.0, "video_width": 1920, "video_height": 1080, "video_codec": "h264", "audio_codec": "aac"}, None)):

            mock_settings.output_dir = tmp_path
            mock_settings.download_retries = 2
            mock_settings.download_retry_delay = 0.1
            mock_settings.video_max_height = 1080
            mock_settings.clip_end_buffer_seconds = 30

            manifest = run(manifest_path=curation_json)
            assert all(c.extract_end_time is not None for c in manifest.clips)
            assert all(c.buffer_seconds == 30.0 for c in manifest.clips)
            clip1 = next(c for c in manifest.clips if c.clip_id == 1)
            assert clip1.actual_duration == 90.0

    def test_redownloads_when_existing_duration_mismatch(self, curation_json: Path, tmp_path: Path) -> None:
        clip_dir = tmp_path / "clips" / "Test Channel - Test Video"
        clip_dir.mkdir(parents=True)
        clip_file = clip_dir / "1. Clip 1 - Hook 1.mp4"
        clip_file.write_bytes(b"x" * 1000)

        validate_calls = []
        def fake_validate(path, expected_duration, max_height=1080):
            if path == clip_file and len(validate_calls) == 0:
                validate_calls.append(1)
                return False, None, f"Duration mismatch: expected ~{expected_duration:.1f}s, got 60.0s."
            validate_calls.append(1)
            return True, {"duration": expected_duration, "video_width": 1920, "video_height": 1080, "video_codec": "h264", "audio_codec": "aac"}, None

        def batch_side_effect(url, clip_dir, pending, format_selector, label="Batch"):
            entries = []
            for clip, start, end, extract_end, filename, expected_path in pending:
                entries.append(ClipManifestEntry(
                    clip_id=clip.id_klip, source_url="https://youtu.be/abc123",
                    start_time=clip.start_klip, end_time=clip.end_klip,
                    output_path=str(expected_path), output_file=filename,
                    title=clip.judul_relevan, hook=clip.hook,
                    status="success", actual_duration=90.0, video_width=1920, video_height=1080,
                    video_codec="h264", audio_codec="aac", retry_count=0
                ))
            return entries, 1, []

        with patch("stages.stage2_download.settings") as mock_settings, \
             patch("stages.stage2_download.setup_logging"), \
             patch("stages.stage2_download.ensure_dirs"), \
             patch("stages.stage2_download._get_video_metadata", return_value={"title": "Test Video", "creator": "Test Channel", "duration": 300.0}), \
             patch("stages.stage2_download._run_batch_download", side_effect=batch_side_effect), \
             patch("stages.stage2_download._validate_clip_file", side_effect=fake_validate):

            mock_settings.output_dir = tmp_path
            mock_settings.download_retries = 2
            mock_settings.download_retry_delay = 0.1
            mock_settings.video_max_height = 1080
            mock_settings.clip_end_buffer_seconds = 30

            manifest = run(manifest_path=curation_json)
            clip1 = next(c for c in manifest.clips if c.clip_id == 1)
            assert clip1.status == "success"
            assert clip1.actual_duration == 90.0


    def test_clip_at_end_of_video_clamps_extract_end(self, curation_json: Path, tmp_path: Path) -> None:
        def batch_side_effect(url, clip_dir, pending, format_selector, label="Batch"):
            entries = []
            for clip, start, end, extract_end, filename, expected_path in pending:
                entries.append(ClipManifestEntry(
                    clip_id=clip.id_klip, source_url="https://youtu.be/abc123",
                    start_time=clip.start_klip, end_time=clip.end_klip,
                    extract_end_time=format_time(extract_end),
                    buffer_seconds=30.0,
                    output_path=str(expected_path), output_file=filename,
                    title=clip.judul_relevan, hook=clip.hook,
                    status="success", actual_duration=extract_end - start, video_width=1920, video_height=1080,
                    video_codec="h264", audio_codec="aac", retry_count=0
                ))
            return entries, 1, []

        with patch("stages.stage2_download.settings") as mock_settings, \
             patch("stages.stage2_download.setup_logging"), \
             patch("stages.stage2_download.ensure_dirs"), \
             patch("stages.stage2_download._get_video_metadata", return_value={"title": "Test Video", "creator": "Test Channel", "duration": 250.0}), \
             patch("stages.stage2_download._run_batch_download", side_effect=batch_side_effect), \
             patch("stages.stage2_download._validate_clip_file", return_value=(True, {"duration": 250.0, "video_width": 1920, "video_height": 1080, "video_codec": "h264", "audio_codec": "aac"}, None)):

            mock_settings.output_dir = tmp_path
            mock_settings.download_retries = 2
            mock_settings.download_retry_delay = 0.1
            mock_settings.video_max_height = 1080
            mock_settings.clip_end_buffer_seconds = 30

            manifest = run(manifest_path=curation_json)
            clip3 = next(c for c in manifest.clips if c.clip_id == 3)
            assert clip3.status == "success"
            # Clip 3: start=3:00 (180s), end=4:00 (240s) + 30s buffer = 270s, but video is 250s -> clamped to 250s
            assert clip3.extract_end_time == "00:04:10"
            assert clip3.actual_duration == 70.0  # 250 - 180
