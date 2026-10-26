"""Tests für das Rollen-Gate: Entwickler-/Produktrollen ohne Testbezug.

Hintergrund: „Principal Engineer – AI-Enabled Embedded Software" (NXP) und
„Senior Manager CAD Infrastructure" (Infineon) standen bei 100 %, weil der
Keyword-Fit die Domänenüberschneidung belohnt — die Rolle ist aber
Produktentwicklung, nicht Test/Absicherung.
"""

from __future__ import annotations

from bewerbungsagent.matching import ROLE_CAP, is_development_role, score_job


def _job(titel: str, beschreibung: str = "", ort: str = "") -> dict:
    return {"titel": titel, "beschreibung": beschreibung, "ort": ort, "firma": "Beispiel GmbH"}


# Viele Treffer im Demo-Profil (CAN, ADAS, HiL, CANoe, ISO 26262, DOORS, Jira,
# Python) — aber kein fremder Stack, damit nur das Rollen-Gate greift.
BESCHREIBUNG = (
    "Entwicklung und Absicherung eingebetteter Systeme: ADAS, HiL und XiL, CAN, CAN-FD, "
    "FlexRay, Automotive Ethernet, CANoe, ECU-Test, AUTOSAR, ASPICE, ISO 26262, "
    "Trace-Analyse, Regression, Release, DOORS, Codebeamer, Jira und Python."
)


class TestIsDevelopmentRole:
    def test_embedded_software_engineer_ist_entwicklerrolle(self):
        assert is_development_role("Principal Engineer – AI-Enabled Embedded Software")

    def test_cad_manager_ist_entwicklerrolle(self):
        assert is_development_role("Senior Manager CAD Infrastructure (f/m/div)")

    def test_firmware_entwickler_ist_entwicklerrolle(self):
        assert is_development_role("Firmware-Entwickler Embedded Systems (m/w/d)")

    def test_software_test_engineer_ist_keine_entwicklerrolle(self):
        assert not is_development_role("Software Test Engineer (m/f/d)")

    def test_testingenieur_embedded_ist_keine_entwicklerrolle(self):
        assert not is_development_role("Testingenieur Embedded Software (m/w/d)")

    def test_entwicklungsingenieur_testsysteme_ist_keine_entwicklerrolle(self):
        assert not is_development_role("Entwicklungsingenieur Testsysteme (m/w/d)")

    def test_systemingenieur_ist_keine_entwicklerrolle(self):
        assert not is_development_role("Systemingenieur (m/w/d)")


class TestRoleCap:
    def test_embedded_software_engineer_wird_gedeckelt(self, demo_profile):
        r = score_job(demo_profile, _job("Principal Engineer – AI-Enabled Embedded Software", BESCHREIBUNG))
        assert r["role_cap"] == ROLE_CAP
        assert r["score"] == ROLE_CAP
        assert "Entwickler-/Produktrolle" in r["begruendung"]

    def test_cad_manager_wird_gedeckelt(self, demo_profile):
        r = score_job(demo_profile, _job("Senior Manager CAD Infrastructure (f/m/div)", BESCHREIBUNG))
        assert r["role_cap"] == ROLE_CAP
        assert r["score"] == ROLE_CAP

    def test_software_test_engineer_bleibt_ungedeckelt(self, demo_profile):
        r = score_job(demo_profile, _job("Software Test Engineer (m/f/d)", BESCHREIBUNG))
        assert r["role_cap"] is None
        assert r["score"] > ROLE_CAP

    def test_testingenieur_embedded_bleibt_ungedeckelt(self, demo_profile):
        r = score_job(demo_profile, _job("Testingenieur Embedded Software (m/w/d)", BESCHREIBUNG))
        assert r["role_cap"] is None

    def test_systemingenieur_bleibt_ungedeckelt(self, demo_profile):
        r = score_job(demo_profile, _job("Systemingenieur (m/w/d)", BESCHREIBUNG))
        assert r["role_cap"] is None
