"""Tes kotak Kreator di panel Review (2026-08-31).

Yang dijaga di sini: `creator_watermark` disimpan di TINGKAT FILE kurasi (bukan per klip),
kosong berarti ikut nama channel, dan Stage 5 memenangkan file kurasi di atas manifest
Stage 2 (karena manifest hanya ditulis ulang saat Download dijalankan).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "stages")):
    if p not in sys.path:
        sys.path.insert(0, p)

from gui_review import apply_decisions  # noqa: E402
from stages.stage5_final import creator_watermark_from_curation  # noqa: E402


def kurasi(**extra) -> dict:
    data = {
        "url_video": "https://youtu.be/xxxxxxxxxxx",
        "judul_video": "Uji",
        "video_id": "xxxxxxxxxxx",
        "daftar_klip": [
            {"id_klip": 1, "judul_relevan": "A", "deskripsi": "d", "hook": "h",
             "start_klip": "00:00:00", "end_klip": "00:01:00", "pilih": True},
            {"id_klip": 2, "judul_relevan": "B", "deskripsi": "d", "hook": "h",
             "start_klip": "00:01:00", "end_klip": "00:02:00", "pilih": True},
        ],
    }
    data.update(extra)
    return data


class TestApplyDecisions:
    def test_creator_ditulis_di_tingkat_file(self):
        d = kurasi()
        apply_decisions(d, {1: (True, ""), 2: (True, "")}, creator_watermark="MALAKA")
        assert d["creator_watermark"] == "MALAKA"
        # satu video = satu kreator: TIDAK boleh bocor jadi field per klip
        assert all("creator_watermark" not in k for k in d["daftar_klip"])

    def test_none_tidak_menyentuh_field(self):
        d = kurasi(creator_watermark="LAMA")
        apply_decisions(d, {1: (True, ""), 2: (True, "")})
        assert d["creator_watermark"] == "LAMA"

    def test_kosong_menghapus_override(self):
        d = kurasi(creator_watermark="LAMA")
        apply_decisions(d, {1: (True, ""), 2: (True, "")}, creator_watermark="")
        assert d["creator_watermark"] == ""

    def test_spasi_dipangkas(self):
        d = kurasi()
        apply_decisions(d, {}, creator_watermark="   AD REVIEW  ")
        assert d["creator_watermark"] == "AD REVIEW"

    def test_keputusan_klip_tetap_jalan(self):
        d = kurasi()
        apply_decisions(d, {1: (False, "Judul baru"), 2: (True, "")},
                        creator_watermark="X")
        k1, k2 = d["daftar_klip"]
        assert k1["pilih"] is False and k1["headline"] == "Judul baru"
        assert k2["pilih"] is True and k2["headline"] == ""


class TestCreatorWatermarkFromCuration:
    def test_membaca_dari_file_kurasi(self, tmp_path: Path):
        (tmp_path / "abcdefghijk.json").write_text(
            json.dumps(kurasi(creator_watermark="MALAKA")), encoding="utf-8")
        assert creator_watermark_from_curation(tmp_path) == "MALAKA"

    def test_mengabaikan_manifest(self, tmp_path: Path):
        """manifest.json Stage 2 juga .json — tidak boleh dianggap file kurasi."""
        (tmp_path / "manifest.json").write_text(
            json.dumps({"creator": "X", "creator_watermark": "SALAH",
                        "daftar_klip": [{"id_klip": 1}]}), encoding="utf-8")
        (tmp_path / "subtitle_manifest.json").write_text(
            json.dumps({"creator_watermark": "SALAH JUGA",
                        "daftar_klip": [{"id_klip": 1}]}), encoding="utf-8")
        assert creator_watermark_from_curation(tmp_path) == ""

    def test_folder_tanpa_kurasi(self, tmp_path: Path):
        assert creator_watermark_from_curation(tmp_path) == ""

    def test_folder_tidak_ada(self, tmp_path: Path):
        assert creator_watermark_from_curation(tmp_path / "nihil") == ""

    def test_json_rusak_dilewati(self, tmp_path: Path):
        (tmp_path / "rusak.json").write_text("{bukan json", encoding="utf-8")
        (tmp_path / "abcdefghijk.json").write_text(
            json.dumps(kurasi(creator_watermark="OK")), encoding="utf-8")
        assert creator_watermark_from_curation(tmp_path) == "OK"

    def test_tanpa_field_mengembalikan_kosong(self, tmp_path: Path):
        (tmp_path / "abcdefghijk.json").write_text(
            json.dumps(kurasi()), encoding="utf-8")
        assert creator_watermark_from_curation(tmp_path) == ""

    def test_file_kurasi_asli_di_output(self):
        """Data NYATA: semua file kurasi di output/ harus terbaca tanpa error."""
        folders = {p.parent for p in (ROOT / "output").glob("*/*/*.json")}
        if not folders:
            pytest.skip("belum ada output/")
        for f in folders:
            hasil = creator_watermark_from_curation(f)
            assert isinstance(hasil, str)


class TestModelMenerimaField:
    def test_curation_result_punya_creator_watermark(self):
        from models import CurationResult
        m = CurationResult(**kurasi(creator_watermark="MALAKA"))
        assert m.creator_watermark == "MALAKA"

    def test_default_kosong(self):
        from models import CurationResult
        assert CurationResult(**kurasi()).creator_watermark == ""

    def test_clip_manifest_punya_field(self):
        from models import ClipManifest
        m = ClipManifest(
            video_id="x", video_title="t", creator="C", creator_watermark="W",
            source_url="u", output_directory="d",
            clips=[{"clip_id": 1, "source_url": "u", "title": "a", "hook": "h",
                    "start_time": "00:00:00", "end_time": "00:00:10",
                    "output_path": "p", "status": "success"}],
        )
        assert m.creator_watermark == "W"
