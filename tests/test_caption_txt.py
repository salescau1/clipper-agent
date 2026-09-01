"""Tes caption.txt (Stage 5): format blok, hashtag, sumber data.

Format yang diminta user: `KLIP N` -> judul -> alinea baru deskripsi -> alinea baru
hashtag. Yang diuji di sini adalah URUTAN dan PEMISAH BARIS itu, bukan cuma
"fungsinya tidak error".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stages"))

from stages.caption_txt import (  # noqa: E402
    CAPTION_FILENAME,
    build_caption_text,
    collect_entries,
    load_curation_map,
    merge_hashtags,
    normalize_hashtag,
    write_caption_file,
)


# --------------------------------------------------------------- hashtag


def test_normalize_hashtag_menambah_pagar():
    assert normalize_hashtag("TabletGaming") == "#TabletGaming"


def test_normalize_hashtag_tidak_menggandakan_pagar():
    assert normalize_hashtag("#TabletGaming") == "#TabletGaming"


def test_normalize_hashtag_membuang_spasi_bukan_menggantinya():
    # Spasi di tengah hashtag memecahnya jadi DUA tag di TikTok.
    assert normalize_hashtag("Tablet Gaming Murah") == "#TabletGamingMurah"


def test_normalize_hashtag_membuang_emoji_dan_tanda_baca():
    assert normalize_hashtag("Tablet‼️ Mini!") == "#TabletMini"


def test_normalize_hashtag_kosong():
    assert normalize_hashtag("") == ""
    assert normalize_hashtag("   ") == ""
    assert normalize_hashtag("#") == ""
    assert normalize_hashtag("!!!") == ""


def test_merge_hashtags_menambahkan_tag_umum():
    hasil = merge_hashtags(["#A", "B"])
    assert hasil[:2] == ["#A", "#B"]
    assert "#fyp" in hasil and "#shorts" in hasil and "#viral" in hasil


def test_merge_hashtags_buang_duplikat_tanpa_peka_huruf():
    hasil = merge_hashtags(["#FYP", "#Fyp", "#fyp"])
    assert hasil.count("#FYP") == 1
    assert len([t for t in hasil if t.lower() == "#fyp"]) == 1


def test_merge_hashtags_tanpa_tag_tetap_ada_tag_umum():
    assert merge_hashtags(None) == ["#fyp", "#shorts", "#viral"]


# --------------------------------------------------------------- sumber data


def _tulis_kurasi(folder: Path, extra: dict | None = None) -> Path:
    data = {
        "url_video": "https://youtu.be/abc12345678",
        "judul_video": "Judul Video Asli",
        "video_id": "abc12345678",
        "total_klip": 2,
        "daftar_klip": [
            {
                "id_klip": 1,
                "judul_relevan": "Judul Klip Satu",
                "deskripsi": "Deskripsi klip satu yang panjang.",
                "start_klip": "00:00:10",
                "end_klip": "00:01:10",
                "tags": ["#Satu", "Dua Tiga"],
                "hook": "hook satu",
            },
            {
                "id_klip": 2,
                "judul_relevan": "Judul Klip Dua",
                "deskripsi": "Deskripsi klip dua.",
                "start_klip": "00:02:00",
                "end_klip": "00:03:00",
                "tags": ["#Empat"],
                "hook": "hook dua",
            },
        ],
    }
    if extra:
        data.update(extra)
    p = folder / "abc12345678.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def _manifest(folder: Path, **over) -> dict:
    data = {
        "video_id": "abc12345678",
        "video_title": "Judul Video Asli",
        "creator": "Channel Asli",
        "source_url": "https://youtu.be/abc12345678",
        "output_directory": str(folder),
        "clips": [
            {"clip_id": 1, "output_file": "1. satu.mp4", "output_path": str(folder / "1. satu.mp4"),
             "title": "Judul Klip Satu", "headline": "", "hook": "hook satu", "status": "success"},
            {"clip_id": 2, "output_file": "2. dua.mp4", "output_path": str(folder / "2. dua.mp4"),
             "title": "Judul Klip Dua", "headline": "", "hook": "hook dua", "status": "success"},
        ],
    }
    data.update(over)
    return data


def test_load_curation_map_menolak_manifest(tmp_path):
    # manifest.json ada di folder yang sama dan lebih dulu secara alfabet daripada
    # <video_id>.json — kalau filter longgar, data video yang SALAH yang terbaca.
    (tmp_path / "manifest.json").write_text(
        json.dumps({"clips": [], "daftar_klip": [{"id_klip": 99}]}), encoding="utf-8")
    (tmp_path / "subtitle_manifest.json").write_text(
        json.dumps({"daftar_klip": [{"id_klip": 98}]}), encoding="utf-8")
    _tulis_kurasi(tmp_path)
    kur = load_curation_map(tmp_path)
    assert sorted(kur) == [1, 2]


def test_load_curation_map_folder_tidak_ada(tmp_path):
    assert load_curation_map(tmp_path / "tidak-ada") == {}


def test_collect_entries_ambil_deskripsi_dan_tags_dari_kurasi(tmp_path):
    _tulis_kurasi(tmp_path)
    entries = collect_entries(_manifest(tmp_path), load_curation_map(tmp_path))
    assert [e["no"] for e in entries] == [1, 2]
    assert entries[0]["deskripsi"] == "Deskripsi klip satu yang panjang."
    assert entries[0]["hashtags"][:2] == ["#Satu", "#DuaTiga"]


def test_collect_entries_headline_user_mengalahkan_judul_gemini(tmp_path):
    _tulis_kurasi(tmp_path)
    m = _manifest(tmp_path)
    m["clips"][0]["headline"] = "HEADLINE KETIKAN USER"
    entries = collect_entries(m, load_curation_map(tmp_path))
    assert entries[0]["judul"] == "HEADLINE KETIKAN USER"


def test_collect_entries_tanpa_kurasi_masih_jalan(tmp_path):
    entries = collect_entries(_manifest(tmp_path), {})
    assert len(entries) == 2
    # Tanpa kurasi, deskripsi jatuh ke hook supaya tidak kosong sama sekali.
    assert entries[0]["deskripsi"] == "hook satu"
    assert entries[0]["hashtags"] == ["#fyp", "#shorts", "#viral"]


def test_collect_entries_lewati_klip_gagal(tmp_path):
    m = _manifest(tmp_path)
    m["clips"][1]["status"] = "failed"
    entries = collect_entries(m, {})
    assert [e["no"] for e in entries] == [1]


def test_collect_entries_pakai_clip_id_bukan_nomor_urut(tmp_path):
    # User men-skip klip 2-4: manifest hanya memuat clip_id 1 dan 5.
    m = _manifest(tmp_path)
    m["clips"][1]["clip_id"] = 5
    entries = collect_entries(m, {})
    assert [e["no"] for e in entries] == [1, 5]


# --------------------------------------------------------------- format


def test_format_blok_judul_deskripsi_hashtag_dipisah_baris_kosong(tmp_path):
    _tulis_kurasi(tmp_path)
    text = build_caption_text(collect_entries(_manifest(tmp_path), load_curation_map(tmp_path)))
    lines = text.split("\n")
    i = lines.index("KLIP 1")
    blok = lines[i:]
    # Urutan yang diminta user: judul, kosong, deskripsi, kosong, hashtag.
    judul_idx = blok.index("Judul Klip Satu")
    assert blok[judul_idx + 1] == ""
    assert blok[judul_idx + 2] == "Deskripsi klip satu yang panjang."
    assert blok[judul_idx + 3] == ""
    assert blok[judul_idx + 4].startswith("#Satu #DuaTiga")


def test_format_memuat_semua_nomor_klip(tmp_path):
    _tulis_kurasi(tmp_path)
    text = build_caption_text(collect_entries(_manifest(tmp_path), load_curation_map(tmp_path)))
    assert "KLIP 1" in text and "KLIP 2" in text


def test_write_caption_file_tanpa_crlf(tmp_path):
    # `Path.write_text` di Windows menghasilkan CRLF; caption harus LF saja.
    out = tmp_path / "final"
    out.mkdir()
    src = tmp_path / "src"
    src.mkdir()
    _tulis_kurasi(src)
    p = write_caption_file(out, _manifest(src), curation_folder=src)
    assert p is not None and p.name == CAPTION_FILENAME
    assert b"\r\n" not in p.read_bytes()


def test_write_caption_file_kosong_kalau_tidak_ada_klip(tmp_path):
    assert write_caption_file(tmp_path, {"clips": []}) is None


def test_write_caption_file_menimpa_isi_lama(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _tulis_kurasi(src)
    out = tmp_path / "final"
    out.mkdir()
    (out / CAPTION_FILENAME).write_text("SAMPAH LAMA", encoding="utf-8")
    p = write_caption_file(out, _manifest(src), curation_folder=src)
    isi = p.read_text(encoding="utf-8")
    assert "SAMPAH LAMA" not in isi
    assert "KLIP 1" in isi


def test_header_memuat_judul_kreator_sumber(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _tulis_kurasi(src)
    m = _manifest(src)
    text = build_caption_text(
        collect_entries(m, load_curation_map(src)),
        video_title=m["video_title"], creator=m["creator"], source_url=m["source_url"],
    )
    assert "Judul Video Asli" in text
    assert "Channel Asli" in text
    assert "https://youtu.be/abc12345678" in text
    assert "Jumlah klip: 2" in text


# --------------------------------------------------------------- data NYATA


def test_atas_output_nyata_kalau_ada():
    """Fixture sintetis lolos, data nyata yang menemukan bug (pelajaran lama).

    Dijalankan atas SEMUA manifest di output/ milik user kalau ada; kalau folder
    kosong (mesin lain / CI), tes di-skip alih-alih gagal.
    """
    root = ROOT / "output"
    manifests = sorted(root.glob("*/*/manifest.json")) if root.is_dir() else []
    if not manifests:
        pytest.skip("output/ kosong di mesin ini")
    for mp in manifests:
        data = json.loads(mp.read_text(encoding="utf-8-sig"))
        entries = collect_entries(data, load_curation_map(mp.parent))
        text = build_caption_text(entries, video_title=str(data.get("video_title") or ""))
        assert entries, f"tidak ada entri caption untuk {mp}"
        for e in entries:
            assert e["judul"], f"judul kosong pada klip {e['no']} di {mp}"
            assert e["hashtags"], f"hashtag kosong pada klip {e['no']} di {mp}"
            assert f"KLIP {e['no']}" in text
