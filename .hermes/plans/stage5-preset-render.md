# Stage 5 — Preset-Driven Render Customizer

Status: PLAN ONLY (belum eksekusi). Dibuat 2026-08-27.
Tujuan: menyambungkan mockup UI (sketches/clipper-ui-mockup/index.html) ke render engine
Stage 5 yang sudah ada, lewat satu file jembatan: render_preset.json.

## Kondisi sekarang (yang sudah jalan)
- stages/stage5_final.py (759 baris): baca Stage 2 manifest.json -> per klip render_clip()
- Geometri video HARDCODED: canvas 1080x1920, video full-width 1080x608, di Y=675
- Subtitle SELALU word-by-word pop (write_ass_word_pop), size 80, Y=1190, warna aktif oranye
  (SUBTITLE_NORMAL_COLOR=&H00FFFFFF, SUBTITLE_ACTIVE_COLOR=&H0000A5FF)
- Overlay frame.png di atas video (assets/frame.png, 1080x1920)
- "Creator" (nama kreator, drawtext oranye) + "Hook" (headline besar, ditulis Gemini) via drawtext
- Konstanta di stages/stage5_fonts.py; layout headline dihitung stage5_layout.py; hook di-refine stage5_design.py (Gemini)
- BELUM ada: custom PNG overlay, pilihan animasi lain, kontrol scale/Y video dari luar

## Fitur UI mockup yang belum tersambung ke render
- Video: source ratio, scale (width), Y position, corner radius, center/reset
- Subtitle: font (8 pilihan), size, outline, Y position, animation (none/pop/fade/up/bounce/zoom/word/karaoke), text, warna
- Headline: text, font, size, X offset, Y, warna, toggle
- Watermark: text, X (dari kanan), Y, toggle
- Custom PNG: upload file, size(width), X, Y, toggle, remove
- Export: resolution + CRF
- Inspector = accordion single-open (Video default terbuka), safe-area pill di header

## MAPPING TERKUNCI (dijawab user 2026-08-27)
1. UI "Headline" -> GANTIKAN penuh elemen "hook" engine. hook lama dihapus dari render.
   Gemini TETAP dipertahankan: menulis teks headline DEFAULT ke preset, bisa ditimpa di UI.
   (Gemini = pengisi default preset, BUKAN bagian renderer. Renderer tetap murni baca preset.)
2. UI "Watermark" -> elemen "creator" engine (nama kreator, teks kecil oranye).
3. Video scale: relatif ke LEBAR canvas. scale 1.0 = penuh lebar (1080px), center horizontal,
   makin kecil makin menyempit. VIDEO_W turunan dari scale.
4. Animasi subtitle: HANYA none/pop/fade/slide-up/word/karaoke (bounce/zoom/shake DIBUANG,
   sudah dihapus dari mockup). Dipetakan ke ASS \t / \k.
5. Custom PNG: simpan path absolut PNG di preset; overlay via ffmpeg (x,y,width) — layer BARU.

## Konsekuensi
- "hook" engine + stage5_layout hook-fitting bisa disederhanakan/di-nonaktifkan; headline
  sekarang datang dari preset (teks + font + size + x + y + color).
- Gemini (stage5_design.refine_hook) tetap dipanggil untuk menghasilkan default headline text,
  tapi hasilnya ditulis ke preset.headline.text (bukan langsung ke drawtext).

## Skema preset JSON (usulan) — render_preset.json, 1 file per render
{
  "canvas":    {"w":1080,"h":1920},
  "video":     {"scale":1.0, "y":675, "radius":0},
  "subtitle":  {"font":"subtitle.ttf","size":80,"y":1190,"outline":6,
                "color":"#FFFFFF","active_color":"#FFA500","animation":"word"},
  "headline":  {"text":"...","font":"title.ttf","size":86,"x":45,"y":55,
                "color":"#D94B0A","enabled":true,"gemini":false},
  "watermark": {"text":"AD REVIEW","x":..,"y":..,"enabled":true},
  "custom_png":{"path":"C:/.../logo.png","x":16,"y":84,"width":220,"enabled":true},
  "export":    {"w":1080,"h":1920,"crf":18}
}

## Rencana refactor (bertahap, aman — default = perilaku lama)
- Fase A: modul stages/stage5_preset.py — load preset JSON + merge default lama.
  Kalau preset tidak ada -> perilaku PERSIS seperti sekarang (zero regresi).
- Fase B: render_clip() baca geometri video + subtitle (size/Y/warna/animasi) +
  headline/watermark dari preset. Konstanta lama jadi fallback.
- Fase C: dispatcher animasi ASS (none/fade/pop/word/karaoke) +
  layer overlay custom PNG di filter_complex.
- Fase D: CLI `--preset path.json`; tombol "Save preset" di UI generate JSON yang sama (download).
- Verifikasi tiap fase: render 1 klip nyata via ffmpeg, cek MP4 ada & durasi>0, bandingkan hasil lama.

## File terkait
- UI mockup: C:/Clipper Agent/clipper/sketches/clipper-ui-mockup/index.html
- Engine:    C:/Clipper Agent/clipper/stages/stage5_final.py
- Konstanta: C:/Clipper Agent/clipper/stages/stage5_fonts.py
- Layout:    C:/Clipper Agent/clipper/stages/stage5_layout.py
- Gemini:    C:/Clipper Agent/clipper/stages/stage5_design.py

## STATUS EKSEKUSI (2026-08-27)
- Fase A SELESAI: stages/stage5_preset.py (DEFAULT_PRESET + load_preset deep-merge + konversi
  warna hex->ASS/drawtext + video_geometry). Verified.
- Fase B SELESAI: stage5_final.render_clip/run/main baca preset; CLI --preset. Fallback = perilaku lama.
- Fase C SELESAI: write_ass dispatcher none/fade/pop/up + word/karaoke; layer overlay custom PNG.
  Diverifikasi render nyata (default.mp4 identik lama, custom.mp4 scale 0.85 + karaoke cyan).
- Fase D SELESAI: mockup tombol "Save preset (JSON)" -> savePreset() download render_preset.json;
  buildPreset() konversi koordinat preview 250x444 -> canvas 1080x1920. E2E verified (preset->render->mp4).

## TEMUAN / SISA KERJA
1. Headline overflow: SELESAI (auto-fit). render_clip pakai fit_text() dari stage5_layout:
   headline dikecilkan/wrap max 2 baris agar muat zona [x .. max_x] (default HEADLINE_RIGHT
   diskalakan ke canvas). fontsize render pakai head_fit_size, bukan preset.size mentah.
   Watermark JUGA auto-fit (1 baris, zona x..tepi kanan). Diverifikasi via frame render:
   headline panjang size 120 -> turun otomatis muat 2 baris; 'AD REVIEW' muat penuh.
   Preset baru (opsional): headline.max_x, headline.min_size, watermark.min_size.
2. Jembatan UI->render: SELESAI.
   - main.py `run` & `stage5` punya opsi --preset (diteruskan ke stage5_final.run).
   - render_with_preset.py: ambil render_preset.json terbaru (Downloads/Desktop/proyek) atau
     --preset eksplisit; arsipkan ke assets/presets/render_preset.active.json; jalankan Stage 5.
   - Mockup: tombol "Render all clips" -> savePreset + modal berisi perintah `python render_with_preset.py`.
   - Diverifikasi E2E: preset JSON -> render_with_preset.py -> Stage 5 -> 5 MP4 nyata di final/.
   - KEPUTUSAN (opsi 3): posisi headline vs watermark dibiarkan WYSIWYG via slider mockup.
     Tidak ada auto-collision-detection. Tabrakan hanya terjadi jika user menaruh koordinat
     berdekatan; preview menampilkan posisi persis sehingga user mengatur sendiri.
3. video.radius: SELESAI. render_clip pakai geq alpha-mask di [clip] (setelah scale+pad+rgba)
   untuk membulatkan 4 sudut video bila radius>0 (di-clamp <= min(w,h)/2). radius=0 = tanpa mask
   (jalur lama, tanpa overhead). Diverifikasi frame render: radius=60 -> 4 sudut video membulat.
4. custom_png.path = assets/overlays/<nama>; user harus taruh file PNG-nya sendiri di situ.
5. subtitle Y: SELESAI dicek. UI suby = jarak-dari-bawah preview; buildPreset konversi ke
   top-based (CANVAS_H - suby*SY) untuk \\an8. Konsisten dgn default preset (1190 top-based). OK.

## SEMUA SISA KERJA SELESAI (Fase A-D + auto-fit + jembatan + poles). Fitur render customizer lengkap & terverifikasi E2E.

## FASE E — INTEGRASI PySide6 (2026-08-28)
GUI clipper_gui.py (PySide6 6.11.2) SUDAH ada; QtWebEngine + QtWebChannel tersedia.
- Halaman "Stage 5" GUI diganti: sekarang QWebEngineView memuat sketches/clipper-ui-mockup/index.html.
- PresetBridge(QObject) registerObject('bridge'); slot save_preset(json) & render_preset(json)
  menulis assets/presets/render_preset.active.json, lalu emit sinyal.
  render_requested -> QProcess jalankan render_with_preset.py --preset <file> (log muncul di dashboard).
- Mockup: qwebchannel.js diload via <script src="qrc:///qtwebchannel/qwebchannel.js">.
  initBridge() retry sampai qt+QWebChannel siap (async inject). Di browser biasa: fallback download JSON.
  savePreset()/showRenderCmd() override: kalau _bridge ada -> kirim ke Python; kalau tidak -> perilaku browser.
- PITFALL yang sudah dibetulkan: init call (applyControls/buildSub) sempat berada SEBELUM deklarasi
  let _subText -> ReferenceError menghentikan seluruh script (fungsi global tak terdefinisi).
  Fix: pindahkan applyControls()+buildSub() ke window 'load' handler. Juga hapus baris duplikat 'initBridge(0); });'.
- Diverifikasi (offscreen QWebEngine): PROBE BRIDGE_CONNECTED; render_preset() menulis preset aktif
  yang valid (semua kunci ada). GUI AST OK.
- Pemakaian: python clipper_gui.py (pakai .venv) -> menu Stage 5 -> atur -> Render all clips (render langsung)
  atau Save preset (simpan ke assets/presets/). Tombol Render memanggil render_with_preset.py otomatis.

## Langkah berikutnya (urut prioritas usulan)
A. Headline auto-fit (benahi temuan #1) — pakai build_layout yang sudah ada.
B. Jembatan UI->render: main.py terima --preset; dokumentasikan alur download->run.
C. (opsional) rounded corner video, cek subtitle-Y.
