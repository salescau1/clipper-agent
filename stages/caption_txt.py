"""Caption TXT untuk copy-paste ke TikTok / Shorts / Reels.

Stage 5 menulis SATU file `caption.txt` di folder hasil (`final/<creator>/<judul>/`)
berisi caption siap pakai untuk semua klip video itu, dengan format yang diminta user:

    KLIP 1
    <judul>

    <deskripsi>

    #tag #tag #tag

Kenapa satu file untuk semua klip, bukan satu file per klip: user membukanya sekali,
lalu menyalin blok per klip sambil mengunggah. Satu file = satu kali buka.

SUMBER DATA (urutan menang):
1. File kurasi Stage 1 (`<video_id>.json` di folder output) — SATU-SATUNYA tempat
   `deskripsi` dan `tags` hidup. Manifest Stage 2 tidak menyimpan keduanya.
2. `manifest.json` Stage 2 — untuk judul (`headline` hasil edit user > `title`) dan
   daftar klip yang benar-benar diunduh.

Jadi kalau file kurasi hilang, caption tetap ditulis tapi tanpa deskripsi/hashtag,
bukan gagal. Fungsi di modul ini MURNI (tanpa Qt/ffmpeg) supaya bisa diuji langsung.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

CAPTION_FILENAME = "caption.txt"

# Hashtag umum yang selalu ditambahkan di belakang tag dari Gemini (yang cuma 3).
# Sengaja sedikit dan generik; hashtag spesifik topik datang dari kurasi.
EXTRA_HASHTAGS: tuple[str, ...] = ("#fyp", "#shorts", "#viral")

SEPARATOR = "-" * 60


def normalize_hashtag(raw: str) -> str:
    """'Tablet Gaming' -> '#TabletGaming'. Kembalikan '' kalau tidak ada isinya.

    Tag dari Gemini kadang sudah ber-'#', kadang belum, kadang berspasi. Spasi di
    tengah hashtag memecahnya jadi dua tag di TikTok, jadi dibuang, bukan diganti '_'.
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    text = text.lstrip("#").strip()
    # Buang apa pun yang bukan huruf/angka/underscore (emoji, tanda baca, spasi).
    text = re.sub(r"[^0-9A-Za-z_\u00C0-\u024F]+", "", text)
    if not text:
        return ""
    return "#" + text


def merge_hashtags(tags: list[Any] | None, extra: tuple[str, ...] = EXTRA_HASHTAGS) -> list[str]:
    """Gabung tag kurasi + tag umum, buang duplikat (tidak peka huruf besar/kecil)."""
    hasil: list[str] = []
    seen: set[str] = set()
    for raw in list(tags or []) + list(extra):
        tag = normalize_hashtag(raw)
        if not tag:
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        hasil.append(tag)
    return hasil


def load_curation_map(folder: Path) -> dict[int, dict[str, Any]]:
    """{id_klip: entri kurasi} dari file kurasi Stage 1 di `folder`.

    Aturan penolakan nama file DISAMAKAN dengan `gui_review.is_curation_file` dan
    `stage5_final.creator_watermark_from_curation`: apa pun yang mengandung
    'manifest' bukan file kurasi. Melonggarkan ini pernah membuat data video yang
    SALAH terbaca (lihat catatan di gui_review.py).
    """
    folder = Path(folder)
    if not folder.is_dir():
        return {}
    for path in sorted(folder.glob("*.json")):
        nama = path.name.lower()
        if "manifest" in nama or nama.endswith((".subtitle.json", ".design.v3.json")):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(data, dict) or not isinstance(data.get("daftar_klip"), list):
            continue
        hasil: dict[int, dict[str, Any]] = {}
        for clip in data["daftar_klip"]:
            if not isinstance(clip, dict):
                continue
            try:
                cid = int(clip.get("id_klip"))
            except (TypeError, ValueError):
                continue
            hasil[cid] = clip
        return hasil
    return {}


def collect_entries(
    manifest: dict[str, Any],
    curation: dict[int, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Daftar {no, judul, deskripsi, hashtags} untuk klip yang MASUK folder hasil.

    Klip berstatus 'failed' dilewati: tidak ada videonya, jadi captionnya cuma
    membingungkan saat menyalin.
    """
    curation = curation or {}
    entries: list[dict[str, Any]] = []
    clips = manifest.get("clips") or manifest.get("daftar_klip") or []
    if not isinstance(clips, list):
        return entries

    for idx, clip in enumerate(clips, 1):
        if not isinstance(clip, dict):
            continue
        status = str(clip.get("status") or "").lower()
        if status and status not in {"success", "skipped", "complete", "completed"}:
            continue
        try:
            no = int(clip.get("clip_id") or clip.get("id_klip") or idx)
        except (TypeError, ValueError):
            no = idx

        kur = curation.get(no, {})
        # Judul: headline hasil edit user MENANG (itu yang tampil di video), lalu
        # judul dari Gemini. Hook TIDAK dipakai sebagai judul — panjangnya bisa
        # >130 karakter kutipan transkrip mentah.
        judul = (
            str(clip.get("headline") or "").strip()
            or str(kur.get("headline") or "").strip()
            or str(clip.get("title") or "").strip()
            or str(kur.get("judul_relevan") or "").strip()
        )
        deskripsi = (
            str(kur.get("deskripsi") or "").strip()
            or str(clip.get("hook") or kur.get("hook") or "").strip()
        )
        entries.append({
            "no": no,
            "judul": judul,
            "deskripsi": deskripsi,
            "hashtags": merge_hashtags(kur.get("tags")),
            "file": str(clip.get("output_file") or "").strip(),
        })
    return entries


def build_caption_text(
    entries: list[dict[str, Any]],
    *,
    video_title: str = "",
    creator: str = "",
    source_url: str = "",
) -> str:
    """Susun isi caption.txt. Blok per klip dipisah garis supaya mudah diseleksi."""
    lines: list[str] = []
    kepala = "CAPTION — siap copy-paste"
    lines.append(kepala)
    if video_title:
        lines.append(f"Video : {video_title}")
    if creator:
        lines.append(f"Kreator: {creator}")
    if source_url:
        lines.append(f"Sumber : {source_url}")
    lines.append(f"Jumlah klip: {len(entries)}")
    lines.append("")

    for entry in entries:
        lines.append(SEPARATOR)
        lines.append(f"KLIP {entry['no']}")
        if entry.get("file"):
            lines.append(f"({entry['file']})")
        lines.append(SEPARATOR)
        lines.append("")
        if entry.get("judul"):
            lines.append(str(entry["judul"]))
            lines.append("")
        if entry.get("deskripsi"):
            lines.append(str(entry["deskripsi"]))
            lines.append("")
        if entry.get("hashtags"):
            lines.append(" ".join(entry["hashtags"]))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_caption_file(
    output_dir: Path,
    manifest: dict[str, Any],
    *,
    curation_folder: Path | None = None,
    creator: str = "",
    video_title: str = "",
    filename: str = CAPTION_FILENAME,
) -> Path | None:
    """Tulis caption.txt di `output_dir`. Kembalikan path-nya, atau None kalau kosong.

    Ditulis sebagai BYTES dengan newline '\\n' saja: `write_text` di Windows
    menghasilkan CRLF, dan file ini juga dibaca ulang oleh tes yang menghitung baris.
    """
    entries = collect_entries(manifest, load_curation_map(curation_folder) if curation_folder else {})
    if not entries:
        return None

    text = build_caption_text(
        entries,
        video_title=video_title or str(manifest.get("video_title") or ""),
        creator=creator or str(manifest.get("creator") or ""),
        source_url=str(manifest.get("source_url") or ""),
    )
    path = Path(output_dir) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path
