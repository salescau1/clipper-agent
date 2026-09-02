"""Central configuration for the Clipper pipeline.

All settings are loaded from environment variables (with sensible defaults)
so that no secrets or machine-specific paths are hardcoded in stage modules.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root is the directory containing this file (clipper/).
PROJECT_ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """Application settings, sourced from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Secrets (never hardcode) ---
    gemini_api_key: str = ""

    # --- LLM Provider (9Router / OpenAI-compatible) ---
    llm_base_url: str = "http://127.0.0.1:20128/v1"

    # --- Model selection ---
    gemini_model: str = "gemini-2.0-flash"
    # Model Whisper untuk transkripsi. Diisi dari WHISPER_MODEL di .env.
    # Default `medium`: `small` sering salah dengar kosakata Sunda dan memicu
    # looping/halusinasi pada audio lapangan (temuan tes KDM, lihat
    # rencana_perbaikan_subtitle.txt). CATATAN: field ini dulu ditulis DUA KALI di
    # kelas ini (di sini dan di bagian Subtitles); pydantic memakai yang terakhir,
    # jadi mengubah yang atas saja tidak berefek. Sekarang tinggal satu.
    whisper_model: str = "medium"
    # MAX klip: jumlah yang DIMINTA ke Gemini (Item 27). Ini batas ATAS pencarian,
    # sekaligus dasar perhitungan max_tokens jawaban di stage1_curate.
    target_clip_count: int = 5
    # MIN klip: ambang PERINGATAN saja, BUKAN jaminan (keputusan user C, 2026-09-03).
    # Yield Gemini tidak bisa dipaksa dan filter overlap 50% di
    # `validate_and_normalize_clips()` masih memotong lagi sesudahnya. Kalau hasil
    # kurang dari MIN, pipeline LANJUT dengan peringatan berangka — tanpa stop dan
    # tanpa retry otomatis (retry membuang 1 dari 20 request/hari DAN menimpa file
    # kurasi yang memuat pilihan review user).
    # 0 = tidak diset -> MIN mengikuti MAX (perilaku lama sebelum Item 27).
    min_clip_count: int = 0

    # --- Stage 1: batas durasi klip (detik) ---
    # Ini yang paling menentukan BERAPA BANYAK klip yang mungkin dihasilkan:
    # maksimum teoretis = durasi_video / clip_min_seconds. Video 14 menit dengan
    # minimal 60s mustahil menghasilkan 20 klip (maks 14, realistis ~7).
    # Turunkan clip_min_seconds kalau butuh banyak klip dari video pendek.
    clip_min_seconds: int = 60
    clip_max_seconds: int = 240

    # --- Directories (relative to project root) ---
    output_dir: Path = PROJECT_ROOT / "output"
    cache_dir: Path = PROJECT_ROOT / "cache"
    logs_dir: Path = PROJECT_ROOT / "logs"
    temp_dir: Path = PROJECT_ROOT / "temp"

    # --- Rendering ---
    target_height: int = 1080
    aspect_ratio: str = "9:16"
    lufs_target: str = "-14"
    bgm_volume: float = 0.08

    # --- Stage 3: Smart 9:16 Crop/Render ---
    output_width: int = 1080
    output_height: int = 1920
    crop_mode: str = "auto"  # auto, center, or face
    face_detection_sample_seconds: int = 2
    audio_target_lufs: str = "-14"

    # --- Subtitles ---
    subtitle_min_duration: float = 0.5
    subtitle_max_duration: float = 6.0
    # 1 kata per entri SRT (diubah dari 3 pada 2026-08-30).
    # Alasannya: kerapatan subtitle sekarang DIBAKUKAN di theme (Customize), dan
    # `stage5_final.regroup_entries()` bisa menggabungkan kata jadi 1/3/5 saat render.
    # Menggabungkan hanya akurat kalau sumbernya halus — SRT 1 kata memberi waktu per
    # kata yang NYATA dari alignment WhisperX, sedangkan SRT 3 kata memaksa waktu di
    # dalam entri ditebak proporsional. Jadi Stage 4 menulis sehalus mungkin SEKALI,
    # lalu theme menentukan tampilannya tanpa perlu menjalankan Stage 4 ulang
    # (~2 menit per klip).
    subtitle_target_words: int = 1

    # --- Download ---
    download_retries: int = 3
    download_retry_delay: float = 5.0
    video_max_height: int = 1080
    ytdlp_player_client: str = ""
    clip_end_buffer_seconds: int = 30

    # --- Transcript ---
    transcript_languages: list[str] = ["id", "id-ID", "en", "en-US"]

    # --- Stage 4: Preferred Languages (Item 24) ---
    # Daftar tag bahasa yang dipakai HANYA untuk merakit `initial_prompt` WhisperX
    # (kosakata Sunda/Inggris/Indo), supaya model tidak salah tebak bahasa daerah.
    # Default backend/CLI = ["id"] sesuai Item 24 ("default kalau tidak diberikan: id").
    # GUI mengirim centangnya sendiri secara eksplisit (`--lang-tags id,su`), jadi
    # nilai di sini hanya berlaku saat CLI dipakai tanpa `--lang-tags`.
    # Bisa ditimpa dari .env: SUBTITLE_LANG_TAGS=["id","su","en"]
    #
    # PERINGATAN: nilai ini TIDAK BOLEH diteruskan ke parameter `language=`
    # faster-whisper/whisperx. Model forced-alignment whisperx hanya punya 41 bahasa;
    # `id` dan `en` ada, `su` dan `jv` TIDAK ADA. Meneruskan `su` ke `language=`
    # mematikan forced alignment -> timestamp per kata hilang -> SRT 1 kata/entri
    # hancur -> kerapatan subtitle 1/3/5 kata di Theme kehilangan fondasinya.
    # Bahasa transkripsi TETAP "id" (lihat stage4_subtitles._ALIGNMENT_LANGUAGE).
    subtitle_lang_tags: list[str] = ["id"]

    @property
    def runtime_dirs(self) -> list[Path]:
        """Directories that must exist before the pipeline runs."""
        return [self.output_dir, self.cache_dir, self.logs_dir, self.temp_dir]


# Single shared settings instance. Import this everywhere.
settings = Settings()