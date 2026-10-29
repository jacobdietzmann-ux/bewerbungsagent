"""Niveau-Angaben sind keine Fähigkeiten.

Ausgangslage: Das Profil beschreibt den Grad einer Fähigkeit in Klammern —
„Python (fundiert)", „C++ (Grundkenntnisse)". ``_split_phrases`` zerlegt auch
den Klammerinhalt, und diese Wörter landeten als **Schlüsselbegriffe** im
Profil. Folge: Eine Anzeige mit „fundierte Kenntnisse in C++" galt als
Profiltreffer, obwohl das Wort dort eine Anforderung beschreibt und nichts über
den Bewerber aussagt. Gemessen über den Bestand war „fundiert" in 283 von 1705
Bewertungen ein Treffer, „grundkenntnisse" in 46.

Die Sperre darf **nicht** zu breit sein: ``audi``, ``bmw``, ``test`` und
``engineer`` stehen absichtlich in ``_ROLE_WORD_NOISE``, weil sie als
*Einzelwort* nichts aussagen — als Phrase („test engineer") sind sie aber
informativ. Eine Prüfung gegen die ganze Rauschmenge löschte „test engineer"
und senkte 265 Scores, ohne dass das etwas mit dem Profil zu tun hatte.
"""

from __future__ import annotations

import pytest

from bewerbungsagent.profile import Profile


def _profil(**skills) -> Profile:
    return Profile({"skills": skills or {"programmierung": ["Python (fundiert)"]},
                    "work_experience": []})


class TestNiveauAngaben:
    @pytest.mark.parametrize("skill", [
        "Python (fundiert)",
        "C++ (Grundkenntnisse)",
        "Python (erweiterte Grundkenntnisse)",
        "Englisch (verhandlungssicher)",
        "Deutsch (Muttersprache)",
    ])
    def test_grad_wird_nicht_zum_schluesselwort(self, skill):
        p = _profil(programmierung=[skill])
        for wort in ("fundiert", "grundkenntnisse", "erweiterte", "verhandlungssicher",
                     "muttersprache"):
            assert wort not in p.keyword_phrases, (skill, wort)
            assert wort not in p.content_words, (skill, wort)

    def test_der_begriff_selbst_bleibt_erhalten(self):
        """„Python (fundiert)" muss weiterhin über „python" matchen."""
        p = _profil(programmierung=["Python (erweiterte Grundkenntnisse)"])
        assert "python" in p.keyword_phrases
        assert "python" in p.content_words

    def test_reine_niveau_phrase_entfaellt(self):
        p = _profil(programmierung=["Python (erweiterte Grundkenntnisse)"])
        assert "erweiterte grundkenntnisse" not in p.keyword_phrases

    def test_anzeige_mit_fundiert_ist_kein_treffer_mehr(self):
        p = _profil(programmierung=["Python (fundiert)"])
        treffer = p.keywords_in("Fundierte Kenntnisse in C++ und Java erforderlich")
        assert "fundiert" not in treffer


class TestKeinUebermass:
    """Regression: die Sperre darf keine echten Phrasen mitnehmen."""

    def test_rollenphrase_test_engineer_bleibt(self):
        p = Profile({"skills": {}, "work_experience": [{
            "role_de": "Test Engineer", "role_en": "Test Engineer",
            "tags": ["BMW", "Audi"],
        }]})
        assert "test engineer" in p.keyword_phrases

    def test_firmenkuerzel_bleiben(self):
        p = Profile({"skills": {}, "work_experience": [{"tags": ["BMW", "Audi"]}]})
        assert "bmw" in p.keyword_phrases
        assert "audi" in p.keyword_phrases

    def test_mehrwort_phrase_mit_rauschwort_bleibt(self):
        """„Root-Cause-Analyse" besteht aus Rauschwörtern, ist aber informativ."""
        p = _profil(test_datenauswertung=["Fehleranalyse (Root-Cause-Analyse)"])
        assert any("root-cause" in k for k in p.keyword_phrases), p.keyword_phrases

    def test_fahrerassistenzsysteme_bleibt(self):
        p = _profil(sonstiges=["Fahrerassistenzsysteme"])
        assert "fahrerassistenzsysteme" in p.keyword_phrases
