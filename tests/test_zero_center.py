"""Tes untuk pemusatan (zero-center) dan geseran X video — dua hal yang dipakai
slider Customize dan HARUS cocok dengan renderer.

Kenapa tes ini ada: seluruh suite lama tidak menyentuh `stage5_preset` maupun
`text_engine` sama sekali, jadi tidak ada jaring pengaman untuk kelas bug
"preview tidak sama dengan render". Yang diuji di sini adalah aritmetikanya —
murni, cepat, tanpa ffmpeg.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stages"))

import stage5_preset as SP  # noqa: E402
import text_engine as TE  # noqa: E402


def base_preset(**video):
    p = SP.load_preset(None)
    p["video"].update(video)
    return p


class TestVideoGeometryX:
    def test_x_nol_berarti_center(self):
        g = SP.video_geometry(base_preset(scale=0.5, x=0))
        assert g["x"] == (1080 - g["w"]) // 2

    def test_x_positif_menggeser_ke_kanan(self):
        c = SP.video_geometry(base_preset(scale=0.5, x=0))
        r = SP.video_geometry(base_preset(scale=0.5, x=120))
        assert r["x"] - c["x"] == 120

    def test_x_negatif_menggeser_ke_kiri(self):
        c = SP.video_geometry(base_preset(scale=0.5, x=0))
        l = SP.video_geometry(base_preset(scale=0.5, x=-90))
        assert l["x"] - c["x"] == -90

    def test_preset_tanpa_x_tetap_center(self):
        """Preset LAMA tidak punya `video.x`. Ia harus tetap center, bukan meledak."""
        p = SP.load_preset(None)
        p["video"].pop("x", None)
        g = SP.video_geometry(p)
        assert g["x"] == (1080 - g["w"]) // 2

    def test_x_ikut_diskalakan_saat_rasio_kanvas_berubah(self):
        p = base_preset(scale=0.5, x=200)
        out = SP.scale_preset_canvas(p, 540, 960)
        # kanvas menyusut setengah -> geseran ikut setengah, kalau tidak video
        # melompat keluar frame saat user mengganti rasio
        assert out["video"]["x"] == 100


class TestMeasureInk:
    """`measure_ink()` adalah sumber angka pemusatan untuk slider zero-center."""

    def _ink(self, text="HALO DUNIA", size=80, y=500, x_off=0, stroke=0, align="center"):
        lines = [text]
        return TE.measure_ink(
            lines=lines, font_name="title.ttf", size=size,
            canvas_w=1080, canvas_h=1920, align=align, line_gap=-0.25,
            stroke_w=stroke, margin=int(round(1080 * TE.ZONE_MARGIN_RATIO)),
            x_off=x_off, y=y,
        )

    def test_mengembalikan_kotak_masuk_akal(self):
        ink = self._ink()
        assert ink and ink["w"] > 0 and ink["h"] > 0
        assert 0 <= ink["x"] < 1080 and 0 <= ink["y"] < 1920

    def test_teks_kosong_mengembalikan_dict_kosong(self):
        ink = TE.measure_ink(
            lines=[""], font_name="title.ttf", size=80, canvas_w=1080, canvas_h=1920,
            align="center", line_gap=-0.25, stroke_w=0, margin=75, x_off=0, y=500,
        )
        assert ink == {}

    def test_dy_top_tidak_bergantung_pada_y(self):
        """`dy_top` hanya soal metrik font, jadi harus sama di berbagai `y`.

        Ini yang membuat pemusatan bisa dihitung SEKALI jalan, tanpa umpan balik.
        """
        a = self._ink(y=200)["dy_top"]
        b = self._ink(y=1500)["dy_top"]
        assert a == b

    def test_rumus_pemusatan_vertikal_benar(self):
        """y = (H - h)/2 - dy_top harus menghasilkan pusat tinta di tengah kanvas."""
        first = self._ink(y=500)
        y_center = (1920 - first["h"]) // 2 - first["dy_top"]
        again = self._ink(y=y_center)
        assert abs(again["cy"] - 1920 // 2) <= 2

    def test_rumus_pemusatan_horizontal_benar(self):
        first = self._ink(x_off=0)
        again = self._ink(x_off=-first["dcx"])
        assert abs(again["cx"] - 1080 // 2) <= 2

    def test_align_center_hampir_pas_tengah_tanpa_koreksi(self):
        ink = self._ink(align="center", x_off=0)
        assert abs(ink["dcx"]) <= 3          # sisa pembulatan glyph saja

    def test_align_left_menempel_margin_kiri(self):
        margin = int(round(1080 * TE.ZONE_MARGIN_RATIO))
        ink = self._ink(align="left", x_off=0)
        assert abs(ink["x"] - margin) <= 3

    def test_stroke_melebarkan_kotak_tinta(self):
        tipis = self._ink(stroke=0)
        tebal = self._ink(stroke=10)
        assert tebal["w"] > tipis["w"] and tebal["h"] > tipis["h"]


class TestInkTanpaShadow:
    """Kotak tinta TIDAK boleh terpengaruh shadow.

    Kalau shadow ikut terhitung, memusatkan teks akan menggesernya sebesar offset
    shadow — kelas bug "preview tidak sama dengan render" yang sudah tiga kali kambuh.
    """

    def _render_ink(self, **extra):
        blk = {
            "text": "HALO", "font": "title.ttf", "size": 90, "x": 45, "y": 600,
            "align": "center", "max_lines": 1, "outline": 4, "color": "#FFFFFF",
        }
        blk.update(extra)
        ink: dict = {}
        TE.render_block(blk, canvas_w=1080, canvas_h=1920, text=blk["text"], ink_out=ink)
        return ink

    def test_shadow_besar_tidak_mengubah_kotak_tinta(self):
        tanpa = self._render_ink(shadow_enabled=False)
        dengan = self._render_ink(
            shadow_enabled=True, shadow_x=30, shadow_y=30, shadow_blur=8
        )
        assert tanpa["x"] == dengan["x"] and tanpa["y"] == dengan["y"]
        assert tanpa["w"] == dengan["w"] and tanpa["h"] == dengan["h"]

    def test_render_block_mengisi_ink_out(self):
        ink = self._render_ink()
        for k in ("x", "y", "w", "h", "cx", "cy", "dy_top", "dcx"):
            assert k in ink


class TestLayerSignature:
    def test_versi_ikut_menentukan_hash(self):
        """Naiknya `_SIG_VERSION` WAJIB mengubah hash.

        Tanpa itu cache PNG lama (tanpa metadata `ink`) terus dipakai dan fitur
        pemusatan diam-diam memakai angka kosong.
        """
        a = TE.layer_signature(1080, 1920, "head", "{}")
        old = TE._SIG_VERSION
        try:
            TE._SIG_VERSION = old + 1
            b = TE.layer_signature(1080, 1920, "head", "{}")
        finally:
            TE._SIG_VERSION = old
        assert a != b


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
