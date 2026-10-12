"""Tests für das Fit-Scoring (``matching.py``)."""

from __future__ import annotations

import pytest

from bewerbungsagent.matching import match_jobs, score_job


def _job(titel="Testingenieur (m/w/d)", beschreibung="", ort=""):
    return {"titel": titel, "beschreibung": beschreibung, "ort": ort, "firma": "Beispiel GmbH"}


class TestScoreJob:
    def test_score_is_bounded(self, demo_profile):
        job = _job(beschreibung="CAN " * 500)
        assert 0 <= score_job(demo_profile, job)["score"] <= 100

    def test_empty_job_scores_zero(self, demo_profile):
        assert score_job(demo_profile, _job(titel="", beschreibung=""))["score"] == 0

    def test_relevant_job_scores_higher_than_irrelevant(self, demo_profile):
        relevant = _job(
            titel="Testingenieur HiL (m/w/d)",
            beschreibung="Erfahrung mit CAN, ADAS, HiL-Prüfständen und Python. ISO 26262 von Vorteil.",
        )
        irrelevant = _job(
            titel="Social Media Manager (m/w/d)",
            beschreibung="Betreuung von Instagram und TikTok, Content-Erstellung, Community-Management.",
        )
        assert score_job(demo_profile, relevant)["score"] > score_job(demo_profile, irrelevant)["score"]

    def test_matched_skills_are_sorted_and_unique(self, demo_profile):
        job = _job(beschreibung="CAN HiL Python CAN CAN HiL")
        matched = score_job(demo_profile, job)["matched_skills"]
        assert matched == sorted(set(matched))

    def test_location_bonus_munich_matches_munchen(self, demo_profile):
        """Regression: 'Munich' (EN) muss den Standortbonus zu 'München' auslösen."""
        job = _job(beschreibung="Test", ort="Munich")
        assert score_job(demo_profile, job, location="München")["location_bonus"] == 10

    def test_location_bonus_zero_for_far_city(self, demo_profile):
        job = _job(beschreibung="Test", ort="Hamburg")
        assert score_job(demo_profile, job, location="München")["location_bonus"] == 0

    @pytest.mark.parametrize("score_min,expected", [(65, "hoch"), (40, "mittel"), (0, "niedrig")])
    def test_category_thresholds(self, demo_profile, score_min, expected):
        # Wir prüfen die Kategorie-Konsistenz zum Score statt exakter Wortlisten.
        for text in ("", "CAN ADAS HiL", "CAN " * 60):
            res = score_job(demo_profile, _job(beschreibung=text))
            s = res["score"]
            cat = res["fit_geschaetzt"]
            if s >= 65:
                assert cat == "hoch"
            elif s >= 40:
                assert cat == "mittel"
            else:
                assert cat == "niedrig"


class TestMatchJobs:
    def test_sorted_descending(self, demo_profile):
        jobs = [
            _job(beschreibung="Social Media Instagram"),
            _job(beschreibung="CAN ADAS HiL Python ISO 26262"),
        ]
        out = match_jobs(demo_profile, jobs)
        assert out[0]["score"] >= out[1]["score"]

    def test_input_jobs_not_mutated(self, demo_profile):
        job = _job(beschreibung="CAN")
        snapshot = dict(job)
        match_jobs(demo_profile, [job])
        assert job == snapshot
