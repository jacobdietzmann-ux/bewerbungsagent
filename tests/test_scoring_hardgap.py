"""Tests für bestätigte Lücken im Titel (``hard_gaps``, z. B. C++).

Hintergrund: Das Profil führte C++ als „Grundkenntnisse", obwohl keine
Kenntnisse vorliegen. C++-Rollen bekamen dadurch Titel- und Textpunkte. Nach
dem Entfernen aus dem Profil senkt sich der Score ohnehin; steht C++ im Titel,
greift zusätzlich der Deckel.
"""

from __future__ import annotations

import json

import pytest

from bewerbungsagent.matching import HARD_GAP_CAP, score_job
from bewerbungsagent.profile import Profile

BESCHREIBUNG = (
    "Absicherung eingebetteter Systeme: ADAS, HiL und XiL, CAN, CAN-FD, FlexRay, "
    "Automotive Ethernet, CANoe, ECU-Test, AUTOSAR, ASPICE, ISO 26262, Trace-Analyse, "
    "Regression, Release, DOORS, Codebeamer, Jira und Python."
)


def _job(titel: str, beschreibung: str = BESCHREIBUNG) -> dict:
    return {"titel": titel, "beschreibung": beschreibung, "ort": "München", "firma": "Beispiel GmbH"}


@pytest.fixture
def profil_ohne_cpp(demo_profile) -> Profile:
    data = json.loads(json.dumps(demo_profile.data))
    for key, wert in list(data.get("skills", {}).items()):
        if isinstance(wert, list):
            data["skills"][key] = [
                str(s).replace("C/C++", "Python").replace("C++", "") for s in wert
            ]
    return Profile(data)


class TestHardGap:
    def test_cpp_im_titel_wird_gedeckelt(self, profil_ohne_cpp):
        r = score_job(profil_ohne_cpp, _job("Testingenieur C++ (m/w/d)"), hard_gaps=["C++"])
        assert r["hard_gap"] == "C++"
        assert r["score"] == HARD_GAP_CAP
        assert "C++" in r["begruendung"]

    def test_ohne_hard_gaps_kein_deckel(self, profil_ohne_cpp):
        r = score_job(profil_ohne_cpp, _job("Testingenieur C++ (m/w/d)"))
        assert r["hard_gap"] is None
        assert r["score"] > HARD_GAP_CAP

    def test_cpp_nur_im_text_kein_deckel(self, profil_ohne_cpp):
        r = score_job(profil_ohne_cpp, _job("Testingenieur (m/w/d)", BESCHREIBUNG + " C++ von Vorteil."),
                      hard_gaps=["C++"])
        assert r["hard_gap"] is None

    def test_belegtes_cpp_kein_deckel(self, demo_profile):
        r = score_job(demo_profile, _job("Testingenieur C++ (m/w/d)"), hard_gaps=["C++"])
        assert r["hard_gap"] is None
        assert r["score"] > HARD_GAP_CAP
