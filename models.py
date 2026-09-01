"""Pydantic data contracts shared between pipeline stages.

These models define the JSON schema that flows between stages:
- Stage 1 produces a CurationResult (curation.json).
- Stage 2 consumes CurationResult and produces raw clip files.
- Stage 3 consumes raw clips and produces rendered clips.
- Stage 4 consumes rendered clips and produces final clips.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, computed_field


class TranscriptSegment(BaseModel):
    """Normalized transcript segment."""

    start: float = Field(description="Start time in seconds.")
    duration: float = Field(description="Duration in seconds.")
    text: str = Field(description="Transcript text.")


class TranscriptCache(BaseModel):
    """Cached transcript metadata."""

    video_id: str
    source: str = Field(description="youtube_manual, youtube_auto, or whisper.")
    language: str = Field(default="", description="Language code.")
    segments: list[TranscriptSegment] = Field(default_factory=list)
    created_at: str = Field(default="")


class GeminiClipCandidate(BaseModel):
    """Internal model for Gemini clip candidate response."""

    title: str = Field(min_length=1, description="Short, hook-driven title for the short.")
    start: str = Field(min_length=1, description="Start time in HH:MM:SS format.")
    end: str = Field(min_length=1, description="End time in HH:MM:SS format.")
    description: str = Field(min_length=1, description="Why this clip works / hook explanation.")
    tags: list[str] = Field(min_length=3, max_length=3, description="Exactly 3 relevant hashtags.")
    hook: str = Field(min_length=1, description="The opening hook phrase.")
    score: float = Field(ge=0, le=100, description="Retention score (0-100).")


class GeminiClipResponse(BaseModel):
    """Structured response schema for Gemini clip curation."""

    clips: list[GeminiClipCandidate] = Field(min_length=1)


class ClipCandidate(BaseModel):
    """A single curated clip segment from the source video."""

    id_klip: int = Field(description="Sequential clip number (1-based).")
    judul_relevan: str = Field(description="Short, hook-driven title for the short.")
    deskripsi: str = Field(description="Why this clip works / hook explanation.")
    start_klip: str = Field(description="Start time in HH:MM:SS format.")
    end_klip: str = Field(description="End time in HH:MM:SS format.")
    tags: list[str] = Field(default_factory=list, description="Relevant tags.")
    hook: str = Field(default="", description="The opening hook phrase.")
    score: float = Field(default=0.0, description="Retention score (0-1).")

    # --- Keputusan user di tahap review (tab Run mode Manual) ---
    # Keduanya WAJIB punya default supaya file kurasi lama tetap tervalidasi.
    pilih: bool = Field(
        default=True,
        description="False = klip TIDAK diunduh Stage 2, tapi tetap disimpan sebagai acuan.",
    )
    headline: str = Field(
        default="",
        description=(
            "Headline hasil edit user untuk klip ini. Kosong = pakai judul_relevan. "
            "Sengaja BUKAN hook: hook adalah kutipan transkrip mentah (bisa >100 karakter) "
            "yang akan dikecilkan drastis oleh auto-fit Stage 5."
        ),
    )

    def headline_text(self) -> str:
        """Teks headline efektif: hasil edit user, atau judul_relevan sebagai default."""
        return (self.headline or "").strip() or (self.judul_relevan or "").strip()

    @field_validator("start_klip", "end_klip")
    @classmethod
    def _validate_time_format(cls, value: str) -> str:
        """Ensure times are HH:MM:SS (or MM:SS / SS) and normalize to HH:MM:SS."""
        from utils import parse_time, format_time

        seconds = parse_time(value)
        return format_time(seconds)

    @computed_field
    @property
    def durasi_detik(self) -> float:
        """Compute duration from start and end times."""
        from utils import parse_time

        start_sec = parse_time(self.start_klip)
        end_sec = parse_time(self.end_klip)
        return round(end_sec - start_sec, 1)


class CurationResult(BaseModel):
    """Output of Stage 1: the curated clip metadata for a source video."""

    url_video: str = Field(description="Source YouTube URL.")
    judul_video: str = Field(description="Title of the source video.")
    video_id: str = Field(default="", description="YouTube video ID.")
    durasi_video: float = Field(default=0.0, description="Source video duration in seconds.")
    transcript_source: str = Field(default="", description="Transcript source: youtube_manual, youtube_auto, whisper.")
    transcript_language: str = Field(default="", description="Transcript language code.")
    total_klip: int = Field(default=0, description="Total number of clips.")
    # Nama kreator yang DITULIS USER di panel Review (opsional). Kosong = ikut nama
    # channel asli dari yt-dlp. Hanya dipakai untuk WATERMARK; nama folder output tetap
    # memakai channel asli, kalau tidak klip yang sudah diunduh jadi tidak ketemu.
    creator_watermark: str = Field(
        default="", description="User-typed creator name for the watermark (empty = use channel).")
    daftar_klip: list[ClipCandidate] = Field(min_length=1, description="Best clip segments.")


class RenderJob(BaseModel):
    """A single clip ready for Stage 3 rendering (9:16 crop + audio normalize)."""

    id: int
    input_path: str = Field(description="Path to the raw downloaded clip.")
    output_path: str = Field(description="Path where the rendered clip will be written.")
    crop_x: int = Field(default=0, description="Horizontal crop offset in pixels.")
    target_w: int = Field(description="Target crop width.")
    target_h: int = Field(description="Target crop height.")


class RenderManifest(BaseModel):
    """Output of Stage 2 / input to Stage 3: list of render jobs."""

    source: str = Field(description="Path to the curation.json that produced these jobs.")
    jobs: list[RenderJob]


class SubtitleManifest(BaseModel):
    """Output of Stage 3 / input to Stage 4: list of subtitle jobs."""

    source: str = Field(description="Path to the render manifest that produced these jobs.")
    jobs: list[SubtitleJob]


class ClipManifestEntry(BaseModel):
    """A single clip entry in the Stage 2 manifest."""

    clip_id: int = Field(description="Sequential clip number (1-based).")
    source_url: str = Field(description="Source YouTube URL.")
    start_time: str = Field(description="Start time in HH:MM:SS format.")
    end_time: str = Field(description="End time in HH:MM:SS format.")
    extract_end_time: str | None = Field(default=None, description="Physical extraction endpoint (end_time + buffer).")
    buffer_seconds: float | None = Field(default=None, description="Buffer seconds added to clip end.")
    output_path: str = Field(description="Path to the downloaded clip file.")
    output_file: str = Field(default="", description="Filename of the downloaded clip.")
    title: str = Field(default="", description="Clip title from Stage 1.")
    headline: str = Field(
        default="",
        description=(
            "Teks headline untuk klip ini: hasil edit user di tahap review, atau "
            "judul_relevan kalau tidak diedit. Stage 5 memakai ini lebih dulu daripada "
            "preset.headline.text (yang global untuk semua klip)."
        ),
    )
    hook: str = Field(default="", description="Clip hook from Stage 1.")
    status: str = Field(description="Download status: success, failed, or skipped.")
    actual_duration: float | None = Field(default=None, description="Actual clip duration in seconds.")
    video_width: int | None = Field(default=None, description="Video width in pixels.")
    video_height: int | None = Field(default=None, description="Video height in pixels.")
    video_codec: str | None = Field(default=None, description="Video codec name.")
    audio_codec: str | None = Field(default=None, description="Audio codec name.")
    error_message: str | None = Field(default=None, description="Error message if download failed.")
    retry_count: int = Field(default=0, description="Number of retry attempts made.")


class ClipManifest(BaseModel):
    """Stage 2 manifest: records all clip download results."""

    video_id: str = Field(description="YouTube video ID.")
    video_title: str = Field(description="Title of the source video.")
    creator: str = Field(default="", description="Channel/uploader name.")
    # Nama kreator ketikan user untuk WATERMARK (diteruskan dari file kurasi Stage 1).
    # Kosong = pakai `creator`. Nama FOLDER output selalu dari `creator`, bukan dari ini.
    creator_watermark: str = Field(
        default="", description="User-typed creator name for the watermark (empty = use creator).")
    source_url: str = Field(description="Source YouTube URL.")
    output_directory: str = Field(description="Output directory for clips.")
    clips: list[ClipManifestEntry] = Field(min_length=1, description="Clip download results.")


class CropJob(BaseModel):
    """A single clip ready for Stage 3 rendering (9:16 crop + audio normalize)."""

    clip_id: int = Field(description="Sequential clip number (1-based).")
    input_file: str = Field(description="Path to the raw downloaded clip (Stage 2 source).")
    output_file: str = Field(description="Path where the rendered clip will be written.")
    source_width: int | None = Field(default=None, description="Source video width in pixels.")
    source_height: int | None = Field(default=None, description="Source video height in pixels.")
    output_width: int = Field(default=1080, description="Target output width in pixels.")
    output_height: int = Field(default=1920, description="Target output height in pixels.")
    crop_mode_requested: str = Field(default="auto", description="Requested crop mode: auto, center, or face.")
    crop_mode_used: str | None = Field(default=None, description="Crop mode actually used after detection.")
    crop_x: int | None = Field(default=None, description="Horizontal crop offset in pixels.")
    duration: float | None = Field(default=None, description="Rendered clip duration in seconds.")
    video_codec: str | None = Field(default=None, description="Video codec name.")
    audio_codec: str | None = Field(default=None, description="Audio codec name.")
    status: str = Field(description="Render status: success, failed, or skipped.")
    error_message: str | None = Field(default=None, description="Error message if rendering failed.")


class CropManifest(BaseModel):
    """Stage 3 manifest: records all crop/render results."""

    video_id: str = Field(description="YouTube video ID.")
    video_title: str = Field(description="Title of the source video.")
    creator: str = Field(default="", description="Channel/uploader name.")
    source_directory: str = Field(description="Stage 2 output directory (read-only source).")
    output_directory: str = Field(description="Stage 3 crop output directory.")
    jobs: list[CropJob] = Field(min_length=1, description="Crop/render results.")


class SubtitleGroup(BaseModel):
    """A group of Whisper words forming one subtitle line."""

    words: list[str] = Field(description="Words in this subtitle group.")
    start: float = Field(description="Group start time in seconds.")
    end: float = Field(description="Group end time in seconds.")
    text: str = Field(description="Joined subtitle text.")
    is_emphasis: bool = Field(default=False, description="Whether this group has emphasis.")


class SubtitleJob(BaseModel):
    """A single clip's subtitle rendering result."""

    clip_id: int = Field(description="Sequential clip number (1-based).")
    input_file: str = Field(description="Path to the Stage 2 source clip.")
    srt_file: str | None = Field(default=None, description="Path to generated SRT file.")
    whisper_model: str = Field(description="Whisper model used for transcription.")
    transcript_source: str = Field(default="unknown", description="youtube_cc, whisper_fallback, or whisperx_aligned.")
    youtube_caption_language: str = Field(default="", description="YouTube caption language code.")
    youtube_caption_type: str = Field(default="", description="manual or auto.")
    whisper_used: bool = Field(default=False, description="Whether Whisper was used.")
    whisper_purpose: str = Field(default="not_used", description="not_used, fallback_transcription, or word_timing.")
    word_count: int = Field(default=0, description="Number of words transcribed.")
    subtitle_group_count: int = Field(default=0, description="Number of subtitle groups.")
    gemini_status: str = Field(default="unknown", description="gemini_success, gemini_failed, fallback, or not_used.")
    fallback_used: bool = Field(default=False, description="Whether fallback grouping was used.")
    validation_status: str = Field(default="unknown", description="validation_passed, validation_failed, or skipped.")
    status: str = Field(description="Job status: success, failed, or skipped.")
    error_message: str | None = Field(default=None, description="Error message if failed.")
    # WhisperX forced alignment fields
    whisperx_used: bool = Field(default=False, description="Whether WhisperX forced alignment was used.")
    whisperx_version: str = Field(default="", description="WhisperX version used for alignment.")
    alignment_model: str = Field(default="", description="Wav2Vec2 alignment model used (e.g., cahya/wav2vec2-large-xlsr-indonesian).")
    aligned_word_count: int = Field(default=0, description="Number of words successfully aligned by WhisperX.")
    alignment_fallback_count: int = Field(default=0, description="Number of words that fell back to interpolation.")