from __future__ import annotations

import os
import re
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from PySide6.QtCore import QProcess, Qt, Signal, QObject, Slot, QUrl, QTimer, QElapsedTimer, QEvent
from PySide6.QtGui import QFont, QIcon, QDesktopServices, QColor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


APP_NAME = "Clipper Agent"
PROJECT_ROOT = Path(__file__).resolve().parent
# Interpreter Python untuk QProcess (main.py & render_with_preset.py).
# Urutan prioritas ada di `bundled_paths.resolve_python_exe()`:
#   1. python-embed/python.exe        (dibawa installer portabel)
#   2. .venv/Scripts/python.exe       (perilaku lama di folder pengembangan)
#   3. sys.executable                 (jaring terakhir)
# Di hasil installer `.venv` MASIH ADA tapi `pyvenv.cfg`-nya menunjuk Python yang
# tidak terpasang di komputer tujuan, jadi python-embed HARUS menang.
from bundled_paths import (  # noqa: E402  (butuh PROJECT_ROOT di atas)
    MODEL_BUNDLE_WARNING,
    model_bundle_status,
    resolve_python_exe,
)

PYTHON_EXE = resolve_python_exe(PROJECT_ROOT)
MAIN_PY = PROJECT_ROOT / "main.py"
CUSTOMIZER_HTML = PROJECT_ROOT / "sketches" / "clipper-ui-mockup" / "index.html"
PRESETS_DIR = PROJECT_ROOT / "assets" / "presets"
RENDER_WITH_PRESET = PROJECT_ROOT / "render_with_preset.py"
FINAL_ROOT = PROJECT_ROOT / "final"
OUTPUT_ROOT = PROJECT_ROOT / "output"
SETTINGS_PATH = PROJECT_ROOT / "assets" / "gui_settings.json"
# Nama file caption dibaca dari modul yang MENULISNYA, supaya tidak ada dua sumber
# kebenaran kalau namanya diubah nanti.
from stages.caption_txt import CAPTION_FILENAME  # noqa: E402

from gui_review import (  # noqa: E402  (butuh PROJECT_ROOT di atas)
    REVIEW_QSS,
    CurationSettings,
    LanguagePicker,
    ModeToggle,
    ReviewPanel,
    ThemesCard,
    vertical_separator,
)
from gui_logparse import (  # noqa: E402
    classify_log_line,
    extract_output_dir,
    normalize_youtube_url,
    parse_clip_progress,
    parse_clip_total,
)


def read_language() -> str:
    """Bahasa UI tersimpan ('id' atau 'en'). Default 'id'."""
    try:
        if SETTINGS_PATH.exists():
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                code = str(data.get("language") or "id").lower()
                return "en" if code.startswith("en") else "id"
    except Exception:
        pass
    return "id"


# Terjemahan untuk widget Qt (halaman Run/History/Settings).
# Bagian Customize (HTML) punya kamusnya sendiri di index.html.
TR: dict[str, dict[str, str]] = {
    "id": {
        "nav_run": "Run",
        "nav_customize": "Customize",
        "nav_history": "History",
        "nav_settings": "Settings",
        "run_title": "Buat klip dari video YouTube",
        "run_desc": "Tempel link, jalankan, video pendek siap upload.",
        "url_label": "URL YouTube",
        "paste": "Paste",
        "run": "Jalankan",
        "stop": "Hentikan",
        # `hint` sudah TIDAK dipakai widget mana pun sejak Item 26 membuang label
        # "Contoh: https://..." (placeholder kotak URL memuat contoh yang sama).
        # Kuncinya dipertahankan supaya preset bahasa/pemeriksa i18n yang membandingkan
        # kunci ID vs EN tidak melaporkan kunci hilang.
        "hint": "Contoh: https://www.youtube.com/watch?v=H-aPguC0xL0",
        "progress": "Progress",
        "ready": "Siap",
        "running": "Pipeline Berjalan...",
        "activity": "Aktivitas",
        "results": "Hasil",
        "open_folder": "Buka folder",
        "open_caption": "Buka caption",
        "history_title": "History",
        "history_desc": "Video hasil render terbaru dari folder final/",
        "rendered": "Rendered videos",
        "refresh": "Refresh",
        "open_final": "Buka folder final",
        "dbl_click": "Klik dua kali untuk memutar video.",
        "settings_title": "Settings",
        "settings_desc": "API endpoint, provider & model — auto-detect biar tidak repot",
        "language": "Bahasa",
        "stage_curation": "Curation",
        "stage_download": "Download",
        "stage_subtitle": "Subtitle",
        "stage_render": "Render",
        "stage_curation_sub": "Pilih momen",
        "stage_download_sub": "Ambil klip",
        "stage_subtitle_sub": "WhisperX",
        "stage_render_sub": "Komposisi final",
        "done": "Selesai",
        "failed": "Gagal",
    },
    "en": {
        "nav_run": "Run",
        "nav_customize": "Customize",
        "nav_history": "History",
        "nav_settings": "Settings",
        "run_title": "Turn a YouTube video into clips",
        "run_desc": "Paste a link, run it, get upload-ready shorts.",
        "url_label": "YouTube URL",
        "paste": "Paste",
        "run": "Run",
        "stop": "Stop",
        "hint": "Example: https://www.youtube.com/watch?v=H-aPguC0xL0",
        "progress": "Progress",
        "ready": "Ready",
        "running": "Pipeline running...",
        "activity": "Activity",
        "results": "Results",
        "open_folder": "Open folder",
        "open_caption": "Open caption",
        "history_title": "History",
        "history_desc": "Latest rendered videos from the final/ folder",
        "rendered": "Rendered videos",
        "refresh": "Refresh",
        "open_final": "Open final folder",
        "dbl_click": "Double-click to play a video.",
        "settings_title": "Settings",
        "settings_desc": "API endpoint, provider & model — auto-detected so you don't have to",
        "language": "Language",
        "stage_curation": "Curation",
        "stage_download": "Download",
        "stage_subtitle": "Subtitle",
        "stage_render": "Render",
        "stage_curation_sub": "Pick moments",
        "stage_download_sub": "Fetch clips",
        "stage_subtitle_sub": "WhisperX",
        "stage_render_sub": "Final composition",
        "done": "Done",
        "failed": "Failed",
    },
}


def t(key: str, lang: str | None = None) -> str:
    code = lang or read_language()
    return TR.get(code, TR["id"]).get(key, TR["id"].get(key, key))


def load_env_file(path: Path = PROJECT_ROOT / ".env") -> None:
    """Muat .env ke os.environ (tanpa menimpa yang sudah di-set).

    GUI mengecek os.getenv langsung; pydantic-settings di config.py membaca .env
    tapi tidak menaruh nilainya ke os.environ, jadi indikator & subprocess butuh ini.
    """
    if not path.exists():
        return
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except Exception:
        pass


def read_env_dict(path: Path = PROJECT_ROOT / ".env") -> dict[str, str]:
    """Baca .env jadi dict (urutan dipertahankan tidak penting di sini)."""
    data: dict[str, str] = {}
    if not path.exists():
        return data
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            data[key.strip()] = val.strip().strip('"').strip("'")
    except Exception:
        pass
    return data


def write_env_values(updates: dict[str, str], path: Path = PROJECT_ROOT / ".env") -> None:
    """Perbarui/tambah key di .env tanpa menghapus key lain & komentar."""
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()

    seen: set[str] = set()
    out: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        out.append(raw)

    for key, val in updates.items():
        if key not in seen:
            out.append(f"{key}={val}")

    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    # Segera efektif di sesi ini.
    for key, val in updates.items():
        os.environ[key] = val


def detect_models(base_url: str, api_key: str, timeout: float = 6.0) -> list[str]:
    """Ambil daftar model dari endpoint OpenAI-compatible /models."""
    import json
    import urllib.request

    base = (base_url or "").rstrip("/")
    if not base:
        return []
    url = base + "/models"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key or 'x'}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    arr = data.get("data", data if isinstance(data, list) else [])
    ids = []
    for m in arr:
        mid = m.get("id") if isinstance(m, dict) else str(m)
        if mid:
            ids.append(mid)
    return sorted(ids)


class PresetBridge(QObject):
    """Jembatan JS(WebEngine) -> Python untuk halaman Customize.

    PERAN TAB (dikunci user 2026-08-30): Customize hanya untuk MERAPIKAN tampilan lalu
    MENYIMPAN sebagai theme; eksekusi render sepenuhnya di tab Run lewat theme tersimpan.
    Karena itu `save_preset` di sini adalah AUTOSAVE DRAF, bukan perintah — ia tidak boleh
    memindahkan halaman (dulu melempar user ke tab Run setiap slider digeser).
    """

    preset_saved = Signal(str)   # draf preset ditulis (autosave)
    theme_saved = Signal(str)    # theme disimpan/ditimpa -> dropdown tab Run harus refresh
    render_requested = Signal(str)  # path preset untuk dirender
    render_clip_requested = Signal(str, int)  # path preset + nomor klip (1-based)
    language_changed = Signal(str)  # 'id' | 'en'
    creator_hint_changed = Signal(str)  # nama creator aktif berubah -> preview digambar ulang

    def __init__(self, parent=None):
        super().__init__(parent)
        # Nama creator video yang SEDANG dituju. Diisi GUI dari file kurasi yang dipilih;
        # kosong = belum ada pilihan, jatuh ke pindaian terbaru sebagai cadangan.
        self._creator_hint: str = ""

    def _write_preset(self, preset_json: str) -> Path:
        PRESETS_DIR.mkdir(parents=True, exist_ok=True)
        target = PRESETS_DIR / "render_preset.active.json"
        try:
            data = json.loads(preset_json)
            target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            target.write_text(preset_json, encoding="utf-8")
        return target

    @Slot(str)
    def save_preset(self, preset_json: str):
        path = self._write_preset(preset_json)
        self.preset_saved.emit(str(path))

    @Slot(str)
    def render_preset(self, preset_json: str):
        path = self._write_preset(preset_json)
        self.render_requested.emit(str(path))

    @Slot(str, int)
    def render_preset_clip(self, preset_json: str, clip_no: int):
        """Render HANYA satu klip (nomor 1-based) untuk uji cepat."""
        path = self._write_preset(preset_json)
        self.render_clip_requested.emit(str(path), int(clip_no))

    @Slot(result=str)
    def list_frames(self) -> str:
        """Kembalikan daftar frame (Frame Library) sebagai JSON untuk grid UI."""
        try:
            import sys as _sys
            stages_dir = str(PROJECT_ROOT / "stages")
            if stages_dir not in _sys.path:
                _sys.path.insert(0, stages_dir)
            import frame_library
            frames = frame_library.list_frames()
            # sematkan URL file:// untuk thumbnail & frame agar bisa dipakai <img src>
            for f in frames:
                tp = f.get("thumbnail_path") or ""
                fp = f.get("frame_path") or ""
                f["thumbnail_url"] = (
                    QUrl.fromLocalFile(tp).toString() if tp else ""
                )
                f["frame_url"] = QUrl.fromLocalFile(fp).toString() if fp else ""
            return json.dumps(frames, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": str(exc)})

    @Slot(result=str)
    def import_frame_dialog(self) -> str:
        """Buka dialog pilih PNG, impor jadi frame baru. Return JSON frame atau {}."""
        try:
            from PySide6.QtWidgets import QFileDialog
            fn, _ = QFileDialog.getOpenFileName(
                None, "Pilih PNG frame (1080x1920)", str(Path.home()),
                "PNG / WebP (*.png *.webp);;Semua file (*.*)"
            )
            if not fn:
                return "{}"
            import sys as _sys
            stages_dir = str(PROJECT_ROOT / "stages")
            if stages_dir not in _sys.path:
                _sys.path.insert(0, stages_dir)
            import frame_library
            meta = frame_library.import_frame(fn)
            tp = meta.get("thumbnail_path") or ""
            fp = meta.get("frame_path") or ""
            meta["thumbnail_url"] = QUrl.fromLocalFile(tp).toString() if tp else ""
            meta["frame_url"] = QUrl.fromLocalFile(fp).toString() if fp else ""
            return json.dumps(meta, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": str(exc)})


    @Slot(result=str)
    def import_overlay_dialog(self) -> str:
        """
        Pilih PNG overlay lewat dialog native dan SALIN ke assets/overlays/.

        Kenapa perlu: input <file> di halaman hanya membaca gambar ke memori browser
        (FileReader -> data URL) untuk preview. File-nya TIDAK pernah ada di disk, jadi
        `custom_png.path` di preset menunjuk file yang tidak ada dan render melewatinya
        tanpa peringatan — overlay muncul di preview tapi hilang di hasil MP4.
        """
        try:
            from PySide6.QtWidgets import QFileDialog
            fn, _ = QFileDialog.getOpenFileName(
                None, "Pilih PNG overlay", str(Path.home()),
                "PNG / WebP (*.png *.webp);;Semua file (*.*)"
            )
            if not fn:
                return "{}"
            src = Path(fn)
            dest_dir = PROJECT_ROOT / "assets" / "overlays"
            dest_dir.mkdir(parents=True, exist_ok=True)
            safe = re.sub(r"[^A-Za-z0-9._-]+", "-", src.name).strip("-") or "overlay.png"
            dest = dest_dir / safe
            n = 1
            while dest.exists() and dest.stat().st_size != src.stat().st_size:
                dest = dest_dir / f"{Path(safe).stem}-{n}{Path(safe).suffix}"
                n += 1
            shutil.copy2(src, dest)
            return json.dumps({
                "name": dest.name,
                "path": f"assets/overlays/{dest.name}",
                "url": QUrl.fromLocalFile(str(dest)).toString(),
            }, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": str(exc)})

    @Slot(str, result=str)
    def overlay_url(self, rel_path: str) -> str:
        """URL file:// untuk overlay yang sudah ada di disk (dipakai saat memuat preset)."""
        try:
            p = (PROJECT_ROOT / str(rel_path or "")).resolve()
            if not p.exists():
                return ""
            return QUrl.fromLocalFile(str(p)).toString()
        except Exception:  # noqa: BLE001
            return ""

    @Slot(result=str)
    def creator_hint(self) -> str:
        """Nama creator untuk contoh watermark di preview.

        Watermark yang dikosongkan berarti "ikut nama creator", dan nama itu ditentukan
        per video saat render (dari `manifest.creator`). Preview tidak punya konteks video,
        jadi nilai ini disuplai dari luar.

        BUG yang diperbaiki 2026-08-30: dulu fungsi ini memindai "kurasi terbaru menurut
        waktu file", jadi saat user mengerjakan video A sambil kurasi video B lebih baru,
        preview memperlihatkan nama channel yang SALAH. Sekarang sumbernya adalah file
        kurasi yang SEDANG DIPILIH di panel Review (`set_creator_hint`), dengan pindaian
        terbaru hanya sebagai cadangan saat belum ada yang dipilih.
        """
        if self._creator_hint:
            return self._creator_hint
        return self._latest_creator_from_disk()

    def set_creator_hint(self, creator: str) -> None:
        """Setel nama creator aktif (dipanggil GUI saat file kurasi dipilih).

        Memancarkan sinyal supaya halaman Customize menggambar ulang watermark — kalau
        tidak, preview tetap menampilkan nama channel sebelumnya sampai user menyentuh
        slider, dan itu wajah dari bug yang dilaporkan user.
        """
        baru = str(creator or "").strip().upper()
        if baru == self._creator_hint:
            return
        self._creator_hint = baru
        self.creator_hint_changed.emit(baru)

    @staticmethod
    def _latest_creator_from_disk() -> str:
        """Cadangan: creator dari kurasi terbaru. Hanya dipakai kalau belum ada pilihan."""
        try:
            import sys as _sys
            root = str(PROJECT_ROOT)
            if root not in _sys.path:
                _sys.path.insert(0, root)
            from gui_review import scan_curation_files

            for p in scan_curation_files(PROJECT_ROOT / "output"):
                # Nama creator tidak disimpan di file kurasi, tapi folder induknya
                # persis nama creator hasil sanitasi Stage 1 (output/<creator>/<judul>/).
                creator = p.parent.parent.name.replace("_", " ").strip()
                if creator and creator.lower() != "output":
                    return creator.upper()
        except Exception:  # noqa: BLE001
            pass
        return ""

    @Slot(str, result=str)
    def render_text_layers(self, spec_json: str) -> str:
        """
        Gambar lapisan teks untuk PREVIEW memakai MESIN YANG SAMA dengan render.

        Ini inti jaminan "preview == output": halaman tidak lagi menggambar teks sendiri
        dengan CSS (`-webkit-text-stroke` / `text-shadow` / `paint-order`), melainkan
        meminta `stages/text_engine.py` — modul yang juga dipakai Stage 5 — lalu
        menampilkan PNG hasilnya. Auto-fit, pemecahan baris, urutan lapisan, warna
        shadow, blur: semuanya dihitung sekali di satu tempat.

        spec_json: {"canvas":{"w":..,"h":..}, "blocks":{"head":{...},"wm":{...}}}
        Return JSON {"head":{"url":..,"size":..,"lines":[..]}, ...}.
        Layer di-cache ke folder temp berdasar hash parameter, jadi menggeser slider
        yang sama berulang tidak menggambar ulang.
        """
        try:
            spec = json.loads(spec_json or "{}")
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": f"spec tidak valid: {exc}"})
        try:
            import sys as _sys
            stages_dir = str(PROJECT_ROOT / "stages")
            if stages_dir not in _sys.path:
                _sys.path.insert(0, stages_dir)
            import text_engine as TE

            canvas = spec.get("canvas") or {}
            cw = int(canvas.get("w") or 1080)
            ch = int(canvas.get("h") or 1920)
            cache = Path(tempfile.gettempdir()) / "clipper_preview_layers"
            cache.mkdir(parents=True, exist_ok=True)

            # Warna outline otomatis HARUS dihitung dengan rumus yang sama seperti
            # render (stage5_preset.auto_border_color), kalau tidak preview memakai
            # hitam sementara render memakai putih untuk teks gelap.
            try:
                from stage5_preset import auto_border_color as _abc
            except Exception:  # noqa: BLE001
                _abc = None

            def auto_stroke(fill: str) -> str:
                if _abc is None:
                    return "#000000"
                v = str(_abc(fill or "#FFFFFF")).lower()
                return "#FFFFFF" if "white" in v else "#000000"

            out: dict[str, Any] = {}
            for key, blk in (spec.get("blocks") or {}).items():
                if not isinstance(blk, dict):
                    continue
                text = str(blk.get("text") or "")
                if not blk.get("enabled", True) or not text.strip():
                    out[key] = {"url": "", "size": 0, "lines": []}
                    continue
                # SUBTITLE punya jalur sendiri: `words_per_line` di render berarti entri
                # SRT dipecah jadi potongan WAKTU (bukan baris bertumpuk), dan animasi
                # word/karaoke mewarnai + membesarkan satu kata aktif. subtitle_engine
                # menghitung keadaan yang BENAR-BENAR terlihat di MP4, lalu preview
                # menampilkan lapisan itu — bukan menebak lewat CSS.
                if key == "sub":
                    import subtitle_engine as SE
                    frames = max(1, int(blk.get("_frames") or 1))
                    urls: list[str] = []
                    size = 0
                    lines: list[str] = []
                    ink: dict = {}
                    for i in range(frames):
                        sig = TE.layer_signature(
                            cw, ch, key, i,
                            json.dumps(blk, sort_keys=True),
                        )
                        png = cache / f"{key}_{sig}.png"
                        if not png.exists():
                            ink = {}
                            img, size, lines, nwords = SE.preview_spec_layers(
                                blk, text, canvas_w=cw, canvas_h=ch,
                                active_index=i,
                                auto_stroke_color=auto_stroke(str(blk.get("color") or "")),
                                ink_out=ink,
                            )
                            # compress_level HARUS sama dengan jalur render
                            # (subtitle_engine.build_layers) supaya PNG preview dan
                            # PNG render identik BYTE, bukan cuma identik piksel.
                            img.save(png, compress_level=1)
                            png.with_suffix(".json").write_text(
                                json.dumps({"size": size, "lines": lines,
                                            "words": nwords, "ink": ink}),
                                encoding="utf-8",
                            )
                        else:
                            try:
                                m = json.loads(
                                    png.with_suffix(".json").read_text(encoding="utf-8")
                                )
                                size = int(m.get("size") or 0)
                                lines = m.get("lines") or []
                                ink = m.get("ink") or {}
                            except Exception:  # noqa: BLE001
                                pass
                        urls.append(QUrl.fromLocalFile(str(png)).toString())
                    out[key] = {"url": urls[0], "urls": urls,
                                "size": size, "lines": lines, "ink": ink}
                    continue
                sig = TE.layer_signature(cw, ch, key, json.dumps(blk, sort_keys=True))
                png = cache / f"{key}_{sig}.png"
                if not png.exists():
                    ink: dict = {}
                    layer, size, lines = TE.render_block(
                        blk, canvas_w=cw, canvas_h=ch, text=text,
                        auto_stroke_color=auto_stroke(str(blk.get("color") or "")),
                        ink_out=ink,
                    )
                    layer.save(png, compress_level=1)
                    meta = {"size": size, "lines": lines, "ink": ink}
                    png.with_suffix(".json").write_text(
                        json.dumps(meta), encoding="utf-8"
                    )
                else:
                    try:
                        meta = json.loads(
                            png.with_suffix(".json").read_text(encoding="utf-8")
                        )
                    except Exception:  # noqa: BLE001
                        meta = {"size": 0, "lines": []}
                out[key] = {
                    "url": QUrl.fromLocalFile(str(png)).toString(),
                    "size": int(meta.get("size") or 0),
                    "lines": meta.get("lines") or [],
                    # Kotak tinta (piksel yang benar-benar tergambar). Dipakai UI untuk
                    # menghitung nilai `y` yang membuat blok teks PAS di tengah kanvas —
                    # tinggi blok hanya diketahui SETELAH auto-fit memilih ukuran font,
                    # jadi angkanya harus datang dari mesin, bukan ditebak di JS.
                    "ink": meta.get("ink") or {},
                }
            return json.dumps(out, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": str(exc)})

    @Slot(str, result=str)
    def delete_frame(self, frame_id: str) -> str:
        """Hapus satu frame dari library. Return JSON hasil."""
        try:
            import sys as _sys
            stages_dir = str(PROJECT_ROOT / "stages")
            if stages_dir not in _sys.path:
                _sys.path.insert(0, stages_dir)
            import frame_library
            return json.dumps(frame_library.delete_frame(frame_id), ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": str(exc)})

    # ---------- Font Library ----------
    @Slot(result=str)
    def list_fonts(self) -> str:
        """Daftar font di assets/fonts/ (+ file:// URL untuk @font-face preview)."""
        try:
            import sys as _sys
            stages_dir = str(PROJECT_ROOT / "stages")
            if stages_dir not in _sys.path:
                _sys.path.insert(0, stages_dir)
            import font_library
            fonts = font_library.list_fonts()
            for f in fonts:
                p = f.get("path") or ""
                f["url"] = QUrl.fromLocalFile(p).toString() if p else ""
            return json.dumps(fonts, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": str(exc)})

    @Slot(result=str)
    def import_font_dialog(self) -> str:
        """Dialog pilih file font (bisa banyak) -> salin ke assets/fonts/."""
        try:
            from PySide6.QtWidgets import QFileDialog
            files, _ = QFileDialog.getOpenFileNames(
                None, "Pilih font (.ttf / .otf)", str(Path.home()),
                "Font (*.ttf *.otf);;Semua file (*.*)"
            )
            if not files:
                return json.dumps({"imported": [], "errors": []})
            import sys as _sys
            stages_dir = str(PROJECT_ROOT / "stages")
            if stages_dir not in _sys.path:
                _sys.path.insert(0, stages_dir)
            import font_library
            imported, errors = [], []
            for fn in files:
                res = font_library.import_font(fn)
                if res.get("error"):
                    errors.append(f"{Path(fn).name}: {res['error']}")
                else:
                    p = res.get("path") or ""
                    res["url"] = QUrl.fromLocalFile(p).toString() if p else ""
                    imported.append(res)
            return json.dumps({"imported": imported, "errors": errors}, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": str(exc)})

    @Slot(str, result=str)
    def delete_font(self, file_name: str) -> str:
        """Hapus font tambahan (font bawaan dilindungi)."""
        try:
            import sys as _sys
            stages_dir = str(PROJECT_ROOT / "stages")
            if stages_dir not in _sys.path:
                _sys.path.insert(0, stages_dir)
            import font_library
            return json.dumps(font_library.delete_font(file_name), ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": str(exc)})

    @Slot(str, result=bool)
    def confirm(self, message: str) -> bool:
        """Konfirmasi native (dipakai sebelum hapus frame/font)."""
        try:
            from PySide6.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                None, "Konfirmasi", message,
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            return reply == QMessageBox.Yes
        except Exception:  # noqa: BLE001
            return False

    @Slot(result=str)
    def open_fonts_folder(self) -> str:
        """Buka assets/fonts/ di file explorer supaya user bisa drop font sendiri."""
        try:
            fonts_dir = PROJECT_ROOT / "assets" / "fonts"
            fonts_dir.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(fonts_dir)))
            return json.dumps({"opened": str(fonts_dir)})
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": str(exc)})

    # ---------- Preset Library (theme tersimpan) ----------
    def _preset_lib(self):
        import sys as _sys
        stages_dir = str(PROJECT_ROOT / "stages")
        if stages_dir not in _sys.path:
            _sys.path.insert(0, stages_dir)
        import preset_library
        return preset_library

    @Slot(result=str)
    def list_presets(self) -> str:
        try:
            return json.dumps(self._preset_lib().list_presets(), ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": str(exc)})

    @Slot(str, str, str, result=str)
    def save_preset_as(self, preset_json: str, name: str, preset_id: str) -> str:
        """Simpan preset sekarang sebagai theme bernama di library.

        Nama ganda DITOLAK (lihat preset_library.save_preset): hasilnya
        {"error":..,"exists":<id>} dan halaman menawarkan timpa/ganti nama.
        """
        try:
            data = json.loads(preset_json)
            res = self._preset_lib().save_preset(data, name, preset_id or None)
            if res.get("id") and not res.get("error"):
                # Beri tahu tab Run: dropdown theme harus memuat ulang, kalau tidak theme
                # yang baru disimpan tidak muncul sampai user menekan ↻ atau restart.
                self.theme_saved.emit(str(res.get("id")))
            return json.dumps(res, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": str(exc)})

    @Slot(str, str, str, result=str)
    def overwrite_theme(self, preset_json: str, name: str, preset_id: str) -> str:
        """Simpan theme dengan MENIMPA yang sudah ada (setelah user mengonfirmasi)."""
        try:
            data = json.loads(preset_json)
            res = self._preset_lib().save_preset(
                data, name, preset_id or None, overwrite=True)
            if res.get("id") and not res.get("error"):
                self.theme_saved.emit(str(res.get("id")))
            return json.dumps(res, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": str(exc)})

    @Slot(str, result=str)
    def load_theme(self, preset_id: str) -> str:
        """Ambil isi preset sebuah theme untuk diterapkan ke UI."""
        try:
            return json.dumps(self._preset_lib().load_preset_entry(preset_id),
                              ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": str(exc)})

    @Slot(str, result=str)
    def delete_theme(self, preset_id: str) -> str:
        try:
            return json.dumps(self._preset_lib().delete_preset(preset_id),
                              ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": str(exc)})

    @Slot(str, str, result=str)
    def rename_theme(self, preset_id: str, name: str) -> str:
        try:
            return json.dumps(self._preset_lib().rename_preset(preset_id, name),
                              ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": str(exc)})

    @Slot(result=str)
    def active_preset(self) -> str:
        """Preset aktif (`render_preset.active.json`) untuk dimuat halaman saat boot.

        Perlu sejak tombol "Terapkan" dibuang (2026-08-30): kalau halaman selalu mulai
        dari default mockup, auto-apply akan MENIMPA preset aktif dengan default itu
        beberapa detik setelah Customize dibuka — gaya user hilang tanpa ia menyentuh
        apa pun. Memuat preset dari disk membuat halaman melanjutkan keadaan terakhir.
        """
        target = PRESETS_DIR / "render_preset.active.json"
        try:
            if not target.exists():
                return "{}"
            return target.read_text(encoding="utf-8-sig")
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": str(exc)})

    @Slot(result=str)
    def list_canvas_presets(self) -> str:
        """Daftar ukuran canvas/rasio umum (9:16, 4:5, 1:1, 16:9, ...)."""
        try:
            import sys as _sys
            stages_dir = str(PROJECT_ROOT / "stages")
            if stages_dir not in _sys.path:
                _sys.path.insert(0, stages_dir)
            import stage5_preset
            return json.dumps(stage5_preset.CANVAS_PRESETS, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": str(exc)})

    @Slot(str, str, result=str)
    def prompt_text(self, message: str, default: str) -> str:
        """Input teks native (dipakai untuk memberi nama theme)."""
        try:
            from PySide6.QtWidgets import QInputDialog
            text, ok = QInputDialog.getText(None, "Clipper", message, text=default or "")
            return json.dumps({"ok": bool(ok), "text": text if ok else ""})
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"ok": False, "error": str(exc)})

    @Slot(str, result=str)
    def set_language(self, lang: str) -> str:
        """Simpan pilihan bahasa UI (id / en) supaya persist antar sesi."""
        try:
            code = "en" if str(lang).lower().startswith("en") else "id"
            SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            if SETTINGS_PATH.exists():
                try:
                    data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8-sig"))
                except Exception:
                    data = {}
            if not isinstance(data, dict):
                data = {}
            data["language"] = code
            SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
            self.language_changed.emit(code)
            return json.dumps({"language": code})
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": str(exc)})

    @Slot(result=str)
    def get_language(self) -> str:
        return json.dumps({"language": read_language()})


def _ink_box(layer) -> dict:
    """Fallback kotak tinta dari bbox LAPISAN (termasuk shadow).

    Dipakai hanya kalau jalur `ink_out` tidak tersedia. Angkanya kurang tepat untuk
    pemusatan karena shadow/blur melebarkan bbox — `text_engine.measure_ink()` yang
    mengukur fill+stroke saja adalah sumber yang benar.
    """
    try:
        bbox = layer.getbbox()
    except Exception:  # noqa: BLE001
        return {}
    if not bbox:
        return {}
    x0, y0, x1, y1 = (int(v) for v in bbox)
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0,
            "cx": (x0 + x1) // 2, "cy": (y0 + y1) // 2}


class NoZoomFilter(QObject):
    """
    Cegah zoom SELURUH halaman UI, alihkan ctrl+wheel ke zoom PREVIEW.

    bug.txt P1.5: pinch touchpad / ctrl+wheel dulu men-zoom seluruh jendela web
    (panel, slider, teks) sehingga layout Customize rusak.

    Kenapa filter Qt ini TIDAK cukup sendirian: gestur pinch touchpad dan
    ctrl+wheel sebagian ditangani DI DALAM Chromium, dan halaman juga perlu tahu
    arah gulirannya untuk menaikkan/menurunkan zoom preview. Jadi pencegahan
    dilakukan di DUA lapis — `wheel` listener non-passive di halaman
    (`initZoomGesture()` di j6.js, satu-satunya yang bisa `preventDefault()`)
    plus filter ini sebagai jaring untuk ctrl+plus/minus/0 dan wheel yang lolos
    sebelum halaman siap. Menghapus salah satunya memunculkan kembali bug lama.
    """

    def eventFilter(self, obj, event):  # noqa: N802
        etype = event.type()
        if etype == QEvent.Wheel:
            if event.modifiers() & Qt.ControlModifier:
                return True  # telan: jangan zoom halaman
        elif etype == QEvent.KeyPress:
            if event.modifiers() & Qt.ControlModifier and event.key() in (
                Qt.Key_Plus, Qt.Key_Minus, Qt.Key_Equal, Qt.Key_0,
            ):
                return True
        return super().eventFilter(obj, event)


class StageCard(QFrame):
    def __init__(self, number: str, title: str, subtitle: str):
        super().__init__()
        self.setObjectName("stageCard")
        self.number = number
        self.title = QLabel(title)
        self.subtitle = QLabel(subtitle)
        self.status = QLabel("○")
        self.status.setObjectName("stageStatus")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        top = QHBoxLayout()
        badge = QLabel(number)
        badge.setObjectName("stageBadge")
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedSize(26, 26)
        top.addWidget(badge)
        top.addStretch()
        top.addWidget(self.status)
        layout.addLayout(top)

        self.title.setObjectName("stageTitle")
        self.subtitle.setObjectName("stageSubtitle")

        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)

    def set_state(self, state: str):
        marks = {"waiting": "○", "running": "◐", "done": "●", "error": "✕"}
        self.status.setText(marks.get(state, "○"))
        self.setProperty("state", state)
        self.status.setProperty("state", state)
        self.style().unpolish(self)
        self.style().polish(self)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)


class SidebarButton(QPushButton):
    def __init__(self, text: str):
        super().__init__(text)
        self.setCheckable(True)
        self.setObjectName("sidebarButton")
        self.setCursor(Qt.PointingHandCursor)


class ClipperWindow(QMainWindow):
    log_signal = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1500, 920)
        self.setMinimumSize(1180, 760)

        self.process: QProcess | None = None
        self.current_mode = "pipeline"
        self._pending_manual = False  # True saat jalur Manual (Stage 1 saja) berjalan
        self._user_stopped = False    # True kalau proses berakhir karena tombol Hentikan
        # Satu-satunya sumber kebenaran "sedang berjalan" untuk `_refresh_run_enabled()`.
        self._running = False
        # Progres per-klip: stage yang sedang jalan + hitungan klipnya.
        self._stage_key = ""
        self._clip_total = 0
        self._clip_done = 0
        self.stage_cards: dict[str, StageCard] = {}
        self.system_status = QLabel()  # kept for status updates; not shown in topbar
        self.system_status.setVisible(False)

        self.build_ui()
        self.apply_styles()
        self.refresh_status()
        # Isi panel Hasil dengan hasil render terakhir supaya tidak kosong tanpa alasan
        # saat app baru dibuka.
        self.populate_results(self._latest_final_dir())

    # ---------- UI ----------
    def build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)

        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        topbar = self.build_topbar()
        outer.addWidget(topbar)

        content = QWidget()
        content.setObjectName("contentArea")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.stack = QStackedWidget()
        self.dashboard = self.build_dashboard()
        self.pages = {
            "Run": self.dashboard,
            "Customize": self.build_stage5_page(),
            "History": self.build_history_page(),
            "Settings": self.build_settings_page(),
        }

        for page in self.pages.values():
            self.stack.addWidget(page)

        content_layout.addWidget(self.stack, 1)
        outer.addWidget(content, 1)

    def build_topbar(self):
        bar = QFrame()
        bar.setObjectName("topbar")
        bar.setFixedHeight(60)

        row = QHBoxLayout(bar)
        row.setContentsMargins(26, 0, 26, 0)
        row.setSpacing(6)

        brand = QLabel("Clipper")
        brand.setObjectName("brand")
        row.addWidget(brand)
        badge = QLabel("Agent")
        badge.setObjectName("brandBadge")
        row.addWidget(badge)

        row.addStretch()

        self.nav_buttons: list[QPushButton] = []
        nav_items = ["Run", "Customize", "History", "Settings"]
        for i, name in enumerate(nav_items):
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setObjectName("navTab")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, idx=i: self.switch_page(idx))
            if i == 0:
                btn.setChecked(True)
            self.nav_buttons.append(btn)
            row.addWidget(btn)

        # Toggle bahasa: sejajar dengan Run/Customize/History/Settings (permintaan user).
        row.addSpacing(10)
        self.lang_buttons: list[QPushButton] = []
        cur_lang = read_language()
        for code, label in (("id", "ID"), ("en", "EN")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setObjectName("langTab")
            b.setCursor(Qt.PointingHandCursor)
            b.setChecked(code == cur_lang)
            b.clicked.connect(lambda checked=False, c=code: self.set_language(c))
            self.lang_buttons.append(b)
            row.addWidget(b)

        row.addSpacing(14)
        self.gemini_status = QLabel("● API")
        self.gemini_status.setObjectName("statusText")
        row.addWidget(self.gemini_status)

        return bar

    # ---------- Tab Run: sidebar per MOMEN KERJA ----------
    # Sengaja BUKAN per tahap pipeline (Curation/Download/Subtitle/Render): dua dari empat
    # tahap itu belum punya setelan apa pun (Download & Render), jadi menunya akan kosong —
    # persis pola "UI hiasan" yang sudah ditolak user. Selain itu kartu progres sudah
    # memakai nama tahap, jadi sidebar bernama sama = dua benda mirip dengan arti berbeda.
    RUN_PANELS = ("Jalankan", "Review", "Progres", "Hasil")

    def _scroll_wrap(self, inner: QWidget) -> QScrollArea:
        """Bungkus panel dalam area scroll.

        WAJIB untuk tiap panel: tanpa ini, isi yang lebih tinggi dari jendela tidak
        digeser melainkan saling menindih (bug yang dilaporkan user 2026-08-29 —
        baris jumlah klip/durasi/subtitle bertumpuk dan terpotong).
        """
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setWidget(inner)
        return sc

    def build_dashboard(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Strip status: SELALU terlihat saat ada proses jalan, apa pun panel yang dibuka.
        # Tanpa ini, membuka panel lain membuat user kehilangan pandangan atas proses —
        # padahal Stage 4 makan ~2 menit per klip dan mudah disangka menggantung.
        outer.addWidget(self._build_status_strip())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        body.addWidget(self._build_run_sidebar())

        self.run_stack = QStackedWidget()
        self.run_stack.addWidget(self._scroll_wrap(self._build_panel_jalankan()))
        self.run_stack.addWidget(self._scroll_wrap(self._build_panel_review()))
        self.run_stack.addWidget(self._scroll_wrap(self._build_panel_progres()))
        self.run_stack.addWidget(self._scroll_wrap(self._build_panel_hasil()))
        body.addWidget(self.run_stack, 1)

        outer.addLayout(body, 1)

        self._last_output_dir: Path | None = None
        self.switch_run_panel(0)
        self._update_run_nav()
        return page

    def _build_status_strip(self) -> QFrame:
        strip = QFrame()
        strip.setObjectName("statusStrip")
        row = QHBoxLayout(strip)
        row.setContentsMargins(24, 8, 24, 8)
        row.setSpacing(12)

        self.strip_stage = QLabel("")
        self.strip_stage.setObjectName("stripStage")
        row.addWidget(self.strip_stage)

        self.progress = QProgressBar()
        self.progress.setObjectName("progress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFormat(t("ready"))
        row.addWidget(self.progress, 1)

        self.elapsed_label = QLabel("00:00")
        self.elapsed_label.setObjectName("elapsed")
        self.elapsed_label.setFixedWidth(58)
        self.elapsed_label.setAlignment(Qt.AlignCenter)
        row.addWidget(self.elapsed_label)

        # Tombol Hentikan hidup di strip, bukan di panel: begitu proses jalan ia harus
        # bisa dijangkau dari panel mana pun.
        self.stop_btn = QPushButton(t("stop"))
        self.stop_btn.setObjectName("stopButton")
        self.stop_btn.setCursor(Qt.PointingHandCursor)
        self.stop_btn.clicked.connect(self.stop_pipeline)
        self.stop_btn.setToolTip(
            "Hentikan proses. Hasil yang SUDAH selesai tetap ada di disk dan "
            "bisa dilanjutkan nanti."
        )
        row.addWidget(self.stop_btn)

        strip.setVisible(False)  # muncul hanya saat ada proses berjalan
        self.status_strip = strip

        self._elapsed = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick_elapsed)
        return strip

    def _build_run_sidebar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("runSidebar")
        bar.setFixedWidth(196)
        col = QVBoxLayout(bar)
        col.setContentsMargins(14, 20, 14, 20)
        col.setSpacing(6)

        self.run_nav: list[SidebarButton] = []
        for i, nama in enumerate(self.RUN_PANELS):
            btn = SidebarButton(nama)
            btn.clicked.connect(lambda _=False, idx=i: self.switch_run_panel(idx))
            col.addWidget(btn)
            self.run_nav.append(btn)

        col.addStretch()
        return bar

    def _on_creator_changed(self, creator: str) -> None:
        """Teruskan nama creator video terpilih ke bridge halaman Customize.

        Bridge mungkin belum ada saat panel Review memuat file pertama kali (halaman
        Customize dibangun setelahnya), jadi nilainya disimpan dan dipasang belakangan.
        """
        self._pending_creator = str(creator or "")
        bridge = getattr(self, "stage5_bridge", None)
        if bridge is not None:
            bridge.set_creator_hint(self._pending_creator)
        # Preview kartu THEMES memakai creator yang sama supaya contoh watermark di
        # tab Run tidak menampilkan nama channel video lain.
        tc = getattr(self, "themes_card", None)
        if tc is not None:
            tc.set_creator_hint(self._pending_creator)

    def switch_run_panel(self, idx: int) -> None:
        for i, b in enumerate(self.run_nav):
            b.setChecked(i == idx)
        self.run_stack.setCurrentIndex(idx)
        if idx == 0:
            # Diperiksa ulang setiap kali panel Jalankan dibuka: bundel model bisa
            # dipasang sambil GUI terbuka, dan peringatan yang basi lebih buruk daripada
            # tidak ada peringatan. Pemeriksaannya murah (beberapa `is_file()`).
            self.refresh_model_warning()

    def _update_run_nav(self) -> None:
        """Tempelkan status ke label sidebar.

        Sidebar menyembunyikan isi panel, jadi tanpa penanda user harus mengklik
        satu-satu untuk tahu ada apa di dalamnya.
        """
        try:
            # Review: n/m klip terpilih dari file yang sedang dimuat.
            teks = self.RUN_PANELS[1]
            if getattr(self, "review", None) and self.review.rows:
                dipilih = sum(1 for r in self.review.rows if r.check.isChecked())
                teks = f"{self.RUN_PANELS[1]} · {dipilih}/{len(self.review.rows)}"
            self.run_nav[1].setText(teks)
            # Di mode Auto panel Review tidak dipakai — diredupkan, bukan disembunyikan,
            # supaya posisi menu tidak berpindah-pindah.
            auto = getattr(self, "mode_toggle", None) and self.mode_toggle.mode == "auto"
            self.run_nav[1].setProperty("dim", bool(auto) and not self.review.rows)

            jalan = bool(self.process and self.process.state() != QProcess.NotRunning)
            self.run_nav[2].setText("Progres ◐" if jalan else "Progres")

            # Hitung HANYA item video sungguhan: daftar bisa memuat baris placeholder
            # ("Belum ada video...") yang tidak punya data path, dan itu tidak boleh
            # dihitung sebagai 1 hasil.
            n = 0
            if getattr(self, "results_list", None):
                n = sum(1 for i in range(self.results_list.count())
                        if self.results_list.item(i).data(Qt.UserRole))
            self.run_nav[3].setText(f"Hasil · {n}" if n else "Hasil")
            self.run_nav[3].setProperty("dim", n == 0)

            for b in self.run_nav:
                b.style().unpolish(b)
                b.style().polish(b)
        except Exception:  # noqa: BLE001
            pass

    # ---------- Panel 1: Jalankan ----------
    def _build_panel_jalankan(self) -> QWidget:
        col = QWidget()
        layout = QVBoxLayout(col)
        # Judul panel DIBUANG (Item 26): nama panel sudah tertulis di sidebar kiri
        # lengkap dengan indikator aktif, jadi judul di sini hanya mengulang dan makan
        # ruang vertikal. Layout langsung mulai dari kartu pertama; margin atas 26px
        # yang tadinya menopang judul dipertahankan supaya kartu tidak menempel topbar.
        layout.setContentsMargins(30, 26, 30, 26)
        layout.setSpacing(16)

        # --- Kartu Utama Run: URL + bahasa + mode/rentang (yang SELALU dipakai) ---
        url_card = QFrame()
        url_card.setObjectName("card")
        url_layout = QVBoxLayout(url_card)
        url_layout.setContentsMargins(20, 18, 20, 18)
        url_layout.setSpacing(12)

        url_title = QLabel(t("url_label"))
        url_title.setObjectName("cardTitle")
        self._tr_url = url_title
        url_layout.addWidget(url_title)

        # Baris 1: URL + tombol Paste.
        row = QHBoxLayout()
        row.setSpacing(8)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://www.youtube.com/watch?v=...")
        self.url_input.setClearButtonEnabled(True)
        row.addWidget(self.url_input, 1)

        self.paste_btn = QPushButton(t("paste"))
        self.paste_btn.setObjectName("ghostButton")
        self.paste_btn.setCursor(Qt.PointingHandCursor)
        self.paste_btn.clicked.connect(self.paste_url)
        row.addWidget(self.paste_btn)
        url_layout.addLayout(row)

        # Hint "Contoh: https://..." DIBUANG (Item 26): placeholder kotak URL sudah
        # memuat contoh yang sama.

        # Baris 2: Preferred Languages (bantuan kosakata initial_prompt WhisperX).
        self.lang_picker = LanguagePicker()
        url_layout.addWidget(self.lang_picker)

        # Baris 3: tiga kelompok SEJAJAR dipisah pembatas vertikal —
        # [Auto|Manual] + (?)  |  Klip MIN-MAX  |  Durasi MIN-MAX.
        row3 = QHBoxLayout()
        row3.setSpacing(14)

        mode_wrap = QWidget()
        mode_group = QHBoxLayout(mode_wrap)
        mode_group.setContentsMargins(0, 0, 0, 0)
        mode_group.setSpacing(6)
        self.mode_toggle = ModeToggle(compact=True)
        self.mode_toggle.changed.connect(lambda _m: self._update_run_nav())
        mode_group.addWidget(self.mode_toggle)
        # Ikon (?) menggantikan keterangan panjang yang dulu ikut melebar di baris ini
        # dan menggencet kotak angka. Isi tooltipnya milik ModeToggle supaya teks
        # tombol dan penjelasannya tidak bisa berbeda arti.
        help_dot = QLabel("?")
        help_dot.setObjectName("helpDot")
        help_dot.setAlignment(Qt.AlignCenter)
        help_dot.setToolTip(ModeToggle.FLOW_HELP)
        mode_group.addWidget(help_dot)
        # AlignTop, bukan pusat: `CurationSettings` memuat hint kapasitas di bawah kotak
        # angkanya sehingga tingginya lebih besar. Tanpa AlignTop tombol Auto/Manual
        # dipusatkan terhadap tinggi TOTAL itu dan turun ~23px — terlihat tidak sejajar
        # dengan kotak Klip/Durasi (terukur 2026-09-03: mode y=259 vs klip y=236).
        row3.addWidget(mode_wrap, 0, Qt.AlignTop)

        row3.addWidget(vertical_separator())

        # CurationSettings memuat dua kelompok terakhir (Klip & Durasi) beserta
        # pembatas di antaranya + hint kapasitas di bawahnya.
        self.curation_settings = CurationSettings()
        self.curation_settings.validity_changed.connect(
            lambda _ok: self._refresh_run_enabled()
        )
        row3.addWidget(self.curation_settings, 1)
        url_layout.addLayout(row3)
        layout.addWidget(url_card)

        # --- Kartu THEMES: pilih theme tersimpan + preview 9:16 + badge APPLIED ---
        set_card = QFrame()
        set_card.setObjectName("card")
        sl = QVBoxLayout(set_card)
        sl.setContentsMargins(20, 18, 20, 18)
        sl.setSpacing(12)
        st = QLabel("THEMES")
        st.setObjectName("cardTitle")
        sl.addWidget(st)
        self.themes_card = ThemesCard()
        sl.addWidget(self.themes_card)
        layout.addWidget(set_card)

        # --- Peringatan bundel model WhisperX (Tugas 4) ---
        # Hasil pemeriksaan BERKAS NYATA di cache yang aktif — bukan indikator hiasan.
        # Ditaruh di atas tombol Jalankan supaya terbaca sebelum pipeline dimulai.
        # Ini PERINGATAN, bukan larangan: WhisperX memang bisa mengunduh sendiri, jadi
        # tombol Jalankan TIDAK dimatikan karena ini (lihat `_refresh_run_enabled`).
        self.model_warn_lbl = QLabel("")
        self.model_warn_lbl.setObjectName("statusWarn")
        self.model_warn_lbl.setWordWrap(True)
        self.model_warn_lbl.setVisible(False)
        layout.addWidget(self.model_warn_lbl)
        self.refresh_model_warning()

        # Tombol Jalankan berdiri sendiri di bawah, bukan berdesakan di baris URL.
        act = QHBoxLayout()
        act.addStretch()
        self.run_btn = QPushButton("▶  " + t("run"))
        self.run_btn.setObjectName("primaryButton")
        self.run_btn.setCursor(Qt.PointingHandCursor)
        self.run_btn.setMinimumWidth(160)
        self.run_btn.clicked.connect(self.run_pipeline)
        act.addWidget(self.run_btn)
        layout.addLayout(act)
        self._refresh_run_enabled()

        # Kartu dipatok ke ATAS. Tanpa stretch di sini, QVBoxLayout membagi sisa tinggi
        # (terukur 371px pada jendela 860px) ke kartu-kartu sehingga isinya melayang di
        # tengah kotak yang jadi terlalu tinggi. Ruang kosong di bawah lebih baik
        # daripada kartu yang menganga.
        layout.addStretch()
        return col

    # ---------- Panel 2: Review klip ----------
    def _build_panel_review(self) -> QWidget:
        col = QWidget()
        layout = QVBoxLayout(col)
        layout.setContentsMargins(30, 26, 30, 26)
        layout.setSpacing(14)

        # Judul panel dibuang (Item 26) — lihat komentar di _build_panel_jalankan.

        card = QFrame()
        card.setObjectName("card")
        rvl = QVBoxLayout(card)
        rvl.setContentsMargins(20, 18, 20, 18)
        rvl.setSpacing(12)
        self.review = ReviewPanel(OUTPUT_ROOT)
        self.review.continue_requested.connect(self.continue_from_curation)
        # Label sidebar ikut berubah saat centang/muat file, supaya jumlah terpilih
        # terlihat tanpa harus membuka panelnya.
        self.review.selection_changed.connect(self._update_run_nav)
        # Creator video yang dipilih -> contoh watermark di Customize. Ini yang membuat
        # preview memakai nama channel video YANG SEDANG DIKERJAKAN, bukan yang terbaru.
        self.review.creator_changed.connect(self._on_creator_changed)
        rvl.addWidget(self.review)
        layout.addWidget(card, 1)
        return col

    # ---------- Panel 3: Progres ----------
    def _build_panel_progres(self) -> QWidget:
        col = QWidget()
        layout = QVBoxLayout(col)
        layout.setContentsMargins(30, 26, 30, 26)
        layout.setSpacing(14)

        # Judul panel dibuang (Item 26) — sidebar sudah menamainya.

        pipeline_card = QFrame()
        pipeline_card.setObjectName("card")
        pl = QVBoxLayout(pipeline_card)
        pl.setContentsMargins(20, 18, 20, 18)
        pl.setSpacing(16)

        ptitle = QLabel(t("progress"))
        ptitle.setObjectName("cardTitle")
        self._tr_prog = ptitle
        pl.addWidget(ptitle)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        # Badge 1-2-3-4, BUKAN 1-2-4-5. Nomor Stage internal melompati 3 (Stage 3
        # dilewati), tapi user melihat empat tahap berurutan — angka 4,5 tanpa 3
        # terlihat seperti ada tahap yang hilang.
        stages = [
            ("1", "Curation", t("stage_curation_sub")),
            ("2", "Download", t("stage_download_sub")),
            ("3", "Subtitle", t("stage_subtitle_sub")),
            ("4", "Render", t("stage_render_sub")),
        ]
        for ci, data in enumerate(stages):
            card = StageCard(*data)
            self.stage_cards[data[1]] = card
            grid.addWidget(card, 0, ci * 2)
            if ci < len(stages) - 1:
                arrow = QLabel("→")
                arrow.setObjectName("arrow")
                arrow.setAlignment(Qt.AlignCenter)
                grid.addWidget(arrow, 0, ci * 2 + 1)
        pl.addLayout(grid)
        layout.addWidget(pipeline_card)

        log_card = QFrame()
        log_card.setObjectName("card")
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(20, 18, 20, 16)

        log_head = QHBoxLayout()
        log_title = QLabel("Log")
        log_title.setObjectName("cardTitle")
        log_head.addWidget(log_title)
        log_head.addStretch()
        clear = QPushButton("Bersihkan")
        clear.setObjectName("ghostButton")
        clear.setCursor(Qt.PointingHandCursor)
        clear.clicked.connect(self.clear_log)
        log_head.addWidget(clear)
        log_layout.addLayout(log_head)

        self.log_list = QListWidget()
        self.log_list.setObjectName("logList")
        self.log_list.setMinimumHeight(220)
        placeholder = QListWidgetItem("Log akan muncul di sini setelah pipeline dijalankan...")
        placeholder.setForeground(Qt.gray)
        self.log_list.addItem(placeholder)
        log_layout.addWidget(self.log_list)
        layout.addWidget(log_card, 1)
        return col

    # ---------- Panel 4: Hasil ----------
    def _build_panel_hasil(self) -> QWidget:
        col = QWidget()
        layout = QVBoxLayout(col)
        layout.setContentsMargins(30, 26, 30, 26)
        layout.setSpacing(14)

        # Judul panel dibuang (Item 26) — sidebar sudah menamainya lengkap dengan
        # jumlah hasil ("Hasil · 3").

        self.results_card = QFrame()
        self.results_card.setObjectName("card")
        rl = QVBoxLayout(self.results_card)
        rl.setContentsMargins(20, 18, 20, 18)
        rl.setSpacing(10)

        res_head = QHBoxLayout()
        res_head.addStretch()
        # Caption siap copy-paste. Ditaruh di panel Hasil karena itu momen kerjanya:
        # video jadi -> buka caption -> tempel di TikTok/Shorts.
        self.open_caption_btn = QPushButton(t("open_caption"))
        self.open_caption_btn.setObjectName("ghostButton")
        self.open_caption_btn.setCursor(Qt.PointingHandCursor)
        self.open_caption_btn.clicked.connect(self.open_caption_file)
        res_head.addWidget(self.open_caption_btn)
        self.open_folder_btn = QPushButton(t("open_folder"))
        self.open_folder_btn.setObjectName("ghostButton")
        self.open_folder_btn.setCursor(Qt.PointingHandCursor)
        self.open_folder_btn.clicked.connect(self.open_final_folder)
        res_head.addWidget(self.open_folder_btn)
        rl.addLayout(res_head)

        self.results_list = QListWidget()
        self.results_list.setObjectName("resultsList")
        self.results_list.setMinimumHeight(240)
        self.results_list.itemDoubleClicked.connect(self._open_result_item)
        rl.addWidget(self.results_list)

        res_hint = QLabel(t("dbl_click"))
        self._tr_reshint = res_hint
        res_hint.setObjectName("hint")
        rl.addWidget(res_hint)

        layout.addWidget(self.results_card, 1)
        return col

    def build_quick_settings(self):
        card = QFrame()
        card.setObjectName("card")
        l = QVBoxLayout(card)
        l.setContentsMargins(22, 18, 22, 20)
        l.setSpacing(10)

        title = QLabel("Pengaturan Cepat")
        title.setObjectName("cardTitle")
        l.addWidget(title)

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Model Gemini"))
        self.model_combo = QComboBox()
        self.model_combo.addItems(["gemini-2.5-flash", "gemini-2.5-pro"])
        self.model_combo.setCurrentText("gemini-2.5-flash")
        model_row.addWidget(self.model_combo, 1)
        l.addLayout(model_row)

        self.gemini_check = QCheckBox("Gunakan Gemini untuk desain Hook (Stage 5)")
        self.gemini_check.setChecked(True)
        l.addWidget(self.gemini_check)

        note = QLabel("Gemini membuat headline gaya pemberitaan yang sesuai layout reference.")
        note.setWordWrap(True)
        note.setObjectName("hint")
        l.addWidget(note)

        return card

    def build_info_panel(self):
        card = QFrame()
        card.setObjectName("card")
        l = QVBoxLayout(card)
        l.setContentsMargins(22, 18, 22, 20)
        l.setSpacing(10)

        title = QLabel("Informasi")
        title.setObjectName("cardTitle")
        l.addWidget(title)

        rows = [
            ("✦", "Gemini AI", "Membantu headline dan design pass Stage 5."),
            ("▧", "Layout Reference", "FRAME KDM.png digunakan sebagai acuan komposisi."),
            ("T", "Tekstil", "Subtitle tetap, word-pop 80% → 100%."),
            ("◈", "Layout", "Video/frame tetap menjadi struktur utama."),
        ]
        for icon, head, text in rows:
            row = QHBoxLayout()
            i = QLabel(icon)
            i.setObjectName("infoIcon")
            i.setFixedWidth(30)
            row.addWidget(i)
            c = QVBoxLayout()
            h = QLabel(head)
            h.setObjectName("infoHead")
            b = QLabel(text)
            b.setObjectName("infoBody")
            b.setWordWrap(True)
            c.addWidget(h)
            c.addWidget(b)
            row.addLayout(c, 1)
            l.addLayout(row)

        return card

    def build_history_page(self):
        page = QWidget()
        l = QVBoxLayout(page)
        title = QLabel(t("history_title"))
        self._tr_hist = title
        title.setObjectName("pageTitle")
        sub = QLabel(t("history_desc"))
        self._tr_histd = sub
        sub.setObjectName("pageSubtitle")
        l.addWidget(title)
        l.addWidget(sub)

        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(22, 18, 22, 18)
        cl.setSpacing(10)

        head = QHBoxLayout()
        h = QLabel(t("rendered"))
        self._tr_rend = h
        h.setObjectName("cardTitle")
        head.addWidget(h)
        head.addStretch()
        refresh = QPushButton("↻  " + t("refresh"))
        self._tr_refresh = refresh
        refresh.clicked.connect(self.refresh_history)
        head.addWidget(refresh)
        open_final = QPushButton("📂  Buka folder final")
        open_final.clicked.connect(lambda: self._open_path(FINAL_ROOT))
        head.addWidget(open_final)
        cl.addLayout(head)

        self.history_list = QListWidget()
        self.history_list.setObjectName("resultsList")
        self.history_list.itemDoubleClicked.connect(self._open_result_item)
        cl.addWidget(self.history_list, 1)

        hint = QLabel(t("dbl_click"))
        self._tr_histhint = hint
        hint.setObjectName("hint")
        cl.addWidget(hint)

        l.addWidget(card, 1)
        self.refresh_history()
        return page

    def build_stage5_page(self):
        page = QWidget()
        l = QVBoxLayout(page)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(0)

        # Tanpa header/keterangan: halaman Customize adalah UI penuh (permintaan user).
        # Tulisan nav "Customize" sudah mewakili judulnya.

        # Embedded HTML customizer (mockup) + QWebChannel bridge to Python.
        self.stage5_web = QWebEngineView()

        # Matikan zoom in/out halaman (Ctrl+scroll, Ctrl +/-/0). Zoom yang dipakai
        # sekarang adalah zoom PREVIEW di dalam halaman, bukan zoom UI.
        self.stage5_web.setZoomFactor(1.0)
        self._nozoom = NoZoomFilter(self)
        self.stage5_web.installEventFilter(self._nozoom)
        focus_proxy = self.stage5_web.focusProxy()
        if focus_proxy is not None:
            focus_proxy.installEventFilter(self._nozoom)
        try:
            from PySide6.QtWebEngineCore import QWebEngineSettings
            self.stage5_web.settings().setAttribute(
                QWebEngineSettings.WebAttribute.ShowScrollBars, True
            )
        except Exception:  # noqa: BLE001
            pass

        self.stage5_bridge = PresetBridge(self)
        self.stage5_channel = QWebChannel(self.stage5_web.page())
        self.stage5_channel.registerObject("bridge", self.stage5_bridge)
        self.stage5_web.page().setWebChannel(self.stage5_channel)
        self.stage5_bridge.preset_saved.connect(self.on_preset_saved)
        # Theme baru disimpan di Customize -> dropdown di tab Run langsung ikut.
        # Tanpa ini theme baru tidak muncul sampai user menekan ↻ atau restart app,
        # dan itu memutus alur "simpan di Customize, jalankan di Run".
        self.stage5_bridge.theme_saved.connect(self.on_theme_saved)
        self.stage5_bridge.render_requested.connect(self.on_render_requested)
        self.stage5_bridge.render_clip_requested.connect(self.on_render_clip_requested)
        self.stage5_bridge.language_changed.connect(self.retranslate)
        # Preview kartu THEMES di tab Run memakai MESIN RENDER yang sama dengan Stage 5
        # (Slot `render_text_layers`), jadi apa yang tergambar di kartu adalah lapisan
        # teks yang benar-benar dipakai saat render — bukan tiruan CSS/QPainter.
        # Dipasang di sini karena bridge baru ada setelah halaman Customize dibangun.
        self.themes_card.set_layer_provider(self.stage5_bridge.render_text_layers)
        # Pasang creator yang mungkin sudah dipilih SEBELUM halaman Customize dibangun
        # (panel Review dibuat lebih dulu dan bisa langsung memuat file).
        pending = getattr(self, "_pending_creator", "")
        if pending:
            self.stage5_bridge.set_creator_hint(pending)
            self.themes_card.set_creator_hint(pending)

        if CUSTOMIZER_HTML.exists():
            self.stage5_web.load(QUrl.fromLocalFile(str(CUSTOMIZER_HTML)))
        else:
            self.stage5_web.setHtml(
                f"<body style='background:#07111f;color:#eef6ff;font-family:sans-serif;"
                f"padding:40px'><h2>Customizer HTML tidak ditemukan</h2>"
                f"<p>{CUSTOMIZER_HTML}</p></body>"
            )
        l.addWidget(self.stage5_web, 1)
        return page

    # ---------- Stage 5 bridge callbacks ----------
    def on_preset_saved(self, path: str):
        """Draf Customize tersimpan (autosave).

        SENGAJA tidak berpindah halaman dan tidak menulis log. Versi lama memanggil
        `switch_page(0)` karena penyimpanan hanya terjadi saat user menekan tombol
        "Terapkan" — sekali, dan berpindah ke Run memang tujuannya. Sejak tombol itu
        dibuang (2026-08-30) preset ditulis otomatis setiap slider digeser, sehingga
        handler lama melempar user ke tab Run di tengah menggeser slider. Itu bug yang
        dilaporkan user; status "tersimpan" cukup ditampilkan di halaman Customize.
        """
        return

    def on_theme_saved(self, theme_id: str) -> None:
        """Theme baru/ditimpa di Customize -> segarkan dropdown Tema di tab Run.

        Sekaligus MEMILIH theme itu: kalau user baru saja menyimpannya, itu hampir pasti
        yang mau dijalankan. Ini yang menyambung dua tab sesuai pembagian peran yang
        diminta user (Customize menyimpan, Run mengeksekusi).
        """
        try:
            tc = self.themes_card
            tc.reload_themes()
            import sys as _sys
            stages_dir = str(PROJECT_ROOT / "stages")
            if stages_dir not in _sys.path:
                _sys.path.insert(0, stages_dir)
            import preset_library
            path = str((preset_library.LIBRARY_DIR / f"{theme_id}.json").resolve())
            i = tc.theme_box.findData(path)
            if i >= 0:
                tc.theme_box.setCurrentIndex(i)
        except Exception as exc:  # noqa: BLE001
            self.log(f"[Theme] gagal menyegarkan daftar: {exc}", "warn")

    def on_render_requested(self, path: str):
        self._start_render(path, only_clip=None)

    def on_render_clip_requested(self, path: str, clip_no: int):
        self._start_render(path, only_clip=int(clip_no))

    def _start_render(self, path: str, only_clip: int | None = None):
        if self.process and self.process.state() != QProcess.NotRunning:
            QMessageBox.information(self, "Proses berjalan", "Ada proses lain sedang berjalan.")
            return
        if not PYTHON_EXE.exists():
            QMessageBox.critical(self, "Python tidak ditemukan", f"{PYTHON_EXE}")
            return
        self.switch_page(0)  # tampilkan log di dashboard
        self.log_list.clear()
        if only_clip:
            self.log(f"[Stage 5] Uji cepat: render HANYA klip #{only_clip} (menimpa hasil lama)...")
        else:
            self.log("[Stage 5] Render dimulai dengan preset dari customizer...")
        self.log(f"[Stage 5] Preset: {path}")

        for card in self.stage_cards.values():
            card.set_state("waiting")
        render_card = self.stage_cards.get(self.STAGE_CARD_KEY["Stage 5"])
        if render_card:
            render_card.set_state("running")
        self._set_progress(self.STAGE_PROGRESS["Stage 5"], "Stage 5 — Render")
        self._last_output_dir = None
        self._elapsed.restart()
        self._timer.start()
        self.elapsed_label.setText("00:00")
        # Render dari Customize memakai penentu tombol yang SAMA dengan pipeline;
        # menulis `run_btn.setEnabled(False)` di sini akan bertabrakan dengannya.
        self._running = True
        self._refresh_run_enabled()

        args = [str(RENDER_WITH_PRESET), "--preset", path]
        if only_clip:
            args += ["--only-clip", str(int(only_clip))]

        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(PROJECT_ROOT))
        self.process.setProgram(str(PYTHON_EXE))
        self.process.setArguments(args)
        self.process.readyReadStandardOutput.connect(self.read_stdout)
        self.process.readyReadStandardError.connect(self.read_stderr)
        self.process.finished.connect(self.pipeline_finished)
        self.process.errorOccurred.connect(self.pipeline_error)
        self.process.start()
        if not self.process.waitForStarted(3000):
            self.log("[Stage 5] Gagal memulai render.")

    def build_settings_page(self):
        page = QWidget()
        l = QVBoxLayout(page)
        t_lbl = QLabel(t("settings_title"))
        self._tr_set = t_lbl
        t_lbl.setObjectName("pageTitle")
        s = QLabel(t("settings_desc"))
        self._tr_setd = s
        s.setObjectName("pageSubtitle")
        l.addWidget(t_lbl)
        l.addWidget(s)

        env = read_env_dict()

        # ---------- LLM Provider card ----------
        api_card = QFrame()
        api_card.setObjectName("card")
        al = QVBoxLayout(api_card)
        al.setContentsMargins(22, 20, 22, 20)
        al.setSpacing(12)

        api_title = QLabel("LLM Provider (OpenAI-compatible)")
        api_title.setObjectName("cardTitle")
        al.addWidget(api_title)

        # API Endpoint
        ep_row = QHBoxLayout()
        ep_lbl = QLabel("API Endpoint")
        ep_lbl.setFixedWidth(120)
        ep_row.addWidget(ep_lbl)
        self.set_base_url = QLineEdit(env.get("LLM_BASE_URL", "http://127.0.0.1:20128/v1"))
        self.set_base_url.setPlaceholderText("http://127.0.0.1:20128/v1")
        ep_row.addWidget(self.set_base_url, 1)
        al.addLayout(ep_row)

        # API Key
        key_row = QHBoxLayout()
        key_lbl = QLabel("API Key")
        key_lbl.setFixedWidth(120)
        key_row.addWidget(key_lbl)
        self.set_api_key = QLineEdit(env.get("GEMINI_API_KEY", ""))
        self.set_api_key.setEchoMode(QLineEdit.Password)
        self.set_api_key.setPlaceholderText("Bearer token / API key")
        key_row.addWidget(self.set_api_key, 1)
        self.show_key_btn = QPushButton("👁")
        self.show_key_btn.setFixedWidth(40)
        self.show_key_btn.setCheckable(True)
        self.show_key_btn.toggled.connect(
            lambda on: self.set_api_key.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)
        )
        key_row.addWidget(self.show_key_btn)
        al.addLayout(key_row)

        # Model + auto-detect
        model_row = QHBoxLayout()
        model_lbl = QLabel("Model")
        model_lbl.setFixedWidth(120)
        model_row.addWidget(model_lbl)
        self.set_model_combo = QComboBox()
        self.set_model_combo.setEditable(True)
        current_model = env.get("GEMINI_MODEL", "")
        if current_model:
            self.set_model_combo.addItem(current_model)
            self.set_model_combo.setCurrentText(current_model)
        model_row.addWidget(self.set_model_combo, 1)
        self.detect_btn = QPushButton("🔄  Auto-detect")
        self.detect_btn.clicked.connect(self.detect_models_clicked)
        model_row.addWidget(self.detect_btn)
        al.addLayout(model_row)

        self.detect_status = QLabel("Klik Auto-detect untuk mengambil daftar model dari endpoint.")
        self.detect_status.setObjectName("hint")
        self.detect_status.setWordWrap(True)
        al.addWidget(self.detect_status)

        # Save
        save_row = QHBoxLayout()
        save_row.addStretch()
        self.test_conn_btn = QPushButton("Test koneksi")
        self.test_conn_btn.clicked.connect(self.detect_models_clicked)
        save_row.addWidget(self.test_conn_btn)
        self.save_settings_btn = QPushButton("💾  Simpan")
        self.save_settings_btn.setObjectName("primaryButton")
        self.save_settings_btn.clicked.connect(self.save_settings)
        save_row.addWidget(self.save_settings_btn)
        al.addLayout(save_row)

        l.addWidget(api_card)

        # ---------- Info card ----------
        info_card = QFrame()
        info_card.setObjectName("card")
        il = QVBoxLayout(info_card)
        il.setContentsMargins(22, 18, 22, 18)
        il.setSpacing(6)
        info_t = QLabel("Info")
        info_t.setObjectName("cardTitle")
        il.addWidget(info_t)
        root_lbl = QLabel(f"Project root: {PROJECT_ROOT}")
        root_lbl.setObjectName("infoBody")
        il.addWidget(root_lbl)
        env_lbl = QLabel(f"Config file: {PROJECT_ROOT / '.env'}")
        env_lbl.setObjectName("infoBody")
        il.addWidget(env_lbl)
        note = QLabel("Endpoint OpenAI-compatible (mis. 9Router di port 20128). "
                      "Auto-detect memanggil GET /models. Perubahan disimpan ke .env dan "
                      "langsung dipakai run berikutnya.")
        note.setObjectName("infoBody")
        note.setWordWrap(True)
        il.addWidget(note)
        l.addWidget(info_card)

        l.addStretch()
        return page

    # ---------- Settings behavior ----------
    def detect_models_clicked(self):
        base = self.set_base_url.text().strip()
        key = self.set_api_key.text().strip()
        self.detect_status.setText("Menghubungi endpoint...")
        self.detect_btn.setEnabled(False)
        QApplication.processEvents()
        try:
            models = detect_models(base, key)
        except Exception as exc:
            self.detect_status.setText(f"Gagal: {type(exc).__name__} — {exc}")
            self.detect_status.setObjectName("statusBad")
            self.detect_status.style().unpolish(self.detect_status)
            self.detect_status.style().polish(self.detect_status)
            self.detect_btn.setEnabled(True)
            return

        current = self.set_model_combo.currentText().strip()
        self.set_model_combo.clear()
        self.set_model_combo.addItems(models)
        if current and current in models:
            self.set_model_combo.setCurrentText(current)
        elif models:
            self.set_model_combo.setCurrentText(models[0])
        self.detect_status.setText(f"✓ {len(models)} model terdeteksi. Pilih salah satu lalu Simpan.")
        self.detect_status.setObjectName("statusGood")
        self.detect_status.style().unpolish(self.detect_status)
        self.detect_status.style().polish(self.detect_status)
        self.detect_btn.setEnabled(True)

    def save_settings(self):
        updates = {
            "LLM_BASE_URL": self.set_base_url.text().strip(),
            "GEMINI_API_KEY": self.set_api_key.text().strip(),
            "GEMINI_MODEL": self.set_model_combo.currentText().strip(),
        }
        try:
            write_env_values(updates)
        except Exception as exc:
            QMessageBox.critical(self, "Gagal simpan", f"Tidak bisa menulis .env:\n{exc}")
            return
        self.refresh_status()
        QMessageBox.information(
            self, "Tersimpan",
            "Pengaturan disimpan ke .env dan langsung aktif untuk run berikutnya.",
        )

    # ---------- Behavior ----------
    def set_language(self, code: str):
        """Ganti bahasa dari topbar: simpan, retranslate Qt, dan beri tahu halaman HTML."""
        code = "en" if str(code).lower().startswith("en") else "id"
        try:
            SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            if SETTINGS_PATH.exists():
                try:
                    data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8-sig"))
                except Exception:
                    data = {}
            if not isinstance(data, dict):
                data = {}
            data["language"] = code
            SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        for b in getattr(self, "lang_buttons", []):
            b.setChecked(b.text().lower() == code)
        self.retranslate(code)
        # halaman Customize (HTML) punya kamusnya sendiri
        try:
            self.stage5_web.page().runJavaScript(
                f"if(typeof applyLangFromHost==='function')applyLangFromHost('{code}');"
            )
        except Exception:  # noqa: BLE001
            pass

    def retranslate(self, lang: str):
        """Perbarui teks widget Qt saat bahasa diganti dari halaman Customize.

        HATI-HATI: seluruh badan fungsi ini dibungkus satu `except Exception: pass`.
        Menyentuh atribut widget yang sudah dihapus TIDAK menimbulkan crash — yang
        terjadi lebih buruk: AttributeError ditelan diam-diam dan SEMUA terjemahan
        sesudah baris itu berhenti bekerja tanpa satu pun pesan error. Kalau sebuah
        widget dibuang, baris terjemahannya HARUS dibuang di edit yang sama.
        Baris `_tr_title` / `_tr_hint` / `_tr_res` dibuang 2026-09-03 bersama judul
        panel & hint URL (Item 26).
        """
        try:
            self._tr_url.setText(t("url_label", lang))
            self.paste_btn.setText(t("paste", lang))
            self._tr_prog.setText(t("progress", lang))
            self.open_folder_btn.setText(t("open_folder", lang))
            self.open_caption_btn.setText(t("open_caption", lang))
            self._tr_reshint.setText(t("dbl_click", lang))
            self._tr_hist.setText(t("history_title", lang))
            self._tr_histd.setText(t("history_desc", lang))
            self._tr_rend.setText(t("rendered", lang))
            self._tr_refresh.setText("↻  " + t("refresh", lang))
            self._tr_histhint.setText(t("dbl_click", lang))
            self._tr_set.setText(t("settings_title", lang))
            self._tr_setd.setText(t("settings_desc", lang))
            for i, key in enumerate(("nav_run", "nav_customize", "nav_history", "nav_settings")):
                if i < len(self.nav_buttons):
                    self.nav_buttons[i].setText(t(key, lang))
            subs = {
                "Curation": "stage_curation_sub", "Download": "stage_download_sub",
                "Subtitle": "stage_subtitle_sub", "Render": "stage_render_sub",
            }
            for name, key in subs.items():
                card = self.stage_cards.get(name)
                if card is not None:
                    card.subtitle.setText(t(key, lang))
            if not (self.process and self.process.state() != QProcess.NotRunning):
                self.run_btn.setText("▶  " + t("run", lang))
            else:
                self.stop_btn.setText(t("stop", lang))
            self._update_run_nav()
        except Exception:  # noqa: BLE001
            pass

    def switch_page(self, idx: int):
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == idx)
        self.stack.setCurrentIndex(idx)

    def paste_url(self):
        self.url_input.setText(QApplication.clipboard().text().strip())

    def clear_log(self):
        self.log_list.clear()

    def log(self, text: str, kategori: str = "info"):
        """Tambah satu baris log, diwarnai menurut kategorinya.

        Warna bukan hiasan: dulu semua baris abu-abu seragam, jadi satu kegagalan
        nyata di antara 200 baris yt-dlp mudah terlewat. Merah = gagal, kuning =
        peringatan (proses lanjut), abu = biasa.
        """
        item = QListWidgetItem(text)
        if kategori == "error":
            item.setForeground(QColor("#FF8A8A"))
        elif kategori == "warn":
            item.setForeground(QColor("#FACC15"))
        self.log_list.addItem(item)
        self.log_list.scrollToBottom()

    def refresh_status(self):
        if os.getenv("GEMINI_API_KEY"):
            self.gemini_status.setText("● API terhubung")
            self.gemini_status.setObjectName("statusGood")
        else:
            self.gemini_status.setText("● API belum diset")
            self.gemini_status.setObjectName("statusWarn")
        self.gemini_status.style().unpolish(self.gemini_status)
        self.gemini_status.style().polish(self.gemini_status)

    # ---------- Progress / elapsed (Langkah A) ----------
    STAGE_PROGRESS = {"Stage 1": 10, "Stage 2": 35, "Stage 4": 60, "Stage 5": 80}
    # Kartu di dashboard dikunci dengan LABEL ("Curation", "Download", ...), sedangkan
    # log memakai "Stage N". Tanpa peta ini `stage_cards["Stage 1"]` -> KeyError dan
    # setiap baris log stage melempar traceback (progress dashboard mati diam-diam).
    STAGE_CARD_KEY = {
        "Stage 1": "Curation",
        "Stage 2": "Download",
        "Stage 4": "Subtitle",
        "Stage 5": "Render",
    }

    def _tick_elapsed(self):
        if not self._elapsed.isValid():
            return
        secs = self._elapsed.elapsed() // 1000
        self.elapsed_label.setText(f"{secs // 60:02d}:{secs % 60:02d}")

    def _set_progress(self, value: int, text: str):
        self.progress.setValue(max(0, min(100, value)))
        self.progress.setFormat(text)
        # Strip status memuat nama tahap terpisah dari bar, supaya terbaca walau
        # bar-nya sempit. Diambil dari teks progres ("Stage 2 — Download").
        if getattr(self, "strip_stage", None):
            self.strip_stage.setText(str(text).split("—")[-1].strip()[:26])

    # ---------- Results / history (Langkah B) ----------
    def _open_path(self, path: Path):
        if path and Path(path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            QMessageBox.information(self, "Belum ada", f"Folder belum ada:\n{path}")

    def _resolve_result_dir(self) -> Path | None:
        """Folder hasil yang sedang relevan bagi user.

        Urutan tebakan: folder dari log (paling akurat) > folder dari item yang dipilih
        di daftar Hasil > folder final terbaru. Dipakai bersama oleh "Buka folder" dan
        "Buka caption" supaya keduanya tidak pernah menunjuk video yang berbeda.
        """
        if self._last_output_dir and Path(self._last_output_dir).is_dir():
            return Path(self._last_output_dir)
        item = self.results_list.currentItem() if hasattr(self, "results_list") else None
        data = item.data(Qt.UserRole) if item else None
        if data:
            p = Path(str(data))
            if p.is_file():
                return p.parent
            if p.is_dir():
                return p
        return self._latest_final_dir()

    def open_final_folder(self):
        """Buka folder hasil video yang baru saja dibuat.

        Versi lama langsung jatuh ke root begitu parsing log gagal, dan itu yang
        dikeluhkan user: judul folder mengandung spasi + emoji sehingga selalu gagal
        diparse.
        """
        self._open_path(self._resolve_result_dir() or FINAL_ROOT)

    def open_caption_file(self):
        """Buka caption.txt folder hasil ini di editor teks bawaan.

        Kalau belum ada (mis. hasil render sebelum fitur ini), file dibuat dulu dari
        manifest Stage 2 + file kurasi — tidak perlu render ulang berjam-jam hanya
        untuk mendapatkan caption.
        """
        folder = self._resolve_result_dir()
        if folder is None:
            QMessageBox.information(
                self, "Belum ada",
                "Belum ada folder hasil. Jalankan pipeline dulu.")
            return

        caption = folder / CAPTION_FILENAME
        if not caption.exists():
            dibuat = self._build_caption_for(folder)
            if dibuat is None:
                QMessageBox.information(
                    self, "Caption belum bisa dibuat",
                    "caption.txt belum ada dan datanya tidak ketemu.\n\n"
                    f"Folder hasil: {folder}\n\n"
                    "Caption dibuat dari file kurasi + manifest di folder output/. "
                    "Coba render ulang video ini (Stage 5) supaya caption ikut ditulis.")
                return
            caption = dibuat
        self._open_path(caption)

    def _build_caption_for(self, final_dir: Path) -> Path | None:
        """Tulis caption.txt untuk folder final yang sudah ada.

        Folder `final/<creator>/<judul>/` tidak menyimpan manifest, jadi manifest
        Stage 2 dicari di `output/` dengan dua cara berurutan:

        1. MENCOCOKKAN NAMA FILE MP4 — paling meyakinkan, karena nama file klip
           identik di kedua folder.
        2. Mencocokkan JUDUL VIDEO yang sudah disanitasi dengan nama folder final.
           Perlu untuk folder final yang masih KOSONG (dua folder seperti ini nyata
           ada di `final/` user: Deddy Corbuzier dan Youtuber Cupu, video-nya belum
           pernah selesai dirender), yang lewat cara 1 tidak akan pernah cocok.

        Nama FOLDER tidak bisa dipakai langsung: folder output disanitasi dan
        dipotong 30 karakter (`Rekomendasi_5_Tablet_mini_Ter-`) sedangkan folder
        final memakai judul asli lengkap dengan emoji.
        """
        try:
            from stages.caption_txt import write_caption_file
            from stages.stage5_final import sanitize_component
        except Exception:  # noqa: BLE001
            return None

        nama_mp4 = {p.name for p in final_dir.glob("*.mp4")}
        target_folder = final_dir.name

        kandidat = sorted(
            OUTPUT_ROOT.glob("*/*/manifest.json"),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        cocok_judul: Path | None = None
        for manifest_path in kandidat:
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            except Exception:  # noqa: BLE001
                continue
            clips = data.get("clips") or []
            if not isinstance(clips, list):
                continue
            files = {str(c.get("output_file") or "") for c in clips if isinstance(c, dict)}
            if nama_mp4 and (files & nama_mp4):
                return self._write_caption_from(manifest_path, data, final_dir)
            if cocok_judul is None:
                judul = sanitize_component(str(data.get("video_title") or ""), "")
                if judul and judul == target_folder:
                    cocok_judul = manifest_path

        if cocok_judul is not None:
            try:
                data = json.loads(cocok_judul.read_text(encoding="utf-8-sig"))
            except Exception:  # noqa: BLE001
                return None
            return self._write_caption_from(cocok_judul, data, final_dir)
        return None

    def _write_caption_from(self, manifest_path: Path, data: dict, final_dir: Path) -> Path | None:
        try:
            from stages.caption_txt import write_caption_file
            return write_caption_file(
                final_dir, data,
                curation_folder=manifest_path.parent,
                creator=str(data.get("creator") or ""),
                video_title=str(data.get("video_title") or ""),
            )
        except Exception:  # noqa: BLE001
            return None

    def _open_result_item(self, item):
        p = item.data(Qt.UserRole)
        if p:
            self._open_path(Path(p))

    def _latest_final_dir(self) -> Path | None:
        if not FINAL_ROOT.exists():
            return None
        dirs = [d for d in FINAL_ROOT.glob("*/*") if d.is_dir()]
        if not dirs:
            return None
        return max(dirs, key=lambda d: d.stat().st_mtime)

    def populate_results(self, output_dir: Path | None):
        """Isi panel Hasil. Kartunya SELALU terlihat (panel itu memang untuk ini),
        yang berubah hanya isi daftarnya + status di sidebar."""
        self.results_list.clear()
        mp4s = sorted(output_dir.glob("*.mp4")) if (output_dir and output_dir.exists()) else []
        if not mp4s:
            kosong = QListWidgetItem("Belum ada video. Jalankan pipeline dulu.")
            kosong.setForeground(Qt.gray)
            self.results_list.addItem(kosong)
            self._update_run_nav()
            return
        for mp4 in mp4s:
            item = QListWidgetItem(f"🎬  {mp4.name}")
            item.setData(Qt.UserRole, str(mp4))
            self.results_list.addItem(item)
        self._update_run_nav()

    def refresh_history(self):
        if not hasattr(self, "history_list"):
            return
        self.history_list.clear()
        if not FINAL_ROOT.exists():
            self.history_list.addItem(QListWidgetItem("Belum ada video. Jalankan pipeline dulu."))
            return
        mp4s = sorted(FINAL_ROOT.glob("*/*/*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not mp4s:
            self.history_list.addItem(QListWidgetItem("Belum ada video di folder final/."))
            return
        for mp4 in mp4s[:50]:
            rel = mp4.relative_to(FINAL_ROOT)
            item = QListWidgetItem(f"🎬  {rel}")
            item.setData(Qt.UserRole, str(mp4))
            self.history_list.addItem(item)

    def _start_stage_process(self, args: list[str], judul: str, first_stage: str) -> None:
        """Jalankan main.py dengan argumen apa pun, memakai pipa log/progres yang sama.

        Dipakai oleh jalur Auto (`run --url`) dan jalur Manual (`continue-from`), supaya
        parsing log, kartu progres, timer, dan panel hasil tidak digandakan.
        `first_stage` menandai kartu mana yang dianggap sudah selesai saat mulai —
        pada jalur Manual, Curation memang sudah kelar sebelum proses ini jalan.
        """
        if self.process and self.process.state() != QProcess.NotRunning:
            QMessageBox.information(self, "Pipeline berjalan", "Pipeline sedang berjalan.")
            return
        if not PYTHON_EXE.exists():
            QMessageBox.critical(self, "Python tidak ditemukan", f"Virtualenv Python tidak ditemukan:\n{PYTHON_EXE}")
            return
        if not MAIN_PY.exists():
            QMessageBox.critical(self, "main.py tidak ditemukan", f"Tidak ditemukan:\n{MAIN_PY}")
            return

        for name, card in self.stage_cards.items():
            card.set_state("waiting")
        if first_stage == "Download":
            # Curation sudah selesai di sesi sebelumnya — tandai supaya tidak terlihat
            # seperti tahap yang terlewat.
            self.stage_cards["Curation"].set_state("done")

        self._user_stopped = False
        self._set_running_ui(True)
        self.log_list.clear()
        # Reset hitungan klip: sisa dari run sebelumnya akan membuat bar melompat.
        self._stage_key = ""
        self._clip_total = 0
        self._clip_done = 0
        for garis in str(judul).splitlines():
            self.log(garis)

        # Peringatan bundel model: diperiksa ULANG saat pipeline mulai (installer model
        # bisa dipasang sambil GUI terbuka) dan dituliskan ke log supaya juga terlihat
        # dari panel Progres, bukan hanya di panel Jalankan.
        # HANYA untuk perintah yang benar-benar menjalankan Stage 4 — mode Manual
        # (`stage1` saja) tidak menyentuh WhisperX, jadi memperingatkan di situ cuma
        # kebisingan yang membuat peringatan sungguhan diabaikan.
        self.refresh_model_warning()
        perintah = args[0] if args else ""
        if perintah in ("run", "continue-from", "stage4") and not getattr(
            self, "_model_bundle_ok", True
        ):
            self.log(MODEL_BUNDLE_WARNING, "warn")

        self._set_progress(3, "Memulai...")
        self._last_output_dir = None
        self._elapsed.restart()
        self._timer.start()
        self.elapsed_label.setText("00:00")
        # Pindah ke panel Progres: begitu Jalankan ditekan, yang relevan adalah
        # apa yang sedang terjadi, bukan formulir yang baru saja diisi.
        self.switch_run_panel(2)

        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(PROJECT_ROOT))
        self.process.setProgram(str(PYTHON_EXE))
        self.process.setArguments([str(MAIN_PY), *args])
        self.process.readyReadStandardOutput.connect(self.read_stdout)
        self.process.readyReadStandardError.connect(self.read_stderr)
        self.process.finished.connect(self.pipeline_finished)
        self.process.errorOccurred.connect(self.pipeline_error)
        self.process.start()

        if not self.process.waitForStarted(3000):
            self.log("Gagal memulai process.")
            self.pipeline_finished(-1, QProcess.CrashExit)

    def _set_running_ui(self, running: bool) -> None:
        """Tukar tampilan idle <-> berjalan.

        Strip status (progress bar + timer + Hentikan) hanya muncul saat proses jalan,
        supaya tidak makan ruang saat idle tapi selalu terjangkau dari panel mana pun.

        Keadaan tombol Jalankan TIDAK ditulis di sini. Dulu baris
        `run_btn.setEnabled(not running)` berdiri sendiri di sini, sehingga tombol yang
        dinonaktifkan karena rentang Min-Max tidak valid HIDUP LAGI setiap proses
        selesai. Sekarang keadaannya hanya ditentukan `_refresh_run_enabled()`.
        """
        self._running = bool(running)
        self.status_strip.setVisible(running)
        self.stop_btn.setEnabled(running)
        self.stop_btn.setText(t("stop"))
        # Setelan tidak boleh diubah saat proses jalan — nilainya sudah terkirim ke CLI,
        # jadi mengubahnya hanya akan menyesatkan.
        for w in (self.curation_settings, self.lang_picker, self.themes_card,
                  self.mode_toggle, self.paste_btn, self.url_input):
            w.setEnabled(not running)
        self._refresh_run_enabled()
        self._update_run_nav()

    def _refresh_run_enabled(self) -> None:
        """SATU-SATUNYA penentu keadaan tombol Jalankan.

        Menggabungkan dua syarat yang dulu ditulis di tempat berbeda dan saling
        menimpa: "tidak sedang berjalan" DAN "input valid" (Klip MAX >= MIN dan
        Durasi MAX >= MIN). Semua jalur yang perlu mengubah tombol ini WAJIB lewat
        sini — jangan menulis `run_btn.setEnabled(...)` di tempat lain.
        """
        btn = getattr(self, "run_btn", None)
        if btn is None:
            return
        cs = getattr(self, "curation_settings", None)
        valid = cs.is_valid() if cs is not None else True
        btn.setEnabled(not getattr(self, "_running", False) and valid)
        btn.setToolTip(
            "" if valid else
            "Rentang belum valid: kotak merah menandai MAX yang lebih kecil dari MIN."
        )

    def refresh_model_warning(self) -> None:
        """Perbarui peringatan bundel model WhisperX dari pemeriksaan berkas NYATA.

        Sumbernya `bundled_paths.model_bundle_status()`: ia melihat folder cache yang
        BENAR-BENAR akan dipakai Stage 4 (PROJECT_ROOT/models kalau ada, kalau tidak
        ~/.cache/huggingface/hub) dan mensyaratkan berkas bobot model ada di sana —
        bukan sekadar foldernya ada. Kalau lengkap, label disembunyikan.
        """
        lbl = getattr(self, "model_warn_lbl", None)
        if lbl is None:
            return
        try:
            st = model_bundle_status(self._whisper_model_name(), PROJECT_ROOT)
        except Exception:  # noqa: BLE001  (label peringatan tidak boleh menjatuhkan GUI)
            lbl.setVisible(False)
            return
        self._model_bundle_ok = bool(st["ok"])
        if st["ok"]:
            lbl.setVisible(False)
            lbl.setText("")
            return
        lbl.setText(
            "⚠  " + MODEL_BUNDLE_WARNING
            + f"\n     Belum ada: {', '.join(st['missing'])}"
            + f"\n     Cache yang diperiksa: {st['cache_dir']}"
        )
        lbl.setToolTip(f"Cache aktif: {st['cache_dir']}")
        lbl.setVisible(True)

    @staticmethod
    def _whisper_model_name() -> str:
        """Ukuran model faster-whisper dari .env (WHISPER_MODEL), default 'medium'.

        Dibaca dari `.env` lewat `read_env_dict()`, bukan `config.settings`: GUI
        sengaja tidak mengimpor `config` (pydantic) supaya tetap ringan, dan nilai
        default di sini harus sama dengan `Settings.whisper_model`.
        """
        nilai = str(read_env_dict().get("WHISPER_MODEL", "") or "").strip()
        return nilai or "medium"

    def _kill_process_tree(self, pid: int) -> bool:
        """Matikan proses beserta SELURUH anak-cucunya (Windows).

        WAJIB, bukan penyempurnaan. Rantai nyatanya:
            clipper_gui -> main.py -> yt-dlp / ffmpeg / whisperx
        `QProcess.kill()` hanya membunuh main.py; TERUKUR 2026-08-29 anaknya tetap hidup
        dan terus mengunduh/menulis file. Artinya user menekan Hentikan, UI bilang
        berhenti, tapi disk masih ditulisi — lebih buruk daripada tidak ada tombol Stop.
        `taskkill /T` membereskan seluruh pohon (terbukti: induk=False anak=False).
        """
        try:
            res = subprocess.run(
                ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                capture_output=True, text=True, timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return res.returncode == 0
        except Exception as exc:  # noqa: BLE001
            self.log(f"   taskkill gagal: {exc}")
            return False

    def stop_pipeline(self) -> None:
        """Hentikan proses pipeline yang sedang berjalan.

        Urutan: `terminate()` dulu (kesempatan menutup file dengan rapi), lalu kalau dalam
        3 detik belum mati, matikan SEPOHON dengan taskkill /T. Langsung kill berisiko
        meninggalkan MP4 setengah jadi yang lolos cek "file sudah ada" di run berikutnya.
        """
        if not (self.process and self.process.state() != QProcess.NotRunning):
            return

        answer = QMessageBox.question(
            self,
            "Hentikan proses?",
            "Proses akan dihentikan.\n\n"
            "Yang SUDAH selesai tetap tersimpan (klip terunduh, SRT, video jadi) dan "
            "bisa dilanjutkan lagi nanti — tahap yang belum akan dilewati saat dijalankan ulang.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self._user_stopped = True
        self.stop_btn.setEnabled(False)
        self.stop_btn.setText("Menghentikan…")
        self.log("⏹ Menghentikan proses atas permintaan user...")

        pid = int(self.process.processId() or 0)

        self.process.terminate()
        if not self.process.waitForFinished(3000):
            # Belum mati: bereskan sepohon supaya yt-dlp/ffmpeg tidak jadi zombie.
            self.log("   Proses tidak merespons, menghentikan seluruh pohon proses...")
            if pid and self._kill_process_tree(pid):
                self.log("   Seluruh proses turunan dihentikan.")
            else:
                self.process.kill()
            self.process.waitForFinished(3000)
        elif pid:
            # Sudah mati rapi, tapi anaknya bisa saja lepas dari induknya. Murah untuk
            # dipastikan, dan gagal (rc != 0) itu normal kalau pohonnya memang sudah bersih.
            self._kill_process_tree(pid)

    def continue_from_curation(self, curation_path: str) -> None:
        """Lanjut dari file kurasi hasil review: Download -> Subtitle -> Render."""
        args = ["continue-from", "--curation", curation_path]
        # SRT selalu ditulis 1 kata/entri; kerapatan tampilannya urusan THEME.
        args += ["--target-words", str(self.curation_settings.subtitle_words())]
        # Centang bahasa hanya merakit `initial_prompt` WhisperX (bukan `language=`).
        # Dikirim DI SINI, bukan di perintah `stage1`: separuh kedua jalur Manual inilah
        # yang benar-benar menjalankan Stage 4. Diperiksa 2026-09-03 —
        # `main.py continue-from` menerima `--lang-tags`, `main.py stage1` TIDAK
        # (Stage 1 transkripsi kasar sendiri dengan language="id" tetap).
        args += ["--lang-tags", self.lang_picker.tags_arg()]
        # Tema dari dropdown diteruskan sebagai --preset. TIDAK menimpa
        # render_preset.active.json: itu milik tab Customize (keputusan user dikunci).
        tema = self.themes_card.preset_path()
        if tema:
            args += ["--preset", tema]
        self._start_stage_process(
            args,
            f"Lanjut dari hasil review: {Path(curation_path).name}",
            first_stage="Download",
        )

    def run_pipeline(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "URL belum diisi", "Masukkan URL YouTube terlebih dahulu.")
            return

        # Validasi bentuk URL SEBELUM proses jalan. Aturannya sama dengan regex di
        # main.py; tanpa cek ini, URL salah baru gagal SETELAH Stage 1 memanggil Gemini
        # — mahal (satu request terbuang) dan pesan errornya jauh dari penyebabnya.
        video_id, alasan = normalize_youtube_url(url)
        if not video_id:
            QMessageBox.warning(self, "URL tidak valid", alasan)
            self.url_input.setFocus()
            self.url_input.selectAll()
            return

        # Rentang tidak valid seharusnya sudah menonaktifkan tombol; cek lagi di sini
        # supaya jalur lain (mis. Enter di kotak URL) tidak menembusnya.
        if not self.curation_settings.is_valid():
            QMessageBox.warning(
                self, "Rentang belum valid",
                "Nilai MAX tidak boleh lebih kecil dari MIN. Kotak yang bermasalah "
                "ditandai merah.",
            )
            return

        n_min, n_max, lo, hi = self.curation_settings.values()
        words = self.curation_settings.subtitle_words()
        langs = self.lang_picker.tags_arg()

        if self.mode_toggle.mode == "manual":
            # Mode Manual: HANYA Stage 1. Klip lalu muncul di Review klip untuk dipilih
            # sebelum download — inilah yang menghemat ~2-3 menit unduh + ~2 menit
            # subtitle per klip yang tidak diinginkan.
            # `--count` = MAX (batas atas pencarian), `--min-count` = ambang kebutuhan.
            # `--lang-tags` TIDAK dikirim di sini: perintah `stage1` tidak menerimanya
            # (diperiksa 2026-09-03 lewat `main.py stage1 --help`) dan memang tidak
            # perlu — centang bahasa hanya memengaruhi initial_prompt WhisperX yang
            # jalan di Stage 4, yaitu di `continue-from` setelah review.
            args = ["stage1", "--url", url,
                    "--count", str(n_max), "--min-count", str(n_min),
                    "--min-sec", str(lo), "--max-sec", str(hi)]
            judul = (f"Curation saja (mode Manual)\nURL: {url}\n"
                     f"Klip {n_min}-{n_max} (MIN tidak dijamin), durasi {lo}-{hi}s")
            self._pending_manual = True
            self._start_stage_process(args, judul, first_stage="Curation")
            return

        args = ["run", "--url", url,
                "--count", str(n_max), "--min-count", str(n_min),
                "--min-sec", str(lo), "--max-sec", str(hi),
                "--target-words", str(words),
                "--lang-tags", langs]
        tema = self.themes_card.preset_path()
        if tema:
            args += ["--preset", tema]
        self._pending_manual = False
        self._start_stage_process(
            args,
            f"Memulai full pipeline...\nURL: {url}\n"
            f"Klip {n_min}-{n_max} (MIN tidak dijamin), durasi {lo}-{hi}s\n"
            f"Bahasa initial_prompt: {langs}\n"
            + (f"Theme: {Path(tema).stem}" if tema else self._no_theme_note()),
            first_stage="Curation",
        )

    @staticmethod
    def _no_theme_note() -> str:
        """Keterangan saat tidak ada theme tersimpan yang bisa dikirim.

        Tanpa `--preset`, Stage 5 jatuh ke `render_preset.active.json`. Itu harus
        DIKATAKAN, bukan dibiarkan diam-diam: keputusan user (Item 25) adalah tab Run
        menjalankan theme tersimpan, jadi keadaan "tidak ada theme" perlu terlihat di
        log alih-alih menghasilkan gaya yang tidak dipilih siapa pun.
        """
        return ("Theme: (belum ada theme tersimpan) — render memakai preset aktif "
                "terakhir dari Customize. Simpan Theme dulu supaya gayanya pasti.")

    def read_stdout(self):
        if not self.process:
            return
        data = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in data.splitlines():
            self.handle_output_line(line)

    def read_stderr(self):
        if not self.process:
            return
        data = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
        for line in data.splitlines():
            self.handle_output_line(line)

    def handle_output_line(self, line: str):
        line = line.strip()
        if not line:
            return

        # Kategori baris menentukan WARNA di log dan apakah kartu stage jadi merah.
        # Logika parsing ada di gui_logparse.py (fungsi murni, ada tesnya) — sebelumnya
        # inline di sini dan setiap ringkasan sukses ("Failed: 0") ikut memerah.
        kategori = classify_log_line(line)
        self.log(line, kategori)

        # Folder hasil: diambil dari PREFIKS log secara utuh. Versi lama memecah baris
        # per spasi, jadi judul folder yang mengandung spasi/emoji tidak pernah ketemu
        # dan tombol "Buka folder" mendarat di root final/.
        cand = extract_output_dir(line)
        if cand is not None:
            try:
                if not cand.is_absolute():
                    cand = (PROJECT_ROOT / cand).resolve()
                if cand.is_dir() and FINAL_ROOT.resolve() in cand.resolve().parents:
                    self._last_output_dir = cand
            except Exception:  # noqa: BLE001
                pass

        # Progres PER-KLIP di dalam stage. Stage 4 makan ~2 menit/klip, jadi bar yang
        # diam di 60% selama 10 menit tampak menggantung padahal jalan.
        total = parse_clip_total(line)
        if total:
            self._clip_total = total
        maju = parse_clip_progress(line)
        if maju:
            idx, tot = maju
            if tot:
                self._clip_total = tot
            self._set_clip_progress(idx, self._clip_total)

        upper = line.upper()
        if ">>> STAGE 1" in upper or "STAGE 1:" in upper:
            self.set_stage("Stage 1")
            self._begin_stage("Stage 1", "Stage 1 — Curation")
        elif ">>> STAGE 2" in upper or "STAGE 2:" in upper:
            self.mark_done_before("Stage 2")
            self.set_stage("Stage 2")
            self._begin_stage("Stage 2", "Stage 2 — Download")
        elif ">>> STAGE 4" in upper or "STAGE 4:" in upper:
            self.mark_done_before("Stage 4")
            self.set_stage("Stage 4")
            self._begin_stage("Stage 4", "Stage 4 — Subtitles")
        elif ">>> STAGE 5" in upper or "STAGE 5:" in upper:
            self.mark_done_before("Stage 5")
            self.set_stage("Stage 5")
            self._begin_stage("Stage 5", "Stage 5 — Render")
        elif "STAGE 5: DONE" in upper or "FULL PIPELINE COMPLETE" in upper:
            for card in self.stage_cards.values():
                card.set_state("done")
            self._set_progress(100, "Selesai")
        elif kategori == "error":
            current = self.current_running_stage()
            if current and current in self.stage_cards:
                self.stage_cards[current].set_state("error")

    # ---------- Progres per-klip ----------
    def _begin_stage(self, stage: str, label: str) -> None:
        """Masuk stage baru: reset hitungan klip lalu set progres ke batas bawah stage."""
        self._stage_key = stage
        self._clip_total = 0
        self._clip_done = 0
        self._set_progress(self.STAGE_PROGRESS.get(stage, 0), label)

    def _set_clip_progress(self, idx: int, total: int) -> None:
        """Gerakkan bar DI DALAM rentang stage yang sedang jalan.

        Rentang tiap stage diambil dari STAGE_PROGRESS (batas bawah) sampai batas bawah
        stage berikutnya. Jadi Stage 4 (60->80) dengan klip 3/5 menghasilkan 72%, bukan
        tetap 60% sampai seluruh stage selesai.
        Kalau totalnya belum diketahui (Stage 4 mencetak header terpisah), bar tidak
        dipaksa maju — tapi teksnya tetap menyebut nomor klip supaya terlihat hidup.
        """
        stage = getattr(self, "_stage_key", "") or ""
        urut = ["Stage 1", "Stage 2", "Stage 4", "Stage 5"]
        lo = self.STAGE_PROGRESS.get(stage, 0)
        if stage in urut and urut.index(stage) + 1 < len(urut):
            hi = self.STAGE_PROGRESS[urut[urut.index(stage) + 1]]
        else:
            hi = 100
        self._clip_done = max(getattr(self, "_clip_done", 0), int(idx))
        label = self.STAGE_CARD_KEY.get(stage, stage or "Proses")
        if total > 0:
            frac = min(1.0, max(0.0, self._clip_done / float(total)))
            nilai = int(round(lo + (hi - lo) * frac))
            self._set_progress(nilai, f"{label} — klip {self._clip_done}/{total}")
        else:
            self.progress.setFormat(f"{label} — klip {self._clip_done}")
            if getattr(self, "strip_stage", None):
                self.strip_stage.setText(f"{label} · klip {self._clip_done}")

    def set_stage(self, name: str):
        self.current_mode = name
        card = self.stage_cards.get(self.STAGE_CARD_KEY.get(name, name))
        if card:
            card.set_state("running")

    def mark_done_before(self, next_stage: str):
        order = ["Stage 1", "Stage 2", "Stage 4", "Stage 5"]
        if next_stage not in order:
            return
        for name in order[: order.index(next_stage)]:
            card = self.stage_cards.get(self.STAGE_CARD_KEY.get(name, name))
            if card:
                card.set_state("done")

    def current_running_stage(self):
        for name, card in self.stage_cards.items():
            if card.property("state") == "running":
                return name
        return None

    def pipeline_finished(self, exit_code: int, exit_status):
        self.read_stdout()
        self.read_stderr()

        self._timer.stop()

        # Dihentikan user BUKAN kegagalan. Tanpa cabang ini, menekan Stop menghasilkan
        # kartu merah "Pipeline Error" + exit code aneh (Windows: 1 atau 0xC000013A),
        # yang membuat user mengira ada yang rusak padahal ia sendiri yang menghentikan.
        if getattr(self, "_user_stopped", False):
            self._user_stopped = False
            self._pending_manual = False
            for name, card in self.stage_cards.items():
                if card.property("state") == "running":
                    card.set_state("waiting")
            self.system_status.setText("●  Dihentikan")
            self.system_status.setObjectName("statusWarn")
            self.log("⏹ Proses dihentikan. Hasil yang sudah selesai tetap tersimpan.")
            self._set_progress(0, "Dihentikan")

            # Segarkan daftar & hasil: Stage 1 mungkin sudah menulis file kurasi, atau
            # beberapa klip sudah jadi, sebelum proses dihentikan.
            self.review.refresh_list()
            self.refresh_history()

            self.system_status.style().unpolish(self.system_status)
            self.system_status.style().polish(self.system_status)
            self._set_running_ui(False)
            self.process = None
            self._update_run_nav()
            return

        if exit_code == 0:
            for card in self.stage_cards.values():
                card.set_state("done")
            self.system_status.setText("●  Pipeline Selesai")
            self.system_status.setObjectName("statusGood")
            self.log("✓ Full pipeline selesai.")
            self._set_progress(100, "Selesai")

            if getattr(self, "_pending_manual", False):
                # Mode Manual: hanya Stage 1 yang jalan. Kartu Download/Subtitle/Render
                # BELUM dikerjakan, jadi jangan ditandai selesai — itu akan bohong.
                self._pending_manual = False
                for nama in ("Download", "Subtitle", "Render"):
                    if nama in self.stage_cards:
                        self.stage_cards[nama].set_state("waiting")
                self._set_progress(100, "Curation selesai — pilih klip di Review")
                self.log("→ Curation selesai. Buka panel 'Review klip' untuk memilih.")
                self.review.refresh_list()
                # Muat otomatis hasil terbaru: itu hampir pasti yang baru saja dibuat.
                if getattr(self.review, "_files", None):
                    self.review.load_file(self.review._files[0])
                    self.review.picker.setCurrentIndex(0)
                # Antar user ke tujuan berikutnya, jangan tinggalkan dia di panel Progres
                # yang sudah tidak ada isinya.
                self.switch_run_panel(1)
            else:
                # Tampilkan hasil (Langkah B).
                out_dir = self._last_output_dir or self._latest_final_dir()
                self._last_output_dir = out_dir
                self.populate_results(out_dir)
                self.refresh_history()
                self.review.refresh_list()
                self.switch_run_panel(3)
        else:
            running = self.current_running_stage()
            if running and running in self.stage_cards:
                self.stage_cards[running].set_state("error")
            self.system_status.setText("●  Pipeline Error")
            self.system_status.setObjectName("statusBad")
            self.log(f"✕ Pipeline berhenti dengan exit code {exit_code}.")
            self.progress.setFormat("Gagal")

        self.system_status.style().unpolish(self.system_status)
        self.system_status.style().polish(self.system_status)

        self._set_running_ui(False)
        self.process = None
        self._update_run_nav()

    def pipeline_error(self, error):
        # Crash/Timedout saat user menekan Stop adalah konsekuensi terminate(), bukan bug.
        if getattr(self, "_user_stopped", False):
            return
        self.log(f"QProcess error: {error}")
        self.system_status.setText("●  Process Error")
        self.system_status.setObjectName("statusBad")
        self.system_status.style().unpolish(self.system_status)
        self.system_status.style().polish(self.system_status)

    def closeEvent(self, event):
        if self.process and self.process.state() != QProcess.NotRunning:
            answer = QMessageBox.question(
                self,
                "Pipeline sedang berjalan",
                "Pipeline masih berjalan. Tutup aplikasi?\n\n"
                "Yang sudah selesai tetap tersimpan dan bisa dilanjutkan nanti.",
                QMessageBox.Yes | QMessageBox.No,
            )
            if answer == QMessageBox.No:
                event.ignore()
                return
            # Tandai supaya handler `finished` tidak melaporkannya sebagai kegagalan,
            # dan matikan sepohon supaya yt-dlp/ffmpeg tidak terus jalan setelah app
            # ditutup (terukur: kill() induk saja meninggalkan anak tetap hidup).
            self._user_stopped = True
            pid = int(self.process.processId() or 0)
            self.process.terminate()
            if not self.process.waitForFinished(2000):
                if not (pid and self._kill_process_tree(pid)):
                    self.process.kill()
            elif pid:
                self._kill_process_tree(pid)
        event.accept()

    def apply_styles(self):
        self.setStyleSheet(r"""
            /* Clipper — tema gelap, disamakan dengan halaman Customize */
            QWidget {
                font-family: "Segoe UI";
                font-size: 13px;
                color: #EAF2FF;
            }

            QMainWindow, #root, #contentArea {
                background: #0B1220;
            }

            /* ---- Top bar ---- */
            #topbar {
                background: rgba(255,255,255,0.03);
                border-bottom: 1px solid rgba(255,255,255,0.10);
            }

            #brand {
                font-size: 16px;
                font-weight: 800;
                color: #EAF2FF;
                letter-spacing: -0.2px;
            }

            #brandBadge {
                font-size: 10px;
                font-weight: 800;
                color: #8FA5BF;
                background: rgba(255,255,255,0.07);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 6px;
                padding: 2px 7px;
                margin-left: 2px;
            }

            #navTab {
                border: none;
                background: transparent;
                color: #8FA5BF;
                font-weight: 800;
                font-size: 12px;
                padding: 7px 14px;
                border-radius: 9px;
            }

            #navTab:hover {
                background: rgba(255,255,255,0.07);
                color: #EAF2FF;
            }

            #navTab:checked {
                background: rgba(114,232,255,0.16);
                color: #EAFAFF;
            }

            #langTab {
                border: 1px solid rgba(255,255,255,0.10);
                background: rgba(255,255,255,0.04);
                color: #8FA5BF;
                font-weight: 900;
                font-size: 11px;
                padding: 6px 11px;
                border-radius: 9px;
            }

            #langTab:hover {
                background: rgba(255,255,255,0.09);
                color: #EAF2FF;
            }

            #langTab:checked {
                background: rgba(124,107,255,0.24);
                border-color: rgba(124,107,255,0.55);
                color: #EDEAFF;
            }

            /* ---- Text ---- */
            #pageTitle {
                font-size: 22px;
                font-weight: 800;
                color: #EAF2FF;
                letter-spacing: -0.4px;
            }

            /* Judul panel tab Run: teks BIASA, bukan judul besar (permintaan user
               2026-08-30). Nama panel sudah ada di sidebar, jadi judul 22px di dalam
               panel hanya mengulang informasi yang sama dengan ukuran mencolok. */
            #panelLabel {
                font-size: 12.5px;
                font-weight: 700;
                color: #8FA5BF;
            }

            #pageSubtitle {
                font-size: 13px;
                color: #8FA5BF;
            }

            #cardTitle {
                font-size: 11px;
                font-weight: 900;
                color: #8FA5BF;
                letter-spacing: 0.09em;
                text-transform: uppercase;
            }

            #hint {
                font-size: 11.5px;
                color: #8FA5BF;
            }

            /* ---- Cards ---- */
            #card {
                background: rgba(255,255,255,0.045);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 18px;
            }

            /* ---- Inputs ---- */
            QLineEdit {
                background: rgba(3,7,18,0.70);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 11px;
                padding: 9px 11px;
                color: #EAF2FF;
                selection-background-color: #72E8FF;
                selection-color: #06101D;
            }

            QLineEdit:focus {
                border-color: #72E8FF;
            }

            QComboBox {
                background: rgba(3,7,18,0.70);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 11px;
                padding: 8px 11px;
                color: #EAF2FF;
            }

            QComboBox:focus, QComboBox:hover {
                border-color: rgba(255,255,255,0.18);
            }

            QComboBox::drop-down {
                border: 0;
                width: 22px;
            }

            QComboBox QAbstractItemView {
                background: #0A1526;
                border: 1px solid rgba(255,255,255,0.18);
                border-radius: 10px;
                color: #EAF2FF;
                selection-background-color: rgba(114,232,255,0.20);
                outline: 0;
                padding: 4px;
            }

            /* ---- Buttons ---- */
            #primaryButton {
                background: #72E8FF;
                color: #06101D;
                border: 0;
                border-radius: 12px;
                padding: 10px 18px;
                font-weight: 800;
            }

            #primaryButton:hover { background: #8CEEFF; }
            #primaryButton:pressed { background: #5FD6EE; }
            #primaryButton:disabled { background: rgba(255,255,255,0.10); color: #6B7C93; }

            /* Tombol Hentikan: merah tegas supaya tidak tertukar dengan Jalankan. */
            #stopButton {
                background: #FF8B8B;
                color: #2A0A0A;
                border: 0;
                border-radius: 12px;
                padding: 10px 18px;
                font-weight: 800;
            }
            #stopButton:hover { background: #FFA5A5; }
            #stopButton:pressed { background: #E97676; }
            #stopButton:disabled { background: rgba(255,139,139,0.28); color: #7A4A4A; }

            /* ---- Tab Run: strip status + sidebar panel ---- */
            #statusStrip {
                background: rgba(114,232,255,0.07);
                border-bottom: 1px solid rgba(114,232,255,0.20);
            }
            #stripStage {
                font-size: 11.5px; font-weight: 800; color: #72E8FF;
                min-width: 120px;
            }
            #statusStrip #stopButton { padding: 6px 14px; }

            #runSidebar {
                background: rgba(255,255,255,0.025);
                border-right: 1px solid rgba(255,255,255,0.08);
            }
            #runSidebar #sidebarButton {
                text-align: left;
                padding: 10px 12px;
                border-radius: 10px;
                font-size: 12.5px;
                font-weight: 700;
                color: #8FA5BF;
                background: transparent;
                border: 1px solid transparent;
            }
            #runSidebar #sidebarButton:hover {
                background: rgba(255,255,255,0.07); color: #EAF2FF;
            }
            #runSidebar #sidebarButton:checked {
                background: rgba(114,232,255,0.14);
                border-color: rgba(114,232,255,0.45);
                color: #72E8FF;
            }
            #runSidebar #sidebarButton[dim="true"] { color: #5B6B80; }

            #ghostButton {
                background: rgba(255,255,255,0.07);
                color: #EAF2FF;
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 12px;
                padding: 10px 15px;
                font-weight: 800;
            }

            #ghostButton:hover { background: rgba(255,255,255,0.11); border-color: rgba(255,255,255,0.18); }
            #ghostButton:disabled { color: #6B7C93; }

            #sidebarButton {
                background: transparent;
                border: 0;
                color: #8FA5BF;
                text-align: left;
                padding: 9px 12px;
                border-radius: 10px;
                font-weight: 700;
            }

            #sidebarButton:hover { background: rgba(255,255,255,0.07); color: #EAF2FF; }

            /* ---- Stage cards ---- */
            #stageCard {
                background: rgba(255,255,255,0.045);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 14px;
            }

            #stageCard[state="running"] { border-color: #72E8FF; background: rgba(114,232,255,0.10); }
            #stageCard[state="done"]    { border-color: rgba(119,247,178,0.55); background: rgba(119,247,178,0.09); }
            #stageCard[state="error"]   { border-color: rgba(255,139,139,0.60); background: rgba(255,139,139,0.10); }

            #stageBadge {
                font-size: 10px;
                font-weight: 900;
                color: #8FA5BF;
                background: rgba(255,255,255,0.07);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 6px;
                padding: 1px 6px;
            }

            #stageTitle { font-size: 13px; font-weight: 800; color: #EAF2FF; }
            #stageSubtitle { font-size: 11px; color: #8FA5BF; }
            #stageStatus { font-size: 15px; font-weight: 900; color: #8FA5BF; }
            #arrow { color: #55677E; font-size: 15px; font-weight: 900; }

            /* ---- Progress ---- */
            #progress {
                background: rgba(255,255,255,0.07);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 10px;
                height: 20px;
                text-align: center;
                color: #EAF2FF;
                font-size: 11px;
                font-weight: 800;
            }

            #progress::chunk {
                background: #72E8FF;
                border-radius: 9px;
            }

            #elapsed {
                font-size: 12px;
                font-weight: 900;
                color: #8FA5BF;
                font-family: "Consolas";
            }

            /* ---- Lists ---- */
            #logList, #resultsList {
                background: rgba(3,7,18,0.72);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 13px;
                padding: 7px;
                font-family: "Consolas";
                font-size: 11.5px;
                color: #C4FFDC;
                outline: 0;
            }

            #logList::item, #resultsList::item {
                padding: 2px 4px;
                border-radius: 5px;
            }

            #resultsList { color: #EAF2FF; font-family: "Segoe UI"; font-size: 12.5px; }
            #resultsList::item:selected, #logList::item:selected {
                background: rgba(114,232,255,0.18);
                color: #EAFAFF;
            }

            QListWidget { border: 1px solid rgba(255,255,255,0.10); border-radius: 13px;
                          background: rgba(3,7,18,0.72); color: #EAF2FF; outline: 0; padding: 6px; }
            QListWidget::item { padding: 6px 8px; border-radius: 8px; }
            QListWidget::item:hover { background: rgba(255,255,255,0.06); }
            QListWidget::item:selected { background: rgba(114,232,255,0.18); color: #EAFAFF; }

            /* ---- Status pills ---- */
            #statusText { font-size: 11.5px; font-weight: 800; color: #8FA5BF; }
            #statusGood { font-size: 11.5px; font-weight: 800; color: #77F7B2; }
            #statusWarn { font-size: 11.5px; font-weight: 800; color: #FACC15; }
            #statusBad  { font-size: 11.5px; font-weight: 800; color: #FF8B8B; }

            /* ---- Info blocks ---- */
            #infoHead { font-size: 12.5px; font-weight: 800; color: #EAF2FF; }
            #infoBody { font-size: 11.5px; color: #8FA5BF; }
            #infoIcon { font-size: 15px; }

            /* ---- Scrollbars ---- */
            QScrollBar:vertical {
                background: transparent; width: 9px; margin: 2px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255,255,255,0.14); border-radius: 5px; min-height: 26px;
            }
            QScrollBar::handle:vertical:hover { background: rgba(255,255,255,0.26); }
            QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
            QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

            QScrollBar:horizontal { background: transparent; height: 9px; margin: 2px; }
            QScrollBar::handle:horizontal {
                background: rgba(255,255,255,0.14); border-radius: 5px; min-width: 26px;
            }

            /* ---- Misc ---- */
            QCheckBox { color: #EAF2FF; font-size: 12px; }
            QToolTip {
                background: #0A1526; color: #EAF2FF;
                border: 1px solid rgba(255,255,255,0.18); border-radius: 8px; padding: 5px 8px;
            }
            QMessageBox { background: #0B1220; }
            QMessageBox QLabel { color: #EAF2FF; }
            QInputDialog { background: #0B1220; }
            QInputDialog QLabel { color: #EAF2FF; }
        """ + REVIEW_QSS)


def main():
    load_env_file()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = ClipperWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
