"""Tes Intro Cover (bug.txt item 12).

Yang dijaga di sini:
  1. Lapisan cover selalu OPAK dan seukuran kanvas — cover yang tembus pandang tidak
     berguna sebagai thumbnail feed TikTok/Shorts.
  2. Cover TIDAK dibuat kalau tidak ada yang bisa digambar (tanpa gambar, tanpa teks),
     supaya render tidak menambah input ffmpeg sia-sia.
  3. Gambar latar dipasang dengan COVER + center-crop, bukan stretch: gambar sampul user
     tidak boleh gepeng saat rasionya beda dari kanvas.
  4. Teks dipusatkan di kanvas, bukan mengikuti x/y layout video.
  5. Blok `intro` ada di DEFAULT_PRESET dan preset lama tanpa blok itu tetap terbaca
     (fitur mati, bukan error).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "stages")):
    if p not in sys.path:
        sys.path.insert(0, p)

from stages.stage5_final import build_intro_cover  # noqa: E402
from stages.stage5_preset import DEFAULT_PRESET, load_preset  # noqa: E402

CW, CH = 1080, 1920
BG_RGB = (7, 12, 22)  # latar default cover saat tidak ada gambar impor


def intro(**over) -> dict:
    base = {
        "enabled": True,
        "duration": 0.4,
        "fade": 0.15,
        "background": "",
        "show_headline": True,
        "show_creator": True,
    }
    base.update(over)
    return base


def build(tmp_path: Path, cfg: dict, *, head="HEADLINE UJI", creator="NAMA CREATOR"):
    return build_intro_cover(
        cfg,
        canvas_w=CW, canvas_h=CH,
        headline_block=DEFAULT_PRESET["headline"],
        watermark_block=DEFAULT_PRESET["watermark"],
        headline_text=head, creator_text=creator,
        out_path=tmp_path / "cover.png",
    )


class TestPresetIntegration:
    def test_intro_block_exists_in_default_preset(self) -> None:
        assert "intro" in DEFAULT_PRESET
        blk = DEFAULT_PRESET["intro"]
        # Wajib mati secara default: fitur baru tidak boleh mengubah hasil render
        # theme lama tanpa diminta.
        assert blk["enabled"] is False
        # Rentang yang diminta user: 0.3-0.5s.
        assert 0.3 <= float(blk["duration"]) <= 0.5

    def test_old_preset_without_intro_still_loads(self, tmp_path: Path) -> None:
        """Preset lama (tanpa blok intro) harus tetap terbaca, fitur sekadar mati."""
        p = tmp_path / "old_preset.json"
        p.write_text(json.dumps({
            "canvas": {"w": 1080, "h": 1920},
            "video": {"scale": 1.0},
        }), encoding="utf-8")
        preset = load_preset(p)
        assert preset["intro"]["enabled"] is False
        assert preset["video"]["scale"] == 1.0

    def test_fade_never_exceeds_duration_in_preset_default(self) -> None:
        blk = DEFAULT_PRESET["intro"]
        assert float(blk["fade"]) <= float(blk["duration"])


class TestCoverLayer:
    def test_cover_is_canvas_sized_and_fully_opaque(self, tmp_path: Path) -> None:
        out = build(tmp_path, intro())
        assert out is not None
        im = Image.open(out)
        assert im.size == (CW, CH)
        assert im.mode == "RGBA"
        # Satu-satunya nilai alpha yang boleh ada adalah 255. Cover semi-transparan
        # akan memperlihatkan video di baliknya dan gagal sebagai thumbnail.
        alphas = set(im.getchannel("A").getdata())
        assert alphas == {255}, f"cover harus opak, alpha ditemukan: {sorted(alphas)[:8]}"

    def test_returns_none_when_nothing_to_draw(self, tmp_path: Path) -> None:
        """Tanpa gambar DAN tanpa teks, tidak ada cover yang perlu dibuat."""
        out = build_intro_cover(
            intro(show_headline=False, show_creator=False),
            canvas_w=CW, canvas_h=CH,
            headline_block=DEFAULT_PRESET["headline"],
            watermark_block=DEFAULT_PRESET["watermark"],
            headline_text="", creator_text="",
            out_path=tmp_path / "cover.png",
        )
        assert out is None
        assert not (tmp_path / "cover.png").exists()

    def test_empty_text_is_not_drawn_even_if_toggled_on(self, tmp_path: Path) -> None:
        """Sakelar ON tapi teksnya kosong -> tetap tidak ada yang digambar."""
        out = build_intro_cover(
            intro(),  # kedua sakelar ON
            canvas_w=CW, canvas_h=CH,
            headline_block=DEFAULT_PRESET["headline"],
            watermark_block=DEFAULT_PRESET["watermark"],
            headline_text="   ", creator_text="",
            out_path=tmp_path / "cover.png",
        )
        assert out is None

    def test_text_is_actually_drawn(self, tmp_path: Path) -> None:
        """Ada piksel yang berbeda dari warna latar = teks benar-benar tergambar."""
        out = build(tmp_path, intro())
        im = Image.open(out).convert("RGB")
        different = sum(
            1
            for y in range(0, CH, 8)
            for x in range(0, CW, 8)
            if max(abs(a - b) for a, b in zip(im.getpixel((x, y)), BG_RGB)) > 12
        )
        assert different > 50, f"teks tidak terlihat di cover (hanya {different} piksel beda)"

    def test_text_is_vertically_centered(self, tmp_path: Path) -> None:
        """Teks harus mengelompok di sekitar tengah kanvas, bukan di posisi layout video.

        Blok headline default punya y=55 (dekat atas). Kalau pemusatan tidak bekerja,
        teks akan muncul di sepertiga atas dan tes ini gagal.
        """
        out = build(tmp_path, intro())
        im = Image.open(out).convert("RGB")
        rows = [
            y
            for y in range(0, CH, 4)
            if any(
                max(abs(a - b) for a, b in zip(im.getpixel((x, y)), BG_RGB)) > 12
                for x in range(0, CW, 8)
            )
        ]
        assert rows, "tidak ada teks yang terdeteksi"
        mid = (rows[0] + rows[-1]) / 2
        # Toleransi 12% tinggi kanvas: headline & creator digeser ±6% dari tengah,
        # jadi titik tengah gabungannya tetap dekat pusat.
        assert abs(mid - CH / 2) < CH * 0.12, (
            f"teks tidak terpusat: rentang {rows[0]}..{rows[-1]}, tengah {mid} vs {CH/2}"
        )

    def test_headline_and_creator_are_separated(self, tmp_path: Path) -> None:
        """Saat keduanya tampil: headline digeser ke ATAS, creator ke BAWAH.

        Kalau hanya satu yang tampil, ia dipusatkan tepat di tengah (tanpa geseran).
        Jadi buktinya adalah: dengan keduanya tampil, tinta merambat LEBIH TINGGI dari
        posisi headline-sendiri dan LEBIH RENDAH dari posisi creator-sendiri.
        Tanpa geseran, kedua teks akan bertumpuk di titik yang sama.
        """
        def rows_of(head: str, creator: str, tag: str) -> tuple[int, int]:
            out = build_intro_cover(
                intro(show_headline=bool(head.strip()), show_creator=bool(creator.strip())),
                canvas_w=CW, canvas_h=CH,
                headline_block=DEFAULT_PRESET["headline"],
                watermark_block=DEFAULT_PRESET["watermark"],
                headline_text=head, creator_text=creator,
                out_path=tmp_path / f"cover_{tag}.png",
            )
            assert out is not None
            im = Image.open(out).convert("RGB")
            rs = [
                y
                for y in range(0, CH, 4)
                if any(
                    max(abs(a - b) for a, b in zip(im.getpixel((x, y)), BG_RGB)) > 12
                    for x in range(0, CW, 8)
                )
            ]
            assert rs, f"tidak ada tinta pada varian {tag}"
            return rs[0], rs[-1]

        head_only_top, _ = rows_of("HEADLINE", "", "head")
        _, wm_only_bottom = rows_of("", "CREATOR", "wm")
        both_top, both_bottom = rows_of("HEADLINE", "CREATOR", "both")

        assert both_top < head_only_top, (
            "headline tidak digeser ke atas saat creator juga tampil "
            f"(both_top={both_top}, head_only_top={head_only_top})"
        )
        assert both_bottom > wm_only_bottom, (
            "nama creator tidak digeser ke bawah saat headline juga tampil "
            f"(both_bottom={both_bottom}, wm_only_bottom={wm_only_bottom})"
        )


class TestBackgroundImage:
    def _bg(self, tmp_path: Path, w: int, h: int, color=(200, 30, 40)) -> Path:
        # Gambar disimpan di dalam ROOT karena `background` di preset adalah path
        # RELATIF terhadap root proyek (sama seperti stiker overlay).
        d = ROOT / "temp" / "_test_intro_bg"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"bg_{w}x{h}.png"
        Image.new("RGB", (w, h), color).save(p)
        return p

    def test_background_image_is_used(self, tmp_path: Path) -> None:
        bg = self._bg(tmp_path, 1080, 1920, (200, 30, 40))
        rel = bg.relative_to(ROOT).as_posix()
        out = build(tmp_path, intro(background=rel, show_headline=False, show_creator=False))
        assert out is not None
        im = Image.open(out).convert("RGB")
        # Sudut kanvas harus memakai warna gambar, bukan latar gelap default.
        assert im.getpixel((5, 5)) != BG_RGB
        r, g, b = im.getpixel((5, 5))
        assert r > 150 and g < 90, f"warna gambar latar tidak terpakai: {(r, g, b)}"

    def test_wide_background_is_cropped_not_stretched(self, tmp_path: Path) -> None:
        """Gambar 16:9 di kanvas 9:16 harus di-crop tengah, bukan dipipihkan.

        Buktinya: garis vertikal di tengah gambar sumber tetap berada di tengah hasil
        dan lebarnya tidak melebar. Kalau di-stretch, garis itu jadi jauh lebih lebar.
        """
        d = ROOT / "temp" / "_test_intro_bg"
        d.mkdir(parents=True, exist_ok=True)
        src = d / "wide_stripe.png"
        w, h = 1920, 1080
        img = Image.new("RGB", (w, h), (10, 10, 10))
        stripe_w = 96                      # 5% dari lebar sumber
        for x in range((w - stripe_w) // 2, (w + stripe_w) // 2):
            for y in range(h):
                img.putpixel((x, y), (250, 250, 250))
        img.save(src)

        rel = src.relative_to(ROOT).as_posix()
        out = build(tmp_path, intro(background=rel, show_headline=False, show_creator=False))
        im = Image.open(out).convert("RGB")

        mid_y = CH // 2
        bright = [x for x in range(CW) if im.getpixel((x, mid_y))[0] > 200]
        assert bright, "garis penanda hilang dari hasil"
        # Skala cover = CH/h = 1.777..., jadi garis 96px menjadi ~171px.
        # Stretch penuh (CW/w = 0.5625) akan membuatnya ~54px — jauh lebih kecil.
        expected = stripe_w * (CH / h)
        actual = bright[-1] - bright[0] + 1
        assert abs(actual - expected) < expected * 0.2, (
            f"lebar garis {actual}px, diharapkan ~{expected:.0f}px (cover-crop, bukan stretch)"
        )
        # Garis tetap terpusat.
        center = (bright[0] + bright[-1]) / 2
        assert abs(center - CW / 2) < 12

    def test_missing_background_falls_back_to_dark(self, tmp_path: Path) -> None:
        """Path gambar yang tidak ada tidak boleh membuat render gagal."""
        out = build(tmp_path, intro(background="assets/overlays/__tidak_ada__.png"))
        assert out is not None
        im = Image.open(out).convert("RGB")
        assert im.getpixel((5, 5)) == BG_RGB
