"""Uji Item 24: rantai `--lang-tags` -> initial_prompt + VAD Silero.

Yang dikunci di sini:
  1. Tag bahasa TIDAK PERNAH masuk parameter `language=`. Kalau 'su' masuk,
     forced alignment whisperx MATI (whisperx punya 41 bahasa beralignment; 'su'
     dan 'jv' tidak termasuk) -> timestamp per kata hilang -> SRT 1 kata/entri
     hancur -> kerapatan subtitle 1/3/5 kata di Theme kehilangan fondasinya.
  2. `vad_filter=True` DIKIRIM. Default faster-whisper adalah False dan kode
     memanggil `WhisperModel(...)` langsung (bukan `whisperx.load_model` yang
     membawa Silero-VAD), jadi tanpa parameter ini VAD tidak aktif sama sekali.
  3. `condition_on_previous_text=False` masih ada (jangan sampai hilang).
  4. DUA jalur pemanggilan diperiksa. File ini pernah kena bug "logika kembar
     ~60 baris" di mana perbaikan di satu jalur tidak sampai ke jalur lainnya.

CATATAN: pytest jalan di `.venv` yang TIDAK punya faster_whisper. Modulnya
di-stub lewat `sys.modules` supaya kwargs bisa diperiksa tanpa mengunduh model.
Verifikasi jalur produksi dari `.whisperx-venv` tetap wajib dilakukan terpisah.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from stages import stage4_subtitles as s4


# ---------------------------------------------------------------------------
# parse_lang_tags / build_initial_prompt
# ---------------------------------------------------------------------------


class TestParseLangTags:
    def test_koma_dipecah(self) -> None:
        assert s4.parse_lang_tags("id,su") == ["id", "su"]
        assert s4.parse_lang_tags("id,su,en") == ["id", "su", "en"]

    def test_daftar_kosong_jatuh_ke_id(self) -> None:
        """Item 24 poin 2: jangan pernah meneruskan daftar kosong."""
        for kosong in ("", ",", ",,", "   ", [], None):
            assert s4.parse_lang_tags(kosong) == ["id"], f"gagal untuk {kosong!r}"

    def test_tag_tak_dikenal_dibuang(self) -> None:
        assert s4.parse_lang_tags("id,xx,su") == ["id", "su"]
        # 'jv' tidak punya kosakata -> dibuang, sisanya tetap dipakai.
        assert s4.parse_lang_tags("jv,su") == ["su"]

    def test_semua_tak_dikenal_jatuh_ke_id(self) -> None:
        assert s4.parse_lang_tags("xx,yy") == ["id"]

    def test_spasi_dan_huruf_besar_dinormalkan(self) -> None:
        assert s4.parse_lang_tags([" SU ", "Id"]) == ["id", "su"]

    def test_duplikat_dihapus(self) -> None:
        assert s4.parse_lang_tags("su,su,id,id") == ["id", "su"]

    def test_urutan_deterministik(self) -> None:
        """Urutan output tidak tergantung urutan centang di UI."""
        assert s4.parse_lang_tags("en,su,id") == s4.parse_lang_tags("id,su,en")


class TestBuildInitialPrompt:
    def test_kosakata_sunda_masuk_saat_su_aktif(self) -> None:
        p = s4.build_initial_prompt("id,su")
        for kata in ("kumaha", "atuh", "euy", "punten", "nuhun", "teteh"):
            assert kata in p, f"kosakata Sunda '{kata}' hilang dari initial_prompt"

    def test_kosakata_inggris_hanya_saat_en_aktif(self) -> None:
        assert "worth it" not in s4.build_initial_prompt("id,su")
        p = s4.build_initial_prompt("id,su,en")
        for kata in ("gadget", "review", "worth it", "podcast", "creator", "gaming",
                     "frame", "setup"):
            assert kata in p

    def test_sunda_tidak_muncul_kalau_su_mati(self) -> None:
        assert "kumaha" not in s4.build_initial_prompt("id")
        assert "kumaha" not in s4.build_initial_prompt("id,en")

    def test_default_tetap_menghasilkan_prompt(self) -> None:
        """Daftar kosong -> prompt Indonesia, bukan string kosong."""
        assert s4.build_initial_prompt("").strip() != ""
        assert "Indonesia" in s4.build_initial_prompt("")

    def test_berbentuk_kalimat_bukan_daftar_berlabel(self) -> None:
        """Bentuk kalimat, bukan 'Label: kata, kata'.

        Diukur 2026-09-03: gaya daftar berlabel memunculkan fragmen ganda di akhir
        klip ("...4,1 juta." lalu segmen baru "7 juta."). Gaya kalimat tidak.
        """
        p = s4.build_initial_prompt("id,su,en")
        assert p.startswith("Ini transkrip percakapan santai ")
        assert "Bahasa Sunda:" not in p, "jangan kembali ke gaya daftar berlabel"
        assert "istilah Inggris/teknologi:" not in p
        assert p.endswith(".")

    def test_hanya_en_tetap_menyebut_indonesia(self) -> None:
        """language= tetap 'id', jadi prompt tidak boleh menghilangkan Indonesia."""
        p = s4.build_initial_prompt("en")
        assert "Indonesia" in p
        assert "gadget" in p


# ---------------------------------------------------------------------------
# Parameter yang benar-benar dikirim ke model.transcribe()
# ---------------------------------------------------------------------------


def _stub_faster_whisper() -> tuple[MagicMock, MagicMock]:
    """(modul_palsu, model_palsu) — transcribe mengembalikan satu segmen."""
    model = MagicMock()
    segmen = MagicMock()
    segmen.text = "halo dunia"
    model.transcribe.return_value = (
        [segmen],
        MagicMock(language="id", language_probability=0.99),
    )
    modul = MagicMock()
    modul.WhisperModel.return_value = model
    return modul, model


def _stub_torch() -> MagicMock:
    """torch palsu (device=cpu).

    WAJIB di-stub: `import torch` di `.venv` proyek ini MENJATUHKAN interpreter
    dengan "Windows fatal exception: access violation" (torch versi .venv tidak
    utuh; yang berfungsi ada di `.whisperx-venv`). Test regresi Stage 4 yang sudah
    ada juga men-stub torch untuk alasan yang sama.
    """
    fake = MagicMock()
    fake.cuda.is_available.return_value = False
    return fake


class TestTranscribeClipAsrKwargs:
    """Jalur 1: `transcribe_clip_asr()` (fallback saat tidak ada CC YouTube)."""

    def _kwargs(self, lang_tags, tmp_path: Path) -> dict:
        modul, model = _stub_faster_whisper()
        video = tmp_path / "klip.mp4"
        video.write_bytes(b"x")

        with (
            patch.dict("sys.modules", {"faster_whisper": modul, "torch": _stub_torch()}),
            patch.object(s4, "_extract_audio_for_whisperx", return_value=True),
        ):
            s4.transcribe_clip_asr(video, lang_tags=lang_tags)

        assert model.transcribe.called, "model.transcribe tidak pernah dipanggil"
        return model.transcribe.call_args.kwargs

    def test_language_tetap_id_walau_su_dikirim(self, tmp_path: Path) -> None:
        kw = self._kwargs("id,su", tmp_path)
        assert kw["language"] == "id", (
            "tag bahasa TIDAK BOLEH masuk language= — 'su' di sini mematikan "
            "forced alignment whisperx dan menghancurkan SRT 1 kata/entri"
        )

    def test_language_tetap_id_walau_hanya_su(self, tmp_path: Path) -> None:
        assert self._kwargs("su", tmp_path)["language"] == "id"

    def test_initial_prompt_terkirim(self, tmp_path: Path) -> None:
        kw = self._kwargs("id,su", tmp_path)
        assert "initial_prompt" in kw
        assert "kumaha" in kw["initial_prompt"]

    def test_vad_filter_aktif(self, tmp_path: Path) -> None:
        kw = self._kwargs("id,su", tmp_path)
        assert kw.get("vad_filter") is True, (
            "vad_filter default False di faster-whisper; tanpa True VAD tidak aktif"
        )
        assert kw.get("vad_parameters") == s4._VAD_PARAMETERS

    def test_anti_looping_masih_ada(self, tmp_path: Path) -> None:
        kw = self._kwargs("id,su", tmp_path)
        assert kw["condition_on_previous_text"] is False
        assert kw["no_speech_threshold"] == 0.6
        assert kw["temperature"] == (0.0, 0.2, 0.4)

    def test_tanpa_lang_tags_tetap_ada_initial_prompt(self, tmp_path: Path) -> None:
        kw = self._kwargs(None, tmp_path)
        assert kw["initial_prompt"].strip() != ""
        assert kw["language"] == "id"


class TestRunCliKwargs:
    """Jalur 2: `_run_cli()` — INI yang dipakai stage4_batch.py di produksi."""

    def _kwargs(self, argv_tags: list[str], tmp_path: Path) -> dict:
        modul, model = _stub_faster_whisper()
        video = tmp_path / "klip.mp4"
        video.write_bytes(b"x")

        fake_whisperx = MagicMock()
        fake_whisperx.load_audio.return_value = [0] * 32000
        fake_whisperx.load_align_model.return_value = (MagicMock(), MagicMock())
        fake_whisperx.align.return_value = {
            "word_segments": [{"word": "halo", "start": 0.1, "end": 0.4}],
        }

        argv = [
            "stage4_subtitles.py",
            "--video", str(video),
            "--youtube-url", "https://www.youtube.com/watch?v=AAAAAAAAAAA",
            "--start", "00:00:00",
            "--end", "00:00:25",
            "--target-words", "1",
            *argv_tags,
        ]

        with (
            patch.dict(
                "sys.modules",
                {
                    "faster_whisper": modul,
                    "whisperx": fake_whisperx,
                    "torch": _stub_torch(),
                },
            ),
            patch.object(s4.sys, "argv", argv),
            patch.object(s4, "find_stage2_manifest", return_value=None),
        ):
            s4._run_cli()

        assert model.transcribe.called
        return model.transcribe.call_args.kwargs

    def test_language_tetap_id_walau_su_dikirim(self, tmp_path: Path) -> None:
        kw = self._kwargs(["--lang-tags", "id,su"], tmp_path)
        assert kw["language"] == "id"

    def test_initial_prompt_ikut_tag(self, tmp_path: Path) -> None:
        kw = self._kwargs(["--lang-tags", "id,su,en"], tmp_path)
        assert "kumaha" in kw["initial_prompt"]
        assert "worth it" in kw["initial_prompt"]

    def test_vad_filter_aktif(self, tmp_path: Path) -> None:
        kw = self._kwargs(["--lang-tags", "id,su"], tmp_path)
        assert kw.get("vad_filter") is True
        assert kw.get("vad_parameters") == s4._VAD_PARAMETERS

    def test_anti_looping_masih_ada(self, tmp_path: Path) -> None:
        kw = self._kwargs(["--lang-tags", "id,su"], tmp_path)
        assert kw["condition_on_previous_text"] is False
        assert kw["no_speech_threshold"] == 0.6

    def test_tanpa_flag_tetap_jalan(self, tmp_path: Path) -> None:
        """`--lang-tags` opsional: jalur lama tanpa flag tidak boleh pecah."""
        kw = self._kwargs([], tmp_path)
        assert kw["language"] == "id"
        assert kw["initial_prompt"].strip() != ""


class TestKeduaJalurKonsisten:
    """Penjaga bug 'logika kembar': kedua jalur harus kirim parameter yang sama."""

    def test_parameter_anti_looping_sama_di_dua_jalur(self, tmp_path: Path) -> None:
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        a = TestTranscribeClipAsrKwargs()._kwargs("id,su,en", dir_a)
        b = TestRunCliKwargs()._kwargs(["--lang-tags", "id,su,en"], dir_b)

        for kunci in (
            "language",
            "condition_on_previous_text",
            "no_speech_threshold",
            "temperature",
            "initial_prompt",
            "vad_filter",
            "vad_parameters",
        ):
            assert a[kunci] == b[kunci], (
                f"'{kunci}' berbeda antar jalur: {a[kunci]!r} vs {b[kunci]!r} — "
                "inilah kelas bug 'logika kembar' yang sudah pernah terjadi di file ini"
            )


# ---------------------------------------------------------------------------
# Rantai CLI: main.py -> stage4_batch.py -> stage4_subtitles.py
# ---------------------------------------------------------------------------


class TestRantaiCli:
    def test_stage4_batch_meneruskan_lang_tags(self, tmp_path: Path) -> None:
        import json
        import subprocess

        video = tmp_path / "klip.mp4"
        video.write_bytes(b"x")
        manifest = tmp_path / "manifest.json"
        manifest.write_text(
            json.dumps({
                "source_url": "https://www.youtube.com/watch?v=AAAAAAAAAAA",
                "clips": [{
                    "clip_id": 1,
                    "status": "success",
                    "start_time": "00:00:00",
                    "end_time": "00:00:25",
                    "output_path": str(video),
                }],
            }),
            encoding="utf-8",
        )

        from stages import stage4_batch

        tercatat: list[list[str]] = []

        def fake_run(cmd, *a, **k):
            tercatat.append(list(cmd))
            # SRT dibuat supaya batch menganggapnya sukses.
            video.with_suffix(".srt").write_text("1\n", encoding="utf-8")
            return MagicMock(returncode=0)

        argv = [
            "stage4_batch.py",
            "--manifest", str(manifest),
            "--lang-tags", "id,su",
            "--target-words", "1",
        ]
        with (
            patch.object(stage4_batch.sys, "argv", argv),
            patch.object(stage4_batch.subprocess, "run", side_effect=fake_run),
        ):
            assert stage4_batch.main() == 0

        assert tercatat, "subprocess tidak pernah dipanggil"
        cmd = tercatat[0]
        assert "--lang-tags" in cmd
        assert cmd[cmd.index("--lang-tags") + 1] == "id,su"

    def test_stage4_batch_tidak_kirim_lang_tags_kosong(self, tmp_path: Path) -> None:
        import json

        video = tmp_path / "klip.mp4"
        video.write_bytes(b"x")
        manifest = tmp_path / "manifest.json"
        manifest.write_text(
            json.dumps({
                "source_url": "https://www.youtube.com/watch?v=AAAAAAAAAAA",
                "clips": [{
                    "clip_id": 1,
                    "status": "success",
                    "start_time": "00:00:00",
                    "end_time": "00:00:25",
                    "output_path": str(video),
                }],
            }),
            encoding="utf-8",
        )

        from stages import stage4_batch

        tercatat: list[list[str]] = []

        def fake_run(cmd, *a, **k):
            tercatat.append(list(cmd))
            video.with_suffix(".srt").write_text("1\n", encoding="utf-8")
            return MagicMock(returncode=0)

        argv = ["stage4_batch.py", "--manifest", str(manifest), "--lang-tags", ",,"]
        with (
            patch.object(stage4_batch.sys, "argv", argv),
            patch.object(stage4_batch.subprocess, "run", side_effect=fake_run),
        ):
            assert stage4_batch.main() == 0

        assert "--lang-tags" not in tercatat[0], (
            "daftar kosong jangan diteruskan; subprocess punya default 'id' sendiri"
        )

    def test_main_stage4_batch_meneruskan_lang_tags(self, tmp_path: Path) -> None:
        import main

        tercatat: list[list[str]] = []

        def fake_run(cmd, *a, **k):
            tercatat.append(list(cmd))
            return MagicMock(returncode=0)

        with patch.object(main.subprocess, "run", side_effect=fake_run):
            main._stage4_batch(
                tmp_path / "manifest.json", target_words=1, lang_tags="id,su"
            )

        cmd = tercatat[0]
        assert "--lang-tags" in cmd
        assert cmd[cmd.index("--lang-tags") + 1] == "id,su"

    def test_main_stage4_batch_membuang_lang_tags_kosong(self, tmp_path: Path) -> None:
        import main

        tercatat: list[list[str]] = []

        def fake_run(cmd, *a, **k):
            tercatat.append(list(cmd))
            return MagicMock(returncode=0)

        with patch.object(main.subprocess, "run", side_effect=fake_run):
            main._stage4_batch(tmp_path / "manifest.json", lang_tags=" , , ")

        assert "--lang-tags" not in tercatat[0]


class TestKonstantaTidakBergeser:
    def test_alignment_language_tetap_id(self) -> None:
        assert s4._ALIGNMENT_LANGUAGE == "id", (
            "whisperx tidak punya model forced-alignment untuk 'su'/'jv' — "
            "bahasa transkripsi harus tetap 'id'"
        )

    def test_default_lang_tags_id(self) -> None:
        assert s4._DEFAULT_LANG_TAGS == ("id",)

    def test_su_tidak_ada_di_daftar_bahasa_alignment(self) -> None:
        """Penjaga dokumentasi: 'su' hanya boleh ada di kosakata prompt."""
        assert "su" in s4._LANG_PROMPT_VOCAB
        assert s4._ALIGNMENT_LANGUAGE != "su"

    def test_vad_tidak_lebih_agresif_dari_default_upstream(self) -> None:
        """Setelan agresif (500/200) sudah diuji dan memotong ucapan nyata.

        Terukur 2026-09-03 pada video 10s hening + 12s bicara + 10s hening:
        500/200 membuang "Tinggi saat ini." di awal (14 kata vs 19 kata),
        sementara 2000/400 memangkas hening tanpa memotong ucapan.
        """
        assert s4._VAD_PARAMETERS["min_silence_duration_ms"] >= 2000
        assert s4._VAD_PARAMETERS["speech_pad_ms"] >= 400


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
