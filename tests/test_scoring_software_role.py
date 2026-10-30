"""Tests für den Software-Rollen-Deckel (45 %).

Hintergrund: „Softwareingenieur für Embedded Software" und „Softwareentwickler
C++ / Qt" standen bei 62–82 %, weil der Keyword-Fit die Domänenüberschneidung
belohnt. Produktcode-Entwicklung ist aber nicht das Profil (Test, Integration,
Absicherung) — diese Rollen fallen unter die Ausblendegrenze.
"""

from __future__ import annotations

from bewerbungsagent.matching import ROLE_CAP, SOFTWARE_CAP, is_software_role, score_job

BESCHREIBUNG = (
    "Entwicklung und Absicherung eingebetteter Systeme: ADAS, HiL und XiL, CAN, "
    "CAN-FD, FlexRay, Automotive Ethernet, CANoe, ECU-Test, ISO 26262, DOORS, Jira."
)


def _job(titel: str, beschreibung: str = BESCHREIBUNG) -> dict:
    return {"titel": titel, "beschreibung": beschreibung, "ort": "München", "firma": "Beispiel GmbH"}


class TestIsSoftwareRole:
    def test_softwareingenieur_kompositum(self):
        assert is_software_role("Softwareingenieur für Embedded Software (w/m/d)")

    def test_softwareentwickler_kompositum(self):
        assert is_software_role("Softwareentwickler C++ / Qt – Simulation & Netzwerktechnik")

    def test_embedded_software_engineer(self):
        assert is_software_role("Staff Embedded Software Engineer (m/f/d)")

    def test_software_test_engineer_bleibt_erlaubt(self):
        assert not is_software_role("Software Test Engineer (m/f/d)")

    def test_softwareentwickler_fuer_testsysteme_bleibt_erlaubt(self):
        assert not is_software_role("Softwareentwickler für Testsysteme")

    def test_applications_engineer_ist_keine_software_rolle(self):
        assert not is_software_role("Senior Staff Field Applications Engineer (f/m/d)")
        assert not is_software_role("Applications Engineer")


class TestSoftwareCap:
    def test_softwarerolle_wird_auf_45_gedeckelt(self, demo_profile):
        r = score_job(demo_profile, _job("Softwareingenieur für Embedded Software (w/m/d)"))
        assert r["role_cap"] == SOFTWARE_CAP == 45
        assert r["score"] <= 45

    def test_hardware_entwickler_bleibt_bei_60(self, demo_profile):
        r = score_job(demo_profile, _job("Embedded Hardware Entwickler (m/w/d)"))
        assert r["role_cap"] == ROLE_CAP == 60

    def test_software_test_engineer_ohne_deckel(self, demo_profile):
        r = score_job(demo_profile, _job("Software Test Engineer (m/f/d)"))
        assert r["role_cap"] is None
