"""Layar review kurasi: pilih klip mana yang diunduh + edit headline per klip.

Alur yang dilayani (permintaan user):

    curation -> REVIEW (edit headline + pilih klip) -> download -> subtitle -> tema -> render

File yang dibaca/ditulis adalah file kurasi Stage 1 itu sendiri:
`output/<creator>/<judul<=30char>/<video_id>.json`. Sengaja file yang sama, bukan file
state baru, karena:
  1. "lanjut besok" jadi otomatis — tidak ada state di memori yang perlu diselamatkan.
  2. Memindahkan/menambah lokasi output akan merusak semua helper "cari manifest terbaru"
     di hilir (`_find_latest_manifest` Stage 2, pencarian by video_id di main.py).

DUA field yang ditulis panel ini: `pilih` (bool) dan `headline` (str) per klip.

PENTING — kenapa TIDAK lewat Pydantic:
File ditulis ulang sebagai dict JSON apa adanya (round-trip mentah), bukan
`CurationResult.model_dump()`. Alasannya `durasi_detik` adalah computed_field dan
manifest bisa memuat field dari versi lain; round-trip mentah menjamin tidak ada field
yang hilang atau berubah tipe hanya karena user mencentang satu kotak.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

# Nama file yang BUKAN file kurasi walau berekstensi .json dan ada di folder yang sama.
# Jebakan yang sudah pernah kena: memilih "json terbaru" di folder output lalu diam-diam
# memproses data video yang salah karena yang terambil adalah manifest.json milik Stage 2.
#
# `subtitle_manifest.json` ditemukan 2026-08-29 saat memindai output NYATA: file itu lolos
# filter versi pertama (namanya tidak diakhiri `.subtitle.json`), masuk daftar, lalu
# `load_curation` melemparkan ValueError. Cek nama file harus mencakup pola manifest APA PUN,
# bukan cuma yang kebetulan sudah diketahui.
NON_CURATION_NAMES = {"manifest.json", "subtitle_manifest.json"}
NON_CURATION_SUFFIXES = (".subtitle.json", ".design.v3.json", "_manifest.json")


def is_curation_file(path: Path) -> bool:
    """True kalau `path` kelihatan seperti file kurasi Stage 1 (bukan manifest stage lain)."""
    name = path.name.lower()
    if name in NON_CURATION_NAMES:
        return False
    if any(name.endswith(sfx) for sfx in NON_CURATION_SUFFIXES):
        return False
    # Pagar terakhir: apa pun yang mengandung kata "manifest" bukan file kurasi.
    # File kurasi selalu bernama <video_id>.json (11 karakter ID YouTube).
    return "manifest" not in name


def load_curation(path: Path) -> dict[str, Any]:
    """Baca file kurasi mentah. `utf-8-sig` karena file lama bisa ber-BOM."""
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or not isinstance(data.get("daftar_klip"), list):
        raise ValueError("Bukan file kurasi: tidak ada 'daftar_klip'.")
    return data


def apply_decisions(
    data: dict[str, Any],
    decisions: dict[int, tuple[bool, str]],
    creator_watermark: str | None = None,
) -> dict[str, Any]:
    """Tempel keputusan review ke dict kurasi TANPA menyentuh field lain.

    decisions: {id_klip: (pilih, headline)}. Headline kosong dibiarkan kosong (bukan
    diisi judul_relevan) supaya "ikut judul" tetap bisa dibedakan dari "diedit user".

    creator_watermark: nama kreator ketikan user, berlaku untuk SEMUA klip di file ini
    (satu video = satu kreator, jadi tempatnya di tingkat file, bukan per klip). None =
    jangan sentuh field itu; "" = hapus override, kembali ke nama channel asli.
    """
    if creator_watermark is not None:
        data["creator_watermark"] = str(creator_watermark).strip()
    for clip in data.get("daftar_klip", []):
        if not isinstance(clip, dict):
            continue
        try:
            cid = int(clip.get("id_klip"))
        except (TypeError, ValueError):
            continue
        if cid not in decisions:
            continue
        pilih, headline = decisions[cid]
        clip["pilih"] = bool(pilih)
        clip["headline"] = str(headline or "").strip()
    return data


def save_curation(path: Path, data: dict[str, Any]) -> None:
    """Tulis atomik: ke file .tmp lalu replace.

    Kalau proses mati di tengah penulisan, file kurasi asli tidak ikut rusak — dan file
    itu satu-satunya sumber keputusan review, jadi kehilangannya berarti mengulang kurasi
    (1 request Gemini dari kuota 20/hari).
    """
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def clip_status(folder: Path, clip_id: int) -> tuple[bool, bool]:
    """(ada_mp4, ada_srt) untuk klip bernomor `clip_id` di `folder`.

    Stage 2 menamai file `<id_klip>. <judul> - <hook>.mp4`, jadi keberadaan file dicek
    dari PREFIKS NOMOR, bukan dari judul (judul bisa berubah setelah user edit headline).
    """
    folder = Path(folder)
    if not folder.is_dir():
        return (False, False)
    mp4 = any(p.suffix.lower() == ".mp4" for p in folder.glob(f"{clip_id}. *"))
    srt = any(p.suffix.lower() == ".srt" for p in folder.glob(f"{clip_id}. *"))
    return (mp4, srt)


def scan_curation_files(output_root: Path) -> list[Path]:
    """Semua file kurasi di `output/<creator>/<judul>/`, terbaru dulu."""
    root = Path(output_root)
    if not root.is_dir():
        return []
    found = [p for p in root.glob("*/*/*.json") if is_curation_file(p)]
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def creator_from_curation(path: Path) -> str:
    """Nama creator untuk file kurasi `path`.

    Sumber terbaik: `manifest.json` Stage 2 di folder yang sama — di situlah nama creator
    disimpan apa adanya (mis. "Youtuber Cupu"). Kalau belum ada (video baru dikurasi,
    belum diunduh), pakai nama FOLDER induk yang merupakan hasil sanitasi nama creator
    (`output/<creator>/<judul>/`), garis bawah diubah kembali jadi spasi.
    """
    path = Path(path)
    man = path.parent / "manifest.json"
    if man.exists():
        try:
            data = json.loads(man.read_text(encoding="utf-8-sig"))
            creator = str(data.get("creator") or "").strip()
            if creator:
                return creator
        except Exception:  # noqa: BLE001
            pass
    folder = path.parent.parent.name.replace("_", " ").strip()
    return folder if folder.lower() != "output" else ""


class ClipRow(QFrame):
    """Satu klip: checkbox pilih, judul, meta, kotak edit headline."""

    toggled = Signal()

    def __init__(self, clip: dict[str, Any], folder: Path):
        super().__init__()
        self.setObjectName("clipRow")
        try:
            self.clip_id = int(clip.get("id_klip"))
        except (TypeError, ValueError):
            self.clip_id = 0

        self.judul = str(clip.get("judul_relevan") or "").strip()
        # Default TERPILIH untuk manifest lama yang belum punya field `pilih`, supaya
        # membuka file lama di panel ini tidak diam-diam mematikan klip.
        pilih = clip.get("pilih")
        pilih = True if pilih is None else bool(pilih)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(10)
        self.check = QCheckBox(f"{self.clip_id}")
        self.check.setObjectName("clipCheck")
        self.check.setChecked(pilih)
        self.check.setToolTip("Centang = klip ini diunduh dan dirender")
        self.check.stateChanged.connect(lambda _=0: self.toggled.emit())
        top.addWidget(self.check)

        title = QLabel(self.judul or "(tanpa judul)")
        title.setObjectName("clipTitle")
        title.setWordWrap(True)
        top.addWidget(title, 1)
        layout.addLayout(top)

        # Meta: skor, durasi, rentang waktu, dan status file NYATA.
        mp4, srt = clip_status(folder, self.clip_id)
        try:
            durasi = float(clip.get("durasi_detik") or 0)
        except (TypeError, ValueError):
            durasi = 0.0
        try:
            skor = float(clip.get("score") or 0)
        except (TypeError, ValueError):
            skor = 0.0
        bits = [
            f"skor {skor:.0f}",
            f"{durasi:.0f}s",
            f"{clip.get('start_klip', '?')} → {clip.get('end_klip', '?')}",
        ]
        # Status ditulis apa adanya, termasuk kondisi ganjil (MP4 ada tapi SRT belum),
        # supaya user tahu tahap mana yang belum jalan untuk klip itu.
        bits.append("MP4 ✓" if mp4 else "MP4 –")
        bits.append("SRT ✓" if srt else "SRT –")
        meta = QLabel("  ·  ".join(bits))
        meta.setObjectName("clipMeta")
        layout.addWidget(meta)

        # DUA kolom headline (permintaan user 2026-08-30):
        #  - "Gemini": teks asli dari kurasi, READ-ONLY tapi bisa disalin. Ini yang
        #    menjaga usulan Gemini tetap utuh — dulu satu kotak dipakai bersama, jadi
        #    mengetik manual berarti menghapus usulan itu tanpa cara mengembalikannya.
        #  - "Headline": kotak yang benar-benar dipakai render. Kosong = ikut kolom Gemini.
        gem_row = QHBoxLayout()
        gem_row.setSpacing(8)
        gem_label = QLabel("Gemini")
        gem_label.setObjectName("clipFieldLabel")
        gem_label.setFixedWidth(64)
        gem_row.addWidget(gem_label)
        self.gemini_text = QLineEdit(self.judul)
        self.gemini_text.setObjectName("geminiText")
        self.gemini_text.setReadOnly(True)
        self.gemini_text.setPlaceholderText("(kurasi tidak memberi judul)")
        self.gemini_text.setToolTip(
            "Usulan Gemini dari file kurasi. Tidak bisa diedit di sini supaya tidak "
            "hilang; salin isinya ke kotak Headline kalau mau dipakai/diubah."
        )
        gem_row.addWidget(self.gemini_text, 1)
        self.copy_btn = QPushButton("Salin →")
        self.copy_btn.setObjectName("modeBtn")
        self.copy_btn.setFixedWidth(70)
        self.copy_btn.setToolTip("Salin usulan Gemini ke kotak Headline untuk diedit")
        self.copy_btn.clicked.connect(self._copy_gemini)
        gem_row.addWidget(self.copy_btn)
        layout.addLayout(gem_row)

        hl_row = QHBoxLayout()
        hl_row.setSpacing(8)
        hl_label = QLabel("Headline")
        hl_label.setObjectName("clipFieldLabel")
        hl_label.setFixedWidth(64)
        hl_row.addWidget(hl_label)
        self.headline = QLineEdit(str(clip.get("headline") or "").strip())
        # Placeholder = judul_relevan: user langsung tahu apa yang dipakai kalau dikosongkan.
        # Default headline SENGAJA judul_relevan, bukan `hook` (hook = kutipan transkrip
        # ~130 karakter yang akan mengecil drastis kena auto-fit).
        self.headline.setPlaceholderText(self.judul or "(ikut judul klip)")
        self.headline.setClearButtonEnabled(True)
        hl_row.addWidget(self.headline, 1)
        layout.addLayout(hl_row)

        desc = str(clip.get("deskripsi") or "").strip()
        if desc:
            d = QLabel(desc)
            d.setObjectName("clipDesc")
            d.setWordWrap(True)
            layout.addWidget(d)

        self._sync_dim()
        self.check.stateChanged.connect(lambda _=0: self._sync_dim())

    def _copy_gemini(self) -> None:
        """Salin usulan Gemini ke kotak Headline supaya bisa diedit.

        Dipilih daripada tombol yang menimpa langsung: user melihat isinya masuk ke
        kotak editnya dan tetap bisa membatalkan dengan mengosongkan kotak itu.
        """
        self.headline.setText(self.gemini_text.text())
        self.headline.setFocus()

    def _sync_dim(self) -> None:
        """Klip yang tidak dipilih diredupkan — status terbaca tanpa perlu membaca teks."""
        self.setProperty("off", not self.check.isChecked())
        self.style().unpolish(self)
        self.style().polish(self)

    def decision(self) -> tuple[bool, str]:
        return (self.check.isChecked(), self.headline.text().strip())


class ReviewPanel(QWidget):
    """Panel review: muat file kurasi, pilih klip, edit headline, simpan."""

    continue_requested = Signal(str)  # path file kurasi yang sudah disimpan
    selection_changed = Signal()      # jumlah klip terpilih / file dimuat berubah
    creator_changed = Signal(str)     # nama creator video yang sedang dimuat

    def __init__(self, output_root: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.output_root = Path(output_root)
        self.path: Path | None = None
        self.data: dict[str, Any] | None = None
        self.rows: list[ClipRow] = []
        self.creator: str = ""   # creator video yang sedang dimuat (untuk watermark)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.file_label = QLabel("Belum ada file kurasi dimuat")
        self.file_label.setObjectName("hint")
        head.addWidget(self.file_label, 1)

        # Daftar hasil pindai: sekali klik, tanpa menjelajah folder. Dialog file tetap
        # ada untuk file di luar folder output.
        self.picker = QComboBox()
        self.picker.setMinimumWidth(300)
        self.picker.setToolTip("Hasil curation yang ada di folder output/")
        self.picker.activated.connect(self._pick_from_list)
        head.addWidget(self.picker)

        self.refresh_btn = QPushButton("⟳")
        self.refresh_btn.setObjectName("ghostButton")
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.setFixedWidth(36)
        self.refresh_btn.setToolTip("Pindai ulang folder output/")
        self.refresh_btn.clicked.connect(self.refresh_list)
        head.addWidget(self.refresh_btn)

        self.load_btn = QPushButton("File lain…")
        self.load_btn.setObjectName("ghostButton")
        self.load_btn.setCursor(Qt.PointingHandCursor)
        self.load_btn.clicked.connect(self.pick_file)
        head.addWidget(self.load_btn)
        outer.addLayout(head)

        # ---- Baris KREATOR: berlaku untuk SEMUA klip di file kurasi ini ----
        # Pola sengaja dibuat sama dengan kolom Gemini/Headline per klip, tapi satu
        # tingkat di atasnya: satu video = satu kreator, jadi tidak ada gunanya per klip.
        # Kiri = nama channel asli (read-only, bisa dicopy). Kanan = ketikan user; kalau
        # diisi, itu yang dipakai WATERMARK. Nama folder output TIDAK ikut berubah.
        crow = QHBoxLayout()
        crow.setSpacing(8)

        lbl_ch = QLabel("Channel")
        lbl_ch.setObjectName("clipFieldLabel")
        lbl_ch.setFixedWidth(64)
        crow.addWidget(lbl_ch)

        self.channel_box = QLineEdit()
        self.channel_box.setReadOnly(True)
        self.channel_box.setObjectName("geminiText")
        self.channel_box.setPlaceholderText("(nama channel dari YouTube)")
        self.channel_box.setToolTip(
            "Nama channel asli dari data YouTube (yt-dlp). Tidak bisa diubah di sini; "
            "boleh dicopy."
        )
        crow.addWidget(self.channel_box, 1)

        self.copy_creator_btn = QPushButton("Salin →")
        self.copy_creator_btn.setObjectName("modeBtn")
        self.copy_creator_btn.setCursor(Qt.PointingHandCursor)
        self.copy_creator_btn.setFixedWidth(70)
        self.copy_creator_btn.setToolTip("Salin nama channel ke kotak Kreator")
        self.copy_creator_btn.clicked.connect(self._copy_creator)
        crow.addWidget(self.copy_creator_btn)

        lbl_cr = QLabel("Kreator")
        lbl_cr.setObjectName("clipFieldLabel")
        lbl_cr.setFixedWidth(52)
        crow.addWidget(lbl_cr)

        self.creator_box = QLineEdit()
        self.creator_box.setPlaceholderText("kosong = ikut Channel")
        self.creator_box.setToolTip(
            "Nama yang dipakai WATERMARK untuk semua klip di file ini. Kosongkan untuk "
            "ikut nama channel asli. Nama folder hasil tidak ikut berubah."
        )
        self.creator_box.textChanged.connect(self._creator_typed)
        crow.addWidget(self.creator_box, 1)
        outer.addLayout(crow)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("reviewScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.holder = QWidget()
        self.holder_layout = QVBoxLayout(self.holder)
        self.holder_layout.setContentsMargins(0, 0, 0, 0)
        self.holder_layout.setSpacing(8)
        self.holder_layout.addStretch()
        self.scroll.setWidget(self.holder)
        outer.addWidget(self.scroll, 1)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.count_label = QLabel("")
        self.count_label.setObjectName("hint")
        foot.addWidget(self.count_label, 1)

        self.all_btn = QPushButton("Pilih semua")
        self.all_btn.setObjectName("ghostButton")
        self.all_btn.setCursor(Qt.PointingHandCursor)
        self.all_btn.clicked.connect(lambda: self._set_all(True))
        foot.addWidget(self.all_btn)

        self.none_btn = QPushButton("Kosongkan")
        self.none_btn.setObjectName("ghostButton")
        self.none_btn.setCursor(Qt.PointingHandCursor)
        self.none_btn.clicked.connect(lambda: self._set_all(False))
        foot.addWidget(self.none_btn)

        self.save_btn = QPushButton("Simpan")
        self.save_btn.setObjectName("ghostButton")
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.clicked.connect(self.save)
        foot.addWidget(self.save_btn)

        self.next_btn = QPushButton("Simpan & lanjut ke Download")
        self.next_btn.setObjectName("primaryButton")
        self.next_btn.setCursor(Qt.PointingHandCursor)
        self.next_btn.clicked.connect(self.save_and_continue)
        foot.addWidget(self.next_btn)
        outer.addLayout(foot)

        self._set_enabled(False)
        self.refresh_list()

    # ---------- muat ----------
    def refresh_list(self) -> None:
        """Pindai `output/` dan isi dropdown. Terbaru dulu.

        Label memuat jumlah klip dan berapa yang dicentang, supaya user tahu file mana
        yang sudah direview tanpa harus membukanya satu-satu.
        """
        self.picker.blockSignals(True)
        self.picker.clear()
        self._files: list[Path] = []
        for p in scan_curation_files(self.output_root):
            try:
                d = load_curation(p)
            except Exception:  # noqa: BLE001
                # File rusak/format lain: lewati diam-diam, jangan gagalkan seluruh daftar.
                continue
            klip = [c for c in d.get("daftar_klip", []) if isinstance(c, dict)]
            dipilih = sum(1 for c in klip if c.get("pilih") is not False)
            judul = str(d.get("judul_video") or p.stem)[:42]
            tgl = datetime.fromtimestamp(p.stat().st_mtime).strftime("%d/%m %H:%M")
            self.picker.addItem(f"{judul} · {dipilih}/{len(klip)} klip · {tgl}")
            self._files.append(p)
        if not self._files:
            self.picker.addItem("(belum ada hasil curation)")
        self.picker.setCurrentIndex(-1 if self._files else 0)
        self.picker.blockSignals(False)

    def _pick_from_list(self, idx: int) -> None:
        if 0 <= idx < len(getattr(self, "_files", [])):
            self.load_file(self._files[idx])

    def pick_file(self) -> None:
        start = self.output_root if self.output_root.is_dir() else Path.home()
        fn, _ = QFileDialog.getOpenFileName(
            self, "Pilih file kurasi (hasil Curation)", str(start),
            "File kurasi (*.json);;Semua file (*.*)",
        )
        if fn:
            self.load_file(Path(fn))

    def load_file(self, path: Path) -> bool:
        path = Path(path)
        if not is_curation_file(path):
            QMessageBox.warning(
                self, "Bukan file kurasi",
                f"{path.name} adalah manifest tahap lain, bukan hasil Curation.\n"
                "File kurasi namanya <video_id>.json.",
            )
            return False
        try:
            data = load_curation(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Gagal membaca", f"{path.name}\n\n{exc}")
            return False

        self.path = path
        self.data = data
        self._rebuild_rows()
        judul = str(data.get("judul_video") or path.stem)
        self.creator = creator_from_curation(path)
        # Isi dua kotak Kreator. `blockSignals` supaya pengisian program tidak dianggap
        # ketikan user (yang akan memancarkan creator_changed dua kali).
        self.channel_box.setText(self.creator)
        self.creator_box.blockSignals(True)
        self.creator_box.setText(str(data.get("creator_watermark") or "").strip())
        self.creator_box.blockSignals(False)
        label = f"{judul}  ·  {path.name}"
        if self.creator:
            label = f"{self.creator}  ·  {label}"
        self.file_label.setText(label)
        self.file_label.setToolTip(str(path))
        self._set_enabled(True)
        self._update_count()
        # Beri tahu pemakai panel (GUI) siapa creator video ini, supaya contoh watermark
        # di preview Customize mengikuti video yang SEDANG dipilih — bukan yang terbaru.
        # Yang dikirim adalah nama EFEKTIF (ketikan user kalau ada), bukan channel mentah.
        self.creator_changed.emit(self.effective_creator())
        return True

    def _clear_rows(self) -> None:
        for row in self.rows:
            self.holder_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self.rows = []

    def _rebuild_rows(self) -> None:
        self._clear_rows()
        folder = self.path.parent if self.path else Path(".")
        clips = [c for c in (self.data or {}).get("daftar_klip", []) if isinstance(c, dict)]
        # Urutkan berdasarkan id_klip supaya urutan tampilan = urutan nomor file output.
        clips.sort(key=lambda c: int(c.get("id_klip") or 0))
        for clip in clips:
            row = ClipRow(clip, folder)
            row.toggled.connect(self._update_count)
            # Sisipkan sebelum stretch terakhir.
            self.holder_layout.insertWidget(self.holder_layout.count() - 1, row)
            self.rows.append(row)

    def _set_enabled(self, on: bool) -> None:
        for b in (self.save_btn, self.next_btn, self.all_btn, self.none_btn):
            b.setEnabled(on)
        for w in (self.creator_box, self.copy_creator_btn):
            w.setEnabled(on)

    def _copy_creator(self) -> None:
        """Isi kotak Kreator dengan nama channel asli, siap diedit."""
        self.creator_box.setText(self.channel_box.text().strip())

    def _creator_typed(self, _txt: str) -> None:
        """Ketikan Kreator -> contoh watermark di preview Customize ikut berubah.

        Dikirim langsung (tanpa menunggu Simpan) supaya user melihat efeknya seketika;
        yang disimpan ke file tetap hanya saat Simpan ditekan.
        """
        self.creator_changed.emit(self.effective_creator())

    def effective_creator(self) -> str:
        """Nama yang akan dipakai watermark: ketikan user kalau ada, kalau tidak channel."""
        return self.creator_box.text().strip() or self.creator

    def _set_all(self, on: bool) -> None:
        for row in self.rows:
            row.check.setChecked(on)
        self._update_count()

    def _update_count(self) -> None:
        total = len(self.rows)
        picked = sum(1 for r in self.rows if r.check.isChecked())
        nums = ", ".join(str(r.clip_id) for r in self.rows if r.check.isChecked())
        txt = f"{picked} dari {total} klip dipilih"
        if picked:
            txt += f"  ·  nomor {nums}"
        self.count_label.setText(txt)
        # Tanpa klip terpilih tidak ada yang bisa diunduh — tutup jalannya, jangan
        # biarkan user menekan lalu bingung kenapa Stage 2 tidak menghasilkan apa pun.
        self.next_btn.setEnabled(bool(self.rows) and picked > 0)
        self.selection_changed.emit()

    # ---------- simpan ----------
    def decisions(self) -> dict[int, tuple[bool, str]]:
        return {r.clip_id: r.decision() for r in self.rows}

    def save(self) -> bool:
        if not (self.path and self.data):
            return False
        try:
            apply_decisions(
                self.data, self.decisions(),
                creator_watermark=self.creator_box.text(),
            )
            save_curation(self.path, self.data)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Gagal menyimpan", f"{self.path}\n\n{exc}")
            return False
        picked = sum(1 for r in self.rows if r.check.isChecked())
        self.file_label.setText(
            f"{self.file_label.text().split('  ·  ')[0]}  ·  "
            f"{self.path.name}  ·  tersimpan ({picked} klip)"
        )
        return True

    def save_and_continue(self) -> None:
        if self.save() and self.path:
            self.continue_requested.emit(str(self.path))


REVIEW_QSS = """
#clipRow {
    background: rgba(255,255,255,0.045);
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 14px;
}
#clipRow[off="true"] {
    background: rgba(255,255,255,0.015);
    border-color: rgba(255,255,255,0.06);
}
#clipRow[off="true"] #clipTitle { color: #6B7C93; }
#clipTitle { font-size: 13.5px; font-weight: 800; color: #EAF2FF; }
#clipMeta { font-size: 11px; color: #8FA5BF; }
#clipDesc { font-size: 11.5px; color: #8FA5BF; }
#clipFieldLabel { font-size: 11px; font-weight: 800; color: #8FA5BF; }
#clipCheck { font-size: 13px; font-weight: 900; color: #72E8FF; }
/* Kolom usulan Gemini: read-only, dibedakan warnanya supaya jelas ini BUKAN kotak
   yang dipakai render — tapi tetap bisa diseleksi & disalin. */
#geminiText {
    background: rgba(255,255,255,0.03);
    color: #9FB4CC;
    border-style: dashed;
}
#reviewScroll { background: transparent; }
#modeBtn {
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 10px;
    padding: 7px 14px;
    color: #8FA5BF;
    font-weight: 800;
    font-size: 11.5px;
}
#modeBtn:hover { background: rgba(255,255,255,0.10); color: #EAF2FF; }
#modeBtn:checked {
    background: rgba(114,232,255,0.16);
    border-color: #72E8FF;
    color: #72E8FF;
}
#capacityHint { font-size: 11px; color: #8FA5BF; }
#capacityWarn { font-size: 11px; font-weight: 800; color: #FACC15; }
/* QSpinBox: tombol naik/turun HARUS diberi tempat sendiri.
   Tanpa aturan sub-control di bawah, Qt menggambar panah default di atas area teks —
   di tema gelap ini hasilnya panah menutupi angka (bug yang dilaporkan user
   2026-08-30: "ada glitch up dan down nya menutupi angka").
   Yang memperbaikinya: padding-right menyisakan ruang, lalu up/down-button
   ditempatkan eksplisit di kolom itu dengan lebar tetap. */
QSpinBox {
    background: rgba(3,7,18,0.70);
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 9px;
    padding: 6px 22px 6px 8px;
    color: #EAF2FF;
}
QSpinBox:focus { border-color: #72E8FF; }
QSpinBox::up-button, QSpinBox::down-button {
    subcontrol-origin: border;
    width: 18px;
    background: rgba(255,255,255,0.06);
    border-left: 1px solid rgba(255,255,255,0.10);
}
QSpinBox::up-button {
    subcontrol-position: top right;
    border-top-right-radius: 8px;
    margin: 1px 1px 0 0;
}
QSpinBox::down-button {
    subcontrol-position: bottom right;
    border-bottom-right-radius: 8px;
    margin: 0 1px 1px 0;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background: rgba(114,232,255,0.22);
}
/* Panah digambar sebagai bentuk kecil, BUKAN ikon tema bawaan yang ukurannya
   tidak bisa dikendalikan. */
QSpinBox::up-arrow {
    width: 7px; height: 7px;
    border-left: 3px solid transparent;
    border-right: 3px solid transparent;
    border-bottom: 4px solid #9FB4CC;
}
QSpinBox::down-arrow {
    width: 7px; height: 7px;
    border-left: 3px solid transparent;
    border-right: 3px solid transparent;
    border-top: 4px solid #9FB4CC;
}
"""


class CurationSettings(QWidget):
    """Setelan Stage 1: jumlah klip + batas durasi klip.

    Batas durasi ada di sini karena ITU penentu utama berapa banyak klip yang mungkin:
    maksimum = durasi video / durasi minimal. Tanpa kontrol ini, meminta 20 klip dari
    video 14 menit dengan minimal 60s mustahil terpenuhi dan akan terlihat seperti bug.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(8)

        lbl = QLabel("Jumlah klip")
        lbl.setObjectName("clipFieldLabel")
        row.addWidget(lbl)
        self.count = QSpinBox()
        self.count.setRange(1, 40)
        self.count.setValue(5)
        # Lebar DIUKUR, bukan ditebak: `_measure_run.py` menaikkan lebar 2px sampai area
        # teks Qt (SC_SpinBoxEditField) cukup untuk nilai maksimum + ruang kursor.
        # 64px hanya menyisakan 22px area teks sedangkan "40" butuh 26px -> angka
        # terpotong (keluhan user 2026-08-31: "kotaknya masih ketutup").
        self.count.setFixedWidth(82)
        self.count.setToolTip(
            "TARGET, bukan jaminan: LLM bisa mengembalikan lebih sedikit dan "
            "kandidat bertumpuk dibuang validator."
        )
        row.addWidget(self.count)

        row.addSpacing(12)
        lbl2 = QLabel("Durasi klip")
        lbl2.setObjectName("clipFieldLabel")
        row.addWidget(lbl2)
        self.min_sec = QSpinBox()
        self.min_sec.setRange(5, 600)
        self.min_sec.setValue(60)
        self.min_sec.setSuffix("s")
        self.min_sec.setFixedWidth(108)   # "600s" butuh 52px area teks (diukur)
        self.min_sec.setToolTip(
            "Durasi minimal. Makin kecil, makin banyak klip yang mungkin dari satu video."
        )
        row.addWidget(self.min_sec)

        dash = QLabel("–")
        dash.setObjectName("clipFieldLabel")
        row.addWidget(dash)
        self.max_sec = QSpinBox()
        self.max_sec.setRange(10, 900)
        self.max_sec.setValue(240)
        self.max_sec.setSuffix("s")
        self.max_sec.setFixedWidth(108)   # "900s" butuh 52px area teks (diukur)
        row.addWidget(self.max_sec)

        row.addStretch()
        outer.addLayout(row)

        # Baris 2: TEMA (preset Stage 5) yang dipakai saat render.
        # Dropdown ini meneruskan `--preset <path>`; ia TIDAK menimpa
        # `render_preset.active.json` (milik tab Customize) — keputusan user dikunci.
        #
        # CATATAN: opsi "Subtitle 1/3 kata" DIBUANG dari sini 2026-08-30 atas permintaan
        # user. Kerapatan subtitle sekarang bagian dari THEME (Customize), dan Stage 4
        # selalu menulis SRT 1 kata/entri (`config.subtitle_target_words = 1`) sehingga
        # theme bisa menggabungkan jadi 1/3/5 kata tanpa menjalankan Stage 4 ulang.
        # Dua kontrol untuk satu hal yang sama (satu mahal, satu gratis) adalah sumber
        # kebingungan yang user sendiri tunjuk.
        row3 = QHBoxLayout()
        row3.setSpacing(8)
        lbl4 = QLabel("Tema")
        lbl4.setObjectName("clipFieldLabel")
        row3.addWidget(lbl4)
        self.theme_box = QComboBox()
        self.theme_box.setMinimumWidth(260)
        self.theme_box.setToolTip(
            "Gaya render yang dieksekusi. Simpan gaya sebagai theme di tab Customize, "
            "lalu pilih di sini. \"Draf Customize\" = isi tab Customize yang belum disimpan."
        )
        row3.addWidget(self.theme_box)
        self.theme_refresh = QPushButton("↻")
        self.theme_refresh.setObjectName("modeBtn")
        self.theme_refresh.setFixedWidth(34)
        self.theme_refresh.setToolTip("Muat ulang daftar theme")
        self.theme_refresh.clicked.connect(self.reload_themes)
        row3.addWidget(self.theme_refresh)
        row3.addStretch()
        outer.addLayout(row3)

        self.hint = QLabel("")
        self.hint.setObjectName("capacityHint")
        self.hint.setWordWrap(True)
        outer.addWidget(self.hint)

        for w in (self.count, self.min_sec, self.max_sec):
            w.valueChanged.connect(self._sync)
        self._sync()
        self.reload_themes()

    def reload_themes(self) -> None:
        """Isi dropdown tema dari Preset Library.

        Urutan (permintaan user 2026-08-30): THEME TERSIMPAN dulu, lalu "Draf Customize"
        di paling bawah. Alasannya pembagian peran yang diminta user — tab Customize untuk
        merapikan tampilan lalu MENYIMPAN sebagai theme, tab Run untuk MENJALANKAN theme
        yang tersimpan. Draf tetap disediakan (kalau user memang belum menyimpan), tapi
        bukan lagi pilihan pertama.
        """
        prev = self.theme_box.currentData() if self.theme_box.count() else None
        self.theme_box.blockSignals(True)
        self.theme_box.clear()
        n_theme = 0
        try:
            import sys as _sys
            stages_dir = str(Path(__file__).resolve().parent / "stages")
            if stages_dir not in _sys.path:
                _sys.path.insert(0, stages_dir)
            import preset_library
            for e in preset_library.list_presets():
                self.theme_box.addItem(f"{e['name']} · {e['ratio']}", e["path"])
                n_theme += 1
        except Exception as exc:  # noqa: BLE001
            self.theme_box.addItem(f"(gagal memuat theme: {exc})", "")
        # Draf = isi tab Customize yang belum disimpan sebagai theme.
        self.theme_box.addItem("Draf Customize (belum disimpan)", "")
        if prev:
            i = self.theme_box.findData(prev)
            if i >= 0:
                self.theme_box.setCurrentIndex(i)
        elif n_theme:
            self.theme_box.setCurrentIndex(0)   # theme terbaru
        self.theme_box.blockSignals(False)

    def preset_path(self) -> str:
        """Path preset theme terpilih, atau "" untuk mengikuti preset aktif."""
        return str(self.theme_box.currentData() or "")

    def _sync(self) -> None:
        """Jaga max > min, dan tampilkan durasi video minimum yang dibutuhkan.

        Angka yang ditampilkan adalah konsekuensi matematis dari setelan, bukan tebakan:
        n klip @ min detik butuh video minimal n*min detik. Ini mencegah user meminta
        20 klip dari video 14 menit lalu menganggap hasilnya bug.
        """
        if self.max_sec.value() <= self.min_sec.value():
            self.max_sec.setValue(self.min_sec.value() + 10)
        n = self.count.value()
        lo = self.min_sec.value()
        butuh = n * lo
        self.hint.setText(
            f"{n} klip @ minimal {lo}s butuh video minimal {butuh // 60}m {butuh % 60}s. "
            f"Video 15m maksimal {900 // lo} klip, video 30m maksimal {1800 // lo} klip."
        )

    def values(self) -> tuple[int, int, int]:
        return (self.count.value(), self.min_sec.value(), self.max_sec.value())

    def subtitle_words(self) -> int:
        """Kerapatan SRT yang diminta ke Stage 4.

        SELALU 1 sejak 2026-08-30: SRT ditulis sehalus mungkin sekali saja, lalu THEME
        yang menentukan tampilannya (1/3/5 kata) tanpa perlu Stage 4 ulang. Dropdown
        "Subtitle" di tab Run sudah dibuang; method ini dipertahankan supaya pemanggil
        di `clipper_gui.py` tidak perlu tahu soal perubahan itu.
        """
        return 1


class ModeToggle(QWidget):
    """Auto (sekali klik sampai render) vs Manual (berhenti setelah curation).

    Jalur sekali klik WAJIB tetap ada — permintaan eksplisit user.
    """

    changed = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self.auto_btn = QPushButton("Auto")
        self.manual_btn = QPushButton("Manual")
        for b in (self.auto_btn, self.manual_btn):
            b.setObjectName("modeBtn")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            row.addWidget(b)

        self.auto_btn.setChecked(True)
        self.auto_btn.setToolTip("Sekali klik: curation → download → subtitle → render")
        self.manual_btn.setToolTip(
            "Berhenti setelah curation supaya bisa pilih klip & edit headline"
        )
        self.auto_btn.clicked.connect(lambda: self._set("auto"))
        self.manual_btn.clicked.connect(lambda: self._set("manual"))

        self.desc = QLabel("")
        self.desc.setObjectName("capacityHint")
        row.addWidget(self.desc, 1)
        self._set("auto")

    def _set(self, mode: str) -> None:
        self.mode = mode
        self.auto_btn.setChecked(mode == "auto")
        self.manual_btn.setChecked(mode == "manual")
        self.desc.setText(
            "Langsung jadi video sampai selesai."
            if mode == "auto"
            else "Berhenti setelah curation — klip muncul di Review klip untuk dipilih."
        )
        self.changed.emit(mode)

