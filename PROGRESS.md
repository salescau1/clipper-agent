# PROGRESS CLIPPER AGENT

Update terakhir: 2026-09-01 12:30 WIB
Status proyek: **23/23 Selesai.** UI 18/18 PASS (`tools/verify_customize_ui.py`, console_errors 0).
Test suite: **367 passed, 0 failed.**

---

## 1. Ringkasan Status Pekerjaan

| Kategori | Selesai / Total | Keterangan |
|---|---|---|
| P1: Bug Kritis & Fungsi Utama | 6 / 6 | Frame, Watermark, Switch On/Off, Thumbnail, Zoom, i18n |
| P2: Behavior & Layout UX | 5 / 5 | Internal Scroll, Min-Width, Auto-Columns, Zero-Center Slider, Urutan Library |
| P3: Fitur Baru | 3 / 3 | Item 12 Intro Cover, Item 21 Subtitle Trilingual, Item 23 Blur Background |
| P4: Rapisasi UI & Redundan | 9 / 9 | termasuk Item 22 Rapisasi Total Panel Style |

Detail lengkap tiap item + bukti verifikasinya ada di `bug.txt`.

---

## 2. Yang Dikerjakan 2026-09-01

### Item 12 — Intro Cover TikTok
`build_intro_cover()` di `stages/stage5_final.py` menggambar satu PNG opak seukuran
kanvas (latar cover-crop + Headline + Nama Creator, dipusatkan lewat `measure_ink()`).
Di ffmpeg dipasang sebagai lapisan teratas: `fade=t=out:alpha=1` lalu
`overlay enable='lte(t,durasi)'`.

**Video & audio utama tidak disentuh** — tetap jalan dari detik 0. Bukan freeze frame,
bukan concat, jadi durasi klip dan sinkronisasi subtitle tidak bergeser.

Verifikasi render nyata (klip 137 detik):
- Durasi output 137.017s vs sumber 137.023s → timeline aman.
- Audio detik 0–0.5: mean_volume −13.5 dB → suara sudah jalan di balik cover.
- t=0.05 → 94% tertutup | t=0.30 → 62% (fade jalan) | t=0.60 & 2.0 → 44% (hilang).
- `tests/test_intro_cover.py`: 12 test PASS.

### Item 21 — Subtitle Trilingual & Anti-Looping
- **Akar masalah model whisper**: `whisper_model` ditulis DUA KALI di `config.py`;
  pydantic memakai definisi terakhir, jadi mengubah yang atas tidak pernah berefek.
  Sekarang satu field, default `medium`, dibaca dari `WHISPER_MODEL` di `.env`.
- Parameter anti-looping dipasang di Stage 1 juga, bukan cuma Stage 4.
- Prioritas sumber: **CC YouTube → fallback ASR faster-whisper → forced alignment**.
  Sebelumnya klip tanpa CC langsung digagalkan tanpa subtitle.
- `correct_text_trilingual()` dipakai untuk kedua jalur, dengan penjaga rasio kata
  0.5x–1.8x supaya model tidak memotong/mengarang isi.
- Diuji nyata: looping "Bagaimana? Bagaimana?..." hilang, kosakata Sunda utuh.
- `tests/test_stage4.py`: 72 test PASS.

### Item 22 — Rapisasi Panel Style
Color picker 5 bulatan + native picker, slider X/Y side-by-side dengan input manual
(class `.ctl-xy` yang stylenya memang ada — sebelumnya markup memakai `slider-col`/`sm2`
yang tidak ada di CSS mana pun), label Font/Align dihapus, divider per seksi, seluruh
`.hint` dibuang.

**Kartu Creator DIKEMBALIKAN** ke panel kanan. Catatan lama "hapus kartu Creator"
adalah salah tulis; kartu itu dipakai untuk mengatur tata letak teks "Creator!".

### Item 23 — Blur Background
Toggle + slider di seksi Video. Kunci i18n `blurBg`/`blurRadius` ditambahkan — sebelumnya
kode memakai `L('blurRadius')||'Blur Radius'` padahal kuncinya tidak ada, dan `L()`
mengembalikan nama kunci (truthy) sehingga fallback tidak pernah jalan dan yang tampil
adalah tulisan mentah "blurRadius".

Preview diperbaiki jadi blur sungguhan (`filter:blur() brightness(.6)`, radius diskalakan
lewat SX). Sebelumnya CSS-nya hanya menggelapkan latar tanpa blur → preview ≠ render.

---

## 3. Status Test Suite

`pytest tests/` → **367 passed | 0 failed**

Sebelumnya 18 gagal, semuanya warisan lama yang mengunci perilaku kode yang sudah
berubah — bukan regresi. Bukti: `.pytest_cache/v/cache/lastfailed` dari run 2026-08-31
memuat 20 test gagal, 18 di antaranya persis sama.

Keputusan Bang Asep (2026-09-01): buang 18 **fungsi** yang gagal, jangan buang filenya —
ketiga file itu juga memuat 117 test yang lulus dan masih berguna.

| Berkas | Dibuang | Penyebab gagal |
|---|---|---|
| `test_models.py` | 5 test + 2 kelas | Me-mock `stage1_curate.genai` yang sudah tidak ada (Stage 1 pindah ke klien OpenAI-compatible) |
| `test_stage2.py` | 12 test + 2 kelas | Minta folder gabungan `Creator - Video Title`; kode memakai dua tingkat `output/<creator>/<judul≤30>/` |
| `test_stage2_buffer.py` | 1 test | Sama seperti di atas |

Struktur dua tingkat itulah yang benar dan sudah dipakai semua output di disk. Mengubah
kode ke bentuk lama akan membuat klip yang sudah diunduh tidak dikenali lagi.

Pembuangannya lewat `tools/_prune_stale_tests.py` — mem-parse `ast` untuk mendapat
rentang baris persis tiap fungsi, lalu memverifikasi hasilnya masih Python yang sah
sebelum menulis. Bukan regex. Cadangan asli di `temp/_backup_tests/`.

---

## 4. Stage 4 Subtitle — Diuji End-to-End (2026-09-01)

Item 21 sebelumnya dinyatakan selesai, tapi pengujiannya dilakukan dari `.venv`.
Stage 4 sebenarnya dijalankan `.whisperx-venv` sebagai subprocess
(`main.py::_stage4_batch` baris 151) — menguji di venv yang salah membuat empat bug
lolos. Semuanya ditemukan lewat render SRT sungguhan, bukan mock.

| Bug | Gejala | Perbaikan |
|---|---|---|
| `openai` tidak ada di `.whisperx-venv` | Koreksi trilingual gagal senyap; subtitle keluar tapi looping & typo tak pernah dibersihkan | Pasang `openai 3.6.0`. Dry-run lebih dulu: 8 paket ditambah, **nol** ditimpa |
| `.env` tidak pernah dibaca | `os.getenv("GEMINI_API_KEY")` selalu None → status `not_configured`. Menutupi bug pertama | `load_dotenv(_PROJECT_ROOT/".env")` di `correct_text_trilingual()` dan sebelum header CLI |
| `KeyError: 'start'` | **Stage 4 crash total** di forced alignment | Segmen kini menyertakan `start: 0.0` + `end: len(audio)/16000.0`. Diperbaiki di `_run_whisperx_alignment()` dan `_run_cli()` |
| Logika koreksi terduplikasi ~60 baris | Perbaikan pada fungsi bersama tak sampai ke jalur CLI | Keduanya kini memanggil `correct_text_trilingual()` |

Akar masalah `.env`: pydantic-settings membaca `.env` ke objek `settings`, **tidak** ke
`os.environ`. Tidak ada satu pun `load_dotenv()` di jalur `.whisperx-venv`.

Bukti uji, klip nyata 137 detik dari `output/AD_REVIEW`:

```
Model              faster-whisper medium
Koreksi trilingual success
Kata ter-align     292 (unaligned 0)
Entri SRT          292, terakhir 00:02:16,784 (< durasi 137,02s)
Looping            nol
Kosakata Sunda     kumaha, damang, atuh, euy, pisan, sadayana, tong diantep — lolos
Jalur run()        transcribe_clip_whisperx() 18/18 kata, fallback 0
```

SRT berisi 1 kata per entri. Itu sengaja: `subtitle_target_words = 1` (config.py:81),
supaya Stage 4 menulis sehalus mungkin sekali saja dan theme mengatur pengelompokan
tanpa menjalankan Stage 4 ulang (~2 menit/klip).

---

## 5. Perbaikan Infrastruktur Test

- **P2.10 tidak lagi flaky.** Dua akar masalah: selektor mencari `.slider-col` yang
  tidak ada, dan menunggu lapisan teks asinkron dengan tenggat tetap 2 detik. Sekarang
  baca `.ctl-xy`/`.xy-label` dan baca ulang sampai kotak tinta tersedia (maks 12×500ms).
  5 run berturut-turut PASS.
- **Versi WhisperX di manifest** tidak lagi selalu "unknown": dibaca dari metadata paket
  tanpa `import whisperx` (paketnya ada di `.whisperx-venv`, bukan `.venv`).

---

## 6. Catatan Teknis Historis

- 2026-09-01: Stage 4 diuji end-to-end dari `.whisperx-venv`; 4 bug ditemukan
  (openai tidak terpasang, `.env` tak terbaca, `KeyError: 'start'`, logika duplikat).
- 2026-09-01: Item 12, 21, 22, 23 diselesaikan; Kartu Creator dikembalikan; P2.10 distabilkan.
- 2026-09-01: Download dan verifikasi model `faster-whisper-medium` (1.5GB) sukses,
  dan sekarang benar-benar terpakai (sebelumnya kode selalu memuat `small`).
- 2026-09-01: Perumusan detail spesifikasi P3 & P4 bersama Bang Asep di `bug.txt`,
  `rencana_perbaikan_subtitle.txt`, dan `PROGRESS.md`.
