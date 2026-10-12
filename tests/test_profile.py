"""Tests für die Profil- und Keyword-Aufbereitung (``profile.py``).

Regressionsschutz für zwei echte Fehler aus der Projekt-Historie:
1. Klammerzusätze ("ISO 26262 (funktionale Sicherheit)") wurden verstümmelt,
   weil ``strip("()")`` *vor* dem Split lief → ``iso 26262`` matchte nie.
2. Generische Wörter ("Analyse") durften nicht als eigenständiges Keyword
   aus Komma-getrennten Skill-Strings entstehen.
"""

from __future__ import annotations

import pytest

from bewerbungsagent.profile import _split_phrases, normalize


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
