"""Verifikasi tab Run: Item 26, 27, 28, Item 24 (UI), Item 25 poin 2c.

Skrip UJI SEMENTARA (dipakai saat mengerjakan paket UI tab Run). Menjalankan window
NYATA secara offscreen, mengubah state, lalu MENGUKUR akibatnya — bukan mencocokkan
keberadaan atribut.

Jebakan Qt yang dihindari di sini (sudah pernah membuat tes lulus tanpa menguji apa pun):
  * `win.show()` WAJIB dipanggil dulu; tanpa itu setiap widget anak melaporkan
    isVisible()==False sehingga assert "X tersembunyi" lulus padahal semuanya tersembunyi.
    Karena itu assert di bawah juga menguji kondisi POSITIF.
  * Argumen CLI diperiksa dengan mencegat QProcess (monkeypatch `_start_stage_process`),
    supaya tidak ada pipeline nyata yang jalan dan tidak ada request Gemini terbuang.

Jalankan:  .venv/Scripts/python.exe tools/_verify_run_tab.py
Keluar 0 kalau semua PASS, 2 kalau ada FAIL.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QLabel, QMessageBox  # noqa: E402

import clipper_gui  # noqa: E402
from gui_review import CurationSettings, LanguagePicker, ThemesCard  # noqa: E402

HASIL: list[tuple[bool, str, str]] = []

# QMessageBox.warning MEMBLOKIR walau platform offscreen (exec() menunggu input yang
# tidak akan pernah datang), jadi dialog dicegat dan hanya dicatat. Tanpa ini skrip
# menggantung tanpa satu pun baris keluaran — sudah terjadi 2026-09-03.
DIALOG: list[tuple[str, str]] = []


def _fake_warning(_parent, judul, teks, *a, **kw):
    DIALOG.append((str(judul), str(teks)))
    return QMessageBox.Ok


QMessageBox.warning = staticmethod(_fake_warning)      # type: ignore[assignment]
QMessageBox.critical = staticmethod(_fake_warning)     # type: ignore[assignment]
QMessageBox.information = staticmethod(_fake_warning)  # type: ignore[assignment]


def cek(nama: str, ok: bool, detail: str = "") -> None:
    HASIL.append((bool(ok), nama, detail))


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    win = clipper_gui.ClipperWindow()
    win.show()                      # WAJIB sebelum mengukur visibilitas
    app.processEvents()

    # ---------------------------------------------------------------- Item 26
    # Judul panel & hint URL benar-benar tidak ada lagi sebagai widget.
    for attr in ("_tr_title", "_tr_hint", "_tr_res"):
        cek(f"26 atribut {attr} dibuang", not hasattr(win, attr),
            f"masih ada: {getattr(win, attr, None)}")

    panel_labels = [w for w in win.findChildren(QLabel)
                    if w.objectName() == "panelLabel"]
    cek("26 tidak ada QLabel #panelLabel", not panel_labels,
        f"{len(panel_labels)} label sisa")

    # Konstanta RUN_PANELS tetap dipakai sidebar + badge Review.
    cek("26 RUN_PANELS masih ada", tuple(win.RUN_PANELS) ==
        ("Jalankan", "Review", "Progres", "Hasil"), str(win.RUN_PANELS))
    cek("26 sidebar nav terisi dari RUN_PANELS",
        [b.text() for b in win.run_nav][:1] == ["Jalankan"]
        and win.run_nav[0].isVisible(),
        f"{[b.text() for b in win.run_nav]}")

    # retranslate() TIDAK boleh berhenti di tengah: cek teks yang letaknya
    # SETELAH baris yang dihapus (nav = paling akhir sebelum stage cards).
    win.retranslate("en")
    app.processEvents()
    en_ok = (win.paste_btn.text() == clipper_gui.t("paste", "en")
             and win.open_folder_btn.text() == clipper_gui.t("open_folder", "en")
             and win.nav_buttons[3].text() == clipper_gui.t("nav_settings", "en")
             and win.stage_cards["Render"].subtitle.text()
             == clipper_gui.t("stage_render_sub", "en")
             and win.run_btn.text() == "▶  " + clipper_gui.t("run", "en"))
    cek("26 retranslate EN sampai widget TERAKHIR", en_ok,
        f"paste={win.paste_btn.text()!r} nav3={win.nav_buttons[3].text()!r} "
        f"stage={win.stage_cards['Render'].subtitle.text()!r} "
        f"run={win.run_btn.text()!r}")

    win.retranslate("id")
    app.processEvents()
    id_ok = (win.paste_btn.text() == clipper_gui.t("paste", "id")
             and win.open_folder_btn.text() == clipper_gui.t("open_folder", "id")
             and win.nav_buttons[3].text() == clipper_gui.t("nav_settings", "id")
             and win.stage_cards["Render"].subtitle.text()
             == clipper_gui.t("stage_render_sub", "id")
             and win.run_btn.text() == "▶  " + clipper_gui.t("run", "id"))
    cek("26 retranslate ID sampai widget TERAKHIR", id_ok,
        f"nav3={win.nav_buttons[3].text()!r} "
        f"stage={win.stage_cards['Render'].subtitle.text()!r}")

    # ---------------------------------------------------------------- Item 24 UI
    lp = win.lang_picker
    cek("24 LanguagePicker ada di panel Jalankan", isinstance(lp, LanguagePicker))
    cek("24 default en=OFF id=ON su=ON",
        (not lp.boxes["en"].isChecked()) and lp.boxes["id"].isChecked()
        and lp.boxes["su"].isChecked(),
        {k: v.isChecked() for k, v in lp.boxes.items()})
    cek("24 tags default = id,su", lp.tags_arg() == "id,su", lp.tags_arg())
    cek("24 checkbox terlihat (positif)",
        all(cb.isVisible() for cb in lp.boxes.values()),
        {k: v.isVisible() for k, v in lp.boxes.items()})

    lp.boxes["en"].setChecked(True)
    app.processEvents()
    cek("24 en dicentang -> en,id,su", lp.tags_arg() == "en,id,su", lp.tags_arg())

    # Kosongkan semuanya -> harus kembali ke `id` + tanda di UI.
    for cb in lp.boxes.values():
        cb.setChecked(False)
    app.processEvents()
    cek("24 semua dilepas -> fallback id", lp.tags_arg() == "id", lp.tags_arg())
    cek("24 fallback ditandai di UI",
        lp.note.objectName() == "capacityWarn" and "Minimal satu" in lp.note.text(),
        f"{lp.note.objectName()} / {lp.note.text()!r}")
    cek("24 tidak pernah kosong", bool(lp.tags()), lp.tags())

    # ---------------------------------------------------------------- Item 27
    cs: CurationSettings = win.curation_settings
    cek("27 dua kotak jumlah klip ada",
        hasattr(cs, "count_min") and hasattr(cs, "count_max")
        and not hasattr(cs, "count"))
    cek("27 default klip 6-10",
        (cs.count_min.value(), cs.count_max.value()) == (6, 10),
        (cs.count_min.value(), cs.count_max.value()))
    cek("27 satuan `s` pada durasi",
        cs.min_sec.suffix() == "s" and cs.max_sec.suffix() == "s"
        and cs.count_min.suffix() == "" and cs.count_max.suffix() == "",
        (cs.min_sec.suffix(), cs.count_min.suffix()))
    cek("27 values() = (min,max,lo,hi)", cs.values() == (6, 10, 60, 240), cs.values())

    # ANGKA MENTAL: mengetik 120 di Max tidak boleh dipaksa jadi min+10.
    cs.max_sec.setValue(120)
    app.processEvents()
    cek("27 Max durasi 120 TIDAK mental", cs.max_sec.value() == 120, cs.max_sec.value())
    # Simulasi ketikan digit-per-digit lewat interpretText (keyboardTracking off).
    cs.max_sec.lineEdit().setText("1")
    cs.max_sec.interpretText()
    per_digit_1 = cs.max_sec.value()
    cs.max_sec.lineEdit().setText("12")
    cs.max_sec.interpretText()
    per_digit_12 = cs.max_sec.value()
    cs.max_sec.lineEdit().setText("120")
    cs.max_sec.interpretText()
    per_digit_120 = cs.max_sec.value()
    cek("27 ketik 1->12->120 berakhir 120", per_digit_120 == 120,
        f"1->{per_digit_1} 12->{per_digit_12} 120->{per_digit_120}")

    # Max < Min -> kotak merah + tombol Jalankan mati.
    cs.max_sec.setValue(30)          # min_sec = 60
    app.processEvents()
    cek("27 Max<Min: properti invalid true", bool(cs.max_sec.property("invalid")),
        cs.max_sec.property("invalid"))
    cek("27 Max<Min: is_valid False", not cs.is_valid())
    cek("27 Max<Min: tombol Jalankan mati", not win.run_btn.isEnabled())

    # PENTING: proses selesai TIDAK boleh menghidupkan tombol lagi.
    win._set_running_ui(True)
    win._set_running_ui(False)
    app.processEvents()
    cek("27 setelah proses selesai tombol TETAP mati (tidak saling menimpa)",
        not win.run_btn.isEnabled())

    cs.max_sec.setValue(240)
    app.processEvents()
    cek("27 rentang dibetulkan: tombol hidup lagi (positif)", win.run_btn.isEnabled())
    cek("27 properti invalid dibersihkan", not bool(cs.max_sec.property("invalid")))

    # Pasangan klip juga divalidasi.
    cs.count_max.setValue(3)         # count_min = 6
    app.processEvents()
    cek("27 Klip Max<Min ditandai + tombol mati",
        bool(cs.count_max.property("invalid")) and not win.run_btn.isEnabled())
    cs.count_max.setValue(10)
    app.processEvents()
    cek("27 Klip dibetulkan -> tombol hidup", win.run_btn.isEnabled())

    # Hint kapasitas memakai MIN dan MAX, dan tidak menjanjikan MIN.
    teks = cs.hint.text()
    cek("27 hint menyebut MIN & MAX", "MIN 6" in teks and "MAX 10" in teks, teks)
    cek("27 hint tidak menjanjikan MIN",
        "bukan jaminan" in teks.lower() or "tidak dijamin" in teks.lower(), teks)

    # Argumen CLI: --count = MAX, --min-count = MIN, --lang-tags terkirim.
    ditangkap: dict[str, list[str]] = {}

    def fake_start(args, judul, first_stage):
        ditangkap["args"] = list(args)
        ditangkap["judul"] = [judul]

    win._start_stage_process = fake_start          # type: ignore[assignment]
    win.url_input.setText("https://www.youtube.com/watch?v=H-aPguC0xL0")
    lp.boxes["su"].setChecked(True)                # -> id,su

    win.mode_toggle._set("auto")
    win.run_pipeline()
    auto_args = ditangkap.get("args", [])
    cek("27/24 mode Auto kirim --count MAX & --min-count MIN & --lang-tags",
        auto_args[:1] == ["run"]
        and "--count" in auto_args and auto_args[auto_args.index("--count") + 1] == "10"
        and "--min-count" in auto_args
        and auto_args[auto_args.index("--min-count") + 1] == "6"
        and "--lang-tags" in auto_args
        and auto_args[auto_args.index("--lang-tags") + 1] == "id,su",
        " ".join(auto_args))
    judul_auto = (ditangkap.get("judul") or [""])[0]
    cek("28 log menyebut theme yang dipakai (atau ketiadaannya)",
        "Theme:" in judul_auto, judul_auto.replace("\n", " | "))

    win.mode_toggle._set("manual")
    win.run_pipeline()
    man_args = ditangkap.get("args", [])
    cek("27 mode Manual kirim --count MAX & --min-count MIN",
        man_args[:1] == ["stage1"]
        and "--count" in man_args and man_args[man_args.index("--count") + 1] == "10"
        and "--min-count" in man_args
        and man_args[man_args.index("--min-count") + 1] == "6",
        " ".join(man_args))
    # `main.py stage1` TIDAK menerima --lang-tags (diperiksa lewat --help); mengirimnya
    # akan membuat typer keluar "No such option" dan mematikan jalur Manual.
    cek("24 stage1 TIDAK dikirim --lang-tags (opsi tak ada di CLI)",
        "--lang-tags" not in man_args, " ".join(man_args))

    # Jalur Manual meneruskan bahasa saat LANJUT dari review — di situlah Stage 4 jalan.
    win.continue_from_curation("output/x/y/vid.json")
    cont_args = ditangkap.get("args", [])
    cek("24 continue-from kirim --lang-tags (Stage 4 jalur Manual)",
        cont_args[:1] == ["continue-from"] and "--lang-tags" in cont_args
        and cont_args[cont_args.index("--lang-tags") + 1] == "id,su",
        " ".join(cont_args))

    # Rentang tidak valid tidak boleh lolos walau run_pipeline dipanggil langsung.
    cs.count_max.setValue(3)
    ditangkap.pop("args", None)
    DIALOG.clear()
    win.run_pipeline()
    cek("27 rentang invalid tidak mengirim apa pun", "args" not in ditangkap,
        ditangkap.get("args"))
    cek("27 rentang invalid memberi peringatan ke user",
        any("Rentang" in j for j, _ in DIALOG), DIALOG)
    cs.count_max.setValue(10)

    # Kelompok Baris 3 sejajar horizontal: y-tengah ketiganya sama.
    app.processEvents()
    y_mode = win.mode_toggle.mapTo(win, win.mode_toggle.rect().center()).y()
    y_klip = cs.count_min.mapTo(win, cs.count_min.rect().center()).y()
    y_dur = cs.min_sec.mapTo(win, cs.min_sec.rect().center()).y()
    cek("27 tiga kelompok sejajar horizontal (selisih y <= 12px)",
        max(abs(y_mode - y_klip), abs(y_klip - y_dur)) <= 12,
        f"mode={y_mode} klip={y_klip} durasi={y_dur}")
    x_mode = win.mode_toggle.mapTo(win, win.mode_toggle.rect().center()).x()
    x_klip = cs.count_min.mapTo(win, cs.count_min.rect().center()).x()
    x_dur = cs.min_sec.mapTo(win, cs.min_sec.rect().center()).x()
    cek("27 urutan kiri->kanan mode, klip, durasi", x_mode < x_klip < x_dur,
        f"{x_mode} < {x_klip} < {x_dur}")
    sep = [w for w in win.findChildren(clipper_gui.QFrame)
           if w.objectName() == "vsep" and w.isVisible()]
    cek("27 ada pembatas vertikal terlihat", len(sep) >= 2, f"{len(sep)} pembatas")

    # Panel Run tetap dibungkus QScrollArea(widgetResizable=True).
    scrolls = [win.run_stack.widget(i) for i in range(win.run_stack.count())]
    cek("27 semua panel Run dibungkus QScrollArea widgetResizable",
        all(isinstance(s, clipper_gui.QScrollArea) and s.widgetResizable()
            for s in scrolls),
        [type(s).__name__ for s in scrolls])

    # ---------------------------------------------------------------- Item 28
    tc: ThemesCard = win.themes_card
    cek("28 kartu THEMES ada", isinstance(tc, ThemesCard))
    judul_kartu = [w.text() for w in win.findChildren(QLabel)
                   if w.objectName() == "cardTitle"]
    cek("28 judul 'THEMES' menggantikan 'SETELAN'",
        "THEMES" in judul_kartu and "SETELAN" not in judul_kartu, judul_kartu)
    cek("28 kotak preview rasio 9:16",
        abs(tc.canvas.width() / tc.canvas.height() - 9 / 16) < 0.01,
        f"{tc.canvas.width()}x{tc.canvas.height()}")
    cek("28 preview lega (>=180px lebar)", tc.canvas.width() >= 180, tc.canvas.width())

    n_theme = sum(1 for i in range(tc.theme_box.count()) if tc.theme_box.itemData(i))
    tc._repaint_preview()
    app.processEvents()
    if n_theme:
        pm = tc.canvas.pixmap()
        cek("28 preview tergambar (pixmap tidak kosong)",
            pm is not None and not pm.isNull() and pm.width() > 0,
            f"null={pm is None or pm.isNull()}")
        cek("28 badge APPLIED terlihat saat ada theme", tc.badge.isVisible())
        cek("28 badge mencerminkan theme yang akan dirender",
            bool(tc.preset_path()) and Path(tc.preset_path()).is_file(),
            tc.preset_path())
        cek("28 caption menyebut frame theme",
            "Frame:" in tc.caption.text(), tc.caption.text()[:80])

        # Ganti theme -> preview & caption berubah.
        if n_theme > 1:
            gambar1 = tc.canvas.pixmap().toImage()
            cap1 = tc.caption.text()
            idx_lain = next(i for i in range(tc.theme_box.count())
                            if tc.theme_box.itemData(i)
                            and i != tc.theme_box.currentIndex())
            tc.theme_box.setCurrentIndex(idx_lain)
            tc._repaint_preview()
            app.processEvents()
            gambar2 = tc.canvas.pixmap().toImage()
            cek("28 ganti theme -> preview/caption berubah",
                gambar1 != gambar2 or cap1 != tc.caption.text(),
                f"gambar_sama={gambar1 == gambar2} caption_sama={cap1 == tc.caption.text()}")
        else:
            cek("28 ganti theme -> preview berubah", True, "hanya 1 theme, dilewati")
    else:
        cek("28 tanpa theme: badge MATI (bukan label mati yang selalu nyala)",
            not tc.badge.isVisible())

    # ---------------------------------------------------------------- Item 25 2c
    items = [tc.theme_box.itemText(i) for i in range(tc.theme_box.count())]
    cek("25.2c item 'Draf Customize' dibuang",
        not any("Draf" in s for s in items), items)
    cek("25.2c tooltip tidak menyebut draf",
        "Draf" not in tc.theme_box.toolTip(), tc.theme_box.toolTip())
    kosong = [tc.theme_box.itemText(i) for i in range(tc.theme_box.count())
              if not tc.theme_box.itemData(i)]
    cek("25.2c tidak ada item ber-data kosong saat ada theme",
        (not kosong) if n_theme else True, kosong)

    win.close()

    gagal = [h for h in HASIL if not h[0]]
    print()
    for ok, nama, detail in HASIL:
        tag = "PASS" if ok else "FAIL"
        print(f"  [{tag}] {nama}" + (f"   -> {detail}" if not ok and detail else ""))
    print(f"\n{len(HASIL) - len(gagal)}/{len(HASIL)} PASS")
    print("VERDICT:", "SEMUA PASS" if not gagal else "ADA YANG FAIL")
    return 0 if not gagal else 2


if __name__ == "__main__":
    raise SystemExit(main())
