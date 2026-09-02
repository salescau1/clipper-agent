"""Uji Item 27 (rentang klip Min-Max) TANPA memanggil API Gemini.

Semua kandidat dibuat sendiri; `curate_with_gemini` dipatch supaya
`max_tokens` bisa dibaca tanpa request nyata. Sesuai aturan proyek: kuota
Gemini 20/hari dan menjalankan curation ulang MENIMPA file kurasi berisi
pilihan review user.

CATATAN pytest: `caplog` TIDAK bisa dipakai di sini. `utils.setup_logging()`
menyetel `logger.propagate = False` pada logger "clipper", dan handler caplog
menempel di root — jadi setelah `stage1_curate.run()` dipanggil sekali,
caplog.records selalu kosong dan assert-nya jadi bohong (lulus/gagal
tergantung urutan test). Log ditangkap lewat handler sendiri di `TangkapLog`.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from models import GeminiClipCandidate
from stages.stage1_curate import (
    _build_gemini_prompt,
    curate_with_gemini,
    validate_and_normalize_clips,
)


class TangkapLog:
    """Context manager: rekam pesan logger 'clipper' apa pun nilai propagate-nya."""

    def __init__(self, level: int = logging.INFO) -> None:
        self.level = level
        self.records: list[logging.LogRecord] = []
        self._logger = logging.getLogger("clipper")
        self._handler: logging.Handler | None = None
        self._level_lama: int | None = None

    def __enter__(self) -> "TangkapLog":
        records = self.records

        class _H(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        self._handler = _H(level=self.level)
        self._level_lama = self._logger.level
        self._logger.setLevel(self.level)
        self._logger.addHandler(self._handler)
        return self

    def __exit__(self, *exc) -> None:
        if self._handler is not None:
            self._logger.removeHandler(self._handler)
        if self._level_lama is not None:
            self._logger.setLevel(self._level_lama)

    def pesan(self, min_level: int = logging.WARNING) -> list[str]:
        return [r.getMessage() for r in self.records if r.levelno >= min_level]


def _kandidat(n: int, mulai_menit: int = 0, durasi_detik: int = 90) -> list[GeminiClipCandidate]:
    """n kandidat valid yang TIDAK bertumpuk (jarak 5 menit antar klip)."""
    out = []
    for i in range(n):
        start = (mulai_menit + i * 5) * 60
        end = start + durasi_detik
        out.append(
            GeminiClipCandidate(
                title=f"Klip {i + 1}",
                start=f"{start // 3600:02d}:{(start % 3600) // 60:02d}:{start % 60:02d}",
                end=f"{end // 3600:02d}:{(end % 3600) // 60:02d}:{end % 60:02d}",
                description="deskripsi uji",
                tags=["#a", "#b", "#c"],
                hook="hook uji",
                score=float(90 - i),
            )
        )
    return out


class TestPengambilanHasilPakaiMax:
    """MAX = batas atas pengambilan hasil (`valid_clips[:MAX]`), bukan MIN."""

    def test_ambil_sampai_max_bukan_min(self) -> None:
        hasil = validate_and_normalize_clips(
            _kandidat(10), video_duration=4000.0, target_count=10, min_count=6
        )
        assert len(hasil) == 10, "MAX 10 harus mengambil 10, bukan dipotong ke MIN 6"

    def test_kelebihan_kandidat_dipotong_di_max(self) -> None:
        hasil = validate_and_normalize_clips(
            _kandidat(14), video_duration=5000.0, target_count=10, min_count=6
        )
        assert len(hasil) == 10

    def test_min_count_none_perilaku_lama(self) -> None:
        hasil = validate_and_normalize_clips(
            _kandidat(3), video_duration=2000.0, target_count=5
        )
        assert len(hasil) == 3, "tanpa min_count, pengambilan tetap pakai target_count"


class TestPeringatanPakaiMin:
    """Pembanding peringatan MIN, bukan MAX — dan angkanya harus disebut."""

    def test_di_bawah_max_tapi_di_atas_min_tidak_memperingatkan(self) -> None:
        with TangkapLog() as log:
            hasil = validate_and_normalize_clips(
                _kandidat(7), video_duration=4000.0, target_count=10, min_count=6
            )
        assert len(hasil) == 7
        assert not any("minimal diminta" in p for p in log.pesan()), (
            "7 dari MAX 10 dengan MIN 6 itu normal — jangan memperingatkan"
        )

    def test_di_bawah_min_memperingatkan_dengan_angka(self) -> None:
        with TangkapLog() as log:
            hasil = validate_and_normalize_clips(
                _kandidat(4), video_duration=3000.0, target_count=10, min_count=6
            )
        assert len(hasil) == 4
        pesan = " ".join(log.pesan())
        assert "4" in pesan and "6" in pesan, f"peringatan wajib menyebut angka: {pesan}"
        assert "minimal diminta" in pesan

    def test_kurang_dari_min_tidak_melempar_error(self) -> None:
        """MIN tidak dijamin: pipeline LANJUT, jangan raise dan jangan retry."""
        hasil = validate_and_normalize_clips(
            _kandidat(1), video_duration=1000.0, target_count=10, min_count=6
        )
        assert len(hasil) == 1


class TestMaxTokensDihitungDariMax:
    """max_tokens WAJIB dari MAX. Kalau dari MIN, JSON balasan terpotong."""

    def _panggil(self, target_count: int) -> int:
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"clips": []}'))]
        )
        with patch("stages.stage1_curate.OpenAI", return_value=fake_client):
            curate_with_gemini("transkrip", target_count, 3000.0)
        return fake_client.chat.completions.create.call_args.kwargs["max_tokens"]

    def test_max_tokens_ikut_max(self) -> None:
        assert self._panggil(10) == max(8192, 1024 + 10 * 500)

    def test_max_tokens_max_lebih_besar_dari_min(self) -> None:
        """20 klip butuh jatah token lebih besar daripada 6 klip."""
        assert self._panggil(20) > self._panggil(6)
        assert self._panggil(20) == 1024 + 20 * 500


class TestPromptPakaiMax:
    """Prompt meminta MAX klip ke Gemini, bukan MIN."""

    def test_prompt_menyebut_max(self) -> None:
        prompt = _build_gemini_prompt("transkrip", 10, 3000.0)
        assert "10 klip" in prompt
        assert "WAJIB kembalikan 10 klip" in prompt


class TestCekKapasitasSebelumRequest:
    """`durasi // durasi_min < MIN` -> peringatan SEBELUM API dipanggil."""

    def _jalankan(self, durasi: float, count: int, min_count: int):
        from stages import stage1_curate

        jejak: list[str] = []

        def fake_curate(*args, **kwargs):
            jejak.append("api_dipanggil")
            return _kandidat(count)

        with TangkapLog() as log:
            with (
                patch.object(stage1_curate, "extract_video_id", return_value="AAAAAAAAAAA"),
                patch.object(
                    stage1_curate,
                    "fetch_video_metadata",
                    return_value={"title": "Uji", "creator": "UJI", "duration": durasi},
                ),
                patch.object(
                    stage1_curate,
                    "load_transcript_cache",
                    return_value=MagicMock(
                        source="youtube_auto",
                        language="id",
                        segments=[
                            stage1_curate.TranscriptSegment(
                                start=0.0, duration=5.0, text="halo"
                            )
                        ],
                    ),
                ),
                patch.object(stage1_curate, "curate_with_gemini", side_effect=fake_curate),
                patch.object(stage1_curate.Path, "write_text", lambda *a, **k: None),
                patch.object(stage1_curate.Path, "mkdir", lambda *a, **k: None),
            ):
                stage1_curate.run(
                    "https://youtu.be/AAAAAAAAAAA",
                    target_count=count,
                    min_count=min_count,
                    min_seconds=60,
                    max_seconds=240,
                )
        return jejak, log

    def test_kapasitas_kurang_memperingatkan_sebelum_api(self) -> None:
        # 3 menit @ minimal 60s = maks 3 klip, sedangkan MIN 6 -> mustahil.
        jejak, log = self._jalankan(180.0, count=10, min_count=6)
        assert jejak == ["api_dipanggil"]
        kapasitas = [p for p in log.pesan() if "KAPASITAS KURANG" in p]
        assert kapasitas, f"peringatan kapasitas tidak muncul: {log.pesan()}"
        assert "3" in kapasitas[0] and "6" in kapasitas[0]

        # Peringatan kapasitas WAJIB lebih dulu daripada panggilan API.
        urutan = [r.getMessage() for r in log.records]
        idx_kapasitas = next(
            i for i, m in enumerate(urutan) if "KAPASITAS KURANG" in m
        )
        idx_validasi = next(
            i for i, m in enumerate(urutan) if "Validating" in m
        )
        assert idx_kapasitas < idx_validasi

    def test_kapasitas_cukup_tanpa_peringatan_kapasitas(self) -> None:
        # 40 menit @ 60s = maks 40 klip, MIN 6 aman.
        _, log = self._jalankan(2400.0, count=10, min_count=6)
        assert not any("KAPASITAS KURANG" in p for p in log.pesan())

    def test_min_lebih_besar_dari_max_dijepit(self) -> None:
        _, log = self._jalankan(2400.0, count=5, min_count=9)
        pesan = " ".join(log.pesan())
        assert "MIN klip" in pesan and "diturunkan" in pesan


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
