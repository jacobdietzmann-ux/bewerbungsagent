"""Tests für den Stack-Abgleich im Fit-Scoring (``matching.stack_gap``).

Hintergrund: Eine Stelle „Lead Integration Engineer (m/w/d) im Team Technology
Consulting" erreichte 74 %, obwohl Java, Spring Boot, Kafka, SOAP und Guidewire
im Profil nicht belegt sind. Die Überschneidung kam aus generischen Wörtern
(„Integration", „Schnittstellen", „Anforderungen"). Der Stack-Abgleich deckelt
solche Rollen — aber nur, wenn **kein** genannter Stack-Begriff belegt ist und
der Titel keinen Test-/Verifikationskern hat.
"""

from __future__ import annotations

import json

from bewerbungsagent.matching import STACK_CAP, score_job, stack_gap
from bewerbungsagent.profile import Profile


def _job(titel: str, beschreibung: str = "", ort: str = "") -> dict:
    return {"titel": titel, "beschreibung": beschreibung, "ort": ort, "firma": "Beispiel GmbH"}


# Anzeigentext mit vielen Profil-Treffern (Integration, Schnittstellen, ADAS,
# HiL, CAN, ISO 26262, DOORS, Jira) — und einem Stack, der im Demo-Profil fehlt.
FREMD = (
    "Wir suchen Verstärkung für Integrationsarchitektur, Schnittstellen und Anforderungen. "
    "Du arbeitest mit Java, Spring Boot, Kafka, SOAP, Guidewire, SQL, Docker und Postman; "
    "Testen, Debugging und Dokumentation gehören zum Alltag. Im Projekt geht es um ADAS, "
    "HiL und XiL, CAN, CAN-FD, FlexRay, Automotive Ethernet, CANoe, ECU-Test, AUTOSAR, "
    "ASPICE, ISO 26262, Trace-Analyse, Regression, Release, DOORS, Codebeamer, Jira und ISTQB."
)


class TestStackGap:
    def test_stack_wird_erkannt_und_als_fehlend_gemeldet(self, demo_profile):
        gefunden, fehlend = stack_gap(demo_profile, "Java, Spring Boot, Kafka, SOAP, Docker")
        assert gefunden == ["Docker", "Java", "Kafka", "SOAP", "Spring Boot"]
        assert fehlend == gefunden

    def test_belegter_begriff_ist_nicht_fehlend(self, demo_profile):
        gefunden, fehlend = stack_gap(demo_profile, "Python, Kafka")
        assert gefunden == ["Kafka", "Python"]
        assert fehlend == ["Kafka"]

    def test_ohne_stack_keine_treffer(self, demo_profile):
        assert stack_gap(demo_profile, "Testingenieur für HiL-Prüfstände") == ([], [])

    def test_lueckenlisten_belegen_keine_kompetenz(self, demo_profile):
        """``confirmed_gaps``/``_meta`` nennen Docker — das darf nicht als Skill zählen."""
        profil = Profile(json.loads(json.dumps(demo_profile.data)))
        profil.data["confirmed_gaps_do_not_overclaim"] = ["Keine Docker-Erfahrung (explizit verneint)"]
        _gefunden, fehlend = stack_gap(profil, "Docker")
        assert fehlend == ["Docker"]


class TestStackCap:
    def test_architekturrolle_ohne_belegten_stack_wird_gedeckelt(self, demo_profile):
        r = score_job(demo_profile, _job(
            "Lead Integration Engineer (m/w/d) im Team Technology Consulting", FREMD))
        assert r["stack_cap"] == STACK_CAP
        assert r["score"] == STACK_CAP
        assert "Deckel" in r["begruendung"]
        assert "Java" in r["stack_missing"]

    def test_testrolle_mit_gleichem_text_bleibt_ungedeckelt(self, demo_profile):
        r = score_job(demo_profile, _job("Testingenieur (m/w/d)", FREMD))
        assert r["stack_cap"] is None
        assert r["score"] > STACK_CAP

    def test_teilweise_belegter_stack_kein_deckel(self, demo_profile):
        r = score_job(demo_profile, _job("System Integration Engineer (m/w/d)", FREMD + " Python."))
        assert r["stack_cap"] is None

    def test_ohne_stack_kein_deckel(self, demo_profile):
        r = score_job(demo_profile, _job(
            "Systemingenieur (m/w/d)", "Integration von Anlagen, Schnittstellen, Testen, CAN, ADAS."))
        assert r["stack_cap"] is None

    def test_einzelner_fremder_begriff_kein_deckel(self, demo_profile):
        """Eine Anzeige, die nur MATLAB nennt, ist kein Ausschluss (MIN_STACK_TERMS)."""
        r = score_job(demo_profile, _job(
            "Embedded Software Engineer (m/w/d)",
            "Entwicklung eingebetteter Software, CAN, ADAS, ISO 26262, AUTOSAR, Trace-Analyse, "
            "Regression, Release, Matlab/Simulink."))
        assert r["stack_found"] == ["MATLAB/Simulink"]
        assert r["stack_cap"] is None
