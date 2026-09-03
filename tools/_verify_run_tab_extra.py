"""Cek tambahan: lapisan teks preview THEMES benar-benar tergambar + panel bisa digulir.

Dipisah dari `_verify_run_tab.py` karena keduanya mengubah ukuran window (uji overflow
harus memanggil `setMinimumSize(0,0)` dulu — `resize()` di bawah minimum DIABAIKAN
secara diam-diam oleh Qt).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import clipper_gui  # noqa: E402

gagal = 0


def cek(nama: str, ok: bool, detail: str = "") -> None:
    global gagal
    if not ok:
        gagal += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {nama}" + (f"   -> {detail}" if detail else ""))


app = QApplication.instance() or QApplication(sys.argv)
win = clipper_gui.ClipperWindow()
win.show()
app.processEvents()

tc = win.themes_card

# --- lapisan teks: minta langsung ke provider yang dipakai kartu ---
preset_path = tc.preset_path()
cek("ada theme tersimpan untuk diuji", bool(preset_path), preset_path)
if preset_path:
    import json
    preset = json.loads(Path(preset_path).read_text(encoding="utf-8-sig"))
    layers = tc._text_layers(preset)
    cek("lapisan teks head/wm/sub tergambar (bukan kotak hiasan)",
        {"head", "wm", "sub"} <= set(layers),
        f"dapat: {sorted(layers)}")
    for k, pm in layers.items():
        cek(f"lapisan {k} punya piksel ({pm.width()}x{pm.height()})",
            pm.width() > 0 and pm.height() > 0 and not pm.isNull())

    thumb = tc._frame_thumbnail(str((preset.get("frame") or {}).get("id") or ""))
    cek("thumbnail frame theme ditemukan", thumb is not None and not thumb.isNull(),
        str((preset.get("frame") or {}).get("id")))

    tc._repaint_preview()
    app.processEvents()
    cek("catatan preview kosong (tidak ada bagian yang gagal dirakit)",
        tc.pv_note.text() == "", repr(tc.pv_note.text()))

    # Preview harus BERBEDA dari kotak kosong: bandingkan dengan pixmap frame saja.
    gabungan = tc.canvas.pixmap().toImage()
    hanya_frame = thumb.scaled(tc.INNER_W, tc.INNER_H,
                               Qt.KeepAspectRatioByExpanding,
                               Qt.SmoothTransformation).toImage()
    cek("preview = frame + teks (bukan frame telanjang)",
        gabungan.size() != hanya_frame.size() or gabungan != hanya_frame)

    # Yang BENAR-BENAR terlihat: grab widget preview lalu hitung warna unik.
    # QLabel ber-layout tetap menggambar pixmap-nya di belakang widget anak; kalau
    # tidak, hasil grab hanya berisi warna latar QSS (1-2 warna).
    tampak = tc.canvas.grab().toImage()
    warna = {tampak.pixel(x, y)
             for x in range(0, tampak.width(), 3)
             for y in range(0, tampak.height(), 3)}
    cek("preview benar-benar TERGAMBAR di widget (bukan kotak kosong)",
        len(warna) > 30, f"{len(warna)} warna unik pada {tampak.width()}x{tampak.height()}")

# --- overflow: panel Run harus MENGGULIR, bukan saling menindih ---
tinggi_awal = win.height()
win.setMinimumSize(0, 0)          # tanpa ini resize() di bawah minimum diabaikan
win.resize(1000, 420)
app.processEvents()
# Qt tidak akan menyusut di bawah minimumSizeHint gabungan anak-anaknya (halaman
# Customize/Settings punya widget bertinggi minimum), jadi yang diassert adalah
# "benar-benar mengecil", bukan angka 420 yang persis.
cek("resize benar-benar diterapkan (window mengecil)",
    win.height() < tinggi_awal and win.height() <= 560,
    f"{tinggi_awal} -> {win.height()}")

sc = win.run_stack.widget(0)
inner = sc.widget()
bar = sc.verticalScrollBar()
cek("panel Jalankan lebih tinggi dari viewport (memang overflow)",
    inner.sizeHint().height() > sc.viewport().height(),
    f"isi={inner.sizeHint().height()} viewport={sc.viewport().height()}")
cek("scrollbar vertikal aktif (isi digulir, tidak ditindih)",
    bar.maximum() > 0, f"max={bar.maximum()}")

# Widget paling bawah (tombol Jalankan) tetap terjangkau setelah digulir.
bar.setValue(bar.maximum())
app.processEvents()
titik = win.run_btn.mapTo(sc.viewport(), win.run_btn.rect().center())
cek("tombol Jalankan terjangkau setelah digulir",
    0 <= titik.y() <= sc.viewport().height(),
    f"y={titik.y()} viewport_h={sc.viewport().height()}")

win.close()
print(f"\nVERDICT: {'SEMUA PASS' if not gagal else f'{gagal} FAIL'}")
raise SystemExit(0 if not gagal else 2)
