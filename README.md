# Clipper

A simple, modular YouTube-to-short-video pipeline. It curates the best clips
from a YouTube video, downloads only the needed time ranges, renders them as
9:16 vertical videos, and burns in animated subtitles.

## Pipeline

```
YouTube URL
    │
    ▼
[Stage 1] Curate clips (transcript + Gemini)   → output/curation.json
    │
    ▼
[Stage 2] Download clip ranges (yt-dlp)        → output/clips/raw/
    │
    ▼
[Stage 3] Render 9:16 vertical (FFmpeg)        → output/clips/rendered/
    │
    ▼
[Stage 4] Burn subtitles (Whisper + ASS)       → output/clips/final/
```

## Requirements

- Python 3.11+
- [FFmpeg](https://ffmpeg.org/) on your PATH
- A Gemini API key (for Stage 1)

## Setup

```bash
cd clipper
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev]"
copy .env.example .env           # then edit .env with your API key
```

## Usage

Run the full pipeline:

```bash
python main.py run --url "https://youtu.be/..."
```

Run a single stage:

```bash
python main.py stage1 --url "https://youtu.be/..."
python main.py stage2
python main.py stage3
python main.py stage4
```

Validate configuration and dependencies:

```bash
python main.py doctor
```

## Configuration

All settings come from environment variables (see `.env.example`). No secrets
are hardcoded. Key variables:

| Variable            | Default            | Purpose                          |
|---------------------|--------------------|----------------------------------|
| `GEMINI_API_KEY`    | *(empty)*          | Gemini API key (Stage 1)         |
| `GEMINI_MODEL`      | `gemini-2.0-flash` | Gemini model for curation        |
| `WHISPER_MODEL`     | `small`            | Whisper model for STT            |
| `TARGET_HEIGHT`     | `1080`             | Vertical render height           |
| `YTDLP_PLAYER_CLIENT` | `android,ios`    | yt-dlp client spoofing           |

## Tests

```bash
pytest
```

## Project Layout

```
clipper/
├── main.py                 # CLI entry point & orchestration
├── config.py               # Central settings (env-driven)
├── models.py               # Pydantic data contracts between stages
├── utils.py                # Generic helpers (logging, time, ffmpeg, retry)
├── stages/
│   ├── stage1_curate.py
│   ├── stage2_download.py
│   ├── stage3_render.py
│   └── stage4_subtitles.py
└── tests/
```