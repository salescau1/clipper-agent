"""Regresi Stage 4: bug-bug yang lolos karena diuji di venv yang salah (2026-09-01).

Ketiga bug di bawah TIDAK terdeteksi test lama karena pengujian dilakukan dari
`.venv`, sedangkan Stage 4 sesungguhnya dijalankan `.whisperx-venv` sebagai
subprocess (main.py::_stage4_batch). Test di sini mengunci perbaikannya supaya
tidak diam-diam kembali.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from stages import stage4_subtitles as s4


class TestSegmenAlignmentPunyaStartEnd:
    """S4.3: whisperx 3.8.x membaca segment["start"] langsung -> KeyError kalau tak ada."""

    def test_run_whisperx_alignment_kirim_start_dan_end(self, tmp_path: Path):
        audio = tmp_path / "a.wav"
        audio.write_bytes(b"x")

        fake_whisperx = MagicMock()
        fake_whisperx.load_align_model.return_value = (MagicMock(), MagicMock())
        # 32000 sampel @ 16 kHz = 2.0 detik
        fake_whisperx.load_audio.return_value = [0] * 32000
        fake_whisperx.align.return_value = {
            "segments": [{"words": [{"word": "halo", "start": 0.1, "end": 0.4}]}],
        }
        fake_torch = MagicMock()
        fake_torch.cuda.is_available.return_value = False

        with patch.dict("sys.modules", {"whisperx": fake_whisperx, "torch": fake_torch}):
            words = s4._run_whisperx_alignment(audio, "halo dunia", language="id")

        assert words == [{"word": "halo", "start": 0.1, "end": 0.4}]

        segmen = fake_whisperx.align.call_args[0][0]
        assert len(segmen) == 1
        assert "start" in segmen[0], "tanpa 'start' whisperx 3.8.x melempar KeyError"
        assert "end" in segmen[0], "tanpa 'end' whisperx 3.8.x melempar KeyError"
        assert segmen[0]["start"] == 0.0
        assert segmen[0]["end"] == pytest.approx(2.0), "durasi = jumlah sampel / 16000"
        assert segmen[0]["text"] == "halo dunia"


class TestKoreksiTrilingualMemuatEnv:
    """S4.2: pydantic-settings baca .env ke `settings`, BUKAN ke os.environ."""

    def test_load_dotenv_dipanggil_saat_env_var_kosong(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        dipanggil = {"n": 0}

        def fake_load_dotenv(path=None):
            dipanggil["n"] += 1
            return True

        fake_dotenv = MagicMock()
        fake_dotenv.load_dotenv = fake_load_dotenv

        with patch.dict("sys.modules", {"dotenv": fake_dotenv}):
            teks, status = s4.correct_text_trilingual("ada teks di sini")

        assert dipanggil["n"] == 1, "load_dotenv wajib dipanggil kalau env var kosong"
        assert status == "not_configured"
        assert teks == "ada teks di sini", "teks asli dikembalikan apa adanya saat gagal"

    def test_load_dotenv_dilewati_kalau_env_var_sudah_ada(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "sudah-ada")
        dipanggil = {"n": 0}

        fake_dotenv = MagicMock()
        fake_dotenv.load_dotenv = lambda path=None: dipanggil.__setitem__("n", dipanggil["n"] + 1)

        fake_openai = MagicMock()
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="teks bersih"))],
        )
        fake_openai.OpenAI.return_value = fake_client

        with patch.dict("sys.modules", {"dotenv": fake_dotenv, "openai": fake_openai}):
            teks, status = s4.correct_text_trilingual("teks kotor")

        assert dipanggil["n"] == 0, "jangan baca .env kalau env var sudah tersedia"
        assert status == "success"
        assert teks == "teks bersih"

    def test_tanpa_python_dotenv_tidak_crash(self, monkeypatch):
        """Lingkungan tanpa python-dotenv harus tetap jalan, bukan ImportError."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

        def blokir_dotenv(name, *args, **kwargs):
            if name == "dotenv":
                raise ImportError("No module named 'dotenv'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=blokir_dotenv):
            teks, status = s4.correct_text_trilingual("teks apa saja")

        assert status == "not_configured"
        assert teks == "teks apa saja"


class TestLogInfoTanpaLogger:
    """`logger` bernilai None di mode whisperx-venv-only; _log_info tidak boleh crash."""

    def test_log_info_jalan_saat_logger_none(self, capsys):
        with patch.object(s4, "logger", None):
            s4._log_info("pesan uji")
        assert "pesan uji" in capsys.readouterr().out

    def test_log_info_pakai_logger_kalau_ada(self):
        fake_logger = MagicMock()
        with patch.object(s4, "logger", fake_logger):
            s4._log_info("pesan %s", "berformat")
        fake_logger.info.assert_called_once_with("pesan %s", "berformat")


class TestModelWhisperMedium:
    """Ukuran model tidak boleh turun ke `small` — salah dengar kosakata Sunda."""

    def test_whisper_model_medium(self):
        assert s4._WHISPER_MODEL == "medium"
