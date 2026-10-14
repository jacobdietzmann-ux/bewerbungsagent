"""Tests für die Profil- und Keyword-Aufbereitung (``profile.py``).

Regressionsschutz für zwei echte Fehler aus der Projekt-Historie:
1. Klammerzusätze ("ISO 26262 (funktionale Sicherheit)") wurden verstümmelt,
   weil ``strip("()")`` *vor* dem Split lief → ``iso 26262`` matchte nie.
2. Generische Wörter ("Analyse") durften nicht als eigenständiges Keyword
   aus Komma-getrennten Skill-Strings entstehen.
"""

from __future__ import annotations

import pytest

from bewerbungsagent.profile import Profile, _split_phrases, normalize


class TestNormalize:
    @pytest.mark.parametrize("raw,expected", [
        ("München", "munchen"),
        ("Groß", "gross"),
        ("  Mixed CASE  ", "  mixed case  "),
        ("", ""),
    ])
    def test_normalize(self, raw, expected):
        assert normalize(raw) == expected

    def test_normalize_umlauts_become_ascii(self):
        # Für Matching müssen Umlaute ASCII-normalisiert werden.
        assert "mu" in normalize("München")
        assert "ß" not in normalize("Straße")


class TestSplitPhrases:
    def test_parenthesized_term_splits_into_both_parts(self):
        """Regression: 'ISO 26262 (funktionale Sicherheit)' muss ISO 26262 liefern."""
        out = _split_phrases("ISO 26262 (funktionale Sicherheit)")
        assert "ISO 26262" in out
        assert "funktionale Sicherheit" in out

    @pytest.mark.parametrize("raw,expected_member", [
        ("ASPICE (Grundkenntnisse)", "ASPICE"),
        ("Octane (ALM Octane)", "Octane"),
        ("LV124/ISO 16750 (Umweltpruefungen)", "ISO 16750"),
    ])
    def test_various_parenthesized_terms(self, raw, expected_member):
        assert expected_member in _split_phrases(raw)

    def test_no_closing_paren_leakage(self):
        """Kein Fragment darf eine unbalancierte Klammer enthalten."""
        for raw in ("ISO 26262 (X)", "ASPICE (Y)"):
            for part in _split_phrases(raw):
                assert part.count("(") == part.count(")")

    def test_simple_term_unchanged(self):
        assert _split_phrases("ISO 21434") == ["ISO 21434"]

    def test_komma_in_klammer_zerlegt_nicht_die_klammer(self):
        """Regression: „(TCP/UDP, serielle Schnittstellen)" hinterließ „udp, …"."""
        out = _split_phrases("Netzwerk- & Kommunikationsprotokolle (TCP/UDP, serielle Schnittstellen)")
        assert "serielle Schnittstellen" in out
        assert "TCP" in out and "UDP" in out
        # Kein Rest darf ein Komma aus dem Klammerinneren behalten.
        assert not any("," in p for p in out)

    def test_kompositum_mit_slash_bleibt_zusammen(self):
        """„E/E" und „C/C++" sind *ein* Begriff — kein Split in Ein-Buchstaben-Reste."""
        out = _split_phrases("Fahrzeugarchitektur E/E (CAN, CAN-FD, LIN)")
        assert "Fahrzeugarchitektur E/E" in out
        assert not any(p.strip().lower().endswith(" e") for p in out)
        assert "CAN-FD" in out

    def test_slash_liste_wird_geteilt(self):
        out = _split_phrases("ISO 26262/LV124/GS 95024")
        assert "ISO 26262" in out
        assert "LV124" in out

    def test_kategorie_praefix_wird_abgetrennt(self):
        out = _split_phrases("Hardware-Verständnis: Elektrotechnik")
        assert "Hardware-Verständnis" in out
        assert "Elektrotechnik" in out


class TestProfileKeywords:
    def test_iso_26262_is_matchable(self, demo_profile):
        """Regression: ISO 26262 muss als Keyword existieren und im Text matchen."""
        assert "iso 26262" in demo_profile.keyword_phrases
        hits = demo_profile.keywords_in("Wir fordern Kenntnisse in ISO 26262 und ASPICE.")
        assert "iso 26262" in hits
        assert "aspice" in hits

    def test_generic_analyse_not_a_keyword(self, demo_profile):
        """Generisches 'Analyse' darf nicht als eigenes Keyword entstehen."""
        assert "analyse" not in set(demo_profile.keyword_phrases)

    def test_short_tokens_use_word_boundary(self, demo_profile):
        """'can' darf nicht in 'candidate' matchen."""
        hits = demo_profile.keywords_in("We are looking for a candidate with drive")
        assert "can" not in hits

    def test_can_matches_as_word(self, demo_profile):
        hits = demo_profile.keywords_in("Erfahrung mit CAN und CAN-FD")
        assert "can" in hits

    def test_display_of_roundtrip(self, demo_profile):
        for kw in demo_profile.keyword_phrases[:20]:
            assert isinstance(demo_profile.display_of(kw), str)


class TestPhraseWordOrder:
    """Mehrwort-Phrasen dürfen nicht an der Wortreihenfolge scheitern."""

    @staticmethod
    def _profil():
        return Profile({
            "_meta": {"hinweis": "Test"},
            "personal": {"name": "Test"},
            "skills": {"rollen": ["Test Engineer"]},
        })

    def test_test_engineer_matches_compound_title(self):
        """Regression: „Test Automation Engineer" verfehlte „test engineer"."""
        prof = self._profil()
        assert "test engineer" in prof.keyword_phrases
        for titel in ("Test Automation Engineer (m/w/d)",
                      "Flight Test Instrumentation Engineer (m/f/d)",
                      "Senior Embedded Systems Test Engineer"):
            assert "test engineer" in prof.keywords_in(titel), titel

    def test_contiguous_match_bleibt_erhalten(self):
        prof = self._profil()
        assert "test engineer" in prof.keywords_in("We need a Test Engineer.")


class TestGapTerms:
    """Bestätigte Lücken dürfen nie als Skill zählen."""

    def test_gap_term_is_not_a_keyword(self):
        prof = Profile({
            "_meta": {"hinweis": "Test"},
            "personal": {"name": "Test"},
            "skills": {"normen": ["Prozessnormen-Transfer: ISO 26262 - DO-178C, MIL-STD-810"]},
            "confirmed_gaps_do_not_overclaim": ["Keine Erfahrung mit DO-178C, MIL-STD-810"],
            "gap_terms": ["DO-178C", "MIL-STD-810"],
        })
        kws = set(prof.keyword_phrases)
        assert "178c" not in kws
        assert "mil-std-810" not in kws
        assert "mil" not in kws          # Token aus MIL-STD-810
        assert "std" not in kws
        assert "gs 95024 - do-178c" not in kws
        assert "iso 26262" in kws        # vorhandene Norm bleibt Keyword

    def test_generisches_wort_blockt_keine_komposita(self):
        """Regression: ``system`` (aus „Robot Operating System") löschte
        „Embedded Systems", „Echtzeitsysteme" und ganze Rollentitel."""
        prof = Profile({
            "_meta": {"hinweis": "Test"},
            "personal": {"name": "Test"},
            "skills": {"systeme": ["Embedded Systems", "Echtzeitsysteme", "E/E-Architektur"]},
            "confirmed_gaps_do_not_overclaim": ["Keine ROS-Erfahrung"],
            "gap_terms": ["ROS", "ROS 2", "Robot Operating System", "Robot Framework"],
        })
        kws = set(prof.keyword_phrases)
        assert "embedded systems" in kws
        assert "echtzeitsysteme" in kws

    def test_ohne_gap_terms_bleibt_alles_wie_vorher(self):
        prof = Profile({
            "_meta": {"hinweis": "Test"},
            "personal": {"name": "Test"},
            "skills": {"normen": ["DO-160"]},
        })
        assert "do-160" in set(prof.keyword_phrases)
