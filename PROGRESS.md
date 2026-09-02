# PROGRESS CLIPPER AGENT

Update terakhir: 2026-09-03 01:10 WIB
Test suite: **374 passed, 0 failed** (diukur sendiri 2026-09-02, bukan dikutip dari dokumen).

---

## 1. Status Singkat

| | Jumlah | Keterangan |
|---|---|---|
| Sudah selesai | 23 item | Item 1-23. Semua terverifikasi, rinciannya di bagian 3. |
| Belum dikerjakan | 5 item | Item 24-28. Spek lengkap di `bug.txt`. |

Yang belum, sekilas:

| Item | Isi | Catatan penting |
|---|---|---|
| 24 | Pilihan bahasa trilingual (EN/ID/Sunda) + anti-halusinasi WhisperX | Separuh sudah ada di kode. Lihat bagian 2. |
| 25 | Hapus autosave draf di tab Customize | Menyentuh fitur lain, lihat bagian 2. |
| 26 | Hapus judul panel & teks contoh URL yang berulang | Ada jebakan i18n, lihat bagian 2. |
| 27 | Sejajarkan kontrol di tab Run + jumlah klip jadi rentang Min-Max + benahi angka durasi yang mental | Penyebab mental = `_sync()`, bukan Qt. Lihat 2b. |
| 28 | Kartu 'SETELAN' jadi 'THEMES' + preview 9:16 + badge Applied | Belum ada sumber gambarnya, lihat bagian 2. |

---

## 2. Hasil Audit Kode 2026-09-02 (sebelum Item 24-28 dikerjakan)

Dokumen bukan bukti keadaan kode, jadi kelima tiket diperiksa langsung ke sumbernya.
Lima temuan di bawah mengubah isi tiket, bukan cuma memperjelas.

**Item 24 — separuh sudah terpasang.**
`condition_on_previous_text=False` + `no_speech_threshold=0.6` sudah ada di
`stage1_curate.py:233` dan `stage4_subtitles.py:525` & `:1701`. Yang belum ada sama sekali:
`initial_prompt`, flag `--lang-tags` di `main.py`, dan checkbox bahasa di GUI.

**Item 24 — bahasa Sunda TIDAK punya model penyelaras.**
Diukur di `.whisperx-venv`: dari 41 bahasa yang punya model alignment, `su` tidak termasuk
(`id` -> `cahya/wav2vec2-large-xlsr-indonesian`, `en` -> `WAV2VEC2_ASR_BASE_960H`).
Kalau centang SUNDANESE diteruskan ke parameter `language=`, forced alignment mati, timestamp
per kata hilang, dan SRT 1-kata/entri yang jadi fondasi kerapatan Theme ikut hancur.
Kesimpulan: centang bahasa HANYA boleh merakit `initial_prompt`; `language` tetap `"id"`.

**Item 24 — VAD ternyata belum aktif, bukan "sudah aktif tinggal diketatkan".**
`vad_filter` default `False` di faster-whisper, dan kode memanggil `WhisperModel(...)`
langsung (`stage4_subtitles.py:520` & `:1696`), bukan `whisperx.load_model` yang membawa
Silero-VAD. Jadi tiketnya harus berbunyi TAMBAHKAN VAD, bukan pastikan.

**Item 25 — autosave masih menyuplai satu fitur di tab Run.**
Dropdown tema punya pilihan "Draf Customize (belum disimpan)" yang mengirim `--preset` kosong,
lalu Stage 5 jatuh ke `render_preset.active.json` (`stage5_final.py:113`) — dan file itu HANYA
ditulis oleh autosave yang mau dihapus. Dihapus tanpa keputusan lain, pilihan itu jadi beku
berisi draf lama tanpa pemberitahuan apa pun. **Belum diputuskan Bang Asep.**
Dua catatan teknis: fungsinya ada di `j2.js:146` (tiket salah menulis `j1.js`/`j5.js`), dan
jangan dihapus — jadikan no-op, karena `syncAll():133` memanggilnya.

**Item 26 — menghapus label akan mematikan ganti bahasa secara senyap.**
`retranslate()` memanggil `self._tr_title.setText()` di baris pertama (`:1887`) dan
`self._tr_hint` di `:1890`, sementara seluruh blok dibungkus `except Exception: pass` (`:1919`).
Menghapus widgetnya tidak crash — lebih buruk: error ditelan diam-diam dan semua terjemahan
sesudahnya (URL, paste, progres, hasil, nav, kartu stage, tombol Jalankan) berhenti bekerja.

**Item 27 — dua tempat akan saling menimpa.**
`_set_running()` menulis `run_btn.setEnabled(not running)` tanpa syarat (`:2226`), jadi tombol
yang dinonaktifkan karena Max<Min hidup lagi setiap proses selesai. Butuh satu fungsi penentu
tunggal.

**Item 28 — preview 9:16 belum punya sumber gambar.**
`preset_library` tidak menyimpan thumbnail (`_summary()` hanya canvas/ratio/frame_id/font/
animation/words_per_line). Yang punya `thumbnail.png` 240x426 adalah `frame_library`. Jadi
preview harus dirakit dari thumbnail frame + bridge `render_text_layers` yang sudah ada,
kalau tidak hasilnya kotak hiasan — yang justru dilarang.

**Urutan eksekusi yang benar.** Item 24 (bagian UI), 26, 27, dan 28 semuanya membongkar kartu
yang SAMA (`_build_panel_jalankan` + `CurationSettings`), jadi kalau dikerjakan terpisah
layoutnya dibongkar-pasang empat kali:
1. Item 25 — terisolasi di mockup JS.
2. Satu paket UI tab Run — Item 26 + 27 + 28 + checkbox bahasa Item 24.
3. Backend Item 24 — wajib diuji dari `.whisperx-venv`, bukan `.venv`.

---

## 2b. Keputusan Bang Asep 2026-09-03 (mengunci tiga hal yang menggantung)

| # | Keputusan | Akibat di tiket |
|---|---|---|
| A | Koreksi trilingual Gemini **TETAP DIPAKAI**. `initial_prompt` + VAD ditambahkan sebagai lapisan lokal di depannya, bukan penggantinya. | Kalimat "buang ketergantungan Gemini" dihapus dari Item 24. `correct_text_trilingual()` di `:1231` & `:1736` tidak disentuh. |
| B | Pilihan **"Draf Customize (belum disimpan)" DIBUANG** dari dropdown tema. Tab Run hanya menjalankan Theme tersimpan. | Item 25 jadi terisolasi: tidak ada lagi jalur `--preset` kosong -> `render_preset.active.json`. Slot `active_preset` + `loadActivePreset()` TETAP (boot state). |
| C | **Jumlah klip jadi rentang pencarian Min-Max.** MIN = ambang kebutuhan user, MAX = batas atas pencarian Gemini. | Item 27 bertambah: `--min-count` baru, `--count` = MAX. MIN **tidak dijamin** — hasil kurang dari MIN tetap LANJUT dengan peringatan berangka, tanpa stop dan tanpa retry otomatis. |

Kebutuhan asli user untuk (C): *"minimal 6 klip tapi cari sampai 10"*. Empat titik kode ikut
berubah: prompt & pengambilan hasil & `max_tokens` memakai MAX (`stage1_curate.py:341`, `:350`,
`:633`, `:484`), sedangkan MIN hanya mengganti pembanding peringatan di `:636`.

Alasan MIN tidak bisa dijamin: yield Gemini tidak bisa dipaksa, dan filter overlap 50% di
`validate_and_normalize_clips()` masih memotong lagi sesudahnya. Retry otomatis ditolak user
karena membuang 1 dari 20 request/hari DAN menimpa file kurasi yang memuat pilihan review.

**Temuan tambahan 2026-09-03 — diagnosis Item 27 di tiket lama SALAH ALAMAT.** Angka durasi
yang mental bukan ulah QSpinBox memaksa `min<=max`, tapi kode sendiri:
`CurationSettings._sync()` (`gui_review.py:838`) berisi
`if max_sec <= min_sec: max_sec.setValue(min+10)` dan tersambung ke `valueChanged` (`:795`),
jadi jalan di SETIAP ketikan — digit "1" dari "120" langsung memicu pemaksaan.

**Nama-nama di Item 25 juga salah semua** dan sudah dikoreksi di `bug.txt`:
`scheduleAutoApply()` ada di `j2.js:147` (bukan j1/j5); yang dipanggil `B.save_preset`
(Slot `clipper_gui.py:293`), bukan `save_active_preset()` yang tidak pernah ada; simpan theme =
`save_preset_as` `:707` / `overwrite_theme` `:725`, bukan `save_theme()`; theme tinggal di
`assets/presets/library/`, folder `themes/` tidak ada.

---

## 3. Yang Sudah Selesai (Item 1-23)

### Item 12 — Intro Cover TikTok
`build_intro_cover()` di `stages/stage5_final.py` menggambar satu PNG opak seukuran kanvas
(latar cover-crop + Headline + nama creator, dipusatkan lewat `measure_ink()`), dipasang
sebagai lapisan teratas dengan `fade=t=out:alpha=1`.

Video & audio utama tidak disentuh — tetap jalan dari detik 0. Bukan freeze frame, bukan
concat, jadi durasi klip dan sinkronisasi subtitle tidak bergeser.

Bukti render nyata (klip 137 detik): durasi output 137.017s vs sumber 137.023s; audio detik
0-0.5 mean_volume -13.5 dB (suara sudah jalan di balik cover); t=0.05 tertutup 94%, t=0.30
62% (fade jalan), t=0.60 dan 2.0 sudah hilang. `tests/test_intro_cover.py` 12 test PASS.

### Item 21 — Subtitle Trilingual & Anti-Looping
- Akar masalah model: `whisper_model` ditulis DUA KALI di `config.py`; pydantic memakai
  definisi terakhir, jadi mengubah yang atas tidak pernah berefek. Sekarang satu field,
  default `medium`, dibaca dari `WHISPER_MODEL` di `.env`.
- Prioritas sumber teks: CC YouTube -> fallback ASR faster-whisper -> forced alignment.
  Sebelumnya klip tanpa CC langsung gagal tanpa subtitle.
- `correct_text_trilingual()` dipakai kedua jalur, dengan penjaga rasio kata 0.5x-1.8x supaya
  model tidak memotong atau mengarang isi.
- Diuji nyata: looping "Bagaimana? Bagaimana?..." hilang, kosakata Sunda utuh.
  `tests/test_stage4.py` 72 test PASS.

### Item 22 — Rapisasi Panel Style
Color picker 5 bulatan + native picker, slider X/Y side-by-side dengan input manual (memakai
class `.ctl-xy` yang stylenya memang ada — markup sebelumnya memakai `slider-col`/`sm2` yang
tidak ada di CSS mana pun), label Font/Align dihapus, divider per seksi, seluruh `.hint` dibuang.

Kartu Creator DIKEMBALIKAN ke panel kanan. Catatan lama "hapus kartu Creator" adalah salah
tulis; kartu itu yang dipakai mengatur tata letak teks "Creator!".

### Item 23 — Blur Background
Toggle + slider di seksi Video. Kunci i18n `blurBg`/`blurRadius` ditambahkan — sebelumnya kode
menulis `L('blurRadius')||'Blur Radius'` padahal kuncinya tidak ada, dan `L()` mengembalikan
nama kunci (truthy) sehingga fallback tidak pernah jalan dan yang tampil adalah tulisan mentah
`blurRadius`. Preview diperbaiki jadi blur sungguhan (`filter:blur() brightness(.6)`).

### Item 1-11, 13-20 — UI Customize
18/18 PASS di `tools/verify_customize_ui.py`, console_errors 0. Mencakup frame di preview,
watermark, sakelar ON/OFF, thumbnail, zoom gestur, i18n, scroll internal Library, min-width
panel, auto-columns, zero-center slider X/Y, dan urutan accordion Library.

---

## 4. Stage 4 Subtitle — Pelajaran Mahal (2026-09-01)

Item 21 sempat dinyatakan selesai, tapi pengujiannya dilakukan dari `.venv`. Stage 4
sebenarnya dijalankan `.whisperx-venv` sebagai subprocess (`main.py::_stage4_batch` baris 151),
jadi menguji di venv yang salah membuat EMPAT bug lolos ke produksi sekaligus:

| Bug | Gejala | Perbaikan |
|---|---|---|
| `openai` tidak ada di `.whisperx-venv` | Koreksi trilingual gagal senyap; subtitle keluar tapi looping & typo tak pernah dibersihkan | Pasang `openai 3.6.0` (dry-run dulu: 8 paket ditambah, nol ditimpa) |
| `.env` tidak pernah dibaca | `os.getenv("GEMINI_API_KEY")` selalu None -> status `not_configured`, menutupi bug pertama | `load_dotenv(_PROJECT_ROOT/".env")` di `correct_text_trilingual()` dan sebelum header CLI |
| `KeyError: 'start'` | Stage 4 crash total di forced alignment | Segmen menyertakan `start: 0.0` + `end: len(audio)/16000.0` |
| Logika koreksi kembar ~60 baris | Perbaikan di fungsi bersama tak sampai ke jalur CLI | Keduanya memanggil `correct_text_trilingual()` |

Akar masalah `.env`: pydantic-settings membaca `.env` ke objek `settings`, BUKAN ke
`os.environ`. Tidak ada satu pun `load_dotenv()` di jalur `.whisperx-venv`.

Bukti uji, klip nyata 137 detik dari `output/AD_REVIEW`:

```
Model              faster-whisper medium
Koreksi trilingual success
Kata ter-align     292 (unaligned 0)
Entri SRT          292, terakhir 00:02:16,784 (< durasi 137,02s)
Looping            nol
Kosakata Sunda     kumaha, damang, atuh, euy, pisan, sadayana, tong diantep — lolos
```

SRT 1 kata per entri itu SENGAJA (`subtitle_target_words = 1`, config.py:81): Stage 4 menulis
sehalus mungkin sekali saja, lalu Theme mengatur pengelompokan 1/3/5 kata tanpa menjalankan
Stage 4 ulang (~2 menit/klip).

---

## 5. Jebakan yang Jangan Diulang

- **Uji di venv yang benar-benar menjalankan kodenya.** `pytest` jalan di `.venv` dan TIDAK
  akan menangkap bug jalur `.whisperx-venv`. Ini sudah memakan satu klaim "selesai" yang palsu.
- **Status di dokumen bukan bukti keadaan kode.** Dokumen ini dipakai sebagai briefing untuk
  Claude, jadi sering ditulis SEBELUM eksekusi. Audit kodenya dulu setiap awal sesi.
- **Jalankan pytest sendiri.** Dokumen menulis 367; hasil ukur nyata 374 passed.
- **Satu fungsi JS hilang = beberapa laporan bug.** `syncAll()` memanggil `scheduleAutoApply()`
  di baris TERAKHIR; ketika fungsi itu pernah terhapus, setiap handler berpola
  `syncAll(); buildInspector()` berhenti di tengah karena ReferenceError — sakelar, warna, dan
  align semua tampak "tidak merespons". Periksa console SEBELUM menduga masalah CSS.
- **`L('kunci')||'fallback'` tidak pernah jatuh ke fallback**, karena `L()` mengembalikan nama
  kunci yang truthy. Tambah kunci baru ke KEDUA kamus `j1.js`.
- **`except Exception: pass` menyembunyikan kerusakan.** `retranslate()` dibungkus itu, jadi
  satu widget hilang mematikan semua terjemahan sesudahnya tanpa pesan error.
- **Test yang hasilnya berubah antar-run adalah test RUSAK**, bukan test yang kadang lewat.
  Skrip verifikasi UI ikut rusak setiap markup berubah — perbaiki selektornya di edit yang sama.
- **Restart GUI di turn yang sama dengan perubahan bridge/JS**, karena QWebEngine meng-cache
  halaman dan user akan menguji kode lama.

---

## 6. Riwayat

- 2026-09-03: Tiga keputusan menggantung dikunci Bang Asep (Gemini tetap dipakai; draf Customize
  dibuang dari dropdown; jumlah klip jadi rentang Min-Max). `bug.txt` ditulis ulang: 9 nama
  fungsi/file yang salah dikoreksi, diagnosis spinbox Item 27 diperbaiki (penyebabnya `_sync()`,
  bukan Qt), dan 4 jebakan yang belum tercatat dimasukkan sebagai bagian "JANGAN" per tiket.
- 2026-09-02: Audit kode kelima tiket terbuka (Item 24-28); lima temuan mengubah isi tiket,
  termasuk ketiadaan model alignment Sunda dan VAD yang ternyata belum aktif. Urutan eksekusi
  diubah jadi tiga tahap. Test diukur ulang: 374 passed.
- 2026-09-01: Stage 4 diuji end-to-end dari `.whisperx-venv`, 4 bug ditemukan. Item 12, 21, 22,
  23 diselesaikan; kartu Creator dikembalikan; P2.10 distabilkan; model
  `faster-whisper-medium` (1.5GB) diunduh dan benar-benar terpakai (sebelumnya kode selalu
  memuat `small`).
- 2026-08-31: 18 test warisan yang mengunci perilaku lama dibuang lewat
  `tools/_prune_stale_tests.py` (parsing `ast`, bukan regex; cadangan di `temp/_backup_tests/`).
  Keputusan Bang Asep: buang FUNGSI yang gagal, jangan buang filenya — ketiga file itu juga
  memuat 117 test yang masih berguna.
