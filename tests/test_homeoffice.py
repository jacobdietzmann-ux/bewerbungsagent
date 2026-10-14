"""Tests für die Erkennung des Homeoffice-Anteils (``homeoffice.py``)."""

from __future__ import annotations

from bewerbungsagent.homeoffice import detect_home_office, home_office_grund


def _job(titel="", beschreibung=""):
    return {"titel": titel, "beschreibung": beschreibung}


class TestDetectHomeOffice:
    def test_voll_remote(self):
        assert detect_home_office(_job(beschreibung="100% remote work")) == "Voll-Remote"
        assert detect_home_office(_job(beschreibung="Fully remote role")) == "Voll-Remote"

    def test_hybrid(self):
        assert detect_home_office(_job(beschreibung="Hybrid working setup")) == "Hybrid"
        assert detect_home_office(
            _job(beschreibung="bis zu 2 Tage Homeoffice pro Woche")) == "Hybrid"

    def test_homeoffice_moeglich(self):
        assert detect_home_office(
            _job(beschreibung="Homeoffice-Regelungen vorhanden")) == "Homeoffice möglich"
        assert detect_home_office(
            _job(beschreibung="Mobiles Arbeiten möglich")) == "Homeoffice möglich"

    def test_vor_ort(self):
        assert detect_home_office(_job(beschreibung="On-site in Munich")) == "Vor Ort"

    def test_unbekannt(self):
        assert detect_home_office(_job(beschreibung="Wir suchen einen Tester.")) == "Unbekannt"
        assert detect_home_office(_job(beschreibung="")) == "Unbekannt"

    def test_remote_test_sites_ist_kein_homeoffice(self):
        """Regression: „remote test sites" heißt entfernte Prüfstände, nicht Homeoffice."""
        assert detect_home_office(
            _job(beschreibung="drive vehicles to remote test sites")) != "Homeoffice möglich"

    def test_100_prozent_schlaegt_allgemeines_homeoffice(self):
        assert detect_home_office(
            _job(beschreibung="Homeoffice und 100% remote work")) == "Voll-Remote"

    def test_grund_nennt_den_beleg(self):
        assert "remote" in home_office_grund(_job(beschreibung="100% remote work")).lower()
