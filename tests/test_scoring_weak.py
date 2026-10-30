"""Tests für `weak_skills`: Grundkenntnisse geben keine Fit-Punkte.

Hintergrund: Das Profil führte Python als „erweiterte Grundkenntnisse" und
zählte damit in Titel, Text und Inhaltswörtern. Tatsächlich sind es
Grundkenntnisse und kleine Skripte — Python soll den Fit nicht mehr tragen,
im Profil und in den Unterlagen aber sichtbar bleiben.
"""

from __future__ import annotations

from bewerbungsagent.matching import score_job

BESCHREIBUNG = (
    "Testautomatisierung mit Python, CAN, ADAS, HiL, XiL, CANoe, ECU-Test, "
    "ISO 26262, DOORS, Jira und FlexRay."
)


def _job(titel: str, beschreibung: str = BESCHREIBUNG) -> dict:
    return {"titel": titel, "beschreibung": beschreibung, "ort": "München", "firma": "Beispiel GmbH"}


class TestWeakSkills:
    def test_python_gibt_keine_punkte(self, demo_profile):
        ohne = score_job(demo_profile, _job("Testingenieur Python (m/w/d)"))
        mit = score_job(demo_profile, _job("Testingenieur Python (m/w/d)"), weak_skills=["Python"])
        assert mit["score"] < ohne["score"]
        assert "python" not in mit["matched_skills"]
        assert "python" not in mit["word_hits"]

    def test_stelle_ohne_python_bleibt_gleich(self, demo_profile):
        job = _job("Testingenieur (m/w/d)", "CAN, ADAS, HiL, ISO 26262, DOORS, Jira.")
        assert score_job(demo_profile, job)["score"] == score_job(demo_profile, job, weak_skills=["Python"])["score"]

    def test_andere_begriffe_bleiben(self, demo_profile):
        r = score_job(demo_profile, _job("Testingenieur Python (m/w/d)"), weak_skills=["Python"])
        assert "can" in r["matched_skills"] or "adas" in r["matched_skills"]
