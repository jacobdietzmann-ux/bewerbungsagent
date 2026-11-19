"""Hinweis auf frühere Bewerbung und Sparring-Kandidaten im Dashboard (19.11.2026)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from bewerbungsagent import auswahl, sparring
from bewerbungsagent.dashboard import build_dashboard, dashboard_applications


def _app(i, firma, titel, status="research", **mehr):
    return {"id": i, "key": f"k{i}", "firma": firma, "titel": titel, "status": status, **mehr}


ABGESAGT = _app(2553, "IABG", "Senior Systems Engineer mechatronische Sonderanlagen",
                "rejected", statusChangedAt="2026-09-25T10:00:00")


class TestFruehereBewerbung:
    def test_iabg_schreibweisen(self):
        """Firma mit Zusatz, „(Senior)" und Gender-Tag: dieselbe Anzeige."""
        neu = _app(167, "IABG Industrieanlagen - Betriebsgesellschaft mbH",
                   "(Senior) Systems Engineer mechatronische Sonderanlagen (m/w/d)")
        frueher = auswahl.fruehere_bewerbung(neu, auswahl.bewerbungs_index([ABGESAGT, neu]))
        assert frueher is ABGESAGT
        assert auswahl.frueher_text(frueher, kurz=True) == "abgesagt 25.09. (ID 2553)"

    def test_umlaut_schreibweise(self):
        alt = _app(1, "IABG", "Requirements Engineer Flugkoerpertechnologien", "sent",
                   sentAt="2026-09-01T09:00:00")
        neu = _app(2, "IABG", "Requirements Engineer Flugkörpertechnologien")
        assert auswahl.fruehere_bewerbung(neu, auswahl.bewerbungs_index([alt])) is alt

    def test_angehaengte_rechtsform(self):
        alt = _app(1, "Agilerobotsse", "Mechatronics Test Engineer (m/f/d)", "rejected")
        neu = _app(2, "Agile Robots SE", "Mechatronics and Hardware Test Engineer (m/f/d)")
        assert auswahl.fruehere_bewerbung(neu, auswahl.bewerbungs_index([alt])) is alt

    def test_andere_firma_oder_rolle(self):
        index = auswahl.bewerbungs_index([ABGESAGT])
        assert auswahl.fruehere_bewerbung(
            _app(3, "Airbus", "Senior Systems Engineer mechatronische Sonderanlagen"), index) is None
        assert auswahl.fruehere_bewerbung(_app(4, "IABG", "Software Engineer"), index) is None

    def test_abgeschlossene_selbst_ohne_hinweis(self):
        index = auswahl.bewerbungs_index([ABGESAGT])
        zweite = _app(9, "IABG", ABGESAGT["titel"], "rejected")
        assert auswahl.fruehere_bewerbung(zweite, index) is None


def test_sparring_liste_nennt_fruehere_bewerbung(demo_profile):
    kandidat = _app(167, "IABG Industrieanlagen - Betriebsgesellschaft mbH",
                    "(Senior) Systems Engineer mechatronische Sonderanlagen", score=80)
    text = sparring.als_markdown([kandidat], demo_profile, alle=[kandidat, ABGESAGT])
    assert "⚠ Ähnlich schon beworben:" in text and "ID 2553" in text


class TestDashboard:
    def test_sparring_kandidat_ohne_unterlagen_sichtbar(self):
        kandidat = _app(1, "Beispiel GmbH", "Testingenieur HiL", "neu", score=80,
                        pendelzeit_min=20)
        schwach = _app(2, "Beispiel GmbH", "Testingenieur HiL", "neu", score=68)
        weit = _app(3, "Beispiel GmbH", "Testingenieur HiL", "neu", score=80, pendelzeit_min=50)
        sichtbar = dashboard_applications([kandidat, schwach, weit], limit=30)
        assert sichtbar == [kandidat]

    def test_badges_im_datensatz(self, tmp_path):
        kandidat = _app(167, "IABG", "(Senior) Systems Engineer mechatronische Sonderanlagen",
                        "neu", score=80)
        ziel = build_dashboard({"applications": [kandidat, ABGESAGT]}, tmp_path / "d.html")
        html = Path(ziel).read_text(encoding="utf-8")
        assert '"sparring": true' in html
        assert "abgesagt 25.09. (ID 2553)" in html


def test_digest_zeigt_hinweis():
    pfad = Path(__file__).resolve().parents[1] / "scripts" / "jobwatch.py"
    spec = importlib.util.spec_from_file_location("jobwatch_aehnlich", pfad)
    jobwatch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(jobwatch)
    job = _app(167, "IABG", "Systems Engineer", score=80, url="https://example.test/1",
               _frueher="abgesagt 25.09. (ID 2553)")
    text = jobwatch.build_digest([job], [job], False, 65, 5)
    assert "⚠ ähnlich abgesagt 25.09. (ID 2553)" in text
