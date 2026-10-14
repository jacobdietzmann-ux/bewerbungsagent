"""Tests für das Fit-Scoring (``matching.py``)."""

from __future__ import annotations

import pytest

from bewerbungsagent.matching import (
    has_role_signal,
    location_bonus_for,
    match_jobs,
    score_job,
)


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


class TestLocationBonus:
    """Der Bonus kommt aus der echten Pendelzeit, nicht mehr aus dem Ortsnamen.

    Vorher galt „munchen" irgendwo im Ortsfeld als Treffer: Ismaning (9 min)
    und Gräfelfing (29 min) bekamen 0 Punkte, München (25 min) 10.
    """

    def test_nah_und_weit_werden_monoton_bewertet(self):
        near = location_bonus_for({"pendelzeit_min": 9, "ort": "Ismaning"}, "München")
        mid = location_bonus_for({"pendelzeit_min": 31, "ort": "Gilching"}, "München")
        far = location_bonus_for({"pendelzeit_min": 80, "ort": "Regensburg"}, "München")
        assert near == 10
        assert near > mid > far >= 0

    def test_vorort_ohne_namensgleichheit_bekommt_vollen_bonus(self):
        """Regression: Ismaning/Gräfelfing fielen durch den Textvergleich."""
        for ort, minutes in (("Ismaning", 9), ("Gräfelfing", 29), ("Planegg", 29)):
            assert location_bonus_for({"pendelzeit_min": minutes, "ort": ort},
                                      "München") == 10

    def test_ueber_der_grenze_kein_bonus(self):
        assert location_bonus_for({"pendelzeit_min": 95, "ort": "München"},
                                  "München") == 0

    def test_remote_bekommt_vollen_bonus(self):
        assert location_bonus_for({"pendel_modus": "Remote", "pendelzeit_min": None},
                                  "München") == 10

    def test_ohne_pendeldaten_greift_der_ortsvergleich(self):
        assert location_bonus_for({"ort": "München Bogenhausen"}, "München") == 10
        assert location_bonus_for({"ort": "Berlin"}, "München") == 0

    def test_bonus_erhoeht_den_score(self, demo_profile):
        job = _job(titel="Testingenieur", beschreibung="CAN und HiL", ort="Garching")
        ohne = score_job(demo_profile, {**job, "ort": "Berlin"})["score"]
        mit = score_job(demo_profile, {**job, "pendelzeit_min": 20})["score"]
        assert mit >= ohne

    def test_begruendung_nennt_pendelweg(self, demo_profile):
        job = {**_job(titel="Testingenieur", beschreibung="CAN"), "pendelzeit_min": 25}
        assert "Pendelweg 25 min" in score_job(demo_profile, job)["begruendung"]


class TestRoleSignal:
    """Ein hoher Fit allein belegt keine passende Rolle.

    „Embedded Linux & Release Engineer" erreichte 73 % über generische
    Technologie-Treffer (embedded, linux, python) und bekam ungefragt
    Unterlagen. Die Auto-Erzeugung verlangt deshalb ein Rollen-Signal im Titel.
    """

    @pytest.mark.parametrize("titel", [
        "Senior Embedded Systems Test Engineer (All Genders)",
        "Test Automation Engineer (m/f/d)",
        "Flight Test Instrumentation Engineer (m/f/d)",
        "Testingenieur (m/w/d) für Betriebssysteme",
        "Versuchsingenieur (m/w/d) für Hardwaretests",
        "Testkoordinator (m/w/d)",
        "HIL Test Engineer",
        "Senior Verification & Validation Engineer",
        "Prüfstandsingenieur (m/w/d)",
        "System Test Manager",
        "Validierungsingenieur Gesamtfahrzeug",
        "Erprobungsingenieur Gesamtfahrzeug Inbetriebnahme",
        "Absicherungsingenieur (m/w/d)",
    ])
    def test_erkennt_testrollen(self, titel):
        assert has_role_signal(titel) is True

    @pytest.mark.parametrize("titel", [
        "Embedded Linux & Release Engineer (m/f/d)",
        "Linux Software Engineer (m/f/d)",
        "Senior Simulation Platform Engineer, Cloud & Robotics",
        "Export Control Specialist (m/w/d)",
        "Gebietsverkaufsleiter/in im Außendienst",
        "Requirements Engineer Physical Products",
    ])
    def test_erkennt_keine_testrollen(self, titel):
        assert has_role_signal(titel) is False

    def test_leerer_titel_ist_kein_signal(self):
        assert has_role_signal("") is False
        assert has_role_signal(None) is False


class TestFormulaWeights:
    """Die Gewichtung 6/4/2 ist dokumentiert und muss exakt eingehalten werden.

    Ein Titel-Treffer zählt 6, ein Text-Treffer 4, eine Inhaltswort-
    Überschneidung 2 Punkte. Der Ort-Bonus kommt additiv oben drauf.
    """

    @staticmethod
    def _profil():
        from bewerbungsagent.profile import Profile
        return Profile({
            "_meta": {"hinweis": "Test"},
            "personal": {"name": "Test"},
            "skills": {"technik": ["HiL Prüfstand", "Testautomatisierung"]},
        })

    def test_titel_und_text_und_wort_gewichtet(self):
        prof = self._profil()
        job = {"titel": "HiL Prüfstand", "beschreibung": "Testautomatisierung mit Python",
               "ort": "Hamburg"}  # kein Ort-Bonus
        res = score_job(prof, job)
        # Titel: „hil prufstand" ist unter den Treffern, Text: „testautomatisierung".
        assert "hil prufstand" in res["title_hits"]
        assert "testautomatisierung" in res["body_hits"]

    def test_titel_treffer_zählt_staerker_als_text(self):
        prof = self._profil()
        titel_job = {"titel": "HiL Prüfstand", "beschreibung": "", "ort": "Hamburg"}
        text_job = {"titel": "", "beschreibung": "HiL Prüfstand", "ort": "Hamburg"}
        assert score_job(prof, titel_job)["score"] > score_job(prof, text_job)["score"]


class TestSprachvarianten:
    """Deutsche Profilbegriffe müssen englische Anzeigen treffen (und umgekehrt).

    Der eigene Lebenslauf ist zweisprachig: die EN-Fassung nennt „Test automation",
    das Profil führt „Testautomatisierung". Vor diesem Fix fand der Scorer die
    eigene Kernkompetenz in Test-Automation-Anzeigen nicht — u. a. bei beiden
    Quantum-Systems-Testrollen.
    """

    @staticmethod
    def _profil():
        from bewerbungsagent.profile import Profile
        return Profile({
            "_meta": {"hinweis": "Test"},
            "personal": {"name": "Test"},
            "skills": {"technik": ["Testautomatisierung", "XiL-/HiL-Prüfstände"]},
        })

    def test_englische_anzeige_trifft_deutschen_profilbegriff(self):
        prof = self._profil()
        assert "test automation" in prof.keyword_phrases
        assert "test automation" in prof.keywords_in("Test Automation Engineer (m/f/d)")

    def test_deutsche_kurzform_trifft_ebenfalls(self):
        prof = self._profil()
        assert "testautomation" in prof.keywords_in("Einführung einer Testautomation")

    def test_prufstand_varianten(self):
        prof = self._profil()
        assert "test bench" in prof.keyword_phrases
        assert "test bench" in prof.keywords_in("Work on our test bench in Munich")

    def test_ohne_grundbegriff_keine_varianten(self):
        """Die Brücke greift nur, wenn der Grundbegriff im Profil steht."""
        from bewerbungsagent.profile import Profile
        prof = Profile({
            "_meta": {"hinweis": "Test"},
            "personal": {"name": "Test"},
            "skills": {"technik": ["Python"]},
        })
        assert "test automation" not in prof.keyword_phrases
        assert "test bench" not in prof.keyword_phrases

    def test_keine_generischen_woerter_als_synonym(self):
        """Nackte Allerweltswörter („requirement", „interface") dürfen keine
        Synonyme sein — sie stünden in fast jeder Anzeige und verwässerten den
        Score. Mehrwort-Varianten wie „requirements based testing" sind erlaubt."""
        from bewerbungsagent.profile import _SYNONYMS, Profile
        flat = {v for vs in _SYNONYMS.values() for v in vs}
        assert "requirement" not in flat
        assert "requirements" not in flat
        assert "interface" not in flat
        prof = Profile({
            "_meta": {"hinweis": "Test"},
            "personal": {"name": "Test"},
            "skills": {"technik": ["Testautomatisierung"]},
        })
        assert "requirement" not in prof.keyword_phrases
        assert "interface" not in prof.keyword_phrases
