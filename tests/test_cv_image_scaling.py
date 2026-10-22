"""Bilder im Lebenslauf werden auf die Druckgröße reduziert.

Hintergrund: Das Profil-Foto hatte 700 × 934 px und wurde mit 25 mm Breite
gedruckt — rund 711 dpi. Auf dem Papier ist davon nichts zu sehen, das PDF wuchs
dadurch aber auf 1,75 MB (das Foto allein: 1,0 MB PNG, per Flate gepackt). Ein
Lebenslauf mit 20 Stellen im Anhang ist damit schnell zu groß für Portale mit
1-MB-Grenze.

Die Bilder werden deshalb vor dem Einbetten auf ``EMBED_DPI`` (300 dpi)
heruntergerechnet: Fotos als JPEG, Unterschriften als PNG (Transparenz).
"""

from __future__ import annotations

import io

import pytest
from PIL import Image as PILImage

from bewerbungsagent import documents as D


def _write_image(path, size, mode="RGB", color=(90, 120, 160)):
    img = PILImage.new(mode, size, color)
    img.save(path)
    return path


class TestImageForPdf:
    def test_grosses_bild_wird_verkleinert(self, tmp_path):
        src = _write_image(tmp_path / "foto.png", (700, 934))
        out = D._image_for_pdf(src, 25.0, jpeg=True)

        assert hasattr(out, "getbuffer"), "erwartet BytesIO für das verkleinerte Bild"
        with PILImage.open(io.BytesIO(out.getvalue())) as im:
            # 25 mm bei 300 dpi = 295 px Breite
            assert im.width == 295
            assert im.height == 394
            assert im.format == "JPEG"

    def test_seitenverhaeltnis_bleibt(self, tmp_path):
        src = _write_image(tmp_path / "foto.png", (800, 400))
        out = D._image_for_pdf(src, 25.0, jpeg=True)
        with PILImage.open(io.BytesIO(out.getvalue())) as im:
            assert im.width == 295
            assert im.height == 148  # 400/800 * 295, gerundet

    def test_kleines_bild_bleibt_pfad(self, tmp_path):
        """Kein Aufblasen: ein 200-px-Bild bleibt unverändert."""
        src = _write_image(tmp_path / "klein.png", (200, 260))
        out = D._image_for_pdf(src, 25.0, jpeg=True)
        assert out == str(src)

    def test_deutlich_kleiner_als_die_quelle(self, tmp_path):
        src = _write_image(tmp_path / "foto.png", (700, 934))
        before = src.stat().st_size
        out = D._image_for_pdf(src, 25.0, jpeg=True)
        assert len(out.getbuffer()) < before

    def test_unterschrift_behaelt_transparenz(self, tmp_path):
        """PNG mit Alpha darf nicht zu JPEG werden — sonst schwarzer Kasten."""
        src = tmp_path / "unterschrift.png"
        PILImage.new("RGBA", (900, 300), (0, 0, 0, 0)).save(src)

        out = D._image_for_pdf(src, 38.0, jpeg=False)

        assert hasattr(out, "getbuffer")
        with PILImage.open(io.BytesIO(out.getvalue())) as im:
            assert im.format == "PNG"
            assert im.mode in ("RGBA", "LA", "P")

    def test_dpi_ist_konfigurierbar(self, tmp_path):
        src = _write_image(tmp_path / "foto.png", (900, 900))
        out = D._image_for_pdf(src, 25.0, dpi=150, jpeg=True)
        with PILImage.open(io.BytesIO(out.getvalue())) as im:
            assert im.width == 148  # 25 mm bei 150 dpi


class TestPhotoImageFlowable:
    def test_foto_wird_mit_richtiger_groesse_eingebettet(self, tmp_path, demo_profile, monkeypatch):
        src = _write_image(tmp_path / "foto.png", (700, 934))
        monkeypatch.setattr(D, "_asset_path", lambda profile, key: src)

        flowable = D._photo_image(demo_profile, width_mm=25.0)

        assert flowable is not None
        # 25 mm Breite, Höhe aus dem Seitenverhältnis (934/700).
        assert round(flowable.drawWidth / D.mm, 1) == 25.0
        assert round(flowable.drawHeight / D.mm, 1) == 33.4

    def test_ohne_foto_none(self, demo_profile, monkeypatch):
        monkeypatch.setattr(D, "_asset_path", lambda profile, key: None)
        assert D._photo_image(demo_profile) is None

    def test_signatur_ist_linksbuendig(self, tmp_path, demo_profile, monkeypatch):
        src = _write_image(tmp_path / "sig.png", (359, 135), mode="RGBA",
                           color=(0, 0, 0, 0))
        monkeypatch.setattr(D, "_asset_path", lambda profile, key: src)
        flowable = D._signature_image(demo_profile, width_mm=38.0)
        assert flowable is not None
        assert flowable.hAlign == "LEFT"


class TestGeneratedCvSize:
    """Ende-zu-Ende: der erzeugte Lebenslauf bleibt deutlich unter 1 MB."""

    @pytest.mark.parametrize("template", ["classic", "sidebar"])
    def test_cv_bleibt_klein(self, tmp_path, demo_profile, monkeypatch, template):
        from bewerbungsagent import documents
        foto = _write_image(tmp_path / "foto.png", (700, 934))
        monkeypatch.setattr(D, "_asset_path",
                            lambda profile, key: foto if key == "foto" else None)

        job = {"titel": "Testingenieur (m/w/d)", "firma": "Acme GmbH",
               "ort": "München", "beschreibung": "HiL, Python, CAN"}
        out = tmp_path / f"cv_{template}.pdf"
        documents.generate_lebenslauf(demo_profile, job, {"matched_skills": []},
                                      out, {"documents": {"accent_color": "#0B3D5C"}},
                                      lang="de", template=template)

        assert out.is_file() and out.stat().st_size > 0
        assert out.stat().st_size < 300 * 1024, "Lebenslauf sollte deutlich unter 1 MB bleiben"
