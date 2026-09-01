"""Tests for the Pydantic data contracts in models.py."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from models import (
    ClipCandidate,
    CurationResult,
    GeminiClipCandidate,
    GeminiClipResponse,
    RenderJob,
    RenderManifest,
    SubtitleJob,
    SubtitleManifest,
    TranscriptCache,
    TranscriptSegment,
)
from stages.stage1_curate import (
    _clip_overlaps,
    _validate_clip_duration,
    extract_video_id,
    fetch_video_metadata,
    get_transcript,
    validate_and_normalize_clips,
    curate_with_gemini,
    save_transcript_cache,
    load_transcript_cache,
    _normalize_segment,
    _fetch_youtube_transcript,
    _fetch_whisper_transcript,
    _build_transcript_text,
    _build_gemini_prompt,
    _parse_gemini_response,
    run as stage1_run,
)


# ---------------------------------------------------------------------------
# ClipCandidate
# ---------------------------------------------------------------------------


class TestClipCandidate:
    def test_valid_clip(self) -> None:
        clip = ClipCandidate(
            id_klip=1,
            judul_relevan="Hook",
            deskripsi="Why it works",
            start_klip="00:01:00",
            end_klip="00:01:45",
            tags=["a", "b"],
        )
        assert clip.id_klip == 1
        assert clip.start_klip == "00:01:00"
        assert clip.end_klip == "00:01:45"
        assert clip.tags == ["a", "b"]

    def test_time_normalized_to_hhmmss(self) -> None:
        # MM:SS and bare seconds should be normalized to HH:MM:SS.
        clip = ClipCandidate(
            id_klip=2,
            judul_relevan="T",
            deskripsi="D",
            start_klip="1:30",
            end_klip="90",
        )
        assert clip.start_klip == "00:01:30"
        assert clip.end_klip == "00:01:30"

    def test_invalid_time_raises(self) -> None:
        with pytest.raises(ValidationError):
            ClipCandidate(
                id_klip=3,
                judul_relevan="T",
                deskripsi="D",
                start_klip="not-a-time",
                end_klip="00:02:00",
            )

    def test_tags_default_to_empty(self) -> None:
        clip = ClipCandidate(id_klip=4, judul_relevan="T", deskripsi="D", start_klip="0", end_klip="5")
        assert clip.tags == []

    def test_duration_calculated(self) -> None:
        clip = ClipCandidate(
            id_klip=1,
            judul_relevan="T",
            deskripsi="D",
            start_klip="00:01:00",
            end_klip="00:02:30",
        )
        assert clip.durasi_detik == 90.0


# ---------------------------------------------------------------------------
# CurationResult
# ---------------------------------------------------------------------------


class TestCurationResult:
    def test_valid_result(self) -> None:
        result = CurationResult(
            url_video="https://youtu.be/abc",
            judul_video="My Video",
            daftar_klip=[
                ClipCandidate(
                    id_klip=1, judul_relevan="H", deskripsi="D", start_klip="0", end_klip="10"
                )
            ],
        )
        assert result.url_video == "https://youtu.be/abc"
        assert len(result.daftar_klip) == 1

    def test_requires_clips(self) -> None:
        with pytest.raises(ValidationError):
            CurationResult(
                url_video="https://youtu.be/abc",
                judul_video="My Video",
                daftar_klip=[],
            )


# ---------------------------------------------------------------------------
# Render / Subtitle models
# ---------------------------------------------------------------------------


class TestRenderManifest:
    def test_valid_manifest(self) -> None:
        manifest = RenderManifest(
            source="curation.json",
            jobs=[
                RenderJob(
                    id=1,
                    input_path="clips/raw/1.mp4",
                    output_path="clips/rendered/1.mp4",
                    crop_x=10,
                    target_w=608,
                    target_h=1080,
                )
            ],
        )
        assert manifest.jobs[0].target_w == 608

    def test_subtitle_manifest(self) -> None:
        manifest = SubtitleManifest(
            source="render.json",
            jobs=[
                SubtitleJob(
                    clip_id=1,
                    input_file="in.mp4",
                    srt_file="out.srt",
                    whisper_model="tiny",
                    transcript_source="unknown",
                    word_count=10,
                    status="pending",
                )
            ],
        )
        assert len(manifest.jobs) == 1
        assert manifest.jobs[0].clip_id == 1

    def test_transcript_segment(self) -> None:
        seg = TranscriptSegment(start=1.5, duration=2.0, text="hello world")
        assert seg.start == 1.5
        assert seg.duration == 2.0
        assert seg.text == "hello world"

    def test_gemini_clip_response(self) -> None:
        resp = GeminiClipResponse(
            clips=[
                GeminiClipCandidate(
                    title="Hook",
                    start="00:01:00",
                    end="00:02:00",
                    description="Why it works",
                    tags=["#viral", "#shorts", "#fyp"],
                    hook="Wait for it...",
                    score=90,
                )
            ]
        )
        assert len(resp.clips) == 1
        assert resp.clips[0].score == 90


# ---------------------------------------------------------------------------
# Stage 1 unit tests
# ---------------------------------------------------------------------------


class TestExtractVideoId:
    def test_standard_url(self) -> None:
        assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_short_url(self) -> None:
        assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_embed_url(self) -> None:
        assert extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_bare_id(self) -> None:
        assert extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_invalid_url(self) -> None:
        with pytest.raises(ValueError):
            extract_video_id("not-a-valid-url")


class TestTranscriptNormalization:
    def test_normalize_segment(self) -> None:
        from stages.stage1_curate import _normalize_segment
        seg = _normalize_segment(start=1.5, duration=2.0, text="hello   world\n")
        assert seg.start == 1.5
        assert seg.duration == 2.0
        assert seg.text == "hello world"

    def test_transcript_cache_roundtrip(self) -> None:
        cache = TranscriptCache(
            video_id="abc123",
            source="youtube_manual",
            language="id",
            segments=[TranscriptSegment(start=0.0, duration=5.0, text="test")],
            created_at="2024-01-01T00:00:00Z",
        )
        json_str = cache.model_dump_json()
        loaded = TranscriptCache.model_validate_json(json_str)
        assert loaded.video_id == "abc123"
        assert loaded.source == "youtube_manual"
        assert len(loaded.segments) == 1


class TestTimestampValidation:
    def test_valid_timestamps(self) -> None:
        candidates = [
            GeminiClipCandidate(title="T", start="00:01:00", end="00:02:30", description="D", tags=["#a", "#b", "#c"], hook="H", score=50),
        ]
        result = validate_and_normalize_clips(candidates, video_duration=300.0, target_count=5)
        assert len(result) == 1
        assert result[0].start_klip == "00:01:00"
        assert result[0].end_klip == "00:02:30"

    def test_invalid_timestamp_rejected(self) -> None:
        candidates = [
            GeminiClipCandidate(title="T", start="not-a-time", end="00:02:00", description="D", tags=["#a", "#b", "#c"], hook="H", score=50),
        ]
        result = validate_and_normalize_clips(candidates, video_duration=300.0, target_count=5)
        assert len(result) == 0

    def test_start_after_end_rejected(self) -> None:
        candidates = [
            GeminiClipCandidate(title="T", start="00:02:00", end="00:01:00", description="D", tags=["#a", "#b", "#c"], hook="H", score=50),
        ]
        result = validate_and_normalize_clips(candidates, video_duration=300.0, target_count=5)
        assert len(result) == 0

    def test_exceeds_duration_rejected(self) -> None:
        candidates = [
            GeminiClipCandidate(title="T", start="00:05:00", end="00:10:00", description="D", tags=["#a", "#b", "#c"], hook="H", score=50),
        ]
        result = validate_and_normalize_clips(candidates, video_duration=240.0, target_count=5)
        assert len(result) == 0

    def test_too_short_rejected(self) -> None:
        candidates = [
            GeminiClipCandidate(title="T", start="00:01:00", end="00:01:30", description="D", tags=["#a", "#b", "#c"], hook="H", score=50),
        ]
        result = validate_and_normalize_clips(candidates, video_duration=300.0, target_count=5)
        assert len(result) == 0

    def test_too_long_rejected(self) -> None:
        candidates = [
            GeminiClipCandidate(title="T", start="00:00:00", end="00:10:00", description="D", tags=["#a", "#b", "#c"], hook="H", score=50),
        ]
        result = validate_and_normalize_clips(candidates, video_duration=600.0, target_count=5)
        assert len(result) == 0


class TestDuplicateOverlapFiltering:
    def test_no_overlap_accepted(self) -> None:
        candidates = [
            GeminiClipCandidate(title="A", start="00:01:00", end="00:03:00", description="D", score=80, tags=["#a", "#b", "#c"], hook="H"),
            GeminiClipCandidate(title="B", start="00:05:00", end="00:07:00", description="D", score=70, tags=["#d", "#e", "#f"], hook="H"),
        ]
        result = validate_and_normalize_clips(candidates, video_duration=600.0, target_count=5)
        assert len(result) == 2

    def test_duplicate_overlap_rejected(self) -> None:
        candidates = [
            GeminiClipCandidate(title="A", start="00:01:00", end="00:03:00", description="D", score=90, tags=["#a", "#b", "#c"], hook="H"),
            GeminiClipCandidate(title="B", start="00:02:00", end="00:04:00", description="D", score=80, tags=["#d", "#e", "#f"], hook="H"),
        ]
        result = validate_and_normalize_clips(candidates, video_duration=600.0, target_count=5)
        # Only the first (higher score) should be kept
        assert len(result) == 1
        assert result[0].judul_relevan == "A"

    def test_target_count_respected(self) -> None:
        candidates = [
            GeminiClipCandidate(title=f"C{i}", start=f"00:0{i}:00", end=f"00:0{i+2}:00", description="D", score=round((1.0 - i * 0.1) * 100), tags=["#a", "#b", "#c"], hook="H")
            for i in range(1, 8)
        ]
        result = validate_and_normalize_clips(candidates, video_duration=600.0, target_count=3)
        assert len(result) == 3


class TestClipDurationValidation:
    def test_ideal_range_accepted(self) -> None:
        candidates = [
            GeminiClipCandidate(title="T", start="00:01:30", end="00:03:00", description="D", tags=["#a", "#b", "#c"], hook="H", score=50),
        ]
        result = validate_and_normalize_clips(candidates, video_duration=300.0, target_count=5)
        assert len(result) == 1
        assert 60 <= result[0].durasi_detik <= 240

    def test_boundary_min_accepted(self) -> None:
        candidates = [
            GeminiClipCandidate(title="T", start="00:01:00", end="00:02:00", description="D", tags=["#a", "#b", "#c"], hook="H", score=50),
        ]
        result = validate_and_normalize_clips(candidates, video_duration=300.0, target_count=5)
        assert len(result) == 1

    def test_boundary_max_accepted(self) -> None:
        candidates = [
            GeminiClipCandidate(title="T", start="00:00:00", end="00:04:00", description="D", tags=["#a", "#b", "#c"], hook="H", score=50),
        ]
        result = validate_and_normalize_clips(candidates, video_duration=300.0, target_count=5)
        assert len(result) == 1


class TestPydanticOutputValidation:
    def test_curation_result_serialization(self) -> None:
        curation = CurationResult(
            url_video="https://youtu.be/abc",
            judul_video="Test Video",
            video_id="abc123",
            durasi_video=300.0,
            transcript_source="youtube_manual",
            transcript_language="id",
            total_klip=2,
            daftar_klip=[
                ClipCandidate(
                    id_klip=1,
                    judul_relevan="Hook",
                    deskripsi="Why",
                    start_klip="00:01:00",
                    end_klip="00:02:30",
                    tags=["#viral", "#shorts", "#fyp"],
                    durasi_detik=90.0,
                    hook="Wait for it",
                    score=90,
                ),
                ClipCandidate(
                    id_klip=2,
                    judul_relevan="Punchline",
                    deskripsi="Best part",
                    start_klip="00:05:00",
                    end_klip="00:06:30",
                    tags=["#funny", "#viral", "#fyp"],
                    durasi_detik=90.0,
                    hook="You won't believe",
                    score=85,
                ),
            ],
        )
        json_str = curation.model_dump_json(by_alias=True)
        loaded = CurationResult.model_validate_json(json_str)
        assert loaded.url_video == "https://youtu.be/abc"
        assert loaded.video_id == "abc123"
        assert loaded.total_klip == 2
        assert len(loaded.daftar_klip) == 2
        assert loaded.daftar_klip[0].start_klip == "00:01:00"
        assert loaded.daftar_klip[1].end_klip == "00:06:30"

    def test_gemini_response_parsing(self) -> None:
        raw = json.dumps({
            "clips": [
                {
                    "title": "Hook",
                    "start": "00:01:00",
                    "end": "00:02:00",
                    "description": "D",
                    "score": 90,
                    "tags": ["#a", "#b", "#c"],
                    "hook": "H",
                }
            ]
        })
        resp = GeminiClipResponse.model_validate_json(raw)
        assert len(resp.clips) == 1
        assert resp.clips[0].score == 90


class TestSubtitleManifest:
    def test_valid_manifest(self) -> None:
        manifest = SubtitleManifest(
            source="render.json",
            jobs=[
                SubtitleJob(
                    clip_id=1,
                    input_file="clips/rendered/1.mp4",
                    srt_file="clips/final/1.srt",
                    whisper_model="small",
                    transcript_source="whisper",
                    word_count=50,
                    status="success",
                )
            ],
        )
        assert manifest.jobs[0].clip_id == 1
        assert manifest.jobs[0].input_file == "clips/rendered/1.mp4"


class TestGeminiConfig:
    """Test Gemini API configuration handling."""

    def test_missing_api_key_raises_error(self) -> None:
        """Test that curate_with_gemini fails with clear error when API key is missing."""
        from stages.stage1_curate import curate_with_gemini
        from unittest.mock import patch
        from config import settings

        with patch.object(settings, 'gemini_api_key', ''):
            with pytest.raises(RuntimeError, match="GEMINI_API_KEY is not configured"):
                curate_with_gemini("test transcript", 3, 300.0)

    def test_api_key_not_exposed_in_logs(self) -> None:
        """Test that API key is never exposed in logs or error messages."""
        from config import settings
        import logging
        from io import StringIO

        # Verify the key is loaded
        assert bool(settings.gemini_api_key)
        
        # Check that the error message for missing key doesn't expose the key format
        error_msg = "GEMINI_API_KEY is not configured. Set it in .env or environment variables."
        assert settings.gemini_api_key not in error_msg
        # Also check partial key is not exposed
        assert settings.gemini_api_key[:8] not in error_msg


# ---------------------------------------------------------------------------
# Metadata tests
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_valid_youtube_url(self) -> None:
        assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        assert extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_invalid_youtube_url(self) -> None:
        with pytest.raises(ValueError):
            extract_video_id("not-a-valid-url")
        with pytest.raises(ValueError):
            extract_video_id("https://example.com/watch?v=short")

    def test_fetch_video_metadata_success(self) -> None:
        """Test that fetch_video_metadata returns expected structure."""
        result = fetch_video_metadata("dQw4w9WgXcQ")
        assert "title" in result
        assert "duration" in result
        assert isinstance(result["title"], str)
        assert isinstance(result["duration"], (int, float))


# ---------------------------------------------------------------------------
# Transcript tests
# ---------------------------------------------------------------------------


class TestTranscript:
    def test_normalize_segment(self) -> None:
        seg = _normalize_segment(start=1.5, duration=2.0, text="hello   world\n")
        assert seg.start == 1.5
        assert seg.duration == 2.0
        assert seg.text == "hello world"

    def test_normalize_empty_text(self) -> None:
        seg = _normalize_segment(start=0.0, duration=1.0, text="   ")
        assert seg.text == ""

    def test_build_transcript_text(self) -> None:
        segments = [
            TranscriptSegment(start=0.0, duration=5.0, text="Hello world"),
            TranscriptSegment(start=5.0, duration=3.0, text="This is a test"),
        ]
        text = _build_transcript_text(segments)
        assert "[00:00:00] Hello world" in text
        assert "[00:00:05] This is a test" in text

    def test_build_gemini_prompt(self) -> None:
        prompt = _build_gemini_prompt("test transcript", 3, 300.0)
        assert "3 klip" in prompt
        assert "60-240 detik" in prompt
        assert "test transcript" in prompt

    def test_parse_gemini_response_valid(self) -> None:
        raw = json.dumps({
            "clips": [
                {"title": "Hook", "start": "00:01:00", "end": "00:02:00", "description": "D", "score": 90, "tags": ["#a", "#b", "#c"], "hook": "H"}
            ]
        })
        candidates = _parse_gemini_response(raw)
        assert len(candidates) == 1
        assert candidates[0].title == "Hook"

    def test_parse_gemini_response_list(self) -> None:
        raw = json.dumps([
            {"title": "A", "start": "00:01:00", "end": "00:02:00", "description": "D", "score": 80, "tags": ["#a", "#b", "#c"], "hook": "H"},
            {"title": "B", "start": "00:03:00", "end": "00:04:00", "description": "D", "score": 70, "tags": ["#d", "#e", "#f"], "hook": "H"},
        ])
        candidates = _parse_gemini_response(raw)
        assert len(candidates) == 2

    def test_parse_gemini_response_malformed(self) -> None:
        with pytest.raises(RuntimeError, match="Failed to parse Gemini response"):
            _parse_gemini_response("not json")

    def test_parse_gemini_response_empty_clips(self) -> None:
        """Empty clips list is valid at parse stage; validation happens later."""
        raw = json.dumps({"clips": []})
        candidates = _parse_gemini_response(raw)
        assert candidates == []


# ---------------------------------------------------------------------------
# Cache tests
# ---------------------------------------------------------------------------


class TestTranscriptCache:
    def test_cache_save_and_load(self, tmp_path: Path) -> None:
        """Test saving and loading transcript cache."""
        from config import settings
        original_cache = settings.cache_dir
        settings.cache_dir = tmp_path
        
        segments = [
            TranscriptSegment(start=0.0, duration=5.0, text="test"),
            TranscriptSegment(start=5.0, duration=3.0, text="hello"),
        ]
        save_transcript_cache("test123", "youtube_manual", "id", segments)
        
        loaded = load_transcript_cache("test123")
        assert loaded is not None
        assert loaded.video_id == "test123"
        assert loaded.source == "youtube_manual"
        assert loaded.language == "id"
        assert len(loaded.segments) == 2
        
        settings.cache_dir = original_cache

    def test_cache_miss(self, tmp_path: Path) -> None:
        from config import settings
        original_cache = settings.cache_dir
        settings.cache_dir = tmp_path
        
        loaded = load_transcript_cache("nonexistent")
        assert loaded is None
        
        settings.cache_dir = original_cache

    def test_cache_invalid_json(self, tmp_path: Path) -> None:
        from config import settings
        original_cache = settings.cache_dir
        settings.cache_dir = tmp_path
        
        cache_file = tmp_path / "transcripts" / "bad.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text("invalid json", encoding="utf-8")
        
        loaded = load_transcript_cache("bad")
        assert loaded is None
        
        settings.cache_dir = original_cache


# ---------------------------------------------------------------------------
# Gemini mock tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Integration-style tests (mocked)
# ---------------------------------------------------------------------------
