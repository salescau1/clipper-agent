# Clipper Agent

Aplikasi desktop (PySide6) yang mengubah satu video YouTube menjadi beberapa klip
vertikal 9:16 bersubtitle, siap unggah ke Shorts/TikTok/Reels.

Dipakai lewat **GUI**. CLI tetap ada di baliknya (GUI memanggilnya), jadi setiap
tahap masih bisa dijalankan sendiri kalau perlu.

## Menjalankan

```powershell
.\run_clipper_gui.ps1
```

atau langsung:

```powershell
.\.venv\Scripts\python.exe .\clipper_gui.py
```

Tab yang tersedia: **Run** (jalankan pipeline), **Customize** (atur tampilan
output lalu simpan sebagai Theme), **History**, **Settings**.

## Alur pipeline

```
URL YouTube
    │
    ▼
[Stage 1] Kurasi klip (transkrip + LLM)      → output/<creator>/<judul>/<video_id>.json
    │
    ▼
[Stage 2] Unduh rentang klip (yt-dlp)        → output/<creator>/<judul>/*.mp4 + manifest.json
    │
    ▼
[Stage 3] DILEWATI (digantikan Stage 5)
    │
    ▼
[Stage 4] Subtitle (faster-whisper + WhisperX) → *.srt, 1 kata per entri
    │
    ▼
[Stage 5] Komposisi akhir 9:16 (FFmpeg)      → final/<creator>/<judul>/*.mp4 + caption.txt
```

Tiga hal yang menentukan cara kerja sistem ini:

- **Stage 4 menulis SRT 1 kata per entri.** Kerapatan tampilan (1/3/5 kata) diatur
  di Theme dan dirakit ulang saat render, jadi mengubah tampilan tidak perlu
  transkripsi ulang (~2 menit per klip).
- **Satu mesin teks untuk preview dan render.** Subtitle, headline, dan watermark
  semuanya digambar `stages/text_engine.py` (Pillow) — preview di Customize dan
  hasil MP4 adalah gambar yang sama, bukan dua pendekatan berbeda.
- **Setiap tahap resumable.** Statusnya = ada atau tidaknya berkas hasil. Jalankan
  ulang setelah gagal di tengah; yang sudah jadi di-SKIP.

## Dua virtualenv (penting)

| Venv | Dipakai untuk |
|---|---|
| `.venv` | GUI, CLI, Stage 1/2/5 |
| `.whisperx-venv` | **hanya Stage 4** — dijalankan sebagai subprocess |

Dependensi WhisperX bentrok dengan `.venv`, jadi keduanya sengaja dipisah.
Konsekuensinya: perubahan pada `stages/stage4_subtitles.py` harus diuji dengan
`.whisperx-venv/Scripts/python.exe`, karena itulah yang benar-benar menjalankannya
di produksi.

## Kebutuhan sistem

- Python 3.11+ (kedua venv sudah tersiapkan di folder ini)
- [FFmpeg](https://ffmpeg.org/) di PATH
- API key untuk kurasi Stage 1, diisi di `.env`
- Model WhisperX (~4,3 GB) diunduh otomatis ke `~/.cache/huggingface/hub` pada
  pemakaian pertama

## Konfigurasi

Semua setelan dibaca dari `.env` (contoh di `.env.example`). Tidak ada rahasia
yang ditulis di kode.

| Variabel | Default | Kegunaan |
|---|---|---|
| `GEMINI_API_KEY` | *(kosong)* | Kunci LLM untuk kurasi Stage 1 |
| `LLM_BASE_URL` | `http://127.0.0.1:20128/v1` | Endpoint OpenAI-compatible |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Model kurasi |
| `WHISPER_MODEL` | `medium` | Model transkripsi. Jangan turunkan ke `small` untuk audio Sunda/lapangan — sering salah dengar dan memicu looping |
| `SUBTITLE_LANG_TAGS` | `id` | Bantuan kosakata WhisperX (`id`, `su`, `en`) |
| `CLIP_MIN_SECONDS` | `60` | Durasi klip minimal |
| `CLIP_MAX_SECONDS` | `240` | Durasi klip maksimal |
| `YTDLP_PLAYER_CLIENT` | *(kosong)* | Spoofing klien yt-dlp |

### Jumlah klip: MIN dan MAX

Kolom `Klip` di tab Run adalah **rentang pencarian**, bukan jaminan:

- **MAX** = jumlah yang diminta ke LLM
- **MIN** = ambang peringatan. Kalau hasilnya kurang, pipeline **tetap lanjut**
  dengan peringatan berangka — tidak berhenti dan tidak mengulang otomatis

Alasannya hasil LLM tidak bisa dipaksa, dan filter tumpang-tindih 50% masih
memotong lagi sesudahnya. Batas atas yang benar-benar mengikat justru durasi
minimal: **maksimum klip = durasi video ÷ durasi minimal**. Video 15 menit dengan
minimal 60s mustahil menghasilkan 20 klip.

### Preferred Languages

Centang `ENGLISH / INDONESIA / SUNDANESE` di tab Run hanya menyusun *initial
prompt* (bantuan kosakata) untuk WhisperX. Bahasa transkripsi dan penyelarasan
timestamp **tetap Indonesia**: WhisperX tidak punya model forced-alignment untuk
bahasa Sunda, dan memaksanya akan menghilangkan timestamp per kata yang menjadi
fondasi SRT 1-kata.

## Kinerja

`.whisperx-venv` memakai torch versi **CPU**. Stage 4 karena itu berjalan sekitar
2,5x durasi audio. Terukur pada 10 klip (30,6 menit audio):

| Tahap | Waktu |
|---|---|
| Stage 2 unduh | 13 menit |
| Stage 4 subtitle | 77 menit |
| Stage 5 render | 34 menit |

Memasang torch CUDA (butuh GPU NVIDIA) akan memotong Stage 4 ke kisaran 8 menit.

## Struktur folder

```
clipper/
├── clipper_gui.py           # Aplikasi GUI (PySide6) — titik masuk utama
├── gui_review.py            # Panel review klip + kartu setelan/THEMES
├── gui_logparse.py          # Parsing log pipeline untuk tab Run
├── main.py                  # CLI & orkestrasi tahap
├── config.py                # Setelan terpusat (dibaca dari .env)
├── models.py                # Kontrak data antar tahap (pydantic)
├── utils.py                 # Helper umum (logging, waktu, ffmpeg, retry)
├── render_with_preset.py    # Render cepat memakai preset tertentu
├── stages/
│   ├── stage1_curate.py     stage2_download.py    stage3_render.py (dilewati)
│   ├── stage4_subtitles.py  stage4_batch.py       stage5_final.py
│   ├── stage5_preset.py     stage5_layout.py      stage5_design.py
│   ├── stage5_fonts.py      text_engine.py        subtitle_engine.py
│   ├── frame_library.py     font_library.py       preset_library.py
│   └── caption_txt.py
├── sketches/clipper-ui-mockup/index.html   # Halaman tab Customize (QWebEngine)
├── assets/                  # frames, fonts, overlays, presets/theme, sfx
├── cache/                   # transkrip YouTube + cache alignment (JANGAN dihapus)
├── temp/  logs/             # kerja sementara & log
├── output/                  # hasil Stage 1-4 per video
└── final/                   # video jadi + caption.txt
```

`cache/transcripts/` menyimpan transkrip video yang sudah pernah diproses supaya
tidak perlu ditarik ulang dari YouTube. Aman untuk dibiarkan; menghapusnya hanya
membuat proses berikutnya lebih lambat dan menambah risiko kena blokir IP.

## Perkakas pengembangan

Folder `tests/` dan `tools/` (termasuk skrip verifikasi UI dan `tools/cleanup.py`)
tidak diperlukan aplikasi saat berjalan, jadi tidak ada di folder kerja ini.
Semuanya tersimpan lengkap di branch **`dev`**:

```bash
git checkout dev -- tests tools
```

Sumber build halaman Customize (`sketches/clipper-ui-mockup/src/` + `build.py`)
juga ada di sana. Yang dipakai aplikasi hanya `index.html` hasil build-nya —
jangan menyuntingnya langsung; ambil `src/` dari branch `dev`, edit di situ, lalu
jalankan `build.py`.
