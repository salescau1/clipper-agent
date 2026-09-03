"""Tests for Stage 2: download curated clip ranges."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config import settings
from models import CurationResult, ClipCandidate, ClipManifest, ClipManifestEntry
from bundled_paths import ytdlp_cmd
from stages.stage2_download import (
    _classify_download_error,
    _clip_filename,
    _clip_output_dir,
    _existing_clip_path,
    _find_latest_manifest,
    _validate_timestamps,
    _validate_clip_file,
    _build_ytdlp_command,
    _build_batch_ytdlp_command,
    _run_batch_download,
    _get_video_duration,
    _get_video_metadata,
    _sanitize_path_component,
    _sanitize_filename,
    load_manifest,
    run,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
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
def curation_json(tmp_path: Path, sample_curation: CurationResult) -> Path:
    path = tmp_path / "curation.json"
    path.write_text(sample_curation.model_dump_json(indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Manifest loading / validation
# ---------------------------------------------------------------------------


class TestLoadManifest:
    def test_valid_manifest(self, curation_json: Path) -> None:
        result = load_manifest(curation_json)
        assert result.video_id == "abc123"
        assert len(result.daftar_klip) == 3

    def test_missing_file(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_manifest(Path("/nonexistent/path.json"))

    def test_invalid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid JSON"):
            load_manifest(path)

    def test_missing_required_fields(self, tmp_path: Path) -> None:
        path = tmp_path / "partial.json"
        path.write_text(json.dumps({"url_video": "https://example.com"}), encoding="utf-8")
        with pytest.raises(ValueError, match="missing required"):
            load_manifest(path)

    def test_empty_clips_list(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.json"
        data = {
            "url_video": "https://example.com",
            "judul_video": "Title",
            "video_id": "vid1",
            "daftar_klip": [],
        }
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(ValueError, match="no clips"):
            load_manifest(path)

    def test_find_latest_manifest(self, tmp_path: Path) -> None:
        with patch("stages.stage2_download.settings") as mock_settings:
            mock_settings.output_dir = tmp_path
            curation_dir = tmp_path / "curation"
            curation_dir.mkdir(parents=True)
            (curation_dir / "a.json").write_text('{"url_video":"x","judul_video":"y","video_id":"z","daftar_klip":[]}')
            (curation_dir / "b.json").write_text('{"url_video":"x","judul_video":"y","video_id":"z","daftar_klip":[]}')
            result = _find_latest_manifest()
            assert result is not None


# ---------------------------------------------------------------------------
# Timestamp validation
# ---------------------------------------------------------------------------


class TestValidateTimestamps:
    def test_valid_timestamps(self) -> None:
        clip = ClipCandidate(
            id_klip=1, judul_relevan="A", deskripsi="B",
            start_klip="00:01:00", end_klip="00:02:00",
            tags=[], hook="H", score=100.0,
        )
        start, end = _validate_timestamps(clip, 300.0)
        assert start == 60.0
        assert end == 120.0

    def test_negative_start(self, tmp_path: Path) -> None:
        # Create curation with end < start (valid Pydantic format, invalid logic)
        clip = ClipCandidate(
            id_klip=1, judul_relevan="A", deskripsi="B",
            start_klip="00:02:00", end_klip="00:01:00",
            tags=[], hook="H", score=100.0,
        )
        with pytest.raises(ValueError, match="must be after"):
            _validate_timestamps(clip, 300.0)

    def test_end_before_start(self) -> None:
        clip = ClipCandidate(
            id_klip=1, judul_relevan="A", deskripsi="B",
            start_klip="00:02:00", end_klip="00:01:00",
            tags=[], hook="H", score=100.0,
        )
        with pytest.raises(ValueError, match="must be after"):
            _validate_timestamps(clip, 300.0)

    def test_exceeds_duration(self) -> None:
        clip = ClipCandidate(
            id_klip=1, judul_relevan="A", deskripsi="B",
            start_klip="00:05:00", end_klip="00:06:00",
            tags=[], hook="H", score=100.0,
        )
        with pytest.raises(ValueError, match="exceeds"):
            _validate_timestamps(clip, 250.0)

    def test_no_duration_check_when_zero(self) -> None:
        clip = ClipCandidate(
            id_klip=1, judul_relevan="A", deskripsi="B",
            start_klip="00:05:00", end_klip="00:06:00",
            tags=[], hook="H", score=100.0,
        )
        start, end = _validate_timestamps(clip, 0.0)
        assert start == 300.0
        assert end == 360.0


# ---------------------------------------------------------------------------
# Output path helpers
# ---------------------------------------------------------------------------


class TestOutputPaths:
    def test_clip_filename_with_clip_object(self) -> None:
        clip = ClipCandidate(
            id_klip=1, judul_relevan="My Clip", deskripsi="D",
            start_klip="00:01:00", end_klip="00:02:00",
            tags=[], hook="Best Moment", score=95.0,
        )
        result = _clip_filename(clip)
        assert result.startswith("1.")
        assert "My Clip" in result
        assert "Best Moment" in result
        assert result.endswith(".mp4")


    def test_existing_clip_path(self, tmp_path: Path) -> None:
        clip_dir = tmp_path / "clips"
        clip_dir.mkdir(parents=True)
        clip_file = clip_dir / "1. Clip.mp4"
        clip_file.write_bytes(b"x" * 100)
        assert _existing_clip_path(clip_dir, 1, "1. Clip.mp4") == clip_file
        assert _existing_clip_path(clip_dir, 1, "missing.mp4") is None

    def test_existing_clip_path_missing(self, tmp_path: Path) -> None:
        clip_dir = tmp_path / "clips"
        clip_dir.mkdir(parents=True)
        assert _existing_clip_path(clip_dir, 1, "1. Clip.mp4") is None


# ---------------------------------------------------------------------------
# yt-dlp command building
# ---------------------------------------------------------------------------


class TestBuildYtDlpCommand:
    def test_command_structure(self) -> None:
        cmd = _build_ytdlp_command(
            url="https://youtu.be/test",
            output_path=Path("/tmp/out.mp4"),
            start_sec=10.0,
            end_sec=70.0,
        )
        # yt-dlp sekarang dipanggil sebagai MODUL (`python -m yt_dlp`) supaya tidak
        # bergantung pada `.venv/Scripts/yt-dlp.exe` — shebang biner itu absolut ke
        # mesin pengembang dan mati di komputer lain. `ytdlp_cmd()` mengembalikan LIST
        # (3 token via modul, atau 1 token `yt-dlp` sebagai fallback PATH), jadi yang
        # diperiksa adalah PREFIKS perintah, bukan keberadaan satu string "yt-dlp".
        assert cmd[: len(ytdlp_cmd())] == ytdlp_cmd()
        assert "--download-sections" in cmd
        assert "*10.0-70.0" in cmd
        assert cmd[-1] == "https://youtu.be/test"

    def test_batch_command_structure(self, tmp_path: Path) -> None:
        cmd = _build_batch_ytdlp_command(
            url="https://youtu.be/test",
            temp_path=tmp_path / "video.mp4",
        )
        assert cmd[: len(ytdlp_cmd())] == ytdlp_cmd()
        assert "-f" in cmd
        assert str(tmp_path / "video.mp4") in cmd
        assert "https://youtu.be/test" in cmd


class TestYtdlpCmdHelper:
    """Kontrak `bundled_paths.ytdlp_cmd()` + pemasangan argumen opsional.

    Kelas ini menjaga bug yang baru saja diperbaiki: perintah yt-dlp dulu memakai
    `cmd.insert(3, "--extractor-args")`. Begitu token awal berubah dari 1 elemen
    (`yt-dlp`) menjadi 3 elemen (`python -m yt_dlp`), indeks tetap itu menyelipkan
    argumen ke TENGAH perintah (antara `-m` dan `yt_dlp`) dan yt-dlp tidak jalan.
    """

    def test_returns_list_not_string(self) -> None:
        cmd = ytdlp_cmd()
        assert isinstance(cmd, list)
        assert all(isinstance(token, str) for token in cmd)
        assert len(cmd) >= 1

    def test_module_path_when_yt_dlp_importable(self) -> None:
        """Di venv proyek `yt_dlp` terpasang, jadi jalurnya HARUS modul."""
        import sys

        import bundled_paths as bp

        if not bp.ytdlp_available():
            pytest.skip("modul yt_dlp tidak terpasang di interpreter ini")
        assert ytdlp_cmd() == [sys.executable, "-m", "yt_dlp"]
        assert bp.ytdlp_source() == "modul python"

    def test_fallback_to_bare_name_when_module_missing(self) -> None:
        """Tanpa modul `yt_dlp`, perilaku lama (nama telanjang di PATH) dipakai."""
        import bundled_paths as bp

        with patch.object(bp, "ytdlp_available", return_value=False):
            assert bp.ytdlp_cmd() == ["yt-dlp"]
            assert bp.ytdlp_source() == "PATH"

    def test_extractor_args_stay_paired(self, tmp_path: Path) -> None:
        """`--extractor-args` harus diikuti nilainya, dan `-f` diikuti selector."""
        with patch("stages.stage2_download.settings") as mock_settings:
            mock_settings.video_max_height = 1080
            mock_settings.ytdlp_player_client = "android,ios"
            for cmd in (
                _build_ytdlp_command(
                    url="https://youtu.be/test",
                    output_path=tmp_path / "clip.mp4",
                    start_sec=1.0,
                    end_sec=2.0,
                ),
                _build_batch_ytdlp_command(
                    url="https://youtu.be/test",
                    temp_path=tmp_path / "full.mp4",
                ),
            ):
                i = cmd.index("--extractor-args")
                assert cmd[i + 1] == "youtube:player_client=android,ios"
                j = cmd.index("-f")
                assert cmd[j + 1].startswith("best")
                # Prefiks perintah tidak boleh tersentuh argumen opsional.
                assert cmd[: len(ytdlp_cmd())] == ytdlp_cmd()


# ---------------------------------------------------------------------------
# Video metadata
# ---------------------------------------------------------------------------


class TestGetVideoDuration:
    def test_success(self) -> None:
        mock_result = MagicMock()
        mock_result.stdout = json.dumps({"duration": 300})
        with patch("stages.stage2_download.run_command", return_value=mock_result):
            dur = _get_video_duration("https://youtu.be/abc123")
            assert dur == 300.0

    def test_failure_returns_zero(self) -> None:
        with patch("stages.stage2_download.run_command", side_effect=Exception("network error")):
            dur = _get_video_duration("https://youtu.be/abc123")
            assert dur == 0.0


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidateClipFile:
    def test_valid_file(self, tmp_path: Path) -> None:
        clip_path = tmp_path / "clip.mp4"
        clip_path.write_bytes(b"x" * 1000)
        mock_result = MagicMock()
        mock_result.stdout = json.dumps({
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "duration": "60.0"},
                {"codec_type": "audio", "codec_name": "aac"},
            ]
        })
        with patch("stages.stage2_download.run_command", return_value=mock_result):
            is_valid, meta, err = _validate_clip_file(clip_path, 60.0)
            assert is_valid is True
            assert meta["video_height"] == 1080
            assert meta["audio_codec"] == "aac"

    def test_missing_file(self, tmp_path: Path) -> None:
        clip_path = tmp_path / "missing.mp4"
        is_valid, meta, err = _validate_clip_file(clip_path, 60.0)
        assert is_valid is False
        assert "does not exist" in (err or "")

    def test_empty_file(self, tmp_path: Path) -> None:
        clip_path = tmp_path / "empty.mp4"
        clip_path.write_bytes(b"")
        is_valid, meta, err = _validate_clip_file(clip_path, 60.0)
        assert is_valid is False
        assert "empty" in (err or "").lower()

    def test_no_video_stream(self, tmp_path: Path) -> None:
        clip_path = tmp_path / "clip.mp4"
        clip_path.write_bytes(b"x" * 1000)
        mock_result = MagicMock()
        mock_result.stdout = json.dumps({"streams": []})
        with patch("stages.stage2_download.run_command", return_value=mock_result):
            is_valid, meta, err = _validate_clip_file(clip_path, 60.0)
            assert is_valid is False
            assert "video stream" in (err or "").lower()

    def test_duration_mismatch(self, tmp_path: Path) -> None:
        clip_path = tmp_path / "clip.mp4"
        clip_path.write_bytes(b"x" * 1000)
        mock_result = MagicMock()
        mock_result.stdout = json.dumps({
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "duration": "10.0"},
                {"codec_type": "audio", "codec_name": "aac"},
            ]
        })
        with patch("stages.stage2_download.run_command", return_value=mock_result):
            is_valid, meta, err = _validate_clip_file(clip_path, 60.0)
            assert is_valid is False
            assert "Duration mismatch" in (err or "")


# ---------------------------------------------------------------------------
# Full run integration (mocked)
# ---------------------------------------------------------------------------


class TestRunStage2:


    def test_failed_clip_handling(self, curation_json: Path, tmp_path: Path) -> None:
        """Test that failed clips are recorded and processing continues."""
        def batch_side_effect(url, clip_dir, pending, format_selector, label="Batch"):
            entries = []
            remaining = []
            for clip, start, end, extract_end, filename, expected_path in pending:
                if clip.id_klip == 1:
                    remaining.append((clip, start, end, extract_end, filename, expected_path))
                else:
                    entries.append(ClipManifestEntry(
                        clip_id=clip.id_klip, source_url="https://youtu.be/abc123",
                        start_time=clip.start_klip, end_time=clip.end_klip,
                        output_path=str(expected_path), output_file=filename,
                        title=clip.judul_relevan, hook=clip.hook,
                        status="success", actual_duration=60.0, video_width=1920, video_height=1080,
                        video_codec="h264", audio_codec="aac", retry_count=0
                    ))
            return entries, 1, remaining

        with patch("stages.stage2_download.settings") as mock_settings, \
             patch("stages.stage2_download.setup_logging"), \
             patch("stages.stage2_download.ensure_dirs"), \
             patch("stages.stage2_download._get_video_metadata", return_value={"title": "Test Video", "creator": "Test Channel", "duration": 300.0}), \
             patch("stages.stage2_download._run_batch_download", side_effect=batch_side_effect), \
             patch("stages.stage2_download._validate_clip_file", return_value=(True, {"duration": 60.0, "video_width": 1920, "video_height": 1080, "video_codec": "h264", "audio_codec": "aac"}, None)):

            mock_settings.output_dir = tmp_path
            mock_settings.download_retries = 3
            mock_settings.download_retry_delay = 0.1
            mock_settings.video_max_height = 1080
            mock_settings.clip_end_buffer_seconds = 30

            manifest = run(manifest_path=curation_json)
            # Batch succeeds for clips 2,3; clip 1 goes to individual recovery and fails
            assert any(c.status == "failed" and c.clip_id == 1 for c in manifest.clips)
            assert all(c.status == "success" for c in manifest.clips if c.clip_id in (2, 3))

    def test_all_fail_raises_error(self, curation_json: Path, tmp_path: Path) -> None:
        """Test that RuntimeError is raised when all clips fail."""
        def batch_side_effect(url, clip_dir, pending, format_selector, label="Batch"):
            return [], 1, pending

        with patch("stages.stage2_download.settings") as mock_settings, \
             patch("stages.stage2_download.setup_logging"), \
             patch("stages.stage2_download.ensure_dirs"), \
             patch("stages.stage2_download._get_video_metadata", return_value={"title": "Test Video", "creator": "Test Channel", "duration": 300.0}), \
             patch("stages.stage2_download._run_batch_download", side_effect=batch_side_effect):

            mock_settings.output_dir = tmp_path
            mock_settings.download_retries = 1
            mock_settings.download_retry_delay = 0.1
            mock_settings.video_max_height = 1080
            mock_settings.clip_end_buffer_seconds = 30

            with pytest.raises(RuntimeError, match="All 3 clips failed"):
                run(manifest_path=curation_json)

    def test_force_redownload(self, curation_json: Path, tmp_path: Path) -> None:
        """Test that force=True causes re-download even when files exist."""
        clip_dir = tmp_path / "clips" / "Test Channel - Test Video"
        clip_dir.mkdir(parents=True)
        (clip_dir / "1. Clip 1 - Hook 1.mp4").write_bytes(b"x" * 1000)

        def batch_side_effect(url, clip_dir, pending, format_selector, label="Batch"):
            entries = []
            for clip, start, end, extract_end, filename, expected_path in pending:
                entries.append(ClipManifestEntry(
                    clip_id=clip.id_klip, source_url="https://youtu.be/abc123",
                    start_time=clip.start_klip, end_time=clip.end_klip,
                    output_path=str(expected_path), output_file=filename,
                    title=clip.judul_relevan, hook=clip.hook,
                    status="success", actual_duration=60.0, video_width=1920, video_height=1080,
                    video_codec="h264", audio_codec="aac", retry_count=0
                ))
            return entries, 1, []

        with patch("stages.stage2_download.settings") as mock_settings, \
             patch("stages.stage2_download.setup_logging"), \
             patch("stages.stage2_download.ensure_dirs"), \
             patch("stages.stage2_download._get_video_metadata", return_value={"title": "Test Video", "creator": "Test Channel", "duration": 300.0}), \
             patch("stages.stage2_download._run_batch_download", side_effect=batch_side_effect), \
             patch("stages.stage2_download._validate_clip_file", return_value=(True, {"duration": 60.0, "video_width": 1920, "video_height": 1080, "video_codec": "h264", "audio_codec": "aac"}, None)):

            mock_settings.output_dir = tmp_path
            mock_settings.download_retries = 2
            mock_settings.download_retry_delay = 0.1
            mock_settings.video_max_height = 1080
            mock_settings.clip_end_buffer_seconds = 30

            manifest = run(manifest_path=curation_json, force=True)

            assert len([c for c in manifest.clips if c.status == "success"]) == 3
            assert all(c.retry_count == 0 for c in manifest.clips)

    def test_invalid_timestamp_skips_download(self, curation_json: Path, tmp_path: Path) -> None:
        """Test that invalid timestamps are recorded as failed without download."""
        data = json.loads(curation_json.read_text(encoding="utf-8"))
        data["daftar_klip"][0]["start_klip"] = "00:01:00"
        data["daftar_klip"][0]["end_klip"] = "00:00:30"
        curation_json.write_text(json.dumps(data), encoding="utf-8")

        def batch_side_effect(url, clip_dir, pending, format_selector, label="Batch"):
            entries = []
            for clip, start, end, extract_end, filename, expected_path in pending:
                entries.append(ClipManifestEntry(
                    clip_id=clip.id_klip, source_url="https://youtu.be/abc123",
                    start_time=clip.start_klip, end_time=clip.end_klip,
                    output_path=str(expected_path), output_file=filename,
                    title=clip.judul_relevan, hook=clip.hook,
                    status="success", actual_duration=60.0, video_width=1920, video_height=1080,
                    video_codec="h264", audio_codec="aac", retry_count=0
                ))
            return entries, 1, []

        with patch("stages.stage2_download.settings") as mock_settings, \
             patch("stages.stage2_download.setup_logging"), \
             patch("stages.stage2_download.ensure_dirs"), \
             patch("stages.stage2_download._get_video_metadata", return_value={"title": "Test Video", "creator": "Test Channel", "duration": 300.0}), \
             patch("stages.stage2_download._run_batch_download", side_effect=batch_side_effect), \
             patch("stages.stage2_download._validate_clip_file", return_value=(True, {"duration": 60.0, "video_width": 1920, "video_height": 1080, "video_codec": "h264", "audio_codec": "aac"}, None)):

            mock_settings.output_dir = tmp_path
            mock_settings.download_retries = 2
            mock_settings.download_retry_delay = 0.1
            mock_settings.video_max_height = 1080
            mock_settings.clip_end_buffer_seconds = 30

            manifest = run(manifest_path=curation_json)

            # Clip 1 should be failed (invalid timestamps)
            clip1 = next(c for c in manifest.clips if c.clip_id == 1)
            assert clip1.status == "failed"
            assert "must be after start" in (clip1.error_message or "")
            # Clips 2 and 3 should succeed
            assert any(c.status == "success" and c.clip_id == 2 for c in manifest.clips)
            assert any(c.status == "success" and c.clip_id == 3 for c in manifest.clips)


# ---------------------------------------------------------------------------
# Sanitization helpers
# ---------------------------------------------------------------------------


class TestSanitization:
    def test_sanitize_path_component_removes_invalid_chars(self) -> None:
        assert "\\" not in _sanitize_path_component("a\\b/c:d*e?f\"g<h>i|j")
        assert "/" not in _sanitize_path_component("a/b")

    def test_sanitize_path_component_collapses_whitespace(self) -> None:
        result = _sanitize_path_component("hello   world")
        assert result == "hello world"

    def test_sanitize_path_component_removes_trailing_space_period(self) -> None:
        result = _sanitize_path_component("name. ")
        assert result == "name"

    def test_sanitize_path_component_reserved_name(self) -> None:
        result = _sanitize_path_component("CON")
        assert result == "CON_clip"

    def test_sanitize_path_component_length_limit(self) -> None:
        long_name = "a" * 150
        result = _sanitize_path_component(long_name)
        assert len(result) <= 100

    def test_sanitize_filename_removes_invalid_chars(self) -> None:
        assert ":" not in _sanitize_filename("a:b.mp4")

    def test_sanitize_filename_preserves_extension(self) -> None:
        result = _sanitize_filename("my clip - hook.mp4")
        assert result.endswith(".mp4")

    def test_sanitize_filename_length_limit(self) -> None:
        long_name = "a" * 150 + ".mp4"
        result = _sanitize_filename(long_name)
        assert len(result) <= 120


# ---------------------------------------------------------------------------
# Output folder naming
# ---------------------------------------------------------------------------


class TestOutputFolderNaming:


    def test_clip_output_dir_sanitizes_invalid_chars(self, tmp_path: Path) -> None:
        with patch("stages.stage2_download.settings") as mock_settings:
            mock_settings.output_dir = tmp_path
            d = _clip_output_dir("Channel/Name", "Title: Episode 1")
            name = d.name
            assert "\\" not in name
            assert "/" not in name
            assert ":" not in name


# ---------------------------------------------------------------------------
# Clip filename generation
# ---------------------------------------------------------------------------


class TestClipFilenames:
    def test_clip_filename_with_title_and_hook(self) -> None:
        clip = ClipCandidate(
            id_klip=1,
            judul_relevan="Kasus Racun Sianida Terdekat",
            deskripsi="D",
            start_klip="00:04:30",
            end_klip="00:06:20",
            hook="Dokter Stefani Pernah Nemu Orang Diracun Gak",
        )
        result = _clip_filename(clip)
        assert result.startswith("1.")
        assert "Kasus Racun Sianida Terdekat" in result
        assert "Dokter Stefani" in result
        assert result.endswith(".mp4")

    def test_clip_filename_fallback_when_no_title(self) -> None:
        clip = ClipCandidate(
            id_klip=2,
            judul_relevan="",
            deskripsi="D",
            start_klip="00:09:59",
            end_klip="00:12:29",
        )
        result = _clip_filename(clip)
        assert result == "2. Clip 2.mp4"

    def test_clip_filename_sanitizes_invalid_chars(self) -> None:
        clip = ClipCandidate(
            id_klip=3,
            judul_relevan="Title: Part 1",
            deskripsi="D",
            start_klip="00:26:25",
            end_klip="00:28:08",
            hook="Hook? Yes!",
        )
        result = _clip_filename(clip)
        assert ":" not in result
        assert "?" not in result

    def test_clip_filename_truncates_long_names(self) -> None:
        long_title = "A" * 100
        long_hook = "B" * 100
        clip = ClipCandidate(
            id_klip=4,
            judul_relevan=long_title,
            deskripsi="D",
            start_klip="00:30:05",
            end_klip="00:31:55",
            hook=long_hook,
        )
        result = _clip_filename(clip)
        assert len(result) <= 125
        assert result.endswith(".mp4")


# ---------------------------------------------------------------------------
# Video metadata fetching
# ---------------------------------------------------------------------------


class TestGetVideoMetadata:
    def test_success(self) -> None:
        mock_result = MagicMock()
        mock_result.stdout = json.dumps({
            "title": "Test Video",
            "uploader": "Test Channel",
            "duration": 300,
        })
        with patch("stages.stage2_download.run_command", return_value=mock_result):
            meta = _get_video_metadata("https://youtu.be/abc123")
            assert meta["title"] == "Test Video"
            assert meta["creator"] == "Test Channel"
            assert meta["duration"] == 300.0

    def test_fallback_to_channel(self) -> None:
        mock_result = MagicMock()
        mock_result.stdout = json.dumps({
            "title": "Test Video",
            "channel": "Channel Name",
            "duration": 300,
        })
        with patch("stages.stage2_download.run_command", return_value=mock_result):
            meta = _get_video_metadata("https://youtu.be/abc123")
            assert meta["creator"] == "Channel Name"

    def test_failure_returns_empty(self) -> None:
        with patch("stages.stage2_download.run_command", side_effect=Exception("network error")):
            meta = _get_video_metadata("https://youtu.be/abc123")
            assert meta["title"] == ""
            assert meta["creator"] == ""
            assert meta["duration"] == 0.0


# ---------------------------------------------------------------------------
# Format selection / quality configuration
# ---------------------------------------------------------------------------


class TestFormatSelection:
    def test_build_ytdlp_command_default_quality(self, tmp_path: Path) -> None:
        output_path = tmp_path / "clip.mp4"
        with patch("stages.stage2_download.settings") as mock_settings:
            mock_settings.video_max_height = 1080
            mock_settings.clip_end_buffer_seconds = 30
            mock_settings.ytdlp_player_client = "android,ios"
            cmd = _build_ytdlp_command(
                url="https://youtu.be/abc123",
                output_path=output_path,
                start_sec=10.0,
                end_sec=70.0,
            )
            # Format selector should contain height<=1080
            fmt = next(c for c in cmd if c.startswith("best"))
            assert "height<=1080" in fmt

    def test_build_ytdlp_command_720p(self, tmp_path: Path) -> None:
        output_path = tmp_path / "clip.mp4"
        with patch("stages.stage2_download.settings") as mock_settings:
            mock_settings.video_max_height = 720
            mock_settings.ytdlp_player_client = "android,ios"
            cmd = _build_ytdlp_command(
                url="https://youtu.be/abc123",
                output_path=output_path,
                start_sec=10.0,
                end_sec=70.0,
            )
            fmt = next(c for c in cmd if c.startswith("best"))
            assert "height<=720" in fmt

    def test_build_ytdlp_command_custom_format(self, tmp_path: Path) -> None:
        output_path = tmp_path / "clip.mp4"
        with patch("stages.stage2_download.settings") as mock_settings:
            mock_settings.video_max_height = 1080
            mock_settings.clip_end_buffer_seconds = 30
            mock_settings.ytdlp_player_client = "android,ios"
            cmd = _build_ytdlp_command(
                url="https://youtu.be/abc123",
                output_path=output_path,
                start_sec=10.0,
                end_sec=70.0,
                format_selector="best[ext=mp4]/best",
            )
            assert "best[ext=mp4]/best" in cmd


# ---------------------------------------------------------------------------
# Audio + video validation
# ---------------------------------------------------------------------------


class TestAudioVideoValidation:
    def test_video_only_rejected(self, tmp_path: Path) -> None:
        clip_path = tmp_path / "clip.mp4"
        clip_path.write_bytes(b"x" * 1000)
        mock_result = MagicMock()
        mock_result.stdout = json.dumps({
            "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "duration": "60.0"}]
        })
        with patch("stages.stage2_download.run_command", return_value=mock_result):
            is_valid, meta, err = _validate_clip_file(clip_path, 60.0)
            assert is_valid is False
            assert "No audio stream" in (err or "")

    def test_audio_and_video_accepted(self, tmp_path: Path) -> None:
        clip_path = tmp_path / "clip.mp4"
        clip_path.write_bytes(b"x" * 1000)

        def fake_run_command(cmd, **kwargs):
            if "-select_streams" in cmd and "a:0" in cmd:
                return MagicMock(stdout=json.dumps({
                    "streams": [{"codec_type": "audio", "codec_name": "aac"}]
                }))
            return MagicMock(stdout=json.dumps({
                "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "duration": "60.0"}]
            }))

        with patch("stages.stage2_download.run_command", side_effect=fake_run_command):
            is_valid, meta, err = _validate_clip_file(clip_path, 60.0)
            assert is_valid is True
            assert meta["video_codec"] == "h264"
            assert meta["audio_codec"] == "aac"
            assert meta["video_height"] == 1080

    def test_resolution_exceeds_max_rejected(self, tmp_path: Path) -> None:
        clip_path = tmp_path / "clip.mp4"
        clip_path.write_bytes(b"x" * 1000)

        def fake_run_command(cmd, **kwargs):
            if "-select_streams" in cmd and "a:0" in cmd:
                return MagicMock(stdout=json.dumps({
                    "streams": [{"codec_type": "audio", "codec_name": "aac"}]
                }))
            return MagicMock(stdout=json.dumps({
                "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "duration": "60.0"}]
            }))

        with patch("stages.stage2_download.run_command", side_effect=fake_run_command):
            is_valid, meta, err = _validate_clip_file(clip_path, 60.0, max_height=720)
            assert is_valid is False
            assert "exceeds configured maximum" in (err or "")


# ---------------------------------------------------------------------------
# Existing output reuse / redownload
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Manifest generation
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------


class TestErrorClassification:
    def test_value_error_is_invalid(self) -> None:
        assert _classify_download_error(ValueError("bad timestamp")) == "invalid"

    def test_http_403_is_transient(self) -> None:
        exc = subprocess.CalledProcessError(1, "yt-dlp", stderr="ERROR: HTTP Error 403: Forbidden")
        assert _classify_download_error(exc) == "transient"

    def test_format_error_is_permanent(self) -> None:
        exc = subprocess.CalledProcessError(1, "yt-dlp", stderr="ERROR: [format] No such format")
        assert _classify_download_error(exc) == "permanent"

    def test_connection_error_is_transient(self) -> None:
        assert _classify_download_error(ConnectionError("network unreachable")) == "transient"

    def test_timeout_error_is_transient(self) -> None:
        assert _classify_download_error(TimeoutError("timed out")) == "transient"

    def test_generic_runtime_error_is_permanent(self) -> None:
        assert _classify_download_error(RuntimeError("something broke")) == "permanent"


# ---------------------------------------------------------------------------
# Resilience tests
# ---------------------------------------------------------------------------


class TestResilience:

    def test_invalid_clip_re_downloaded(self, curation_json: Path, tmp_path: Path) -> None:
        """Invalid existing clips trigger re-download."""
        clip_dir = tmp_path / "clips" / "Test Channel - Test Video"
        clip_dir.mkdir(parents=True)
        clip_file = clip_dir / "1. Clip 1 - Hook 1.mp4"
        clip_file.write_bytes(b"x" * 1000)

        # Create valid existing files for clips 2 and 3 (so they are skipped)
        for i in [2, 3]:
            clip_file = clip_dir / f"{i}. Clip {i} - Hook {i}.mp4"
            clip_file.write_bytes(b"x" * 1000)

        call_count = [0]
        def fake_validate(path, expected_duration, max_height=1080):
            call_count[0] += 1
            if call_count[0] == 1:
                return False, None, "No audio stream found."
            return True, {"duration": expected_duration, "video_width": 1920, "video_height": 1080, "video_codec": "h264", "audio_codec": "aac"}, None

        def batch_side_effect(url, clip_dir, pending, format_selector, label="Batch"):
            entries = []
            for clip, start, end, extract_end, filename, expected_path in pending:
                # Only clip 1 is in pending (clips 2,3 are skipped as valid)
                if clip.id_klip == 1:
                    entries.append(ClipManifestEntry(
                        clip_id=clip.id_klip, source_url="https://youtu.be/abc123",
                        start_time=clip.start_klip, end_time=clip.end_klip,
                        output_path=str(expected_path), output_file=filename,
                        title=clip.judul_relevan, hook=clip.hook,
                        status="success", actual_duration=60.0, video_width=1920, video_height=1080,
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
            # Clip 1 re-downloaded and succeeds, clips 2-3 skipped
            assert any(c.status == "success" and c.clip_id == 1 for c in manifest.clips)
            assert all(c.status == "skipped" for c in manifest.clips if c.clip_id in (2, 3))

    def test_transient_failure_retries_with_backoff(self, curation_json: Path, tmp_path: Path) -> None:
        """Transient failures are handled gracefully (batch retry with fallback format)."""
        call_count = [0]
        def batch_side_effect(url, clip_dir, pending, format_selector, label="Batch"):
            call_count[0] += 1
            entries = []
            remaining = []
            for clip, start, end, extract_end, filename, expected_path in pending:
                if call_count[0] == 1 and clip.id_klip <= 2:
                    # First batch: clips 1,2 remain (will be retried)
                    remaining.append((clip, start, end, extract_end, filename, expected_path))
                else:
                    # Second batch or retry: all succeed
                    entries.append(ClipManifestEntry(
                        clip_id=clip.id_klip, source_url="https://youtu.be/abc123",
                        start_time=clip.start_klip, end_time=clip.end_klip,
                        output_path=str(expected_path), output_file=filename,
                        title=clip.judul_relevan, hook=clip.hook,
                        status="success", actual_duration=60.0, video_width=1920, video_height=1080,
                        video_codec="h264", audio_codec="aac", retry_count=call_count[0] - 1
                    ))
            return entries, 1, remaining

        with patch("stages.stage2_download.settings") as mock_settings, \
             patch("stages.stage2_download.setup_logging"), \
             patch("stages.stage2_download.ensure_dirs"), \
             patch("stages.stage2_download._get_video_metadata", return_value={"title": "Test Video", "creator": "Test Channel", "duration": 300.0}), \
             patch("stages.stage2_download._run_batch_download", side_effect=batch_side_effect), \
             patch("stages.stage2_download._validate_clip_file", return_value=(True, {"duration": 60.0, "video_width": 1920, "video_height": 1080, "video_codec": "h264", "audio_codec": "aac"}, None)):

            mock_settings.output_dir = tmp_path
            mock_settings.download_retries = 3
            mock_settings.download_retry_delay = 0.1
            mock_settings.video_max_height = 1080
            mock_settings.clip_end_buffer_seconds = 30

            manifest = run(manifest_path=curation_json)
            # All clips should succeed after retry
            assert all(c.status == "success" for c in manifest.clips)
            # Clip 1 should have retry_count > 0 (it was retried)
            clip1 = next(c for c in manifest.clips if c.clip_id == 1)
            assert clip1.retry_count == 1

    def test_permanent_failure_no_infinite_retry(self, curation_json: Path, tmp_path: Path) -> None:
        """Permanent failures do not retry indefinitely."""
        def batch_side_effect(url, clip_dir, pending, format_selector, label="Batch"):
            return [], 1, pending  # All clips remain pending (failure)

        with patch("stages.stage2_download.settings") as mock_settings, \
             patch("stages.stage2_download.setup_logging"), \
             patch("stages.stage2_download.ensure_dirs"), \
             patch("stages.stage2_download._get_video_metadata", return_value={"title": "Test Video", "creator": "Test Channel", "duration": 300.0}), \
             patch("stages.stage2_download._run_batch_download", side_effect=batch_side_effect):

            mock_settings.output_dir = tmp_path
            mock_settings.download_retries = 3
            mock_settings.download_retry_delay = 0.1
            mock_settings.video_max_height = 1080
            mock_settings.clip_end_buffer_seconds = 30

            with pytest.raises(RuntimeError, match="All 3 clips failed"):
                run(manifest_path=curation_json)


# ---------------------------------------------------------------------------
# Batch download specific tests
# ---------------------------------------------------------------------------


class TestBatchDownload:
    def test_batch_command_downloads_full_video(self, tmp_path: Path) -> None:
        """Verify batch command builds for full video download to temp path."""
        cmd = _build_batch_ytdlp_command(
            url="https://youtu.be/test",
            temp_path=tmp_path / "temp.mp4",
        )
        # Prefiks perintah = hasil `ytdlp_cmd()` (jalur modul `python -m yt_dlp`,
        # atau fallback `yt-dlp` kalau modulnya tidak terpasang).
        assert cmd[: len(ytdlp_cmd())] == ytdlp_cmd()
        assert str(tmp_path / "temp.mp4") in cmd
        assert "https://youtu.be/test" in cmd

    def test_batch_command_with_player_client(self, tmp_path: Path) -> None:
        """Verify batch command includes player_client when configured."""
        with patch("stages.stage2_download.settings") as mock_settings:
            mock_settings.ytdlp_player_client = "android,ios"
            cmd = _build_batch_ytdlp_command(
                url="https://youtu.be/test",
                temp_path=tmp_path / "temp.mp4",
            )
            assert "--extractor-args" in cmd
            assert "youtube:player_client=android,ios" in cmd
