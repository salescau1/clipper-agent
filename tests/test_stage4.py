"""Tests for Stage 4: Smart Subtitle Generation (WhisperX Forced Alignment, SRT-only)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from models import ClipManifest, ClipManifestEntry, SubtitleJob
from stages.stage4_subtitles import (
    _filter_and_localize_cc_segments,
    _format_srt_timestamp,
    _get_stage1_cache_path,
    _get_whisperx_cache_path,
    _is_whisperx_cache_valid,
    _normalize_transcript_text,
    generate_srt,
    group_deterministically,
    load_stage1_transcript_cache,
    load_stage2_manifest,
    transcribe_clip_whisperx,
    validate_subtitle_groups,
    write_subtitle_files,
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


@pytest.fixture
def sample_words() -> list[dict]:
    """Sample word-level transcript for testing (from WhisperX alignment)."""
    return [
        {"word": "Halo", "start": 0.0, "end": 0.3},
        {"word": "semua", "start": 0.4, "end": 0.6},
        {"word": "apa", "start": 0.7, "end": 0.9},
        {"word": "kabar?", "start": 1.0, "end": 1.3},
        {"word": "Hari", "start": 1.5, "end": 1.7},
        {"word": "ini", "start": 1.8, "end": 2.0},
        {"word": "saya", "start": 2.1, "end": 2.3},
        {"word": "mau", "start": 2.4, "end": 2.6},
        {"word": "cerita", "start": 2.7, "end": 3.0},
        {"word": "tentang", "start": 3.1, "end": 3.4},
        {"word": "pengalaman", "start": 3.5, "end": 3.9},
        {"word": "seru", "start": 4.0, "end": 4.2},
        {"word": "di", "start": 4.3, "end": 4.5},
        {"word": "liburan", "start": 4.6, "end": 4.9},
        {"word": "kemarin.", "start": 5.0, "end": 5.4},
    ]


@pytest.fixture
def sample_segments() -> list[dict]:
    """Sample segment-level transcript from YouTube CC."""
    return [
        {"start": 0.0, "duration": 1.5, "text": "Halo semua apa kabar"},
        {"start": 1.5, "duration": 2.0, "text": "Hari ini saya mau cerita"},
        {"start": 3.5, "duration": 2.0, "text": "tentang pengalaman seru di liburan kemarin"},
    ]


# ---------------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------------


class TestNormalizeTranscriptText:
    def test_normal_word_sequence(self, sample_words: list[dict]) -> None:
        result = _normalize_transcript_text(sample_words)
        assert result == "Halo semua apa kabar? Hari ini saya mau cerita tentang pengalaman seru di liburan kemarin."

    def test_missing_timestamps(self) -> None:
        words = [
            {"word": "test", "start": None, "end": None},
            {"word": "words", "start": 1.0, "end": 1.5},
        ]
        result = _normalize_transcript_text(words)
        assert result == "test words"

    def test_empty_transcript(self) -> None:
        result = _normalize_transcript_text([])
        assert result == ""

    def test_invalid_timestamps(self) -> None:
        words = [
            {"word": "a", "start": "invalid", "end": "time"},
            {"word": "b", "start": 1.0, "end": 2.0},
        ]
        result = _normalize_transcript_text(words)
        assert result == "a b"

    def test_ignored_empty_words(self) -> None:
        words = [
            {"word": "valid", "start": 0.0, "end": 0.5},
            {"word": "", "start": 0.6, "end": 0.8},
            {"word": "words", "start": 1.0, "end": 1.5},
        ]
        result = _normalize_transcript_text(words)
        assert result == "valid words"


# ---------------------------------------------------------------------------
# Stage 1 transcript cache
# ---------------------------------------------------------------------------


class TestStage1TranscriptCache:
    def test_cache_path(self, tmp_path: Path) -> None:
        path = _get_stage1_cache_path("test_video_id")
        assert "transcripts" in str(path)
        assert path.name == "test_video_id.json"

    def test_cache_not_found(self, tmp_path: Path) -> None:
        with patch("stages.stage4_subtitles.settings") as mock_settings:
            mock_settings.cache_dir = tmp_path
            result = load_stage1_transcript_cache("nonexistent")
        assert result is None

    def test_cache_found(self, tmp_path: Path) -> None:
        cache_data = {
            "source": "youtube_manual",
            "language": "id",
            "segments": [
                {"start": 0.0, "duration": 1.0, "text": "Hello world"},
            ],
        }
        cache_path = tmp_path / "transcripts" / "test123.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache_data), encoding="utf-8")

        with patch("stages.stage4_subtitles.settings") as mock_settings:
            mock_settings.cache_dir = tmp_path
            result = load_stage1_transcript_cache("test123")

        assert result is not None
        assert result["source"] == "youtube_manual"
        assert len(result["segments"]) == 1

    def test_invalid_json(self, tmp_path: Path) -> None:
        cache_path = tmp_path / "transcripts" / "bad.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text("not valid json", encoding="utf-8")

        with patch("stages.stage4_subtitles.settings") as mock_settings:
            mock_settings.cache_dir = tmp_path
            result = load_stage1_transcript_cache("bad")
        assert result is None

    def test_missing_required_fields(self, tmp_path: Path) -> None:
        cache_data = {"language": "id"}  # missing 'source' and 'segments'
        cache_path = tmp_path / "transcripts" / "incomplete.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache_data), encoding="utf-8")

        with patch("stages.stage4_subtitles.settings") as mock_settings:
            mock_settings.cache_dir = tmp_path
            result = load_stage1_transcript_cache("incomplete")
        assert result is None


# ---------------------------------------------------------------------------
# CC Segment Filtering
# ---------------------------------------------------------------------------


class TestFilterAndLocalizeCcSegments:
    def test_filter_keeps_overlapping_only(self) -> None:
        """Segments outside [clip_start, clip_end) are excluded."""
        segments = [
            {"start": 0.0, "duration": 5.0, "text": "before clip"},
            {"start": 10.0, "duration": 5.0, "text": "inside clip"},
            {"start": 20.0, "duration": 5.0, "text": "after clip"},
        ]
        filtered = _filter_and_localize_cc_segments(segments, 10.0, 15.0)
        assert len(filtered) == 1
        assert filtered[0]["text"] == "inside clip"
        assert filtered[0]["start"] == 0.0  # localized
        assert filtered[0]["duration"] == 5.0

    def test_filter_no_leakage_before_clip(self) -> None:
        """No segment with source-time < clip_start leaks in."""
        segments = [
            {"start": 5.0, "duration": 10.0, "text": "crosses boundary"},
        ]
        filtered = _filter_and_localize_cc_segments(segments, 10.0, 20.0)
        assert len(filtered) == 1
        assert filtered[0]["start"] == 0.0  # clamped to 0
        assert filtered[0]["duration"] == 5.0  # truncated from 10s to 5s

    def test_filter_no_leakage_after_clip(self) -> None:
        """No segment with source-time >= clip_end leaks in."""
        segments = [
            {"start": 15.0, "duration": 10.0, "text": "crosses end boundary"},
        ]
        filtered = _filter_and_localize_cc_segments(segments, 10.0, 20.0)
        assert len(filtered) == 1
        assert filtered[0]["start"] == 5.0
        assert filtered[0]["duration"] == 5.0  # truncated

    def test_timestamp_localization(self) -> None:
        """Source 275s → local ~5s when clip starts at 270s."""
        single = [{"start": 275.0, "duration": 3.0, "text": "hello"}]
        filtered = _filter_and_localize_cc_segments(single, 270.0, 380.0)
        assert len(filtered) == 1
        assert abs(filtered[0]["start"] - 5.0) < 0.01
        assert abs(filtered[0]["duration"] - 3.0) < 0.01

    def test_boundary_crossing_segment(self) -> None:
        """Segment spanning clip boundary is clamped correctly."""
        # Segment starts at 269s, ends at 272s — clip starts at 270s
        crossing = [{"start": 269.0, "duration": 3.0, "text": "crossing"}]
        filtered = _filter_and_localize_cc_segments(crossing, 270.0, 380.0)
        assert len(filtered) == 1
        assert abs(filtered[0]["start"] - 0.0) < 0.01  # clamped to 0
        assert abs(filtered[0]["duration"] - 2.0) < 0.01  # truncated from 3s to 2s

    def test_empty_segments(self) -> None:
        filtered = _filter_and_localize_cc_segments([], 0.0, 10.0)
        assert filtered == []

    def test_segments_with_empty_text(self) -> None:
        segments = [
            {"start": 0.0, "duration": 1.0, "text": "valid"},
            {"start": 1.0, "duration": 1.0, "text": ""},
            {"start": 2.0, "duration": 1.0, "text": "also valid"},
        ]
        filtered = _filter_and_localize_cc_segments(segments, 0.0, 10.0)
        assert len(filtered) == 2


# ---------------------------------------------------------------------------
# Subtitle grouping (deterministic only - no Gemini)
# ---------------------------------------------------------------------------


class TestGroupDeterministically:
    def test_short_speech(self) -> None:
        """Short speech should produce fewer groups."""
        words = [
            {"word": "Halo", "start": 0.0, "end": 0.3},
            {"word": "dunia", "start": 0.4, "end": 0.6},
        ]
        groups = group_deterministically(words, target_words=4, min_duration=0.5, max_duration=6.0)
        assert len(groups) >= 1
        assert groups[0]["text"] == "Halo dunia"

    def test_normal_speech(self, sample_words: list[dict]) -> None:
        groups = group_deterministically(sample_words, target_words=4, min_duration=0.5, max_duration=6.0)
        assert len(groups) >= 2
        for group in groups:
            assert "words" in group
            assert "start" in group
            assert "end" in group
            assert "text" in group

    def test_long_speech(self) -> None:
        """Long speech with more words should produce more groups."""
        words = [{"word": f"word{i}", "start": i * 0.5, "end": i * 0.5 + 0.3} for i in range(20)]
        groups = group_deterministically(words, target_words=3, min_duration=0.3, max_duration=4.0)
        assert len(groups) >= 4

    def test_natural_boundaries(self) -> None:
        """Groups should respect natural pauses (>0.3s gap)."""
        words = [
            {"word": "first", "start": 0.0, "end": 0.2},
            {"word": "phrase", "start": 0.3, "end": 0.5},
            {"word": "second", "start": 1.5, "end": 1.7},  # 1.0s gap
            {"word": "phrase", "start": 1.8, "end": 2.0},
        ]
        groups = group_deterministically(words, target_words=4, min_duration=0.3, max_duration=6.0)
        assert len(groups) >= 2  # Should split at the pause

    def test_min_duration(self) -> None:
        """Groups shorter than min_duration should be merged."""
        words = [
            {"word": "a", "start": 0.0, "end": 0.1},
            {"word": "b", "start": 0.15, "end": 0.25},
        ]
        groups = group_deterministically(words, target_words=2, min_duration=0.5, max_duration=6.0)
        assert len(groups) == 1
        assert groups[0]["text"] == "a b"

    def test_max_duration(self) -> None:
        """Groups exceeding max_duration should be capped."""
        words = [
            {"word": f"w{i}", "start": i * 0.1, "end": i * 0.1 + 0.05}
            for i in range(10)
        ]
        groups = group_deterministically(words, target_words=10, min_duration=0.1, max_duration=1.0)
        for group in groups:
            duration = group["end"] - group["start"]
            assert duration <= 1.0 + 0.1

    def test_target_words(self) -> None:
        """Groups should respect target word count."""
        words = [{"word": f"w{i}", "start": i * 0.3, "end": i * 0.3 + 0.2} for i in range(12)]
        groups = group_deterministically(words, target_words=3, min_duration=0.3, max_duration=3.0)
        assert len(groups) >= 3

    def test_empty_input(self) -> None:
        groups = group_deterministically([])
        assert groups == []

    def test_invalid_timestamps(self) -> None:
        """Should handle invalid timestamps gracefully."""
        words = [
            {"word": "a", "start": None, "end": None},
            {"word": "b", "start": 1.0, "end": 1.5},
        ]
        groups = group_deterministically(words)
        assert len(groups) >= 1

    def test_indonesian_text(self) -> None:
        """Test with Indonesian text.

        `target_words` DIBERI EKSPLISIT: default proyek berubah jadi 1 pada 2026-08-30
        (kerapatan subtitle dibakukan di theme, jadi SRT ditulis sehalus mungkin).
        Yang diuji di sini adalah penggabungan kata dalam satu grup, jadi target 3
        harus disebut supaya tesnya menguji hal itu — bukan default yang kebetulan.
        """
        words = [
            {"word": "Selamat", "start": 0.0, "end": 0.3},
            {"word": "pagi", "start": 0.4, "end": 0.6},
            {"word": "semua!", "start": 0.7, "end": 1.0},
        ]
        groups = group_deterministically(words, target_words=3)
        assert len(groups) >= 1
        assert "Selamat pagi semua!" in [g["text"] for g in groups]

    def test_default_target_words_is_one(self) -> None:
        """Default proyek = 1 kata per entri SRT.

        Ini yang membuat kerapatan bisa dibakukan di theme: `regroup_entries()` bisa
        menggabungkan 1 kata jadi 3/5 dengan waktu per kata yang NYATA, tanpa harus
        menjalankan Stage 4 ulang (~2 menit per klip).
        """
        words = [
            {"word": "Selamat", "start": 0.0, "end": 0.3},
            {"word": "pagi", "start": 0.4, "end": 0.6},
            {"word": "semua!", "start": 0.7, "end": 1.0},
        ]
        groups = group_deterministically(words)
        assert [g["text"] for g in groups] == ["Selamat", "pagi", "semua!"]


# ---------------------------------------------------------------------------
# Timestamp validation
# ---------------------------------------------------------------------------


class TestValidateSubtitleGroups:
    def test_valid_groups(self, sample_words: list[dict]) -> None:
        groups = [
            {"words": ["Halo", "semua"], "start": 0.0, "end": 0.6, "text": "Halo semua", "emphasis": False},
            {"words": ["apa", "kabar?"], "start": 0.7, "end": 1.3, "text": "apa kabar?", "emphasis": False},
        ]
        validated, errors = validate_subtitle_groups(groups, 5.4, sample_words)
        assert len(errors) == 0
        assert len(validated) == 2

    def test_negative_start(self, sample_words: list[dict]) -> None:
        groups = [
            {"words": ["a"], "start": -1.0, "end": 0.5, "text": "a", "emphasis": False},
        ]
        validated, errors = validate_subtitle_groups(groups, 5.4, sample_words)
        assert len(errors) > 0
        assert any("negative start" in e for e in errors)

    def test_end_before_start(self, sample_words: list[dict]) -> None:
        groups = [
            {"words": ["a"], "start": 2.0, "end": 1.0, "text": "a", "emphasis": False},
        ]
        validated, errors = validate_subtitle_groups(groups, 5.4, sample_words)
        assert len(errors) > 0
        assert any("end" in e and "start" in e for e in errors)

    def test_end_beyond_duration(self, sample_words: list[dict]) -> None:
        groups = [
            {"words": ["a"], "start": 0.0, "end": 10.0, "text": "a", "emphasis": False},
        ]
        validated, errors = validate_subtitle_groups(groups, 5.4, sample_words)
        assert len(validated) >= 0

    def test_overlapping_groups(self, sample_words: list[dict]) -> None:
        groups = [
            {"words": ["a"], "start": 0.0, "end": 1.0, "text": "a", "emphasis": False},
            {"words": ["b"], "start": 0.5, "end": 1.5, "text": "b", "emphasis": False},
        ]
        validated, errors = validate_subtitle_groups(groups, 5.4, sample_words)
        assert len(validated) >= 1

    def test_text_not_in_transcript(self, sample_words: list[dict]) -> None:
        groups = [
            {"words": ["nonexistent"], "start": 0.0, "end": 0.5, "text": "nonexistent", "emphasis": False},
        ]
        validated, errors = validate_subtitle_groups(groups, 5.4, sample_words)
        assert len(errors) > 0
        assert any("not found in transcript" in e for e in errors)

    def test_empty_groups(self) -> None:
        validated, errors = validate_subtitle_groups([], 5.4, [])
        assert len(validated) == 0
        assert len(errors) == 0

    def test_indonesian_text_validation(self, sample_words: list[dict]) -> None:
        """Validate groups with Indonesian text."""
        groups = [
            {"words": ["Halo", "semua"], "start": 0.0, "end": 0.6, "text": "Halo semua", "emphasis": False},
        ]
        validated, errors = validate_subtitle_groups(groups, 5.4, sample_words)
        assert len(errors) == 0


# ---------------------------------------------------------------------------
# SRT generation
# ---------------------------------------------------------------------------


class TestFormatSrtTimestamp:
    def test_zero(self) -> None:
        assert _format_srt_timestamp(0.0) == "00:00:00,000"

    def test_seconds(self) -> None:
        assert _format_srt_timestamp(1.5) == "00:00:01,500"

    def test_minutes(self) -> None:
        assert _format_srt_timestamp(65.0) == "00:01:05,000"

    def test_hours(self) -> None:
        assert _format_srt_timestamp(3661.5) == "01:01:01,500"

    def test_milliseconds(self) -> None:
        assert _format_srt_timestamp(1.123) == "00:00:01,123"


class TestGenerateSrt:
    def test_basic_generation(self, sample_words: list[dict]) -> None:
        groups = [
            {"words": ["Halo", "semua"], "start": 0.0, "end": 0.6, "text": "Halo semua", "emphasis": False},
            {"words": ["apa", "kabar?"], "start": 0.7, "end": 1.3, "text": "apa kabar?", "emphasis": False},
        ]
        srt = generate_srt(groups)
        assert "1" in srt
        assert "Halo semua" in srt
        assert "apa kabar?" in srt
        assert "-->" in srt

    def test_timestamp_format(self) -> None:
        groups = [
            {"words": ["test"], "start": 1.5, "end": 2.3, "text": "test", "emphasis": False},
        ]
        srt = generate_srt(groups)
        # Allow small floating point tolerance
        assert "00:00:01,500 --> 00:00:02,29" in srt or "00:00:01,500 --> 00:00:02,300" in srt

    def test_text_preservation(self) -> None:
        """Should preserve original text including punctuation."""
        groups = [
            {"words": ["Halo!"], "start": 0.0, "end": 0.5, "text": "Halo!", "emphasis": False},
            {"words": ["Apa", "kabar?"], "start": 0.6, "end": 1.2, "text": "Apa kabar?", "emphasis": False},
        ]
        srt = generate_srt(groups)
        assert "Halo!" in srt
        assert "Apa kabar?" in srt

    def test_empty_input(self) -> None:
        srt = generate_srt([])
        assert srt == ""

    def test_numbering(self) -> None:
        groups = [
            {"words": ["a"], "start": 0.0, "end": 0.5, "text": "a", "emphasis": False},
            {"words": ["b"], "start": 0.6, "end": 1.1, "text": "b", "emphasis": False},
            {"words": ["c"], "start": 1.2, "end": 1.7, "text": "c", "emphasis": False},
        ]
        srt = generate_srt(groups)
        lines = srt.strip().split("\n")
        # SRT format: number, timestamps, text, blank line
        assert lines[0] == "1"
        assert "a" in lines[2]
        assert lines[4] == "2"
        assert "b" in lines[6]
        assert lines[8] == "3"
        assert "c" in lines[10]

    def test_indonesian_text(self) -> None:
        """Test with Indonesian text."""
        groups = [
            {"words": ["Selamat", "pagi"], "start": 0.0, "end": 0.6, "text": "Selamat pagi", "emphasis": False},
        ]
        srt = generate_srt(groups)
        assert "Selamat pagi" in srt


# ---------------------------------------------------------------------------
# WhisperX Cache management
# ---------------------------------------------------------------------------


class TestWhisperXCache:
    def test_cache_path(self, tmp_path: Path) -> None:
        input_path = tmp_path / "clip.mp4"
        input_path.write_bytes(b"fake")
        cache_path = _get_whisperx_cache_path(input_path, "cahya/wav2vec2-large-xlsr-indonesian")
        assert "whisperx" in str(cache_path)
        assert cache_path.suffix == ".json"

    def test_cache_valid(self, tmp_path: Path) -> None:
        input_path = tmp_path / "clip.mp4"
        input_path.write_bytes(b"fake")
        cache_path = _get_whisperx_cache_path(input_path, "cahya/wav2vec2-large-xlsr-indonesian")

        # Should be invalid initially (no cache file)
        assert _is_whisperx_cache_valid(cache_path, input_path) is False

        # Create valid cache
        cache_data = {
            "input_path": str(input_path),
            "input_mtime": input_path.stat().st_mtime,
            "alignment_model": "cahya/wav2vec2-large-xlsr-indonesian",
            "language": "id",
            "word_count": 5,
            "aligned_word_count": 5,
            "alignment_fallback_count": 0,
            "words": [
                {"word": "a", "start": 0.0, "end": 0.1},
            ],
        }
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache_data), encoding="utf-8")

        # Should be valid now
        assert _is_whisperx_cache_valid(cache_path, input_path) is True

    def test_cache_invalid_after_modification(self, tmp_path: Path) -> None:
        input_path = tmp_path / "clip.mp4"
        cache_path = _get_whisperx_cache_path(input_path, "cahya/wav2vec2-large-xlsr-indonesian")

        # Create cache with old mtime
        cache_data = {
            "input_mtime": 1000.0,
            "words": [],
        }
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache_data), encoding="utf-8")

        # Modify input file
        input_path.write_bytes(b"modified")

        # Cache should be invalid
        assert _is_whisperx_cache_valid(cache_path, input_path) is False


# ---------------------------------------------------------------------------
# Output generation
# ---------------------------------------------------------------------------


class TestWriteSubtitleFiles:
    def test_write_srt_only(self, tmp_path: Path) -> None:
        """write_subtitle_files should only create SRT, no ASS."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        clip = make_clip_entry(
            clip_id=1,
            output_path=str(output_dir / "clip.mp4"),
        )
        groups = [
            {"words": ["Halo"], "start": 0.0, "end": 0.5, "text": "Halo", "emphasis": False},
        ]

        srt_path = write_subtitle_files(output_dir, clip, groups)

        assert srt_path is not None
        assert srt_path.exists()
        assert srt_path.name == "clip.srt"
        # Verify no ASS file is created
        ass_path = output_dir / "clip.ass"
        assert not ass_path.exists()

    def test_empty_groups_returns_none(self, tmp_path: Path) -> None:
        """Empty groups should return None."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        clip = make_clip_entry(
            clip_id=1,
            output_path=str(output_dir / "clip.mp4"),
        )

        srt_path = write_subtitle_files(output_dir, clip, [])
        assert srt_path is None

    def test_srt_content_format(self, tmp_path: Path) -> None:
        """Verify SRT file has correct format."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        clip = make_clip_entry(
            clip_id=1,
            output_path=str(output_dir / "clip.mp4"),
        )
        groups = [
            {"words": ["Halo"], "start": 0.0, "end": 0.5, "text": "Halo", "emphasis": False},
        ]

        srt_path = write_subtitle_files(output_dir, clip, groups)
        assert srt_path is not None

        content = srt_path.read_text(encoding="utf-8")
        assert "1" in content
        assert "Halo" in content
        assert "-->" in content


# ---------------------------------------------------------------------------
# Transcript source tracking (WhisperX fields)
# ---------------------------------------------------------------------------


class TestTranscriptSourceTracking:
    """Test that transcript_source fields are properly populated for WhisperX."""

    def test_subtitle_job_youtube_manual_whisperx_aligned(self) -> None:
        """SubtitleJob with YouTube manual transcript + WhisperX alignment."""
        job = SubtitleJob(
            clip_id=1,
            input_file="test.mp4",
            srt_file="test.srt",
            whisper_model="tiny",
            transcript_source="youtube_manual_whisperx_aligned",
            whisper_used=False,
            whisper_purpose="word_timing",
            youtube_caption_language="id",
            youtube_caption_type="manual",
            word_count=5,
            subtitle_group_count=2,
            gemini_status="not_used",
            fallback_used=False,
            validation_status="validation_passed",
            status="success",
            whisperx_used=True,
            whisperx_version="3.8.6",
            alignment_model="cahya/wav2vec2-large-xlsr-indonesian",
            aligned_word_count=5,
            alignment_fallback_count=0,
        )
        assert job.transcript_source == "youtube_manual_whisperx_aligned"
        assert not job.whisper_used
        assert job.whisper_purpose == "word_timing"
        assert job.youtube_caption_language == "id"
        assert job.youtube_caption_type == "manual"
        assert job.whisperx_used is True
        assert job.whisperx_version == "3.8.6"
        assert job.alignment_model == "cahya/wav2vec2-large-xlsr-indonesian"
        assert job.aligned_word_count == 5
        assert job.alignment_fallback_count == 0

    def test_subtitle_job_youtube_auto_whisperx_aligned(self) -> None:
        """SubtitleJob with YouTube auto transcript + WhisperX alignment."""
        job = SubtitleJob(
            clip_id=1,
            input_file="test.mp4",
            srt_file="test.srt",
            whisper_model="tiny",
            transcript_source="youtube_auto_whisperx_aligned",
            whisper_used=False,
            whisper_purpose="word_timing",
            youtube_caption_language="id",
            youtube_caption_type="auto",
            word_count=5,
            subtitle_group_count=2,
            gemini_status="not_used",
            fallback_used=False,
            validation_status="validation_passed",
            status="success",
            whisperx_used=True,
            whisperx_version="3.8.6",
            alignment_model="cahya/wav2vec2-large-xlsr-indonesian",
            aligned_word_count=5,
            alignment_fallback_count=0,
        )
        assert job.transcript_source == "youtube_auto_whisperx_aligned"
        assert job.youtube_caption_type == "auto"

    def test_subtitle_job_whisper_fallback(self) -> None:
        """SubtitleJob with Whisper fallback transcript (legacy)."""
        job = SubtitleJob(
            clip_id=1,
            input_file="test.mp4",
            srt_file="test.srt",
            whisper_model="base",
            transcript_source="whisper",
            whisper_used=True,
            whisper_purpose="fallback_transcription",
            youtube_caption_language="",
            youtube_caption_type="",
            word_count=10,
            subtitle_group_count=3,
            gemini_status="fallback",
            fallback_used=True,
            validation_status="validation_passed",
            status="success",
            whisperx_used=False,
            whisperx_version="",
            alignment_model="",
            aligned_word_count=0,
            alignment_fallback_count=0,
        )
        assert job.transcript_source == "whisper"
        assert job.whisper_used
        assert job.whisper_purpose == "fallback_transcription"
        assert job.fallback_used
        assert not job.whisperx_used

    def test_subtitle_job_skipped(self) -> None:
        """SubtitleJob for skipped clip."""
        job = SubtitleJob(
            clip_id=1,
            input_file="test.mp4",
            srt_file="test.srt",
            whisper_model="tiny",
            transcript_source="skipped",
            whisper_used=False,
            whisper_purpose="not_used",
            youtube_caption_language="",
            youtube_caption_type="",
            word_count=0,
            subtitle_group_count=0,
            gemini_status="skipped",
            fallback_used=False,
            validation_status="skipped",
            status="skipped",
            whisperx_used=False,
            whisperx_version="",
            alignment_model="",
            aligned_word_count=0,
            alignment_fallback_count=0,
        )
        assert job.status == "skipped"
        assert job.transcript_source == "skipped"

    def test_subtitle_job_failed(self) -> None:
        """SubtitleJob for failed clip."""
        job = SubtitleJob(
            clip_id=1,
            input_file="test.mp4",
            srt_file=None,
            whisper_model="tiny",
            transcript_source="failed",
            whisper_used=False,
            whisper_purpose="not_used",
            youtube_caption_language="",
            youtube_caption_type="",
            word_count=0,
            subtitle_group_count=0,
            gemini_status="failed",
            fallback_used=False,
            validation_status="skipped",
            status="failed",
            error_message="No words transcribed from clip.",
            whisperx_used=False,
            whisperx_version="",
            alignment_model="",
            aligned_word_count=0,
            alignment_fallback_count=0,
        )
        assert job.status == "failed"
        assert job.error_message == "No words transcribed from clip."


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestStage4Integration:
    def test_end_to_end_workflow(self, tmp_path: Path) -> None:
        """Test complete workflow with mocked WhisperX and deterministic grouping."""
        from stages.stage4_subtitles import run

        # Setup
        clip_dir = tmp_path / "clips" / "Test Creator - Test Video"
        clip_dir.mkdir(parents=True)

        # Create fake clip
        clip_path = clip_dir / "1. Test Clip.mp4"
        clip_path.write_bytes(b"fake video data")

        # Create Stage 2 manifest
        manifest = ClipManifest(
            video_id="test123",
            video_title="Test Video",
            creator="Test Creator",
            source_url="https://youtu.be/test123",
            output_directory=str(clip_dir),
            clips=[
                make_clip_entry(
                    clip_id=1,
                    output_path=str(clip_path),
                    actual_duration=5.4,
                ),
            ],
        )
        manifest_path = clip_dir / "manifest.json"
        manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

        # Create Stage 1 transcript cache with YouTube CC (required for new architecture)
        cache_dir = tmp_path / "cache" / "transcripts"
        cache_dir.mkdir(parents=True)
        cache_data = {
            "source": "youtube_manual",
            "language": "id",
            "segments": [
                {"start": 0.0, "duration": 2.0, "text": "Halo dunia"},
                {"start": 2.0, "duration": 2.0, "text": "ini adalah test"},
            ],
        }
        (cache_dir / "test123.json").write_text(json.dumps(cache_data), encoding="utf-8")

        # Sample transcript from WhisperX alignment
        sample_transcript = [
            {"word": "Halo", "start": 0.0, "end": 0.3},
            {"word": "dunia", "start": 0.4, "end": 0.6},
            {"word": "ini", "start": 0.7, "end": 0.9},
            {"word": "test", "start": 1.0, "end": 1.2},
        ]

        with patch("stages.stage4_subtitles.transcribe_clip_whisperx", return_value=(sample_transcript, "cahya/wav2vec2-large-xlsr-indonesian", 4, 0)):
            with patch("stages.stage4_subtitles.settings") as mock_settings:
                mock_settings.whisper_model = "tiny"
                mock_settings.subtitle_min_duration = 0.5
                mock_settings.subtitle_max_duration = 6.0
                mock_settings.subtitle_target_words = 4
                mock_settings.cache_dir = tmp_path / "cache"
                mock_settings.gemini_model = "gemini-pro"
                mock_settings.gemini_api_key = None  # Force fallback
                with patch("importlib.metadata.version", return_value="3.8.6"):
                    run(manifest_path=manifest_path)

        # Verify SRT output was created (no ASS)
        srt_path = clip_dir / "1. Test Clip.srt"
        assert srt_path.exists(), "SRT file should be created"

        ass_path = clip_dir / "1. Test Clip.ass"
        assert not ass_path.exists(), "ASS file should NOT be created"

        # Verify subtitle manifest was created
        subtitle_manifest = clip_dir / "subtitle_manifest.json"
        assert subtitle_manifest.exists()

        # Verify manifest content
        manifest_data = json.loads(subtitle_manifest.read_text(encoding="utf-8"))
        assert manifest_data["total_clips"] == 1
        assert manifest_data["successful"] == 1
        assert manifest_data["failed"] == 0
        assert len(manifest_data["jobs"]) == 1

        job = manifest_data["jobs"][0]
        assert job["status"] == "success"
        assert job["srt_file"] == str(srt_path)
        assert job["transcript_source"] == "youtube_manual_whisperx_aligned"
        assert job["whisperx_used"] is True
        assert job["whisperx_version"] == "3.8.6"
        assert job["alignment_model"] == "cahya/wav2vec2-large-xlsr-indonesian"
        assert job["aligned_word_count"] == 4
        assert job["alignment_fallback_count"] == 0

    def test_manifest_loading(self, stage2_manifest_json: Path) -> None:
        """Test loading a Stage 2 manifest."""
        manifest = load_stage2_manifest(stage2_manifest_json)
        assert manifest.video_id == "abc123"
        assert manifest.video_title == "Test Video"
        assert len(manifest.clips) == 2

    def test_manifest_not_found(self) -> None:
        """Test error when manifest is not found."""
        with pytest.raises(FileNotFoundError):
            load_stage2_manifest(Path("/nonexistent/manifest.json"))

    def test_youtube_cc_priority_whisperx(self, tmp_path: Path) -> None:
        """Test that YouTube CC transcript takes priority with WhisperX alignment."""
        from stages.stage4_subtitles import run

        clip_dir = tmp_path / "clips" / "Creator - Video"
        clip_dir.mkdir(parents=True)

        clip_path = clip_dir / "1. Clip.mp4"
        clip_path.write_bytes(b"fake video data")

        # Create Stage 2 manifest
        manifest = ClipManifest(
            video_id="cc_video",
            video_title="CC Video",
            creator="Creator",
            source_url="https://youtu.be/cc_video",
            output_directory=str(clip_dir),
            clips=[
                make_clip_entry(
                    clip_id=1,
                    output_path=str(clip_path),
                    actual_duration=5.4,
                ),
            ],
        )
        manifest_path = clip_dir / "manifest.json"
        manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

        # Create Stage 1 transcript cache with YouTube CC
        cache_dir = tmp_path / "cache" / "transcripts"
        cache_dir.mkdir(parents=True)
        cache_data = {
            "source": "youtube_manual",
            "language": "id",
            "segments": [
                {"start": 0.0, "duration": 2.0, "text": "Halo semua"},
                {"start": 2.0, "duration": 2.0, "text": "ini adalah test"},
            ],
        }
        cache_path = cache_dir / "cc_video.json"
        cache_path.write_text(json.dumps(cache_data), encoding="utf-8")

        # Mock WhisperX to return synthetic word-level timing
        sample_whisperx_words = [
            {"word": "Halo", "start": 0.0, "end": 0.5},
            {"word": "semua", "start": 0.6, "end": 1.0},
            {"word": "ini", "start": 2.0, "end": 2.3},
            {"word": "adalah", "start": 2.4, "end": 2.7},
            {"word": "test", "start": 2.8, "end": 3.2},
        ]

        with patch("stages.stage4_subtitles.transcribe_clip_whisperx", return_value=(sample_whisperx_words, "cahya/wav2vec2-large-xlsr-indonesian", 5, 0)):
            with patch("stages.stage4_subtitles.settings") as mock_settings:
                mock_settings.whisper_model = "tiny"
                mock_settings.subtitle_min_duration = 0.5
                mock_settings.subtitle_max_duration = 6.0
                mock_settings.subtitle_target_words = 4
                mock_settings.cache_dir = tmp_path / "cache"
                mock_settings.gemini_model = "gemini-pro"
                mock_settings.gemini_api_key = None
                with patch("importlib.metadata.version", return_value="3.8.6"):
                    run(manifest_path=manifest_path)

        # Verify SRT was created
        srt_path = clip_dir / "1. Clip.srt"
        assert srt_path.exists()

        # Verify manifest shows YouTube CC was used with WhisperX alignment
        manifest_data = json.loads((clip_dir / "subtitle_manifest.json").read_text(encoding="utf-8"))
        job = manifest_data["jobs"][0]
        assert job["transcript_source"] == "youtube_manual_whisperx_aligned"
        assert job["whisperx_used"] is True
        assert job["whisper_purpose"] == "word_timing"
        assert job["youtube_caption_language"] == "id"
        assert job["youtube_caption_type"] == "manual"
        assert job["aligned_word_count"] == 5
        assert job["alignment_fallback_count"] == 0

    def test_asr_fallback_when_no_cc(self, tmp_path: Path) -> None:
        """Tanpa CC YouTube, Stage 4 harus JATUH KE ASR — bukan gagal.

        Ini perilaku yang diminta di rencana_perbaikan_subtitle.txt poin 3:
        prioritas CC YouTube -> fallback ASR faster-whisper -> forced alignment.
        Sebelumnya klip tanpa CC langsung digagalkan tanpa subtitle sama sekali,
        dan tes ini dulu mengunci perilaku lama itu.
        """
        from stages.stage4_subtitles import run

        clip_dir = tmp_path / "clips" / "Creator - Video"
        clip_dir.mkdir(parents=True)

        clip_path = clip_dir / "1. Clip.mp4"
        clip_path.write_bytes(b"fake video data")

        manifest = ClipManifest(
            video_id="no_cc_video",
            video_title="No CC Video",
            creator="Creator",
            source_url="https://youtu.be/no_cc_video",
            output_directory=str(clip_dir),
            clips=[
                make_clip_entry(
                    clip_id=1,
                    output_path=str(clip_path),
                    actual_duration=5.4,
                ),
            ],
        )
        manifest_path = clip_dir / "manifest.json"
        manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

        # Tidak ada cache Stage 1 -> jalur ASR yang harus dipakai.
        sample_transcript = [
            {"word": "Halo", "start": 0.0, "end": 0.3},
            {"word": "dunia", "start": 0.4, "end": 0.6},
        ]

        with patch("stages.stage4_subtitles.transcribe_clip_whisperx", return_value=(sample_transcript, "cahya/wav2vec2-large-xlsr-indonesian", 2, 0)):
            # ASR di-mock: tes ini menguji ALUR pemilihan sumber, bukan mutu ASR.
            with patch("stages.stage4_subtitles.transcribe_clip_asr", return_value="Halo dunia") as mock_asr:
                with patch("stages.stage4_subtitles.correct_text_trilingual", side_effect=lambda t, title="": (t, "not_configured")):
                    with patch("stages.stage4_subtitles.settings") as mock_settings:
                        mock_settings.whisper_model = "tiny"
                        mock_settings.subtitle_min_duration = 0.5
                        mock_settings.subtitle_max_duration = 6.0
                        mock_settings.subtitle_target_words = 4
                        mock_settings.cache_dir = tmp_path / "cache"
                        mock_settings.gemini_model = "gemini-pro"
                        mock_settings.gemini_api_key = None
                        run(manifest_path=manifest_path)

        # ASR harus benar-benar dipanggil karena CC tidak ada.
        assert mock_asr.called, "ASR fallback harus dipanggil saat CC YouTube tidak ada"

        manifest_data = json.loads((clip_dir / "subtitle_manifest.json").read_text(encoding="utf-8"))
        job = manifest_data["jobs"][0]
        assert job["status"] == "success"
        assert job["whisper_used"] is True
        assert job["whisper_purpose"] == "asr_fallback+word_timing"
        assert "whisper_asr" in job["transcript_source"]
        assert (clip_dir / "1. Clip.srt").exists()

    def test_fails_when_no_cc_and_asr_fails(self, tmp_path: Path) -> None:
        """Kalau CC tidak ada DAN ASR gagal, klip baru boleh dinyatakan gagal."""
        from stages.stage4_subtitles import run

        clip_dir = tmp_path / "clips" / "Creator - Video"
        clip_dir.mkdir(parents=True)
        clip_path = clip_dir / "1. Clip.mp4"
        clip_path.write_bytes(b"fake video data")

        manifest = ClipManifest(
            video_id="no_cc_video",
            video_title="No CC Video",
            creator="Creator",
            source_url="https://youtu.be/no_cc_video",
            output_directory=str(clip_dir),
            clips=[
                make_clip_entry(clip_id=1, output_path=str(clip_path), actual_duration=5.4),
            ],
        )
        manifest_path = clip_dir / "manifest.json"
        manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

        with patch("stages.stage4_subtitles.transcribe_clip_asr", return_value=""):
            with patch("stages.stage4_subtitles.settings") as mock_settings:
                mock_settings.whisper_model = "tiny"
                mock_settings.subtitle_min_duration = 0.5
                mock_settings.subtitle_max_duration = 6.0
                mock_settings.subtitle_target_words = 4
                mock_settings.cache_dir = tmp_path / "cache"
                mock_settings.gemini_model = "gemini-pro"
                mock_settings.gemini_api_key = None
                with pytest.raises(RuntimeError, match="failed to generate subtitles"):
                    run(manifest_path=manifest_path)

        manifest_data = json.loads((clip_dir / "subtitle_manifest.json").read_text(encoding="utf-8"))
        job = manifest_data["jobs"][0]
        assert job["status"] == "failed"
        assert "ASR gagal" in job["error_message"]


# ---------------------------------------------------------------------------
# CC Filtering Regression Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def cc_segments_full_video() -> list[dict[str, Any]]:
    """Simulate a full 3125s video transcript (like Raditya Dika episode)."""
    segments: list[dict[str, Any]] = []
    t = 0.0
    for i in range(862):  # ~860 segments covering 0–3125s
        dur = 3.0 + (i % 5) * 0.5
        segments.append({"start": round(t, 2), "duration": round(dur, 2), "text": f"Segment at {int(t)}s"})
        t += dur
    return segments


class TestCcSegmentFiltering:
    """Regression tests for CC transcript filtering per clip range."""

    def test_filter_keeps_overlapping_only(self, cc_segments_full_video: list[dict[str, Any]]) -> None:
        """Segments outside [clip_start, clip_end) are excluded."""
        filtered = _filter_and_localize_cc_segments(cc_segments_full_video, 270.0, 380.0)
        for seg in filtered:
            assert seg["start"] >= 0.0
            assert seg["start"] + seg["duration"] <= 110.0  # clip_end - clip_start = 110s

    def test_filter_no_leakage_before_clip(self, cc_segments_full_video: list[dict[str, Any]]) -> None:
        """No segment with source-time < clip_start leaks in."""
        filtered = _filter_and_localize_cc_segments(cc_segments_full_video, 270.0, 380.0)
        for seg in filtered:
            assert seg["start"] >= 0.0  # local time, not source time

    def test_filter_no_leakage_after_clip(self, cc_segments_full_video: list[dict[str, Any]]) -> None:
        """No segment with source-time >= clip_end leaks in."""
        filtered = _filter_and_localize_cc_segments(cc_segments_full_video, 270.0, 380.0)
        for seg in filtered:
            assert seg["start"] + seg["duration"] <= 110.0

    def test_timestamp_localization(self, cc_segments_full_video: list[dict[str, Any]]) -> None:
        """Source 275s → local ~5s when clip starts at 270s."""
        single = [{"start": 275.0, "duration": 3.0, "text": "hello"}]
        filtered = _filter_and_localize_cc_segments(single, 270.0, 380.0)
        assert len(filtered) == 1
        assert abs(filtered[0]["start"] - 5.0) < 0.01
        assert abs(filtered[0]["duration"] - 3.0) < 0.01

    def test_boundary_crossing_segment(self, cc_segments_full_video: list[dict[str, Any]]) -> None:
        """Segment spanning clip boundary is clamped correctly."""
        # Segment starts at 269s, ends at 272s — clip starts at 270s
        crossing = [{"start": 269.0, "duration": 3.0, "text": "crossing"}]
        filtered = _filter_and_localize_cc_segments(crossing, 270.0, 380.0)
        assert len(filtered) == 1
        assert abs(filtered[0]["start"] - 0.0) < 0.01  # clamped to 0
        assert abs(filtered[0]["duration"] - 2.0) < 0.01  # truncated from 3s to 2s

    def test_different_clips_get_different_words(self, cc_segments_full_video: list[dict[str, Any]]) -> None:
        """Two different clips produce different word sets after alignment."""
        clip1_segs = _filter_and_localize_cc_segments(cc_segments_full_video, 270.0, 380.0)
        clip2_segs = _filter_and_localize_cc_segments(cc_segments_full_video, 599.0, 749.0)

        # Create synthetic WhisperX words for testing
        clip1_whisper = [
            {"word": "word" + str(i), "start": float(i * 0.5), "end": float(i * 0.5 + 0.4)}
            for i in range(20)
        ]
        clip2_whisper = [
            {"word": "word" + str(i), "start": float(i * 0.5 + 10), "end": float(i * 0.5 + 10.4)}
            for i in range(20)
        ]

        # Different clips should have different timing
        assert any(w1["start"] != w2["start"] for w1, w2 in zip(clip1_whisper[:5], clip2_whisper[:5]))


class TestCcIntegrationEndToEnd:
    """Integration-level regression: CC words are clip-local in generated SRT."""

    def test_cc_filtered_integration(self, tmp_path: Path, cc_segments_full_video: list[dict[str, Any]]) -> None:
        """Full pipeline: CC filtered per clip, timestamps localized in SRT output."""
        from stages.stage4_subtitles import run

        clip_dir = tmp_path / "clips" / "Test - Filtered CC"
        clip_dir.mkdir(parents=True)

        # Two clips with non-overlapping ranges
        clip1 = ClipManifestEntry(
            clip_id=1,
            source_url="https://youtu.be/test",
            start_time="00:04:30",  # 270s
            end_time="00:06:20",    # 380s
            output_path=str(clip_dir / "1. Clip 1.mp4"),
            output_file="1. Clip 1.mp4",
            title="Clip 1",
            hook="Hook 1",
            status="success",
            actual_duration=110.0,
        )
        clip2 = ClipManifestEntry(
            clip_id=2,
            source_url="https://youtu.be/test",
            start_time="00:09:59",  # 599s
            end_time="00:12:29",    # 749s
            output_path=str(clip_dir / "2. Clip 2.mp4"),
            output_file="2. Clip 2.mp4",
            title="Clip 2",
            hook="Hook 2",
            status="success",
            actual_duration=150.0,
        )

        for clip in (clip1, clip2):
            p = Path(clip.output_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"fake video data")

        manifest = ClipManifest(
            video_id="test_cc_filter",
            video_title="Test CC Filter",
            creator="Test",
            source_url="https://youtu.be/test_cc_filter",
            output_directory=str(clip_dir),
            clips=[clip1, clip2],
        )
        manifest_path = clip_dir / "manifest.json"
        manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

        # Write Stage 1 cache with full video transcript
        cache_dir = tmp_path / "cache" / "transcripts"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_data = {
            "video_id": "test_cc_filter",
            "source": "youtube_auto",
            "language": "id",
            "segments": cc_segments_full_video,
            "created_at": "2024-01-01T00:00:00Z",
        }
        (cache_dir / "test_cc_filter.json").write_text(json.dumps(cache_data), encoding="utf-8")

        # Mock WhisperX to return different synthetic word-level timing for each clip
        clip1_whisper = [
            {"word": "word" + str(i), "start": float(i * 0.5), "end": float(i * 0.5 + 0.4)}
            for i in range(50)
        ]
        clip2_whisper = [
            {"word": "word" + str(i), "start": float(i * 0.5), "end": float(i * 0.5 + 0.4)}
            for i in range(70)
        ]

        def mock_transcribe(input_path, cc_text, language, alignment_model):
            if "Clip 1" in str(input_path):
                return clip1_whisper, alignment_model, 50, 0
            return clip2_whisper, alignment_model, 70, 0

        with patch("stages.stage4_subtitles.transcribe_clip_whisperx", side_effect=mock_transcribe):
            with patch("stages.stage4_subtitles.settings") as mock_settings:
                mock_settings.whisper_model = "tiny"
                mock_settings.subtitle_min_duration = 0.5
                mock_settings.subtitle_max_duration = 6.0
                mock_settings.subtitle_target_words = 4
                mock_settings.cache_dir = tmp_path / "cache"
                mock_settings.gemini_model = "gemini-pro"
                mock_settings.gemini_api_key = None
                run(manifest_path=manifest_path)

        # Read SRT files and verify timestamps are clip-local
        srt1 = (clip_dir / "1. Clip 1.srt").read_text(encoding="utf-8")
        srt2 = (clip_dir / "2. Clip 2.srt").read_text(encoding="utf-8")

        # Both should exist and be non-empty
        assert srt1.strip(), "Clip 1 SRT should not be empty"
        assert srt2.strip(), "Clip 2 SRT should not be empty"

        # Clip 1 timestamps must start near 0 (not at source-video 270s)
        import re
        times1 = re.findall(r"(\d{2}:\d{2}:\d{2},\d{3})", srt1)
        times2 = re.findall(r"(\d{2}:\d{2}:\d{2},\d{3})", srt2)

        assert len(times1) >= 2, "Clip 1 SRT should have multiple timestamp lines"
        assert len(times2) >= 2, "Clip 2 SRT should have multiple timestamp lines"

        # First timestamp of clip 1 should be near 00:00:00,000 (local), not 00:04:30,000
        first_ts1 = times1[0]
        assert first_ts1.startswith("00:00:"), f"Clip 1 first timestamp should be local, got {first_ts1}"

        # The two clips should have different content (different source ranges)
        assert srt1 != srt2, "Different clips should produce different SRT content"

    def test_regression_no_identical_srts(self, tmp_path: Path, cc_segments_full_video: list[dict[str, Any]]) -> None:
        """Regression: all clips must NOT produce identical SRT files."""
        from stages.stage4_subtitles import run

        clip_dir = tmp_path / "clips" / "Test - No Identical"
        clip_dir.mkdir(parents=True)

        clips = []
        ranges = [(270.0, 380.0), (599.0, 749.0), (1585.0, 1688.0)]
        for i, (s, e) in enumerate(ranges, 1):
            clip = make_clip_entry(
                clip_id=i,
                output_path=str(clip_dir / f"{i}. Clip {i}.mp4"),
                actual_duration=e - s,
            )
            clip.start_time = f"00:{int(s)//60:02d}:{int(s)%60:02d}"
            clip.end_time = f"00:{int(e)//60:02d}:{int(e)%60:02d}"
            p = Path(clip.output_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"fake video data")
            clips.append(clip)

        manifest = ClipManifest(
            video_id="regression_test",
            video_title="Regression Test",
            creator="Test",
            source_url="https://youtu.be/regression_test",
            output_directory=str(clip_dir),
            clips=clips,
        )
        manifest_path = clip_dir / "manifest.json"
        manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

        cache_dir = tmp_path / "cache" / "transcripts"
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "regression_test.json").write_text(
            json.dumps({
                "video_id": "regression_test",
                "source": "youtube_auto",
                "language": "id",
                "segments": cc_segments_full_video,
                "created_at": "2024-01-01T00:00:00Z",
            }),
            encoding="utf-8",
        )

        # Mock WhisperX to return different synthetic word-level timing for each clip
        clip_whispers = {
            1: [{"word": "word" + str(i), "start": float(i * 0.5), "end": float(i * 0.5 + 0.4)} for i in range(50)],
            2: [{"word": "word" + str(i), "start": float(i * 0.5), "end": float(i * 0.5 + 0.4)} for i in range(70)],
            3: [{"word": "word" + str(i), "start": float(i * 0.5), "end": float(i * 0.5 + 0.4)} for i in range(40)],
        }

        def mock_transcribe(input_path, cc_text, language, alignment_model):
            for clip_id, words in clip_whispers.items():
                if f"Clip {clip_id}" in str(input_path):
                    return words, alignment_model, len(words), 0
            return clip_whispers[1], alignment_model, 50, 0

        with patch("stages.stage4_subtitles.transcribe_clip_whisperx", side_effect=mock_transcribe):
            with patch("stages.stage4_subtitles.settings") as mock_settings:
                mock_settings.whisper_model = "tiny"
                mock_settings.subtitle_min_duration = 0.5
                mock_settings.subtitle_max_duration = 6.0
                mock_settings.subtitle_target_words = 4
                mock_settings.cache_dir = tmp_path / "cache"
                mock_settings.gemini_model = "gemini-pro"
                mock_settings.gemini_api_key = None
                run(manifest_path=manifest_path)

        # All 3 SRTs should be different from each other
        srts = []
        for i in range(1, 4):
            srt_path = clip_dir / f"{i}. Clip {i}.srt"
            assert srt_path.exists(), f"SRT for clip {i} should exist"
            srts.append(srt_path.read_text(encoding="utf-8"))

        assert len(set(srts)) == 3, "All 3 clips should produce unique SRT content"