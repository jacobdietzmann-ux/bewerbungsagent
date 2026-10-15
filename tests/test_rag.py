"""Tests für die Retrieval-Schicht des Anschreibens (``rag.py``).

Geprüft wird das „R“ in RAG: belegte Skill-Behauptungen mit Quelle und Zeitraum
sowie die Lücken-Transparenz — nicht eine Sprachmodell-Generierung, die bewusst
außerhalb dieses Moduls liegt.
"""

from __future__ import annotations

import json
from pathlib import Path

from bewerbungsagent.profile import Profile
from bewerbungsagent.rag import citation, gap_evidence, retrieve_evidence

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "profil-demo.json"


def _profile() -> Profile:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    # Lücken explizit setzen, damit die Lücken-Erkennung testbar ist.
    data["gap_terms"] = ["DO-178C", "ROS", "Docker"]
    return Profile(data)


def _match(skills: list[str]) -> dict:
    return {"matched_skills": skills}


class TestRetrieveEvidence:
    def test_liefert_quelle_und_zeitraum(self):
        prof = _profile()
        # Ein Skill, der im Demo-Profil eine Erfahrungs-Station belegt.
        ev = retrieve_evidence(prof, _match(["testautomatisierung"]), "de", max_claims=3)
        assert ev, "mindestens ein belegbarer Skill erwartet"
        first = ev[0]
        assert first.label
        assert first.claim
        assert first.source, "die Quelle (Station) darf nicht leer sein"
        assert first.period, "der Zeitraum darf nicht leer sein"

    def test_generische_fuellwoerter_werden_nicht_als_skill_belegt(self):
        """Füllwörter („deutsch“, „software“) dürfen kein Skill-Label erzeugen.

        Der Fallback liefert Rollen-Bullets mit leerem ``skill`` — aber eben
        keine Behauptung „Software: …“, nur weil das Füllwort im Titel stand.
        """
        prof = _profile()
        ev = retrieve_evidence(prof, _match(["deutsch", "englisch", "software"]), "de")
        assert all(e.skill == "" for e in ev)

    def test_dedupliziert_redundante_labels(self):
        prof = _profile()
        ev = retrieve_evidence(prof, _match(["testautomatisierung", "test automation"]), "de",
                               max_claims=6)
        labels = {e.label.lower() for e in ev}
        # Die Synonym-Brücke darf nicht zweimal dieselbe Behauptung liefern.
        assert len(labels) == len(ev)

    def test_max_claims_greift(self):
        prof = _profile()
        ev = retrieve_evidence(prof, _match(["python", "hil", "testautomatisierung"]), "de",
                               max_claims=1)
        assert len(ev) == 1


class TestCitation:
    def test_deutsch(self):
        from bewerbungsagent.rag import Evidence
        ev = Evidence(skill="x", label="X", claim="c", source="Testkoordinator",
                      period="01/2024 – 09/2026")
        assert citation(ev, "de") == "Belegt durch: Testkoordinator (01/2024 – 09/2026)"

    def test_englisch(self):
        from bewerbungsagent.rag import Evidence
        ev = Evidence(skill="x", label="X", claim="c", source="Test Coordinator",
                      period="01/2024 – 09/2026")
        assert citation(ev, "en") == "Evidenced by: Test Coordinator (01/2024 – 09/2026)"

    def test_ohne_quelle_keine_angabe(self):
        from bewerbungsagent.rag import Evidence
        ev = Evidence(skill="x", label="X", claim="c", source="", period="")
        assert citation(ev, "de") == ""


class TestGapEvidence:
    def test_luecke_wird_nur_bei_relevanz_benannt(self):
        prof = _profile()
        # Verteidigungs-Stelle verlangt DO-178C → Lücke ist relevant.
        job = {"titel": "Avionik-Ingenieur", "beschreibung": "Kenntnisse in DO-178C erforderlich"}
        gaps = gap_evidence(prof, job, "de")
        assert any("DO-178C" in g for g in gaps)

    def test_irrelevante_luecke_bleibt_weg(self):
        prof = _profile()
        job = {"titel": "Testingenieur", "beschreibung": "HiL-Prüfstände und Testautomatisierung"}
        gaps = gap_evidence(prof, job, "de")
        assert all("DO-178C" not in g and "ROS" not in g and "Docker" not in g for g in gaps)

    def test_kurze_terme_mit_wortgrenzen(self):
        prof = _profile()
        # „ROS“ darf nicht in „across“/„crossing“ matchen.
        job = {"titel": "", "beschreibung": "across the crossing, no robotics"}
        gaps = gap_evidence(prof, job, "de")
        assert not any("ROS" in g for g in gaps)

    def test_englisch(self):
        prof = _profile()
        job = {"titel": "", "beschreibung": "Requires DO-178C compliance"}
        gaps = gap_evidence(prof, job, "en")
        assert any("DO-178C" in g for g in gaps)

    def test_leere_stelle_keine_luecken(self):
        prof = _profile()
        assert gap_evidence(prof, {}, "de") == []


class TestLetterIntegration:
    """Die RAG-Anreicherung muss im erzeugten Anschreiben ankommen (opt-in)."""

    def _story_text(self, demo, job, match, flags):
        from bewerbungsagent import documents as D
        config = {"documents": {"accent_color": "#0B3D5C", **flags}}
        story, _accent = D._letter_story(demo, job, match, config, "de", max_bullets=3)
        from reportlab.platypus import Paragraph
        return " ".join(p.text for p in story if isinstance(p, Paragraph))

    def test_quellenangaben_erscheinen_wenn_aktiviert(self, demo_profile):
        job = {"titel": "Test Engineer", "firma": "Acme"}
        match = {"matched_skills": ["testautomatisierung"]}
        on = self._story_text(demo_profile, job, match, {"anschreiben_quellen": True})
        off = self._story_text(demo_profile, job, match, {"anschreiben_quellen": False})
        assert "Belegt durch:" in on
        assert "Belegt durch:" not in off

    def test_luecken_erscheinen_wenn_aktiviert(self):
        from bewerbungsagent.profile import Profile
        # Demo-Profil mit einer Lücke, die die Stelle verlangt.
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        data["gap_terms"] = ["DO-178C"]
        prof = Profile(data)
        job = {"titel": "Avionik", "firma": "Acme",
               "beschreibung": "Kenntnisse in DO-178C erforderlich"}
        match = {"matched_skills": []}
        on = self._story_text(prof, job, match, {"anschreiben_luecken": True})
        off = self._story_text(prof, job, match, {"anschreiben_luecken": False})
        assert "DO-178C" in on
        assert "DO-178C" not in off

    def test_beides_standardmaessig_aus(self, demo_profile):
        job = {"titel": "Test Engineer", "firma": "Acme"}
        match = {"matched_skills": ["testautomatisierung"]}
        s = self._story_text(demo_profile, job, match, {})
        assert "Belegt durch:" not in s
