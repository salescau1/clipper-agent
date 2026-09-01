"""Stage 1: Curate clips from a YouTube video.

Pipeline:
    1. Extract video ID and fetch metadata via yt-dlp.
    2. Obtain transcript (YouTube manual → auto → Whisper fallback).
    3. Cache transcript for future runs.
    4. Send transcript to Gemini for clip curation (structured output).
    5. Validate and normalize clip timestamps.
    6. Remove duplicates and excessive overlaps.
    7. Save validated curation manifest.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from config import settings
from openai import OpenAI
from models import (
    CurationResult,
    GeminiClipCandidate,
    GeminiClipResponse,
    TranscriptCache,
    TranscriptSegment,
    ClipCandidate,
)
from utils import (
    ensure_dirs,
    format_time,
    get_logger,
    parse_time,
    safe_remove,
    setup_logging,
)

logger = get_logger("stage1")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIN_CLIP_SECONDS = 60
_MAX_CLIP_SECONDS = 240
_IDEAL_MIN_CLIP_SECONDS = 90
_IDEAL_MAX_CLIP_SECONDS = 180
_OVERLAP_THRESHOLD = 0.5  # 50% overlap ratio triggers dedup

# ---------------------------------------------------------------------------
# Video metadata
# ---------------------------------------------------------------------------


def extract_video_id(url: str) -> str:
    """Extract the 11-character YouTube video ID from a URL or bare ID."""
    patterns = [
        r"(?:v=|\/|youtu\.be\/|embed\/|shorts\/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise ValueError(f"Invalid YouTube URL: {url}")


def fetch_video_metadata(video_id: str) -> dict[str, Any]:
    """Fetch video title and duration using yt-dlp without downloading."""
    logger.info("Fetching metadata for video %s", video_id)
    try:
        result = subprocess.run(
            [
                "yt-dlp",
                "--dump-json",
                "--no-download",
                "--skip-download",
                f"https://www.youtube.com/watch?v={video_id}",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        data = json.loads(result.stdout)
        return {
            "title": data.get("title", f"Video {video_id}"),
            "creator": data.get("uploader") or data.get("channel") or "",
            "duration": data.get("duration", 0) or 0,
        }
    except subprocess.CalledProcessError as exc:
        logger.warning("yt-dlp metadata fetch failed: %s", exc.stderr[:200] if exc.stderr else str(exc))
        return {"title": f"Video {video_id}", "creator": "", "duration": 0}
    except Exception as exc:
        logger.warning("Could not fetch metadata: %s", exc)
        return {"title": f"Video {video_id}", "creator": "", "duration": 0}


# ---------------------------------------------------------------------------
# Transcript
# ---------------------------------------------------------------------------


def _normalize_segment(start: float, duration: float, text: str) -> TranscriptSegment:
    """Create a normalized transcript segment."""
    clean_text = " ".join(text.split())
    return TranscriptSegment(start=start, duration=duration, text=clean_text)


def _fetch_youtube_transcript(video_id: str, languages: list[str]) -> tuple[list[TranscriptSegment], str, str]:
    """Fetch YouTube transcript (manual preferred, then auto-generated).

    Returns:
        (segments, source, language)

    Raises:
        RuntimeError: If no transcript is available.
    """
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._transcripts import TranscriptList

    api = YouTubeTranscriptApi()
    transcript_list: TranscriptList = api.list(video_id)

    # Build available transcript info for diagnostics
    available_info = []
    try:
        for t in transcript_list:
            available_info.append(f"{t.language_code} ({'manual' if t.is_manually_created else 'auto'})")
    except Exception:
        pass

    logger.info("Available transcripts: %s", ", ".join(available_info) if available_info else "none found")

    # Try manual first, then auto-generated, then any available
    candidates = []
    selected_source = ""
    selected_lang = ""
    try:
        manual = transcript_list.find_manually_created_transcript(languages)
        candidates.append(("youtube_manual", manual))
        selected_source = "youtube_manual"
        selected_lang = getattr(manual, "language_code", "") or ""
    except Exception:
        pass
    try:
        auto = transcript_list.find_generated_transcript(languages)
        candidates.append(("youtube_auto", auto))
        if not selected_source:
            selected_source = "youtube_auto"
            selected_lang = getattr(auto, "language_code", "") or ""
    except Exception:
        pass
    try:
        # Fallback: any transcript in any language
        all_transcripts = list(transcript_list)
        if all_transcripts:
            fallback = all_transcripts[0]
            candidates.append(("youtube_auto", fallback))
            if not selected_source:
                selected_source = "youtube_auto"
                selected_lang = getattr(fallback, "language_code", "") or ""
    except Exception:
        pass

    if not candidates:
        raise RuntimeError(
            f"No YouTube transcript available for video {video_id}. "
            "Captions may be disabled or the video may not have transcripts."
        )

    source, transcript = candidates[0]
    language = getattr(transcript, "language_code", "") or ""
    is_manual = getattr(transcript, "is_manually_created", False)
    logger.info("Selected: %s (%s, %s)", language, "manual" if is_manual else "auto", source)

    try:
        fetched = transcript.fetch()
        raw = fetched.to_raw_data()
        segments = [
            _normalize_segment(
                start=float(item["start"]),
                duration=float(item.get("duration", 0)),
                text=item.get("text", ""),
            )
            for item in raw
        ]
        if not segments:
            raise RuntimeError("Transcript fetched but contains no segments.")
        logger.info("YouTube transcript obtained: source=%s, language=%s, segments=%d", source, language, len(segments))
        return segments, source, language
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch YouTube transcript: {exc}") from exc


def _fetch_whisper_transcript(video_id: str, url: str) -> list[TranscriptSegment]:
    """Download audio and transcribe with Whisper as fallback."""
    import whisper

    temp_audio = settings.temp_dir / f"whisper_{video_id}_{int(time.time())}.m4a"
    try:
        logger.info("Downloading audio for Whisper transcription...")
        subprocess.run(
            [
                "yt-dlp",
                "-f", "bestaudio/best",
                "-o", str(temp_audio),
                "--force-overwrites",
                "--no-warnings",
                "--extractor-args", "youtube:player_client=android,ios",
                url,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=300,
        )

        logger.info("Running Whisper model '%s'...", settings.whisper_model)
        model = whisper.load_model(settings.whisper_model)
        # condition_on_previous_text=False mencegah looping/halusinasi kata pada audio
        # lapangan bising & kosakata Sunda; no_speech_threshold membuang derau tanpa
        # vokal. Tanpa ini transkrip Stage 1 mengulang kalimat ("Bagaimana? Bagaimana?")
        # dan kurasinya jadi salah topik.
        result = model.transcribe(
            str(temp_audio),
            language="id",
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            temperature=(0.0, 0.2, 0.4),
        )

        segments = [
            _normalize_segment(
                start=float(seg["start"]),
                duration=float(seg.get("end", seg["start"]) - seg["start"]),
                text=seg.get("text", "").strip(),
            )
            for seg in result.get("segments", [])
        ]
        if not segments:
            raise RuntimeError("Whisper produced no segments.")
        logger.info("Whisper transcription complete: %d segments", len(segments))
        return segments
    finally:
        safe_remove(temp_audio)


def get_transcript(video_id: str, url: str, languages: list[str]) -> tuple[list[TranscriptSegment], str, str]:
    """Get transcript with YouTube-first, Whisper-fallback strategy.

    Returns:
        (segments, source, language)
    """
    # Try YouTube first
    try:
        return _fetch_youtube_transcript(video_id, languages)
    except Exception as yt_error:
        logger.warning("YouTube transcript failed: %s", yt_error)
        logger.info("Falling back to Whisper local transcription...")
        try:
            segments = _fetch_whisper_transcript(video_id, url)
            return segments, "whisper", ""
        except Exception as whisper_error:
            raise RuntimeError(
                f"Both YouTube transcript and Whisper fallback failed.\n"
                f"  YouTube: {yt_error}\n"
                f"  Whisper: {whisper_error}"
            ) from whisper_error


# ---------------------------------------------------------------------------
# Transcript cache
# ---------------------------------------------------------------------------


def _cache_path(video_id: str) -> Path:
    return settings.cache_dir / "transcripts" / f"{video_id}.json"


def save_transcript_cache(video_id: str, source: str, language: str, segments: list[TranscriptSegment]) -> None:
    """Save transcript to cache."""
    cache_file = _cache_path(video_id)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache = TranscriptCache(
        video_id=video_id,
        source=source,
        language=language,
        segments=segments,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    cache_file.write_text(cache.model_dump_json(indent=2), encoding="utf-8")
    logger.debug("Transcript cached at %s", cache_file)


def load_transcript_cache(video_id: str) -> TranscriptCache | None:
    """Load cached transcript if it exists."""
    cache_file = _cache_path(video_id)
    if not cache_file.exists():
        return None
    try:
        return TranscriptCache.model_validate_json(cache_file.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to load transcript cache: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Gemini curation
# ---------------------------------------------------------------------------


def _build_transcript_text(segments: list[TranscriptSegment]) -> str:
    """Convert transcript segments to a readable text with timestamps."""
    lines = []
    for seg in segments:
        ts = format_time(seg.start)
        lines.append(f"[{ts}] {seg.text}")
    return "\n".join(lines)


def _build_gemini_prompt(
    transcript_text: str,
    target_count: int,
    duration_seconds: float,
    min_seconds: int = _MIN_CLIP_SECONDS,
    max_seconds: int = _MAX_CLIP_SECONDS,
) -> str:
    duration_str = format_time(duration_seconds) if duration_seconds else "unknown"
    # Ideal disempitkan di dalam batas user, bukan konstanta tetap: kalau user memilih
    # 30-90s, menyebut "ideal 90-180" di prompt akan membuat LLM melanggar batasnya
    # sendiri dan semua kandidat dibuang validator.
    ideal_min = min_seconds + max(1, (max_seconds - min_seconds) // 4)
    ideal_max = max_seconds - max(1, (max_seconds - min_seconds) // 4)
    return f"""Bertindaklah sebagai Senior TikTok Retention Strategist.
Tugas Anda adalah membedah transkrip YouTube ini dan mengekstrak {target_count} klip (durasi {min_seconds}-{max_seconds} detik, ideal {ideal_min}-{ideal_max} detik) yang dirancang murni untuk menembus algoritma For You Page (FYP).

ATURAN MUTLAK:
1. THE 3-SECOND HOOK: Setiap klip WAJIB dimulai tepat pada kalimat yang mengagetkan, pernyataan kontroversial, atau pertanyaan provokatif. Jangan mulai dari kalimat basa-basi.
2. THE INFINITE LOOP: Titik potong akhir (end_klip) harus dipotong tepat sebelum sebuah resolusi tuntas.
3. Ekstrak timestamp presisi tanpa memotong kata yang sedang diucapkan.
4. Durasi total video: {duration_str}.
5. Jangan pilih klip yang saling tumpang tindih secara substansial.
6. Jangan pilih bagian yang hanya masuk akal jika menonton seluruh video.
7. WAJIB kembalikan {target_count} klip. Sebarkan klip merata dari awal sampai akhir video, jangan menumpuk di satu bagian.
8. Durasi setiap klip WAJIB antara {min_seconds} dan {max_seconds} detik. Klip di luar rentang ini akan DITOLAK.

FORMAT KELUARAN WAJIB (JSON):
Setiap objek klip WAJIB memiliki field berikut. Field yang kosong atau tidak sesuai akan dianggap INVALID dan ditolak:
- judul_relevan: judul pendek, menarik, hook-driven untuk short video
- start_klip: timestamp mulai dalam format HH:MM:SS
- end_klip: timestamp akhir dalam format HH:MM:SS
- durasi_detik: durasi klip dalam detik (end - start)
- hook: kalimat pembuka yang langsung menangkap perhatian
- deskripsi: penjelasan singkat mengapa klip ini menarik
- tags: exactly 3 hashtag yang relevan
- score: angka 0-100 yang menunjukkan potensi retensi

KRITERIA KLIP BAGUS:
- Hook langsung di detik pertama
- Ada konteks yang cukup
- Ada narasi atau argumen yang jelas
- Ada payoff
- Bernilai mandiri
- Potensi retensi tinggi

HINDARI:
- Pembukaan/salam
- Pengantar yang panjang
- Filler
- Bagian yang repetitif
- Bagian yang membutuhkan konteks luar untuk dipahami

Transkrip Video:
{transcript_text}"""


def _parse_gemini_response(response_text: str) -> list[GeminiClipCandidate]:
    """Parse Gemini response text into structured clip candidates."""
    try:
        cleaned = response_text.strip()

        # Gemini/OpenAI-compatible providers may wrap JSON in Markdown fences.
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()

            # Remove opening fence: ```json / ```
            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]

            # Remove closing fence.
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]

            cleaned = "\n".join(lines).strip()

        data = json.loads(cleaned)

        if isinstance(data, dict) and "clips" in data:
            clips_data = data["clips"]
        elif isinstance(data, list):
            clips_data = data
        else:
            raise ValueError(
                f"Unexpected response structure: {type(data).__name__}"
            )

        candidates: list[GeminiClipCandidate] = []

        for c in clips_data:
            if isinstance(c, dict):
                # Normalize alternate field names Gemini sometimes returns.
                c = dict(c)
                c.setdefault("title", c.get("judul_relevan") or c.get("title") or "")
                c.setdefault(
                    "start",
                    c.get("start_timestamp") or c.get("start_klip") or c.get("start") or "",
                )
                c.setdefault(
                    "end",
                    c.get("end_timestamp") or c.get("end_klip") or c.get("end") or "",
                )
                c.setdefault(
                    "description",
                    c.get("deskripsi") or c.get("description") or "",
                )
                c.setdefault("tags", c.get("tags") or [])
                c.setdefault("hook", c.get("hook") or "")
                c.setdefault(
                    "score",
                    c.get("score") or c.get("retention_score") or 0.0,
                )

            candidates.append(GeminiClipCandidate.model_validate(c))

        return candidates

    except Exception as exc:
        raise RuntimeError(
            f"Failed to parse Gemini response: {exc}\n"
            f"Response: {response_text[:500]}"
        ) from exc

def curate_with_gemini(
    transcript_text: str,
    target_count: int,
    duration_seconds: float,
    min_seconds: int = _MIN_CLIP_SECONDS,
    max_seconds: int = _MAX_CLIP_SECONDS,
) -> list[GeminiClipCandidate]:
    """Send transcript to Gemini via 9Router (OpenAI-compatible) and return structured clip candidates."""
    logger.info("Sending transcript to LLM (%s) via %s for curation...", settings.gemini_model, settings.llm_base_url)

    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured. Set it in .env or environment variables.")

    # 9Router exposes an OpenAI-compatible endpoint. Prefix an unqualified
    # model with "ag/" so the request is routed specifically through the
    # Antigravity provider instead of letting 9Router choose another provider.
    model = settings.gemini_model.strip()
    if "/" not in model:
        model = f"ag/{model}"

    client = OpenAI(
        base_url=settings.llm_base_url.rstrip("/"),
        api_key=settings.gemini_api_key,
        timeout=180.0,
        max_retries=0,
    )
    prompt = _build_gemini_prompt(
        transcript_text, target_count, duration_seconds, min_seconds, max_seconds
    )

    # Jatah token jawaban harus ikut jumlah klip. Metadata satu klip (judul, hook,
    # deskripsi, 3 tag, skor, timestamp) terukur ~350-450 token; 8192 tetap cukup untuk
    # 5 klip tapi 20 klip akan terpotong di tengah dan JSON-nya gagal diparse —
    # kegagalan yang muncul sebagai "Failed to parse Gemini response", bukan sebagai
    # "jawaban kepanjangan", jadi sulit didiagnosis kalau tidak dinaikkan di sini.
    max_tokens = max(8192, 1024 + target_count * 500)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=max_tokens,
        )
    except Exception as exc:
        raise RuntimeError(f"LLM API call failed: {exc}") from exc

    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("LLM API returned an empty response.")

    candidates = _parse_gemini_response(content)
    logger.info("LLM returned %d clip candidates", len(candidates))
    logger.debug("LLM raw response:\n%s", content[:2000])
    return candidates


# ---------------------------------------------------------------------------
# Clip validation and normalization
# ---------------------------------------------------------------------------


def _validate_clip_duration(
    start_sec: float,
    end_sec: float,
    min_seconds: int = _MIN_CLIP_SECONDS,
    max_seconds: int = _MAX_CLIP_SECONDS,
) -> bool:
    """Check if clip duration is within acceptable range."""
    duration = end_sec - start_sec
    return min_seconds <= duration <= max_seconds


def _validate_clip_metadata(candidate: GeminiClipCandidate, idx: int) -> list[str]:
    """Validate required metadata fields for a clip candidate."""
    errors = []
    if not candidate.title or not str(candidate.title).strip():
        errors.append("title is empty")
    if not candidate.description or not str(candidate.description).strip():
        errors.append("description is empty")
    if not candidate.hook or not str(candidate.hook).strip():
        errors.append("hook is empty")
    tags = candidate.tags or []
    if len(tags) != 3:
        errors.append(f"tags must contain exactly 3 items, got {len(tags)}")
    if not isinstance(candidate.score, (int, float)) or not (0 <= candidate.score <= 100):
        errors.append(f"score must be between 0 and 100, got {candidate.score}")
    return errors


def _clip_overlaps(
    a_start: float, a_end: float, b_start: float, b_end: float, threshold: float = _OVERLAP_THRESHOLD
) -> bool:
    """Check if two clips overlap beyond the threshold."""
    overlap_start = max(a_start, b_start)
    overlap_end = min(a_end, b_end)
    if overlap_end <= overlap_start:
        return False
    overlap_duration = overlap_end - overlap_start
    a_duration = a_end - a_start
    b_duration = b_end - b_start
    min_duration = min(a_duration, b_duration)
    if min_duration <= 0:
        return False
    return (overlap_duration / min_duration) >= threshold


def validate_and_normalize_clips(
    candidates: list[GeminiClipCandidate],
    video_duration: float,
    target_count: int,
    min_seconds: int = _MIN_CLIP_SECONDS,
    max_seconds: int = _MAX_CLIP_SECONDS,
) -> list[ClipCandidate]:
    """Validate, normalize, deduplicate, and rank clip candidates."""
    logger.info("Validating %d clip candidates...", len(candidates))

    valid_clips: list[tuple[float, float, ClipCandidate]] = []
    seen_ranges: list[tuple[float, float]] = []

    for idx, candidate in enumerate(candidates, start=1):
        # Metadata validation
        metadata_errors = _validate_clip_metadata(candidate, idx)
        if metadata_errors:
            logger.warning("Skipping clip %d: invalid metadata: %s", idx, "; ".join(metadata_errors))
            continue

        try:
            start_sec = parse_time(candidate.start)
            end_sec = parse_time(candidate.end)
        except ValueError as exc:
            logger.warning("Skipping clip %d: invalid timestamp (%s)", idx, exc)
            continue

        # Basic validation
        if start_sec < 0 or end_sec < 0:
            logger.warning("Skipping clip %d: negative timestamp", idx)
            continue
        if start_sec >= end_sec:
            logger.warning("Skipping clip %d: start >= end (%s >= %s)", idx, candidate.start, candidate.end)
            continue
        if video_duration > 0 and end_sec > video_duration:
            logger.warning(
                "Skipping clip %d: end time %s exceeds video duration %s",
                idx, candidate.end, format_time(video_duration),
            )
            continue
        if not _validate_clip_duration(start_sec, end_sec, min_seconds, max_seconds):
            duration = end_sec - start_sec
            logger.warning(
                "Skipping clip %d: duration %.1fs outside range [%d, %d]",
                idx, duration, min_seconds, max_seconds,
            )
            continue

        # Overlap check
        overlaps = False
        for prev_start, prev_end in seen_ranges:
            if _clip_overlaps(start_sec, end_sec, prev_start, prev_end):
                overlaps = True
                break

        if overlaps:
            logger.info("Clip %d overlaps with existing clip, skipping", idx)
            continue

        duration_sec = end_sec - start_sec
        clip = ClipCandidate(
            id_klip=len(valid_clips) + 1,
            judul_relevan=str(candidate.title).strip(),
            deskripsi=str(candidate.description).strip(),
            start_klip=format_time(start_sec),
            end_klip=format_time(end_sec),
            tags=tags[:3] if (tags := candidate.tags or []) else [],
            durasi_detik=round(duration_sec, 1),
            hook=str(candidate.hook).strip(),
            score=float(candidate.score),
        )
        valid_clips.append((start_sec, end_sec, clip))
        seen_ranges.append((start_sec, end_sec))

    # Sort by score descending, then take up to target_count
    valid_clips.sort(key=lambda x: x[2].score, reverse=True)
    selected = valid_clips[:target_count]
    selected.sort(key=lambda x: x[0])  # Re-sort by start time for output

    if len(selected) < target_count:
        logger.warning(
            "Only %d valid clips found (requested %d). Returning available clips.",
            len(selected), target_count,
        )

    logger.info("Validated %d clips after filtering %d candidates", len(selected), len(candidates))
    return [clip for _, _, clip in selected]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run(
    url: str,
    target_count: int | None = None,
    min_seconds: int | None = None,
    max_seconds: int | None = None,
) -> None:
    """Run Stage 1: curate clips from a YouTube video.

    Args:
        url: Source YouTube URL.
        target_count: Number of clips to curate. Defaults to config value.
        min_seconds: Durasi klip minimal. Ini penentu utama berapa banyak klip yang
            MUNGKIN dihasilkan (maks teoretis = durasi video / min_seconds).
        max_seconds: Durasi klip maksimal.
    """
    setup_logging()
    ensure_dirs()

    count = target_count or settings.target_clip_count
    lo = int(min_seconds or settings.clip_min_seconds)
    hi = int(max_seconds or settings.clip_max_seconds)
    if lo < 5:
        raise ValueError(f"min_seconds terlalu kecil: {lo} (minimal 5)")
    if hi <= lo:
        raise ValueError(f"max_seconds ({hi}) harus lebih besar dari min_seconds ({lo})")

    logger.info("=" * 60)
    logger.info("[1/5] STAGE 1: CURATE CLIPS")
    logger.info("URL: %s | Target clips: %d | Durasi klip: %d-%ds", url, count, lo, hi)
    logger.info("=" * 60)

    # Step 1: Video metadata
    logger.info("[1/5] Reading video metadata...")
    video_id = extract_video_id(url)
    metadata = fetch_video_metadata(video_id)
    video_title = metadata["title"]
    video_creator = metadata.get("creator", "")
    video_duration = float(metadata["duration"])
    logger.info("Video ID: %s | Title: %s | Duration: %s", video_id, video_title, format_time(video_duration))

    # Step 2: Transcript
    logger.info("[2/5] Obtaining transcript...")
    cached = load_transcript_cache(video_id)
    if cached:
        logger.info("Using cached transcript (source: %s, language: %s)", cached.source, cached.language)
        segments = cached.segments
        transcript_source = cached.source
        transcript_language = cached.language
    else:
        segments, transcript_source, transcript_language = get_transcript(video_id, url, settings.transcript_languages)
        save_transcript_cache(video_id, transcript_source, transcript_language, segments)
        logger.info("Transcript cached for future runs.")

    if not segments:
        raise RuntimeError("No transcript segments available after all attempts.")

    logger.info("Transcript: %d segments, source=%s, language=%s", len(segments), transcript_source, transcript_language)

    # Step 3: Gemini analysis
    logger.info("[3/5] Analyzing transcript with Gemini...")
    transcript_text = _build_transcript_text(segments)

    # Peringatan sebelum request dikirim: kalau video terlalu pendek untuk jumlah klip
    # yang diminta, mustahil terpenuhi. Lebih baik user tahu SEKARANG daripada mengira
    # hasilnya bug setelah menunggu request selesai.
    if video_duration > 0:
        maks_teoretis = int(video_duration // lo)
        if maks_teoretis < count:
            logger.warning(
                "Video %s hanya bisa memuat maksimal %d klip @ %ds (diminta %d). "
                "Turunkan durasi minimal atau kurangi jumlah klip.",
                format_time(video_duration), maks_teoretis, lo, count,
            )

    gemini_candidates = curate_with_gemini(transcript_text, count, video_duration, lo, hi)

    # Step 4: Validate clips
    logger.info("[4/5] Validating clip candidates...")
    validated_clips = validate_and_normalize_clips(
        gemini_candidates, video_duration, count, lo, hi
    )

    if not validated_clips:
        raise RuntimeError("No valid clips after validation. Check transcript quality or Gemini output.")

    # Step 5: Save curation manifest
    logger.info("[5/5] Saving curation manifest...")
    curation = CurationResult(
        url_video=url,
        judul_video=video_title,
        video_id=video_id,
        durasi_video=video_duration,
        transcript_source=transcript_source,
        transcript_language=transcript_language,
        total_klip=len(validated_clips),
        daftar_klip=validated_clips,
    )

    # Output goes to output/<creator>/<title>/ — folder names are sanitized
    # and the title folder is capped at 30 characters.
    def _short_title_folder(title: str, max_len: int = 30) -> str:
        safe = re.sub(r"[^\w\-]+", "_", title).strip("_")
        return (safe[:max_len].rstrip("_")) or video_id

    creator_folder = re.sub(r"[^\w\-]+", "_", (video_creator or "unknown")).strip("_") or "unknown"
    output_dir = settings.output_dir / creator_folder / _short_title_folder(video_title)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{video_id}.json"
    output_path.write_text(curation.model_dump_json(indent=2), encoding="utf-8")

    # Also save as latest for convenience
    latest_path = settings.output_dir / "curation_latest.json"
    latest_path.write_text(curation.model_dump_json(indent=2), encoding="utf-8")

    logger.info("=" * 60)
    logger.info("[v] STAGE 1 COMPLETE")
    logger.info("Saved: %s", output_path)
    logger.info("Clips curated: %d / %d requested", len(validated_clips), count)
    for clip in validated_clips:
        logger.info(
            "  Clip %d: %s [%s -> %s] (%.1fs) score=%.2f",
            clip.id_klip, clip.judul_relevan, clip.start_klip, clip.end_klip, clip.durasi_detik, clip.score,
        )
    logger.info("=" * 60)