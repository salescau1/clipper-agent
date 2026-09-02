"""Stage 4: Smart Subtitle Generation (WhisperX Forced Alignment).

FINAL ARCHITECTURE:
    YouTube CC (authoritative TEXT) + WhisperX forced alignment (authoritative TIMING)
    → Python deterministic grouping + validation → SRT

Pipeline:
    1. Load Stage 2 manifest (READ-ONLY — never modify source clips).
    2. Load YouTube CC transcript from Stage 1 cache (authoritative text).
    3. Run WhisperX forced alignment on the individual Stage 2 clip
       using CC text as reference (authoritative word-level timing).
    4. Deterministic Python grouping (target words, min/max duration, pauses).
    5. Validate all subtitle timings against clip duration.
    6. Generate SRT files directly in the Stage 2 output folder.
    7. Write subtitle_manifest.json with full tracking.

Source responsibilities:
    - YouTube CC: authoritative transcript TEXT, spoken wording, language
    - WhisperX: authoritative word-level TIMING via forced alignment (NOT ASR)
    - Python: deterministic grouping, validation, SRT generation
    - Gemini: koreksi teks trilingual (Indo + Sunda + Inggris) sebelum forced
      alignment. AKTIF kalau GEMINI_API_KEY ada di .env, dilewati kalau kosong —
      pipeline tetap jalan tanpanya, hasilnya saja lebih banyak typo.

Output layout:
    output/clips/<stage2-folder>/
        <clip>.srt
        subtitle_manifest.json
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import subprocess
from pathlib import Path
from typing import Any
from youtube_transcript_api import YouTubeTranscriptApi

# Ensure project root is on sys.path so 'config', 'models', 'utils' resolve
# regardless of whether this script is run directly, imported, or invoked via
# subprocess by stage4_batch.py.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Lazy imports to avoid requiring project deps (pydantic, etc.) in environments
# that only have whisperx (e.g. when called via stage4_batch.py in whisperx-venv).
def _lazy_config():
    from config import settings
    return settings

def _lazy_models():
    from models import ClipManifest, ClipManifestEntry, SubtitleGroup, SubtitleJob
    return ClipManifest, ClipManifestEntry, SubtitleGroup, SubtitleJob

def _lazy_utils():
    from utils import ensure_dirs, get_logger, parse_time, setup_logging
    return ensure_dirs, get_logger, parse_time, setup_logging

# Only set up logger when config/utils are available (i.e. in .venv)
try:
    _ensure_dirs, _get_logger, _parse_time, _setup_logging = _lazy_utils()
    logger = _get_logger("stage4")
except ImportError:
    logger = None


def _log_info(msg: str, *args: Any) -> None:
    """Log info tanpa mengasumsikan logger tersedia.

    `logger` bernilai None kalau `utils` tidak bisa diimpor (mode whisperx-venv-only).
    Di lingkungan itu 53 pemanggilan `logger.info(...)` lain di file ini akan melempar
    AttributeError; helper ini dipakai untuk jalur baru supaya tidak menambah risiko itu.
    """
    if logger is not None:
        logger.info(msg, *args)
    else:
        print(f"      {msg % args if args else msg}")

# Resolve models now (fails gracefully in whisperx-venv-only mode)
try:
    ClipManifest, ClipManifestEntry, SubtitleGroup, SubtitleJob = _lazy_models()
except ImportError:
    ClipManifest = ClipManifestEntry = SubtitleGroup = SubtitleJob = None

# Resolve settings now (fails gracefully in whisperx-venv-only mode;
# constants below fall back to hardcoded defaults if settings unavailable).
try:
    settings = _lazy_config()
except ImportError:
    settings = None

# ---------------------------------------------------------------------------
# Default constants (used when settings is unavailable in whisperx-venv)
# ---------------------------------------------------------------------------
_MIN_SUBTITLE_DURATION = 0.5
_MAX_SUBTITLE_DURATION = 6.0
_TARGET_WORDS = 3
_WHISPERX_CACHE_DIR: Path | None = None

# ---------------------------------------------------------------------------
# Stage 1 Transcript Cache Integration
# ---------------------------------------------------------------------------


def _get_stage1_cache_path(video_id: str) -> Path:
    """Get the path to the Stage 1 transcript cache for a video ID.

    Args:
        video_id: YouTube video ID.

    Returns:
        Path to the transcript cache JSON file.
    """
    return settings.cache_dir / "transcripts" / f"{video_id}.json"


def load_stage1_transcript_cache(video_id: str) -> dict[str, Any] | None:
    """Load Stage 1 transcript cache for a video ID.

    Args:
        video_id: YouTube video ID.

    Returns:
        Dict with 'source', 'language', 'segments' keys, or None if not found.
    """
    cache_path = _get_stage1_cache_path(video_id)
    if not cache_path.exists():
        logger.debug("No Stage 1 transcript cache found for video_id=%s", video_id)
        return None
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
        # Validate required fields
        if "source" not in raw or "segments" not in raw:
            logger.warning("Stage 1 cache for %s missing required fields", video_id)
            return None
        logger.info(
            "Loaded Stage 1 transcript cache: source=%s, language=%s, segments=%d",
            raw.get("source"), raw.get("language"), len(raw.get("segments", [])),
        )
        return raw
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load Stage 1 transcript cache: %s", e)
        return None


def _filter_and_localize_cc_segments(
    segments: list[dict[str, Any]],
    clip_start: float,
    clip_end: float,
) -> list[dict[str, Any]]:
    """Filter YouTube CC segments to clip's source-video time range and localize timestamps.

    YouTube CC segments use source-video timestamps (0..video_length).
    This function:
    1. Keeps only segments that overlap with [clip_start, clip_end).
    2. Shifts all timestamps by subtracting clip_start so they are local
       to the generated Stage 2 clip.
    3. Clamps segment starts/ends to the clip boundary so no leakage occurs.

    Args:
        segments: List of CC segment dicts with 'start', 'duration', 'text'.
        clip_start: Clip start time in source-video seconds (from manifest).
        clip_end: Clip end time in source-video seconds (from manifest).

    Returns:
        Filtered and localized segment dicts (same shape as input).
    """
    filtered: list[dict[str, Any]] = []
    for seg in segments:
        seg_start = float(seg.get("start", 0))
        seg_end = seg_start + float(seg.get("duration", 0))
        seg_text = seg.get("text", "").strip()
        if not seg_text:
            continue
        # Keep only segments that overlap with [clip_start, clip_end)
        if seg_end <= clip_start or seg_start >= clip_end:
            continue
        # Localize: shift by clip_start, clamp to [0, clip_duration)
        local_start = max(0.0, seg_start - clip_start)
        local_end = min(clip_end - clip_start, seg_end - clip_start)
        local_duration = max(0.0, local_end - local_start)
        filtered.append({
            "start": round(local_start, 2),
            "duration": round(local_duration, 2),
            "text": seg_text,
        })
    logger.info(
        "Filtered CC: %d → %d segments (clip %ds-%ds)",
        len(segments), len(filtered), clip_start, clip_end,
    )
    return filtered


def _normalize_transcript_text(words: list[dict[str, Any]]) -> str:
    """Normalize word-level transcript to a single text string.

    Args:
        words: List of word dicts with 'word', 'start', 'end' keys.

    Returns:
        Normalized transcript text with proper spacing and punctuation.
    """
    if not words:
        return ""

    text_parts = []
    for w in words:
        word_text = w.get("word", "").strip()
        if word_text:
            text_parts.append(word_text)

    return " ".join(text_parts)


# Minimum and maximum display duration for a subtitle group (seconds)
# ---------------------------------------------------------------------------
# Defaults from config (runtime-resolved via settings, with fallbacks)
# ---------------------------------------------------------------------------

_MIN_SUBTITLE_DURATION = 0.5  # fallback; overridden below if settings available
_MAX_SUBTITLE_DURATION = 6.0
_TARGET_WORDS = 3
# Ukuran model faster-whisper. `medium` dipilih sebagai default karena `small`
# sering salah dengar kosakata Sunda dan memicu looping pada audio lapangan.
# Nilai nyata datang dari WHISPER_MODEL di .env lewat settings; konstanta ini
# hanya berlaku saat modul dijalankan di whisperx-venv (tanpa config).
_WHISPER_MODEL = "medium"
_WHISPERX_CACHE_DIR: Path | None = None

if settings is not None:
    _MIN_SUBTITLE_DURATION = settings.subtitle_min_duration
    _MAX_SUBTITLE_DURATION = settings.subtitle_max_duration
    _TARGET_WORDS = settings.subtitle_target_words
    _WHISPER_MODEL = settings.whisper_model
    _WHISPERX_CACHE_DIR = settings.cache_dir / "whisperx"


# ---------------------------------------------------------------------------
# Item 24: Preferred Languages (trilingual) + anti-looping
# ---------------------------------------------------------------------------
#
# LARANGAN KERAS — tag bahasa di sini TIDAK BOLEH masuk parameter `language=`.
#
# Diukur langsung di `.whisperx-venv` (2026-09-02): whisperx hanya punya 41 bahasa
# dengan model forced-alignment (DEFAULT_ALIGN_MODELS_TORCH 5 + DEFAULT_ALIGN_MODELS_HF
# 36). `id` ADA (cahya/wav2vec2-large-xlsr-indonesian), `en` ADA, tetapi `su` (Sunda)
# TIDAK ADA dan `jv` (Jawa) TIDAK ADA.
#
# Kalau `su` diteruskan ke `language=`:
#   forced alignment MATI -> timestamp per kata hilang -> SRT 1-kata-per-entri hancur
#   -> kerapatan subtitle 1/3/5 kata di Theme kehilangan fondasinya.
#
# Jadi bahasa transkripsi & alignment TETAP `_ALIGNMENT_LANGUAGE` ("id"). Tag bahasa
# HANYA dipakai untuk merakit `initial_prompt` — itu satu-satunya tempat centang
# bahasa berpengaruh. Jangan "merapikan" ini dengan meneruskan tag ke language=.
_ALIGNMENT_LANGUAGE = "id"

# Tag default kalau tidak ada yang diberikan. JANGAN pernah memakai daftar kosong:
# initial_prompt kosong mengembalikan perilaku lama (rawan salah tebak bahasa).
_DEFAULT_LANG_TAGS: tuple[str, ...] = ("id",)

# Kosakata per tag. Diambil apa adanya dari bug.txt Item 24 poin 3a — jangan dikarang
# sendiri: daftar ini yang menahan salah dengar kosakata Sunda dan istilah tech.
_LANG_PROMPT_VOCAB: dict[str, str] = {
    "su": (
        "kumaha, atuh, euy, punten, naha, pisan, da, maneh, barudak, abah, sare, "
        "hayu, nuhun, lur, akang, teteh"
    ),
    "en": (
        "gadget, review, worth it, podcast, creator, gaming, frame, setup"
    ),
    "id": (
        "percakapan santai umum"
    ),
}

# Klausa per tag untuk merangkai initial_prompt sebagai KALIMAT, bukan daftar kata
# telanjang. Diukur 2026-09-03 pada klip uji 25s (GEMINI_API_KEY dikosongkan supaya
# koreksi Gemini tidak mengaburkan hasil):
#   gaya daftar  "Transkrip percakapan campuran. Bahasa Sunda: kumaha, atuh, ..."
#       -> 42 kata, DAN muncul fragmen ganda di akhir: segmen "...4,1 juta."
#          disusul segmen baru "7 juta." (angka yang sama diucapkan sekali).
#   gaya kalimat "Ini transkrip percakapan santai berbahasa Indonesia yang
#                 bercampur Bahasa Sunda seperti kumaha, atuh, ..."
#       -> 40 kata, fragmen "7 juta." HILANG.
# Whisper memakai initial_prompt sebagai konteks kalimat SEBELUMNYA, jadi bentuk
# prosa lebih menyerupai data latihnya daripada daftar berlabel. Jangan diubah
# kembali ke gaya "Label: kata, kata" tanpa mengukur ulang.
_LANG_PROMPT_CLAUSE: dict[str, str] = {
    "id": "berbahasa Indonesia",
    "su": "bercampur Bahasa Sunda seperti " + _LANG_PROMPT_VOCAB["su"],
}

# `en` ditulis sebagai kalimat terpisah supaya rangkaiannya tetap enak dibaca saat
# tiga tag aktif sekaligus (kalau digabung dengan " yang ", daftar kosakata Sunda
# dan Inggris menempel tanpa jeda).
_LANG_PROMPT_EXTRA: dict[str, str] = {
    "en": "Ada juga istilah Inggris seperti " + _LANG_PROMPT_VOCAB["en"] + ".",
}

# Urutan tetap supaya prompt yang dihasilkan deterministik (mudah diuji & dibaca log),
# tidak tergantung urutan centang di UI.
_LANG_PROMPT_ORDER: tuple[str, ...] = ("id", "su", "en")

# Default tag bahasa saat CLI tidak mengirim `--lang-tags`. Dibaca dari settings
# (SUBTITLE_LANG_TAGS di .env) kalau config bisa diimpor; kalau tidak, jatuh ke
# `_DEFAULT_LANG_TAGS`. Nilainya dinormalkan di bawah setelah parse_lang_tags ada.
_LANG_TAGS_DEFAULT_RAW: list[str] = list(_DEFAULT_LANG_TAGS)
if settings is not None:
    try:
        _LANG_TAGS_DEFAULT_RAW = list(settings.subtitle_lang_tags)
    except AttributeError:
        # Config lama tanpa field ini — biarkan default ["id"].
        pass


def parse_lang_tags(raw: str | list[str] | tuple[str, ...] | None) -> list[str]:
    """Normalkan `--lang-tags` menjadi daftar tag yang valid dan unik.

    Terima "id,su", ["id", "su"], atau None. Tag yang tidak dikenali dibuang.
    Daftar kosong SELALU jatuh ke `_DEFAULT_LANG_TAGS` (["id"]) — Item 24 poin 2:
    jangan pernah meneruskan daftar kosong ke bawah.
    """
    if raw is None:
        items: list[str] = []
    elif isinstance(raw, str):
        items = raw.split(",")
    else:
        items = list(raw)

    tags: list[str] = []
    for item in items:
        tag = str(item).strip().lower()
        if not tag:
            continue
        if tag not in _LANG_PROMPT_VOCAB:
            _log_info("Tag bahasa '%s' tidak dikenali — dilewati.", tag)
            continue
        if tag not in tags:
            tags.append(tag)

    if not tags:
        return list(_DEFAULT_LANG_TAGS)
    # Urutkan mengikuti _LANG_PROMPT_ORDER supaya prompt deterministik.
    return [t for t in _LANG_PROMPT_ORDER if t in tags]


def build_initial_prompt(
    raw_tags: str | list[str] | tuple[str, ...] | None = None,
) -> str:
    """Rakit `initial_prompt` faster-whisper dari tag bahasa yang aktif.

    initial_prompt bekerja sebagai konteks awal decoder: menyebut kosakata yang
    memang muncul di video mempersempit ruang tebak model, jadi kata Sunda tidak
    lagi dipaksa jadi kata Indonesia/Spanyol yang bunyinya mirip.

    Bentuknya KALIMAT, bukan daftar berpoin — lihat alasan terukurnya di komentar
    `_LANG_PROMPT_CLAUSE`. Contoh keluaran untuk "id,su,en":
        "Ini transkrip percakapan santai berbahasa Indonesia yang bercampur Bahasa
         Sunda seperti kumaha, atuh, ... Ada juga istilah Inggris seperti gadget,
         review, ..."

    CATATAN: ini lapisan LOKAL di depan koreksi Gemini (`correct_text_trilingual()`),
    BUKAN penggantinya (keputusan user A, 2026-09-03).
    """
    tags = parse_lang_tags(raw_tags)
    klausa = [_LANG_PROMPT_CLAUSE[t] for t in tags if t in _LANG_PROMPT_CLAUSE]
    if klausa:
        kalimat = "Ini transkrip percakapan santai " + " yang ".join(klausa) + "."
    else:
        # Bisa terjadi kalau hanya `en` yang aktif. Tetap sebut bahasa dasarnya:
        # transkripsi berjalan dengan language="id" apa pun tag-nya.
        kalimat = "Ini transkrip percakapan santai berbahasa Indonesia."
    tambahan = [_LANG_PROMPT_EXTRA[t] for t in tags if t in _LANG_PROMPT_EXTRA]
    return " ".join([kalimat, *tambahan])


# Parameter VAD (Silero-VAD lewat faster-whisper). Ini pekerjaan MENAMBAH:
# `vad_filter` default False di faster-whisper (terukur: faster_whisper 1.2.1 di
# `.whisperx-venv`), dan kode ini memanggil `WhisperModel(...)` langsung — BUKAN
# `whisperx.load_model` yang membawa Silero-VAD. Jadi tanpa baris ini VAD tidak
# aktif sama sekali dan audio hening / musik latar tetap dikirim ke decoder, yang
# memproduksi teks gaib dan looping.
#
# Bukti terukur 2026-09-03, video uji 10s hening + 12s bicara + 10s hening:
#   vad_filter OFF -> 2 segmen; segmen kedua 30.00s->34.00s berbunyi
#                     "Terima kasih telah menonton" (teks gaib murni, di bagian
#                     yang audionya benar-benar sunyi), dan segmen pertama
#                     direntangkan 0.00s->30.00s.
#   vad_filter ON  -> 1 segmen 10.10s->22.10s, tepat di bagian yang ada suaranya.
#                     Nol teks gaib.
#
# Nilainya SENGAJA sama dengan default VadOptions faster-whisper (2000/400) dan
# ditulis eksplisit, bukan dikosongkan. Setelan lebih agresif (500/200) sudah diuji
# dan DITOLAK: pada video uji yang sama ia ikut memotong ucapan nyata di awal
# ("Tinggi saat ini." hilang, 14 kata vs 19 kata). Jangan diperketat tanpa
# mengukur ulang dengan klip yang punya bagian hening.
_VAD_PARAMETERS: dict[str, Any] = {
    "min_silence_duration_ms": 2000,
    "speech_pad_ms": 400,
}


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------


def find_stage2_manifest(video_id: str | None = None) -> Path | None:
    """Find a Stage 2 manifest by video_id or return the latest one.

    Stage 2 writes manifests to output/<creator>/<title>/manifest.json.
    Legacy location (output/clips/) is also searched for backwards compat.

    Args:
        video_id: Optional YouTube video ID to match.

    Returns:
        Path to the manifest file, or None if not found.
    """
    # New layout: output/<creator>/<title>/manifest.json
    candidates: list[Path] = []
    for pattern in ("*/*/manifest.json", "*/manifest.json"):
        candidates.extend(settings.output_dir.glob(pattern))
    # Legacy layout: output/clips/*/manifest.json
    if (settings.output_dir / "clips").exists():
        candidates.extend((settings.output_dir / "clips").glob("*/manifest.json"))

    manifests = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)

    if video_id:
        for manifest_path in manifests:
            try:
                raw = json.loads(manifest_path.read_text(encoding="utf-8"))
                if raw.get("video_id") == video_id:
                    return manifest_path
            except (json.JSONDecodeError, OSError):
                continue
        logger.warning("No manifest found for video_id=%s", video_id)
        return None

    return manifests[0] if manifests else None


def load_stage2_manifest(manifest_path: Path | None = None) -> ClipManifest:
    """Load and validate a Stage 2 manifest.

    Args:
        manifest_path: Explicit path to manifest.json. If None, finds latest.

    Returns:
        Validated ClipManifest.

    Raises:
        FileNotFoundError: If no manifest is found.
        ValueError: If manifest is invalid.
    """
    if manifest_path is None:
        manifest_path = find_stage2_manifest()

    if manifest_path is None or not manifest_path.exists():
        raise FileNotFoundError(
            f"No Stage 2 manifest found. Run Stage 2 first.\n"
            f"Searched in: {settings.output_dir / 'clips'}"
        )

    logger.info("Loading Stage 2 manifest: %s", manifest_path)
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    return ClipManifest.model_validate(raw)


# ---------------------------------------------------------------------------
# WhisperX forced alignment
# ---------------------------------------------------------------------------


def _get_whisperx_cache_path(input_path: Path, alignment_model: str) -> Path:
    """Get the cache path for a WhisperX alignment result.

    Args:
        input_path: Path to the input video.
        alignment_model: Wav2Vec2 alignment model name.

    Returns:
        Path to the cached alignment JSON.
    """
    cache_key = re.sub(r'[^a-zA-Z0-9_-]', '_', str(input_path))
    model_key = re.sub(r'[^a-zA-Z0-9_-]', '_', alignment_model)
    return _WHISPERX_CACHE_DIR / f"{cache_key}_{model_key}.json"


def _is_whisperx_cache_valid(cache_path: Path, input_path: Path) -> bool:
    """Check if the cached WhisperX alignment is still valid.

    Args:
        cache_path: Path to the cached alignment.
        input_path: Path to the input video.

    Returns:
        True if cache exists and input file hasn't changed.
    """
    if not cache_path.exists():
        return False
    try:
        cache_data = json.loads(cache_path.read_text(encoding="utf-8"))
        cached_mtime = cache_data.get("input_mtime")
        input_mtime = input_path.stat().st_mtime
        return cached_mtime == input_mtime
    except (json.JSONDecodeError, OSError):
        return False


def _extract_audio_for_whisperx(input_path: Path, output_path: Path) -> bool:
    """Extract audio from video for WhisperX processing.

    Args:
        input_path: Path to the video file.
        output_path: Path to write the extracted audio (WAV, 16kHz mono).

    Returns:
        True if extraction succeeded.
    """
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(input_path),
                "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                str(output_path)
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.error("FFmpeg audio extraction failed: %s", result.stderr)
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error("FFmpeg audio extraction timed out")
        return False
    except Exception as e:
        logger.error("FFmpeg audio extraction error: %s", e)
        return False


def _run_whisperx_alignment(
    audio_path: Path,
    cc_text: str,
    language: str = "id",
    alignment_model: str = "cahya/wav2vec2-large-xlsr-indonesian",
) -> list[dict[str, Any]] | None:
    """Run WhisperX forced alignment on audio with CC text as reference.

    This uses WhisperX's alignment module (wav2vec2) to align the provided
    CC transcript text to the audio, producing word-level timestamps.
    WhisperX ASR is NOT used — only forced alignment.

    Args:
        audio_path: Path to the extracted audio file (WAV, 16kHz mono).
        cc_text: Full CC transcript text for this clip (localized).
        language: Language code (default: Indonesian).
        alignment_model: Wav2Vec2 model for alignment.

    Returns:
        List of word dicts with 'word', 'start', 'end' keys, or None on failure.
    """
    try:
        import whisperx
        import torch
    except ImportError:
        logger.error("WhisperX not installed in current environment")
        return None

    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info("Running WhisperX forced alignment on %s (device=%s)", audio_path.name, device)

    try:
        # Load alignment model
        align_model, align_metadata = whisperx.load_align_model(
            language_code=language,
            device=device,
            model_name=alignment_model,
        )

        # Load audio
        audio = whisperx.load_audio(str(audio_path))

        # WhisperX 3.8.x MEWAJIBKAN tiap segmen punya "start" dan "end" — tanpa itu
        # whisperx/alignment.py melempar KeyError: 'start'. Karena ini forced alignment
        # atas satu blok teks utuh, rentangnya adalah seluruh audio: 0 -> durasi.
        # SAMPLE_RATE whisperx = 16000, jadi durasi = jumlah sampel / 16000.
        audio_duration = len(audio) / 16000.0
        transcript_segments = [{
            "text": cc_text,
            "start": 0.0,
            "end": audio_duration,
        }]

        # Run forced alignment
        result = whisperx.align(
            transcript_segments,
            align_model,
            align_metadata,
            audio,
            device,
            return_char_alignments=False,
        )

        # Extract word-level timestamps
        words = []
        if "segments" in result and result["segments"]:
            for seg in result["segments"]:
                seg_words = seg.get("words", [])
                if seg_words:
                    for w in seg_words:
                        word_text = w.get("word", "").strip()
                        if word_text:
                            words.append({
                                "word": word_text,
                                "start": round(float(w.get("start", 0.0)), 2),
                                "end": round(float(w.get("end", 0.0)), 2),
                            })

        logger.info("WhisperX aligned %d words", len(words))
        return words

    except Exception as e:
        logger.error("WhisperX forced alignment failed: %s", e)
        return None


def transcribe_clip_asr(
    input_path: Path,
    language: str = _ALIGNMENT_LANGUAGE,
    lang_tags: str | list[str] | tuple[str, ...] | None = None,
) -> str:
    """Transkripsi ASR sebagai JALUR FALLBACK ketika video tidak punya CC YouTube.

    Jalur utama Stage 4 tetap: teks CC YouTube -> forced alignment. Google ASR jauh
    lebih kuat di bahasa daerah, jadi CC dipakai kalau ada. Fungsi ini baru dipanggil
    kalau CC tidak tersedia — tanpanya klip tanpa CC gagal total tanpa subtitle
    (perilaku sebelumnya).

    Parameter anti-halusinasi WAJIB ada di sini:
        condition_on_previous_text=False  -> memutus umpan balik yang memicu
            pengulangan kata ("Bagaimana? Bagaimana?...") pada audio lapangan bising.
        no_speech_threshold=0.6           -> membuang derau angin tanpa vokal manusia.
        temperature=(0.0, 0.2, 0.4)       -> fallback sampling saat decoder stagnan.
        vad_filter=True                   -> Silero-VAD memangkas hening/musik latar
            SEBELUM decoder jalan (Item 24 poin 3b). `vad_filter` default False di
            faster-whisper dan kode ini memanggil `WhisperModel(...)` langsung, BUKAN
            `whisperx.load_model` yang membawa VAD-nya sendiri — jadi tanpa baris ini
            VAD tidak aktif sama sekali dan bagian hening menghasilkan teks gaib.
        initial_prompt=<kosakata bahasa>  -> mempersempit ruang tebak model ke bahasa
            yang dipilih user (Item 24 poin 3a).

    `language` TETAP "id" (_ALIGNMENT_LANGUAGE). `lang_tags` HANYA merakit
    initial_prompt dan TIDAK BOLEH masuk parameter `language=` — lihat larangan
    lengkapnya di blok komentar _ALIGNMENT_LANGUAGE.

    Teks hasil di sini masih kasar; pembersihannya dilakukan koreksi Gemini trilingual
    di `run()`, lalu di-align ke audio supaya detik per katanya tetap presisi.

    Returns:
        Teks transkrip mentah (satu string), atau "" kalau gagal.
    """
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_audio:
        audio_path = Path(tmp_audio.name)

    try:
        if not _extract_audio_for_whisperx(input_path, audio_path):
            return ""

        try:
            from faster_whisper import WhisperModel
        except ImportError:
            logger.error("faster-whisper tidak terpasang di environment ini")
            return ""

        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"
        compute_type = "float16" if device == "cuda" else "int8"

        # Tag bahasa -> initial_prompt (Item 24 3a). Dinormalkan di sini supaya
        # daftar kosong TIDAK pernah lolos ke bawah (jatuh ke ["id"]).
        tags = parse_lang_tags(
            lang_tags if lang_tags is not None else _LANG_TAGS_DEFAULT_RAW
        )
        initial_prompt = build_initial_prompt(tags)

        logger.info(
            "ASR fallback: faster-whisper '%s' (device=%s) untuk %s",
            _WHISPER_MODEL, device, input_path.name,
        )
        _log_info(
            "ASR fallback: lang-tags=%s | VAD=ON | language=%s (tetap, jangan diganti)",
            ",".join(tags), language,
        )
        try:
            model = WhisperModel(_WHISPER_MODEL, device=device, compute_type=compute_type)
            segments, info = model.transcribe(
                str(audio_path),
                # `language` TETAP "id": tag bahasa TIDAK BOLEH masuk ke sini, kalau
                # `su` masuk maka forced alignment mati dan SRT 1 kata/entri hancur.
                language=language,
                beam_size=5,
                condition_on_previous_text=False,
                no_speech_threshold=0.6,
                temperature=(0.0, 0.2, 0.4),
                # Item 24 3a: satu-satunya tempat centang bahasa berpengaruh.
                initial_prompt=initial_prompt,
                # Item 24 3b: VAD Silero DIPASANG (default faster-whisper False).
                vad_filter=True,
                vad_parameters=_VAD_PARAMETERS,
            )
            parts = [seg.text.strip() for seg in segments if seg.text and seg.text.strip()]
            text = " ".join(parts).strip()
            logger.info(
                "ASR fallback: %d segmen, bahasa terdeteksi %s (%.2f), %d kata",
                len(parts), getattr(info, "language", "?"),
                getattr(info, "language_probability", 0.0) or 0.0,
                len(text.split()),
            )
            return text
        except Exception as e:
            logger.error("ASR fallback gagal untuk %s: %s", input_path.name, e)
            return ""
    finally:
        try:
            audio_path.unlink(missing_ok=True)
        except Exception:
            pass


def correct_text_trilingual(
    raw_text: str,
    video_title: str = "",
) -> tuple[str, str]:
    """Bersihkan transkrip dengan LLM: typo, salah dengar, dan kata halusinasi/looping.

    Bahasanya campuran Indonesia + Sunda + istilah Inggris, jadi prompt secara eksplisit
    melarang menerjemahkan kosakata Sunda dan istilah Inggris. Judul video dikirim
    sebagai konteks supaya model tahu topik obrolannya.

    Dipakai untuk KEDUA jalur (CC maupun ASR): CC otomatis YouTube juga punya typo.
    Dilewati kalau GEMINI_API_KEY kosong — pipeline tetap jalan tanpa koreksi.

    Returns:
        (teks, status) — status: "success" | "empty" | "not_configured" | "failed: ..."
        Saat gagal, teks yang dikembalikan adalah `raw_text` apa adanya, sehingga
        pemanggil tidak perlu menangani kasus kosong.
    """
    if not raw_text.strip():
        return raw_text, "empty_input"

    # .env WAJIB dibaca eksplisit di sini. Stage 4 dijalankan oleh .whisperx-venv
    # sebagai subprocess (lihat main.py::_stage4_batch), dan di jalur itu tidak ada
    # yang memuat .env: pydantic-settings di config.py membaca .env ke objek
    # `settings`, TIDAK ke os.environ. Tanpa baris ini os.getenv("GEMINI_API_KEY")
    # selalu None sehingga koreksi trilingual diam-diam dilewati dengan status
    # "not_configured" — subtitle tetap keluar tapi looping & typo tidak pernah
    # dibersihkan. Dibungkus try/except supaya lingkungan tanpa python-dotenv
    # tetap jalan (fallback ke environment variable milik sistem).
    if not os.getenv("GEMINI_API_KEY"):
        try:
            from dotenv import load_dotenv

            load_dotenv(_PROJECT_ROOT / ".env")
        except ImportError:
            pass

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        _log_info("GEMINI_API_KEY kosong — koreksi trilingual dilewati.")
        return raw_text, "not_configured"

    try:
        from openai import OpenAI

        client = OpenAI(
            base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
            api_key=api_key,
            timeout=120.0,
            max_retries=1,
        )

        prompt = f"""Teks transkrip ini berisi obrolan campuran Bahasa Indonesia, istilah gaul/Inggris, dan Bahasa Sunda.
Konteks Judul Video: "{video_title or 'Tidak diketahui'}"

Tugas: Perbaiki salah dengar/typo dan hilangkan kata halusinasi/looping.
Pertahankan kosakata asli Sunda (misal: 'kumaha', 'atuh', 'euy', 'naha', 'pisan', 'tong diantep', 'salakina') dan istilah Inggris tanpa diterjemahkan paksa.
DILARANG menambah/mengurangi inti kalimat. Keluarkan teks yang sudah bersih.
HANYA KELUARKAN TEKS BERSIH SAJA TANPA TAMBAHAN APAPUN.

Transkrip mentah:
{raw_text}"""

        # 9Router menuntut prefiks penyedia (mis. `ag/`) pada nama model. Nama tanpa
        # garis miring ditolak, jadi lengkapi di sini alih-alih memaksa user menulisnya.
        gem_model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip()
        if "/" not in gem_model:
            gem_model = f"ag/{gem_model}"

        response = client.chat.completions.create(
            model=gem_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=2048,
        )
        corrected = (response.choices[0].message.content or "").strip()
        if not corrected:
            logger.warning("Koreksi trilingual mengembalikan teks kosong — pakai teks asli.")
            return raw_text, "empty"

        # Penjaga kewarasan: model yang "terlalu rajin" bisa memotong atau mengarang.
        # Kalau panjangnya berubah drastis, teks asli lebih aman dipakai daripada
        # teks bersih yang isinya sudah bergeser dari ucapan aslinya.
        ratio = len(corrected.split()) / max(1, len(raw_text.split()))
        if ratio < 0.5 or ratio > 1.8:
            logger.warning(
                "Koreksi trilingual ditolak: jumlah kata berubah %.2fx (%d -> %d).",
                ratio, len(raw_text.split()), len(corrected.split()),
            )
            return raw_text, f"rejected_ratio_{ratio:.2f}"

        logger.info(
            "Koreksi trilingual sukses (%d -> %d kata).",
            len(raw_text.split()), len(corrected.split()),
        )
        return corrected, "success"

    except Exception as e:
        logger.error("Koreksi trilingual gagal: %s", e)
        return raw_text, f"failed: {e}"


def transcribe_clip_whisperx(
    input_path: Path,
    cc_text: str,
    language: str = "id",
    alignment_model: str = "cahya/wav2vec2-large-xlsr-indonesian",
) -> tuple[list[dict[str, Any]], str, int, int]:
    """Run WhisperX forced alignment on a clip using CC text as reference.

    This is the PRIMARY transcription path for Stage 4.
    WhisperX ASR is NOT used — only forced alignment with CC text.

    Args:
        input_path: Path to the video file.
        cc_text: Full CC transcript text for this clip (localized).
        language: Language code (default: Indonesian).
        alignment_model: Wav2Vec2 alignment model name.

    Returns:
        Tuple of (words, alignment_model_used, aligned_count, fallback_count).
        Returns empty list on failure.
    """
    cache_path = _get_whisperx_cache_path(input_path, alignment_model)

    # Check cache first
    if _is_whisperx_cache_valid(cache_path, input_path):
        logger.info("Using cached WhisperX alignment for: %s", input_path.name)
        try:
            cache_data = json.loads(cache_path.read_text(encoding="utf-8"))
            return (
                cache_data["words"],
                cache_data.get("alignment_model", alignment_model),
                cache_data.get("aligned_word_count", 0),
                cache_data.get("alignment_fallback_count", 0),
            )
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("WhisperX cache corrupted for %s: %s", input_path.name, e)

    # Extract audio to temporary WAV file
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_audio:
        audio_path = Path(tmp_audio.name)

    try:
        if not _extract_audio_for_whisperx(input_path, audio_path):
            return [], alignment_model, 0, 0

        # Run WhisperX forced alignment
        words = _run_whisperx_alignment(
            audio_path,
            cc_text,
            language=language,
            alignment_model=alignment_model,
        )

        if not words:
            logger.error("WhisperX alignment produced no words for %s", input_path.name)
            return [], alignment_model, 0, 0

        # Count aligned vs fallback words (WhisperX marks unaligned with start=end=0 or similar)
        aligned_count = sum(1 for w in words if w.get("end", 0) > w.get("start", 0))
        fallback_count = len(words) - aligned_count

        # Cache the result
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_data = {
            "input_path": str(input_path),
            "input_mtime": input_path.stat().st_mtime,
            "alignment_model": alignment_model,
            "language": language,
            "word_count": len(words),
            "aligned_word_count": aligned_count,
            "alignment_fallback_count": fallback_count,
            "words": words,
        }
        cache_path.write_text(json.dumps(cache_data, ensure_ascii=False, indent=2), encoding="utf-8")

        logger.info(
            "WhisperX aligned %d words (%d aligned, %d fallback) for: %s",
            len(words), aligned_count, fallback_count, input_path.name,
        )
        return words, alignment_model, aligned_count, fallback_count

    finally:
        # Clean up temp audio file
        try:
            audio_path.unlink(missing_ok=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Deterministic grouping (fallback and primary)
# ---------------------------------------------------------------------------


def _end_of(word: dict[str, Any], fallback: float) -> float:
    """Waktu akhir sebuah kata, aman terhadap `end: None`.

    WhisperX bisa mengembalikan kata tanpa timestamp (mis. token yang gagal di-align).
    `dict.get("end", fallback)` TIDAK menolong di kasus itu: kuncinya ADA, isinya None,
    jadi nilai None yang diteruskan lalu meledak di `group["end"] - group["start"]`.
    Bug ini muncul setelah `subtitle_target_words` jadi 1 (2026-08-30): dengan target 1
    setiap kata langsung menjadi grup, sehingga kata bertimestamp None pasti sampai ke
    perhitungan durasi — sebelumnya sering tertutup karena tergabung dengan kata lain.
    """
    v = word.get("end")
    if v is None:
        v = word.get("start")
    return float(fallback if v is None else v)


def group_deterministically(
    words: list[dict[str, Any]],
    target_words: int = _TARGET_WORDS,
    min_duration: float = _MIN_SUBTITLE_DURATION,
    max_duration: float = _MAX_SUBTITLE_DURATION,
) -> list[dict[str, Any]]:
    """Deterministic grouping based on WhisperX word timestamps.

    Groups words into chunks respecting:
    - Target word count (default: 4)
    - Minimum duration (default: 0.5s)
    - Maximum duration (default: 6.0s)
    - Natural speech boundaries (pauses > 0.3s)

    Args:
        words: Word-level transcript from WhisperX alignment.
        target_words: Target words per group.
        min_duration: Minimum display duration in seconds.
        max_duration: Maximum display duration in seconds.

    Returns:
        List of group dicts with 'words', 'start', 'end', 'text', 'emphasis'.
    """
    if not words:
        return []

    groups = []
    current_group: list[dict[str, Any]] = []
    current_start = 0.0
    current_end = 0.0

    for i, word in enumerate(words):
        word_start = word.get("start", 0.0)
        if word_start is None:
            word_start = 0.0
        word_end = word.get("end", word_start + 0.1)
        if word_end is None:
            word_end = word_start + 0.1
        word_text = word.get("word", "").strip()

        if not word_text:
            continue

        # Check for natural pause (gap > 0.3s between words)
        has_pause = False
        if current_group and len(current_group) >= 2:
            prev_word = current_group[-1]
            prev_end = prev_word.get("end")
            if prev_end is not None and word_start - prev_end > 0.3:
                has_pause = True

        # Start new group if:
        # 1. We have a natural pause (only if already 2+ words)
        # 2. Current group is too long (> max_duration)
        # 3. Current group has reached target word count (hard limit)
        should_start_new = (
            has_pause
            or (current_group and (word_end - current_start) > max_duration)
            or (len(current_group) >= target_words)
        )

        if should_start_new and current_group:
            # Finalize current group
            group_end = _end_of(current_group[-1], word_start)
            group_text = " ".join(w.get("word", "") for w in current_group if w.get("word"))
            groups.append({
                "words": [w.get("word", "") for w in current_group if w.get("word")],
                "start": current_start,
                "end": group_end,
                "text": group_text,
                "emphasis": False,
            })
            current_group = []
            current_start = word_start

        current_group.append(word)
        current_end = word_end

    # Finalize last group
    if current_group:
        group_end = _end_of(current_group[-1], current_start)
        group_text = " ".join(w.get("word", "") for w in current_group if w.get("word"))
        groups.append({
            "words": [w.get("word", "") for w in current_group if w.get("word")],
            "start": current_start,
            "end": group_end,
            "text": group_text,
            "emphasis": False,
        })

    # Apply duration constraints
    final_groups = []
    for group in groups:
        duration = group["end"] - group["start"]

        # Skip groups that are too short - but ONLY if they have fewer words than target
        # and the previous group also hasn't reached target word count
        if duration < min_duration * 0.5 and len(group["words"]) < target_words:
            # Only merge if previous group also has fewer words than target
            should_merge = False
            if final_groups and len(final_groups[-1]["words"]) < target_words:
                prev = final_groups[-1]
                prev["end"] = group["end"]
                prev["text"] += " " + group["text"]
                prev["words"].extend(group["words"])
                should_merge = True
            if not should_merge:
                final_groups.append(group)
            continue

        # Cap duration at max
        if duration > max_duration:
            group["end"] = group["start"] + max_duration

        final_groups.append(group)

    logger.info("Deterministic grouping produced %d subtitle groups", len(final_groups))
    return final_groups


# ---------------------------------------------------------------------------
# Timestamp validation
# ---------------------------------------------------------------------------


def validate_subtitle_groups(
    groups: list[dict[str, Any]],
    video_duration: float,
    words: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate subtitle groups against WhisperX words and video duration.

    Args:
        groups: Subtitle groups to validate.
        video_duration: Total video duration in seconds.
        words: Original word-level transcript from WhisperX.

    Returns:
        Tuple of (validated_groups, error_messages).
    """
    errors = []
    validated = []

    # Build word timeline for validation
    word_timeline = [(w["start"], w["end"], w["word"]) for w in words if w.get("word")]

    for i, group in enumerate(groups):
        start = group.get("start", 0.0)
        end = group.get("end", 0.0)
        text = group.get("text", "")
        group_words = group.get("words", [])

        # Validate start >= 0
        if start < 0:
            errors.append(f"Group {i+1}: negative start time {start}")
            continue

        # Validate end > start
        if end <= start:
            errors.append(f"Group {i+1}: end ({end}) not greater than start ({start})")
            continue

        # Validate end <= video duration (with small tolerance)
        if end > video_duration + 0.1:
            errors.append(f"Group {i+1}: end ({end}) exceeds video duration ({video_duration})")
            end = video_duration

        # Validate all words in group exist in transcript
        transcript_words = [w[2] for w in word_timeline]
        group_text_normalized = text.lower().replace(",", "").replace(".", "").replace("!", "").replace("?", "")
        transcript_text_normalized = " ".join(transcript_words).lower().replace(",", "").replace(".", "").replace("!", "").replace("?", "")

        # Check that group text is contained in transcript
        if group_text_normalized and group_text_normalized not in transcript_text_normalized:
            errors.append(f"Group {i+1}: text '{text}' not found in transcript")
            continue

        # Check for overlaps with previous group
        if validated:
            prev_end = validated[-1]["end"]
            if start < prev_end - 0.05:  # Allow small tolerance
                # Shift start to avoid overlap
                start = prev_end
                group["start"] = start

        validated.append(group)

    if errors:
        logger.warning("Found %d validation errors", len(errors))
        for err in errors[:5]:  # Log first 5 errors
            logger.warning("  %s", err)

    return validated, errors


# ---------------------------------------------------------------------------
# SRT generation
# ---------------------------------------------------------------------------


def _format_srt_timestamp(seconds: float) -> str:
    """Format seconds as SRT timestamp (HH:MM:SS,mmm).

    Args:
        seconds: Time in seconds.

    Returns:
        Formatted timestamp string.
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def generate_srt(groups: list[dict[str, Any]]) -> str:
    """Generate SRT format subtitle string.

    Args:
        groups: Validated subtitle groups.

    Returns:
        SRT formatted string.
    """
    if not groups:
        return ""

    srt_lines = []
    for i, group in enumerate(groups, 1):
        start = group.get("start", 0.0)
        end = group.get("end", 0.0)
        text = group.get("text", "")

        srt_lines.append(str(i))
        srt_lines.append(f"{_format_srt_timestamp(start)} --> {_format_srt_timestamp(end)}")
        srt_lines.append(text)
        srt_lines.append("")  # Empty line between entries

    return "\n".join(srt_lines)


# ---------------------------------------------------------------------------
# Output generation
# ---------------------------------------------------------------------------


def write_subtitle_files(
    output_dir: Path,
    clip_entry: ClipManifestEntry,
    groups: list[dict[str, Any]],
) -> Path | None:
    """Write SRT file for a clip.

    Args:
        output_dir: Stage 2 output directory.
        clip_entry: Clip manifest entry.
        groups: Validated subtitle groups.

    Returns:
        Path to the SRT file, or None if not generated.
    """
    clip_path = Path(clip_entry.output_path)
    base_name = clip_path.stem
    srt_path = output_dir / f"{base_name}.srt"

    srt_content = generate_srt(groups)
    if srt_content:
        srt_path.write_text(srt_content, encoding="utf-8")
        logger.info("Wrote SRT: %s", srt_path.name)
        return srt_path

    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run(
    manifest_path: Path | None = None,
    video_id: str | None = None,
    force: bool = False,
    lang_tags: str | list[str] | tuple[str, ...] | None = None,
) -> None:
    """Run Stage 4: generate subtitles for all clips using WhisperX forced alignment.

    Args:
        manifest_path: Explicit path to Stage 2 manifest. If None, finds latest.
        video_id: Optional YouTube video ID to filter.
        force: If True, re-align and regenerate even if outputs exist.
        lang_tags: Tag bahasa ("id,su" atau ["id","su"]) untuk merakit initial_prompt
            ASR fallback. TIDAK dipakai sebagai `language=` — lihat larangan di blok
            komentar `_ALIGNMENT_LANGUAGE`. Daftar kosong jatuh ke ["id"].
    """
    _setup_logging()
    _ensure_dirs()

    # Tag bahasa dinormalkan sekali di awal supaya seluruh klip memakai daftar yang sama
    # dan daftar kosong tidak pernah lolos ke bawah.
    active_lang_tags = parse_lang_tags(
        lang_tags if lang_tags is not None else _LANG_TAGS_DEFAULT_RAW
    )

    logger.info("=" * 60)
    logger.info("[4/5] STAGE 4: SMART SUBTITLE GENERATION (WhisperX)")
    logger.info(
        "Lang tags: %s (initial_prompt saja) | language= tetap '%s' | VAD: ON",
        ",".join(active_lang_tags), _ALIGNMENT_LANGUAGE,
    )
    logger.info("=" * 60)

    # Load Stage 2 manifest
    try:
        manifest = load_stage2_manifest(manifest_path)
    except FileNotFoundError as e:
        logger.error(str(e))
        raise

    video_id_used = manifest.video_id
    video_title = manifest.video_title
    creator = manifest.creator
    output_dir = Path(manifest.output_directory)

    logger.info(
        "Video ID: %s | Title: %s | Creator: %s | Clips to process: %d",
        video_id_used, video_title, creator or "(unknown)", len(manifest.clips),
    )

    # Prepare jobs
    source_clips = [c for c in manifest.clips if c.status in ("success", "skipped") and c.output_path]
    if not source_clips:
        raise RuntimeError("No successfully downloaded clips found in Stage 2 manifest.")

    jobs: list[SubtitleJob] = []
    successful = 0
    failed = 0

    # Versi WhisperX untuk manifest. Dibaca dari METADATA paket saja — tanpa
    # `import whisperx`. Alasannya: whisperx dipasang di `.whisperx-venv`, bukan di
    # `.venv` yang menjalankan Stage 4, jadi import-nya selalu gagal di sini dan
    # membuat versi tercatat "unknown" walau paketnya ada.
    whisperx_version = "unknown"
    try:
        import importlib.metadata
        whisperx_version = importlib.metadata.version("whisperx")
    except Exception:
        whisperx_version = "unknown"

    # Default Indonesian alignment model
    alignment_model = "cahya/wav2vec2-large-xlsr-indonesian"

    for idx, clip in enumerate(source_clips, start=1):
        input_path = Path(clip.output_path)
        clip_id = clip.clip_id

        logger.info(
            "[%d/%d] Processing Clip %d / Source: %s",
            idx, len(source_clips), clip_id, input_path.name,
        )

        # Check if SRT already exists (skip if valid)
        base_name = Path(input_path).stem
        srt_path = output_dir / f"{base_name}.srt"

        if not force and srt_path.exists():
            logger.info("Clip %d: SRT already exists, skipping.", clip_id)
            jobs.append(SubtitleJob(
                clip_id=clip_id,
                input_file=str(input_path),
                srt_file=str(srt_path),
                whisper_model=_WHISPER_MODEL,
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
                whisperx_version=whisperx_version,
                alignment_model="",
                aligned_word_count=0,
                alignment_fallback_count=0,
            ))
            successful += 1
            continue

        # NEW ARCHITECTURE: CC text + WhisperX forced alignment → Python grouping → validation
        transcript_source = "unknown"
        youtube_caption_language = ""
        youtube_caption_type = ""
        whisper_used = False
        whisper_purpose = "not_used"
        whisperx_used = False
        words: list[dict[str, Any]] = []
        cc_segments = []
        aligned_word_count = 0
        alignment_fallback_count = 0

        # Check Stage 1 transcript cache for CC text
        stage1_cache = load_stage1_transcript_cache(video_id_used)
        if stage1_cache is not None:
            source = stage1_cache.get("source", "")
            segments = stage1_cache.get("segments", [])
            language = stage1_cache.get("language", "")

            if source in ("youtube_manual", "youtube_auto") and segments:
                # Use YouTube CC transcript — filter to clip range and localize
                # `_parse_time` (bukan `parse_time`): di modul ini utils diimpor lewat
                # `_lazy_utils()` dan hanya nama ber-underscore yang ada di global.
                # `parse_time` bare = NameError, dan jalur ini baru tereksekusi kalau
                # Stage 1 punya cache CC YouTube — jadi bug-nya lolos sampai tes
                # integrasi CC dijalankan.
                clip_start = _parse_time(clip.start_time)
                clip_end = _parse_time(clip.end_time)
                cc_segments = _filter_and_localize_cc_segments(
                    segments, clip_start, clip_end,
                )
                transcript_source = source
                youtube_caption_language = language
                youtube_caption_type = "manual" if source == "youtube_manual" else "auto"
                logger.info(
                    "Clip %d: Found YouTube CC transcript (%s, %s, %d/%d segs, clip %ds-%ds)",
                    clip_id, source, language, len(cc_segments), len(segments),
                    clip_start, clip_end,
                )

        # Build full CC text for this clip (concatenate all filtered segments)
        cc_text = " ".join(seg.get("text", "") for seg in cc_segments).strip()

        # PRIORITAS SUMBER TRANSKRIP (rencana_perbaikan_subtitle.txt poin 3):
        #   1. CC YouTube (manual/auto) — Google ASR paling kuat di bahasa daerah.
        #   2. Fallback ASR faster-whisper lokal + parameter anti-looping.
        # Sebelumnya klip tanpa CC langsung DIGAGALKAN tanpa subtitle sama sekali.
        if not cc_text:
            logger.warning(
                "Clip %d: Tidak ada CC YouTube — beralih ke ASR faster-whisper.", clip_id,
            )
            cc_text = transcribe_clip_asr(
                input_path,
                language=_ALIGNMENT_LANGUAGE,
                lang_tags=active_lang_tags,
            )
            if cc_text:
                transcript_source = "whisper_asr"
                whisper_used = True
                whisper_purpose = "asr_fallback"

        if not cc_text:
            logger.error(
                "Clip %d: CC YouTube tidak ada DAN ASR gagal — dilewati.", clip_id,
            )
            jobs.append(SubtitleJob(
                clip_id=clip_id,
                input_file=str(input_path),
                srt_file=None,
                whisper_model=_WHISPER_MODEL,
                transcript_source="failed",
                whisper_used=whisper_used,
                whisper_purpose=whisper_purpose,
                youtube_caption_language=youtube_caption_language,
                youtube_caption_type=youtube_caption_type,
                word_count=0,
                subtitle_group_count=0,
                gemini_status="not_used",
                fallback_used=False,
                validation_status="skipped",
                status="failed",
                error_message="Tidak ada teks transkrip: CC YouTube kosong dan ASR gagal.",
                whisperx_used=False,
                whisperx_version=whisperx_version,
                alignment_model=alignment_model,
                aligned_word_count=0,
                alignment_fallback_count=0,
            ))
            failed += 1
            continue

        # Koreksi teks trilingual (Indo + Sunda + Inggris) SEBELUM forced alignment.
        # Urutannya penting: teks yang sudah bersih itulah yang di-align ke audio, jadi
        # detik per kata mengikuti kata yang benar. Membersihkan SETELAH alignment akan
        # merusak pemetaan waktu.
        cc_text, gemini_status = correct_text_trilingual(cc_text, video_title)
        if gemini_status == "success":
            logger.info("Clip %d: teks dibersihkan oleh koreksi trilingual.", clip_id)

        # Run WhisperX forced alignment with CC text as reference
        logger.info("Clip %d: Running WhisperX forced alignment...", clip_id)
        words, model_used, aligned_count, fallback_count = transcribe_clip_whisperx(
            input_path,
            cc_text,
            language=youtube_caption_language or "id",
            alignment_model=alignment_model,
        )

        if not words:
            logger.error("Clip %d: WhisperX forced alignment failed, skipping.", clip_id)
            jobs.append(SubtitleJob(
                clip_id=clip_id,
                input_file=str(input_path),
                srt_file=None,
                whisper_model=_WHISPER_MODEL,
                transcript_source=transcript_source,
                whisper_used=False,
                whisper_purpose="failed",
                youtube_caption_language=youtube_caption_language,
                youtube_caption_type=youtube_caption_type,
                word_count=0,
                subtitle_group_count=0,
                gemini_status="not_used",
                fallback_used=False,
                validation_status="skipped",
                status="failed",
                error_message="WhisperX forced alignment failed.",
                whisperx_used=False,
                whisperx_version=whisperx_version,
                alignment_model=alignment_model,
                aligned_word_count=0,
                alignment_fallback_count=0,
            ))
            failed += 1
            continue

        whisperx_used = True
        aligned_word_count = aligned_count
        alignment_fallback_count = fallback_count
        transcript_source = f"{transcript_source}_whisperx_aligned"
        # Peran Whisper di klip ini. Kalau teksnya datang dari CC YouTube, Whisper hanya
        # dipakai untuk waktu per kata. Kalau CC tidak ada, ia juga jadi sumber TEKS —
        # bedanya penting saat menelusuri kualitas subtitle dari manifest.
        whisper_purpose = (
            "asr_fallback+word_timing" if whisper_purpose == "asr_fallback" else "word_timing"
        )

        # Deterministic grouping (primary path — no Gemini required)
        logger.info("Clip %d: Running deterministic grouping...", clip_id)
        groups = group_deterministically(words)

        # Step 5: Get video duration for validation
        video_duration = clip.actual_duration or 0.0
        if video_duration <= 0:
            try:
                result = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", str(input_path)],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                video_duration = float(result.stdout.strip())
            except Exception:
                video_duration = 0.0

        # Step 6: Validate groups
        validated_groups, validation_errors = validate_subtitle_groups(
            groups, video_duration, words
        )

        validation_status = "validation_passed" if not validation_errors else "validation_failed"
        if validation_errors:
            logger.warning("Clip %d: %d validation errors", clip_id, len(validation_errors))

        if not validated_groups:
            logger.error("Clip %d: No valid subtitle groups after validation", clip_id)
            jobs.append(SubtitleJob(
                clip_id=clip_id,
                input_file=str(input_path),
                srt_file=None,
                whisper_model=_WHISPER_MODEL,
                transcript_source=transcript_source,
                whisper_used=whisper_used,
                whisper_purpose=whisper_purpose,
                youtube_caption_language=youtube_caption_language,
                youtube_caption_type=youtube_caption_type,
                word_count=len(words),
                subtitle_group_count=0,
                gemini_status=gemini_status,
                fallback_used=False,
                validation_status="validation_failed",
                status="failed",
                error_message="No valid subtitle groups after validation.",
                whisperx_used=whisperx_used,
                whisperx_version=whisperx_version,
                alignment_model=model_used,
                aligned_word_count=aligned_word_count,
                alignment_fallback_count=alignment_fallback_count,
            ))
            failed += 1
            continue

        # Step 7: Write SRT file
        srt_path = write_subtitle_files(output_dir, clip, validated_groups)

        if srt_path is None or not srt_path.exists():
            logger.error("Clip %d: Failed to write subtitle files", clip_id)
            jobs.append(SubtitleJob(
                clip_id=clip_id,
                input_file=str(input_path),
                srt_file=None,
                whisper_model=_WHISPER_MODEL,
                transcript_source=transcript_source,
                whisper_used=whisper_used,
                whisper_purpose=whisper_purpose,
                youtube_caption_language=youtube_caption_language,
                youtube_caption_type=youtube_caption_type,
                word_count=len(words),
                subtitle_group_count=len(validated_groups),
                gemini_status=gemini_status,
                fallback_used=False,
                validation_status=validation_status,
                status="failed",
                error_message="Failed to write subtitle files.",
                whisperx_used=whisperx_used,
                whisperx_version=whisperx_version,
                alignment_model=model_used,
                aligned_word_count=aligned_word_count,
                alignment_fallback_count=alignment_fallback_count,
            ))
            failed += 1
            continue

        logger.info(
            "Clip %d / Status: success | Source: %s | Groups: %d | Words: %d | "
            "Aligned: %d | Fallback: %d | WhisperX: %s",
            clip_id, transcript_source, len(validated_groups), len(words),
            aligned_word_count, alignment_fallback_count, whisperx_used,
        )

        jobs.append(SubtitleJob(
            clip_id=clip_id,
            input_file=str(input_path),
            srt_file=str(srt_path),
            whisper_model=_WHISPER_MODEL,
            transcript_source=transcript_source,
            whisper_used=whisper_used,
            whisper_purpose=whisper_purpose,
            youtube_caption_language=youtube_caption_language,
            youtube_caption_type=youtube_caption_type,
            word_count=len(words),
            subtitle_group_count=len(validated_groups),
            gemini_status=gemini_status,
            fallback_used=False,
            validation_status=validation_status,
            status="success",
            whisperx_used=whisperx_used,
            whisperx_version=whisperx_version,
            alignment_model=model_used,
            aligned_word_count=aligned_word_count,
            alignment_fallback_count=alignment_fallback_count,
        ))
        successful += 1

    # Write subtitle manifest
    manifest_data = {
        "video_id": video_id_used,
        "video_title": video_title,
        "creator": creator,
        "source_directory": str(output_dir),
        "whisper_model": _WHISPER_MODEL,
        "whisperx_version": whisperx_version,
        "alignment_model": alignment_model,
        "total_clips": len(source_clips),
        "successful": successful,
        "failed": failed,
        "jobs": [j.model_dump() for j in jobs],
    }

    manifest_out_path = output_dir / "subtitle_manifest.json"
    manifest_out_path.write_text(
        json.dumps(manifest_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Wrote subtitle manifest: %s", manifest_out_path)

    # Summary
    logger.info("=" * 60)
    logger.info("STAGE 4 COMPLETE")
    logger.info("Successful: %d | Failed: %d", successful, failed)
    logger.info("Output directory: %s", output_dir)

    if failed == len(source_clips):
        raise RuntimeError(f"All {failed} clips failed to generate subtitles.")


# ---------------------------------------------------------------------------
# CLI entry point (called by stage4_batch.py)
# ---------------------------------------------------------------------------


def video_id_from_url(url: str) -> str:
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", url)
    if not m:
        raise ValueError(f"Could not extract YouTube video ID from: {url}")
    return m.group(1)


def raw_transcript_items(video_id: str) -> list[dict[str, Any]]:
    """Fetch Indonesian YouTube CC, compatible with current/older API shapes."""
    try:
        from youtube_transcript_api import TranscriptsDisabled
    except ImportError:
        TranscriptsDisabled = Exception
    api = YouTubeTranscriptApi()
    try:
        fetched = api.fetch(video_id, languages=["id", "id-ID", "en", "en-US"])
    except TranscriptsDisabled:
        return []
    except Exception:
        try:
            fetched = api.fetch(video_id)
        except TranscriptsDisabled:
            return []

    if hasattr(fetched, "to_raw_data"):
        raw = fetched.to_raw_data()
    elif hasattr(fetched, "snippets"):
        raw = [
            {
                "start": float(s.start),
                "duration": float(getattr(s, "duration", 0.0)),
                "text": str(s.text),
            }
            for s in fetched.snippets
        ]
    elif isinstance(fetched, list):
        raw = fetched
    else:
        raise RuntimeError("Unsupported YouTube transcript object.")

    return [
        {
            "start": float(item.get("start", 0.0)),
            "duration": float(item.get("duration", 0.0)),
            "text": str(item.get("text", "")).replace("\n", " ").strip(),
        }
        for item in raw
        if str(item.get("text", "")).strip()
    ]


def clip_cc_segments(
    items: list[dict[str, Any]], clip_start: float, clip_end: float
) -> list[dict[str, Any]]:
    """
    Keep CC segments overlapping the logical clip range.
    Rebase timestamps from source-video time to Stage-2 clip-local time.
    """
    result = []
    for item in items:
        start = item["start"]
        end = start + max(0.0, item["duration"])

        if end <= clip_start or start >= clip_end:
            continue

        local_start = max(start, clip_start) - clip_start
        local_end = min(end, clip_end) - clip_start
        if local_end <= local_start:
            local_end = local_start + 0.05

        result.append(
            {
                "start": local_start,
                "end": local_end,
                "text": item["text"],
            }
        )

    # Repair zero/overlapping boundaries using the following segment where possible.
    for i in range(len(result) - 1):
        if result[i]["end"] <= result[i + 1]["start"]:
            continue
        midpoint = (result[i]["end"] + result[i + 1]["start"]) / 2.0
        result[i]["end"] = max(result[i]["start"] + 0.05, midpoint)
        result[i + 1]["start"] = min(result[i + 1]["end"] - 0.05, midpoint)

    return result


def clean_word(word: str) -> str:
    return re.sub(r"\s+", " ", str(word)).strip()


def fmt_srt(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    ms = int(round((seconds - int(seconds)) * 1000))
    whole = int(seconds)
    if ms >= 1000:
        whole += 1
        ms = 0
    h = whole // 3600
    m = (whole % 3600) // 60
    s = whole % 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def make_srt(
    words: list[dict[str, Any]],
    output_path: Path,
    max_words: int = 7,
    max_chars: int = 42,
    max_duration: float = 3.5,
) -> int:
    """
    Deterministic subtitle grouping from WhisperX word timestamps.
    Text comes from the aligned CC words; timestamps come from WhisperX.
    """
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []

    def flush():
        nonlocal current
        if current:
            groups.append(current)
            current = []

    for raw in words:
        text = clean_word(raw.get("word", ""))
        if not text:
            continue
        w = {
            "word": text,
            "start": float(raw["start"]),
            "end": float(raw["end"]),
        }

        if not current:
            current = [w]
            continue

        candidate_text = " ".join(x["word"] for x in current + [w])
        candidate_duration = w["end"] - current[0]["start"]

        previous = current[-1]["word"]
        sentence_break = bool(re.search(r"[.!?…]$", previous))

        if (
            len(current) >= max_words
            or len(candidate_text) > max_chars
            or candidate_duration > max_duration
            or sentence_break
        ):
            flush()
            current = [w]
        else:
            current.append(w)

    flush()

    # Merge very tiny trailing groups where safe.
    merged: list[list[dict[str, Any]]] = []
    for group in groups:
        if (
            merged
            and len(group) <= 2
            and len(merged[-1]) + len(group) <= max_words
            and group[0]["start"] - merged[-1][-1]["end"] < 0.8
        ):
            candidate = merged[-1] + group
            text = " ".join(x["word"] for x in candidate)
            duration = candidate[-1]["end"] - candidate[0]["start"]
            if len(text) <= max_chars and duration <= max_duration:
                merged[-1] = candidate
                continue
        merged.append(group)

    with output_path.open("w", encoding="utf-8") as f:
        for idx, group in enumerate(merged, 1):
            start = group[0]["start"]
            end = max(group[-1]["end"], start + 0.05)
            text = " ".join(x["word"] for x in group)
            f.write(f"{idx}\n{fmt_srt(start)} --> {fmt_srt(end)}\n{text}\n\n")

    return len(merged)


def _run_cli() -> None:
    """Single-clip CLI: --video + --youtube-url + --start + --end."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate clip-local SRT from YouTube CC using WhisperX forced alignment."
    )
    parser.add_argument("--video", required=True, help="Stage 2 MP4 path")
    parser.add_argument("--youtube-url", required=True, help="Original YouTube URL")
    parser.add_argument("--start", required=True, help="Logical clip start in source video")
    parser.add_argument("--end", required=True, help="Logical clip end in source video")
    parser.add_argument("--output", help="Optional SRT path; default is next to MP4")
    parser.add_argument(
        "--target-words",
        type=int,
        default=None,
        help="Kata per baris subtitle di SRT. Default dari settings.subtitle_target_words "
             "(3). Stage 5 bisa memecah LEBIH HALUS saat render tapi tidak bisa "
             "menggabungkan kembali, jadi nilai di sini adalah batas terkasar.",
    )
    parser.add_argument(
        "--lang-tags",
        default=None,
        help="Tag bahasa dipisah koma untuk initial_prompt WhisperX, mis. 'id,su' atau "
             "'id,su,en'. Default 'id'. HANYA memengaruhi initial_prompt — parameter "
             "language= transkripsi TETAP 'id' karena whisperx tidak punya model "
             "forced-alignment untuk 'su'.",
    )
    args = parser.parse_args()

    # Tag bahasa dinormalkan sekali di sini; daftar kosong jatuh ke ["id"].
    lang_tags = parse_lang_tags(
        args.lang_tags if args.lang_tags is not None else _LANG_TAGS_DEFAULT_RAW
    )
    initial_prompt = build_initial_prompt(lang_tags)

    # Batas aman: 0/negatif akan membuat make_srt menghasilkan grup kosong.
    target_words = int(args.target_words or _TARGET_WORDS)
    if target_words < 1:
        raise ValueError(f"--target-words minimal 1 (diberi {target_words})")

    video_path = Path(args.video).resolve()
    if not video_path.exists():
        raise FileNotFoundError(video_path)

    clip_start = _parse_time(args.start)
    clip_end = _parse_time(args.end)
    if clip_end <= clip_start:
        raise ValueError("Clip end must be greater than clip start.")

    output_path = (
        Path(args.output).resolve()
        if args.output
        else video_path.with_suffix(".srt")
    )

    # .env dimuat sebelum header dicetak supaya baris "Gemini: ON/OFF" jujur.
    # Tanpa ini header selalu menulis OFF di jalur .whisperx-venv (os.environ kosong),
    # padahal koreksinya nanti tetap jalan — bikin salah baca saat menonton log.
    try:
        from dotenv import load_dotenv

        load_dotenv(_PROJECT_ROOT / ".env")
    except ImportError:
        pass

    print("=== CLIPPER WHISPERX SRT ===")
    print(f"MP4:        {video_path}")
    print(f"Source:     {args.youtube_url}")
    print(f"Clip range: {clip_start:.3f}s -> {clip_end:.3f}s")
    print(f"ASR:        faster-whisper ({_WHISPER_MODEL})")
    print(f"Lang tags:  {','.join(lang_tags)}  (initial_prompt saja; language= tetap '{_ALIGNMENT_LANGUAGE}')")
    print("VAD:        ON (Silero via faster-whisper vad_filter)")
    print(f"Gemini:     {'ON (koreksi trilingual)' if os.getenv('GEMINI_API_KEY') else 'OFF (GEMINI_API_KEY kosong)'}")
    print("Stage 3:    SKIPPED")
    print()

    video_id = video_id_from_url(args.youtube_url)
    print("[1/4] Transcribing with faster-whisper...")
    # Direct transcription - no YouTube CC dependency
    try:
        from faster_whisper import WhisperModel
        # Ukuran model dibaca dari settings (WHISPER_MODEL di .env), TIDAK dihardcode:
        # `small` sering salah dengar kosakata Sunda dan memicu looping pada audio
        # lapangan, dan model medium yang sudah diunduh jadi tidak terpakai.
        wm = _WHISPER_MODEL
        print(f"      Loading faster-whisper model ({wm})...")
        model = WhisperModel(wm, device="cpu", compute_type="int8")
        segments, info = model.transcribe(
            str(video_path), 
            # `language` TETAP "id" (_ALIGNMENT_LANGUAGE). Tag bahasa dari --lang-tags
            # TIDAK BOLEH masuk ke sini: whisperx tidak punya model forced-alignment
            # untuk 'su'/'jv', jadi kalau 'su' dipakai di sini alignment mati dan
            # timestamp per kata (fondasi SRT 1 kata/entri) hilang.
            language=_ALIGNMENT_LANGUAGE,
            beam_size=5,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            temperature=(0.0, 0.2, 0.4),
            # Item 24 3a: initial_prompt dari tag bahasa yang aktif — satu-satunya
            # tempat centang bahasa berpengaruh.
            initial_prompt=initial_prompt,
            # Item 24 3b: VAD Silero DIPASANG di sini juga. Jalur ini yang dipakai
            # stage4_batch.py di produksi; kalau hanya jalur transcribe_clip_asr()
            # yang diperbaiki, produksi tidak kebagian sama sekali (kelas bug
            # 'logika kembar' yang sudah pernah terjadi di file ini).
            vad_filter=True,
            vad_parameters=_VAD_PARAMETERS,
        )
        
        # Note: faster-whisper returns local timestamps (0 to clip_duration)
        # since we extracted just the clip in stage 2
        clip_segments = []
        for seg in segments:
            text = seg.text.strip()
            if text:
                clip_segments.append({
                    "start": seg.start,
                    "end": seg.end,
                    "text": text
                })
        print(f"      Segments transcribed: {len(clip_segments)}")
        print(f"      Detected language: {info.language} ({info.language_probability:.2f})")

        # Koreksi trilingual dipanggil dari fungsi bersama `correct_text_trilingual()`.
        # Sebelumnya jalur CLI ini punya salinan logikanya sendiri (~60 baris duplikat):
        # prompt, pemilihan model, dan penanganan error ditulis dua kali, sehingga
        # perbaikan pada fungsi bersama (mis. pemuatan .env dan proteksi rasio panjang)
        # tidak pernah sampai ke jalur yang dipakai stage4_batch.py.
        transcript_text = " ".join(seg["text"] for seg in clip_segments)

        video_title = "Unknown"
        try:
            manifest_path = find_stage2_manifest(video_id)
            if manifest_path:
                raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                video_title = raw_manifest.get("video_title", "Unknown")
        except Exception:
            pass

        cc_text_for_alignment, gemini_status = correct_text_trilingual(
            transcript_text, video_title,
        )
        print(f"      Koreksi trilingual: {gemini_status}")

    except Exception as e:
        print(f"      faster-whisper failed: {e}")
        raise RuntimeError(f"Transcription failed: {e}")
    print(f"[2/4] Segments in clip: {len(clip_segments)}")

    print("[3/4] Loading audio + Indonesian WhisperX alignment model...")
    import whisperx
    audio = whisperx.load_audio(str(video_path))
    model_a, metadata = whisperx.load_align_model(
        language_code="id",
        device="cpu",
    )

    # "start"/"end" WAJIB ada — whisperx 3.8.x membacanya langsung di alignment.py:210.
    # Lihat komentar di _run_whisperx_alignment() untuk alasan lengkapnya.
    transcript_segments = [{
        "text": cc_text_for_alignment,
        "start": 0.0,
        "end": len(audio) / 16000.0,
    }]

    print("      Running forced alignment (NO transcription)...")
    aligned = whisperx.align(
        transcript_segments,
        model_a,
        metadata,
        audio,
        "cpu",
        return_char_alignments=False,
        interpolate_method="nearest",
    )

    words = aligned.get("word_segments", [])
    if not words:
        raise RuntimeError("WhisperX returned zero word-level timestamps.")

    unaligned = [
        w for w in words
        if w.get("start") is None or w.get("end") is None
    ]
    words = [w for w in words if w.get("start") is not None and w.get("end") is not None]

    print(f"      Aligned words:   {len(words)}")
    print(f"      Unaligned words: {len(unaligned)}")
    print()
    print("      First 20 aligned words:")
    for w in words[:20]:
        print(f"        {w['start']:8.3f} -> {w['end']:8.3f}  {w['word']}")

    print()
    print(f"[4/4] Writing SRT: {output_path}")
    groups = make_srt(words, output_path, max_words=target_words)
    print(f"      Subtitle groups: {groups}")
    print()
    print("=== DONE ===")
    print(f"SRT: {output_path}")


def main():
    """Dual entry: batch mode (no args) or CLI single-clip mode."""
    import sys
    if len(sys.argv) > 1 and sys.argv[1].startswith("--"):
        _run_cli()
    else:
        run()


if __name__ == "__main__":
    main()