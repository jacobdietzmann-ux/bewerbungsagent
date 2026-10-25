"""Tests für die Qualitätsprüfung der Unterlagen (``quality.py``, P0b)."""

from __future__ import annotations

from pathlib import Path

import pytest

from bewerbungsagent.dashboard import _quality_summary
from bewerbungsagent.profile import Profile
from bewerbungsagent.quality import (
    check_application,
    check_letter,
    check_pdf,
    pdf_page_count,
)

JOB = {
    "firma": "Beispiel GmbH",
    "titel": "Testingenieur HiL (m/w/d)",
    "beschreibung": "Test von Steuergeräten, CAN, HiL-Prüfstände, Verifikation.",
    "matched_skills": ["can", "hil"],
    "gehalt": "62–78 T€",
    "gehalt_quelle": "Anzeige",
}

CLAIM_OK = ("Verantwortung für die Testkoordination zur Absicherung der "
            "Hardware- und Software-Integration, inklusive Analyse von CAN-Traces und DTCs.")


def _letter(*, claims=(CLAIM_OK,), period="01/2024 – 09/2026", employer="Autobauer AG",
            transparency=False, opening="Sehr geehrte Damen und Herren,",
            closing="Mit freundlichen Grüßen") -> str:
    lines = [
        "Max Mustermann", "Beispielstraße 1, 12345 Musterstadt",
        "Beispiel GmbH", "Garching", "10/2026",
        f"Bewerbung als {JOB['titel']}",
        opening,
        "Ihre Anforderungen decke ich wie folgt ab:",
    ]
    for claim in claims:
        lines.append(f"•  Fachliche Kompetenz: {claim}")
    lines.append(f"Station Testkoordinator · {period}")
    if employer:
        lines.append(f"Mein Projekt bei {employer} ist abgeschlossen.")
    if transparency:
        lines.append("Transparenz zu Anforderungen außerhalb meines Profils:")
        lines.append("•  Keine Erfahrung mit DO-178C")
    lines.append(closing)
    return "\n".join(lines)


def _findings(findings, pruefung):
    return [f for f in findings if f["pruefung"] == pruefung]


class TestCheckLetter:
    def test_sauberes_anschreiben_ohne_fehler(self, demo_profile):
        findings = check_letter(demo_profile, JOB, JOB, {"documents": {}}, "de", _letter())
        assert not [f for f in findings if f["schwere"] == "fehler"], findings

    def test_erfundene_behauptung_wird_erkannt(self, demo_profile):
        fake = "Entwicklung einer AUTOSAR-Basissoftware in C++ für Steuergeräte."
        findings = check_letter(demo_profile, JOB, JOB, {"documents": {}}, "de",
                                _letter(claims=(fake,)))
        fehler = _findings(findings, "Behauptung")
        assert fehler and "AUTOSAR" in fehler[0]["detail"]

    def test_belegte_behauptung_ist_kein_befund(self, demo_profile):
        findings = check_letter(demo_profile, JOB, JOB, {"documents": {}}, "de", _letter())
        assert not _findings(findings, "Behauptung")

    def test_falscher_zeitraum_wird_erkannt(self, demo_profile):
        findings = check_letter(demo_profile, JOB, JOB, {"documents": {}}, "de",
                                _letter(period="05/2019 – 07/2020"))
        fehler = _findings(findings, "Zeitraum")
        assert fehler and "05/2019" in fehler[0]["detail"]

    def test_richtiger_zeitraum_ist_kein_befund(self, demo_profile):
        findings = check_letter(demo_profile, JOB, JOB, {"documents": {}}, "de",
                                _letter(period="01/2024 – 09/2026"))
        assert not _findings(findings, "Zeitraum")

    def test_fehlende_anrede_und_grußformel(self, demo_profile):
        findings = check_letter(demo_profile, JOB, JOB, {"documents": {}}, "de",
                                _letter(opening="Hallo,", closing="Bis bald"))
        details = " ".join(f["detail"] for f in _findings(findings, "Pflichtteile"))
        assert "Anrede" in details and "Grußformel" in details

    def test_arbeitgeber_ausserhalb_des_profils(self, demo_profile):
        findings = check_letter(demo_profile, JOB, JOB, {"documents": {}}, "de",
                                _letter(employer="Airbus Defence"))
        fehler = _findings(findings, "Arbeitgeber")
        assert fehler and "Airbus" in fehler[0]["detail"]

    def test_arbeitgeber_im_profil_ist_ok(self, demo_profile):
        findings = check_letter(demo_profile, JOB, JOB, {"documents": {}}, "de",
                                _letter(employer="Autobauer AG"))
        assert not _findings(findings, "Arbeitgeber")

    def test_luecke_ohne_transparenz_ist_warnung(self):
        profile = Profile({
            "personal": {"name": "Test"},
            "work_experience": [{
                "period": "01/2024 – 09/2026",
                "role_de": "Testkoordinator", "role_en": "Test Coordinator",
                "bullets_de": [CLAIM_OK], "bullets_en": [CLAIM_OK],
                "tags": ["CAN"],
            }],
            "skills": {"technik": ["CAN"]},
            "gap_terms": ["DO-178C"],
        })
        job = {**JOB, "beschreibung": "Erfahrung mit DO-178C erforderlich."}
        findings = check_letter(profile, job, job, {"documents": {}}, "de", _letter())
        warnungen = _findings(findings, "Lücken")
        assert warnungen and warnungen[0]["schwere"] == "warnung"

        mit = check_letter(profile, job, job, {"documents": {}}, "de",
                           _letter(transparency=True))
        assert not _findings(mit, "Lücken")

    def test_anforderungen_ohne_treffer_ist_hinweis(self, demo_profile):
        text = _letter().replace("CAN", "Bus").replace("HiL", "Prüfplatz")
        findings = check_letter(demo_profile, JOB, JOB, {"documents": {}}, "de", text)
        treffer = _findings(findings, "Anforderungen")
        assert treffer and treffer[0]["schwere"] == "hinweis"

    def test_arbeitgeber_in_profil_bullets_ist_ok(self):
        """Realdaten: FERCHAU nennt im Bullet „bei AIRBUS“ — das ist belegt."""
        profile = Profile({
            "personal": {"name": "Test"},
            "work_experience": [{
                "period": "01/2024 – 09/2026",
                "role_de": "Testkoordinator", "role_en": "Test Coordinator",
                "bullets_de": ["Schnittstellenmanagement bei AIRBUS im Projekt X."],
                "bullets_en": ["Interface management at AIRBUS."],
                "tags": ["CAN"],
            }],
            "skills": {"technik": ["CAN"]},
        })
        findings = check_letter(profile, JOB, JOB, {"documents": {}}, "de",
                                _letter(employer="AIRBUS"))
        assert not _findings(findings, "Arbeitgeber")


class TestCheckPdf:
    def _make_pdf(self, path: Path, pages: int = 1) -> Path:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate

        doc = SimpleDocTemplate(str(path), pagesize=A4)
        style = getSampleStyleSheet()["BodyText"]
        story = [Paragraph("Seite", style)]
        for _ in range(pages - 1):
            story.extend([PageBreak(), Paragraph("Seite", style)])
        doc.build(story)
        return path

    def test_gueltiges_pdf(self, tmp_path):
        pdf = self._make_pdf(tmp_path / "ok.pdf")
        assert check_pdf(pdf) == []
        assert pdf_page_count(pdf.read_bytes()) == 1

    def test_fehlende_datei(self, tmp_path):
        findings = check_pdf(tmp_path / "fehlt.pdf")
        assert findings and findings[0]["pruefung"] == "PDF vorhanden"

    def test_keine_pdf_datei(self, tmp_path):
        fake = tmp_path / "fake.pdf"
        fake.write_text("kein pdf", encoding="utf-8")
        findings = check_pdf(fake)
        assert findings and findings[0]["pruefung"] == "PDF lesbar"

    def test_zu_viele_seiten_ist_warnung(self, tmp_path):
        pdf = self._make_pdf(tmp_path / "lang.pdf", pages=2)
        findings = check_pdf(pdf, max_pages=1)
        assert findings and findings[0]["pruefung"] == "PDF Seitenzahl"
        assert findings[0]["schwere"] == "warnung"


class TestCheckApplication:
    def test_fehler_setzt_ok_auf_false(self, demo_profile, tmp_path):
        pdf = tmp_path / "a.pdf"
        pdf.write_bytes(b"%PDF-1.4 kaputt")
        res = check_application(demo_profile, JOB, JOB, {"documents": {}},
                                texte={"anschreiben_de": _letter(opening="Hallo,")},
                                pdfs={"anschreiben_de": pdf})
        assert res["ok"] is False
        assert any(f["pruefung"] == "Pflichtteile" for f in res["befunde"])

    def test_nur_hinweise_bleibt_ok(self, demo_profile, tmp_path):
        pdf = tmp_path / "a.pdf"
        pdf.write_bytes(b"%PDF-1.4" + b"x" * 5000)
        res = check_application(demo_profile, JOB, JOB, {"documents": {}},
                                texte={"anschreiben_de": _letter()},
                                pdfs={})
        assert res["ok"] is True
        assert res["umfang"] == "voll"


class TestDashboardSummary:
    def test_ohne_pruefung(self):
        assert _quality_summary(None) is None

    def test_mit_fehlern_und_warnungen(self):
        summary = _quality_summary({
            "ok": False,
            "umfang": "voll",
            "befunde": [
                {"schwere": "fehler", "detail": "Anrede fehlt"},
                {"schwere": "warnung", "detail": "Lücke nicht ausgewiesen"},
            ],
        })
        assert summary["n"] == 2
        assert summary["errors"] == 1
        assert "Anrede fehlt" in summary["befunde"][0]

    def test_nur_dateipruefung_wird_als_solche_gemeldet(self):
        summary = _quality_summary({"ok": True, "befunde": []})
        assert summary["umfang"] == "datei"
