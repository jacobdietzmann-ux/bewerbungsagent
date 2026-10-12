"""Tests für die Text-Bausteine der Dokumenterzeugung.

Die PDF-Erzeugung selbst (ReportLab) wird hier NICHT getestet — sie ist
deterministisch, aber schwer zu asserten (binäres PDF). Stattdessen testen wir
die **reinen Text-Funktionen**, die den Inhalt bestimmen:

- ``_headline``: wählt die richtige Headline (Chip vs. Test, DE vs. EN)
- ``_is_chip_role``: erkennt Hardware-/Embedded-Rollen
- ``_sanitize``: ersetzt Zeichen, die Helvetica (Latin-1) nicht kann
- ``esc``: HTML-Escaping für ReportLab-Paragraphs
- ``_clean_label``: korrigiert kleingeschriebene Einzelwort-Labels
- ``_summary_skills``: liefert rollenabhängige Schwerpunkte ohne Rauschen

Das ist eine Art "Golden-File"-Test auf Baustein-Ebene: Wir prüfen, dass der
**Inhalt** stimmt, nicht die Pixel.
"""

from __future__ import annotations

import pytest

from bewerbungsagent import documents as D
from bewerbungsagent.profile import Profile


@pytest.fixture
def demo(demo_profile_data):
    return Profile(demo_profile_data)


class TestHeadline:
    def test_test_role_english(self, demo):
        job = {"titel": "Test Engineer", "firma": "Firma"}
        match = {"matched_skills": ["testing", "hil"]}
        assert D._headline(job, match, "en") == D.PROFESSIONAL_HEADLINE_EN

    def test_test_role_german(self, demo):
        job = {"titel": "Testingenieur", "firma": "Firma"}
        match = {"matched_skills": ["testing"]}
        assert D._headline(job, match, "de") == D.PROFESSIONAL_HEADLINE_DE

    def test_chip_role_english(self, demo):
        job = {"titel": "Embedded Engineer", "firma": "Firma"}
        match = {"matched_skills": ["embedded"]}
        assert D._headline(job, match, "en") == D.PROFESSIONAL_HEADLINE_CHIP_EN

    def test_chip_role_german(self, demo):
        job = {"titel": "Hardware-Entwickler", "firma": "Firma"}
        match = {"matched_skills": ["hardware"]}
        assert D._headline(job, match, "de") == D.PROFESSIONAL_HEADLINE_CHIP_DE


class TestIsChipRole:
    def test_embedded_signal(self):
        job = {"titel": "Embedded Software Developer", "firma": "X"}
        match = {"matched_skills": ["c++"]}
        assert D._is_chip_role(job, match) is True

    def test_aurix_signal(self):
        job = {"titel": "Entwickler", "firma": "X"}
        match = {"matched_skills": ["aurix"]}
        assert D._is_chip_role(job, match) is True

    def test_plain_test_role_is_not_chip(self):
        job = {"titel": "Test Engineer", "firma": "X"}
        match = {"matched_skills": ["testing", "hil"]}
        assert D._is_chip_role(job, match) is False

    def test_electronics_keyword(self):
        job = {"titel": "Ingenieur", "firma": "X"}
        match = {"matched_skills": ["elektronik"]}
        assert D._is_chip_role(job, match) is True


class TestSanitize:
    def test_arrow_replaced(self):
        assert "→" not in D._sanitize("Test → Ende")

    def test_en_dash_replaced(self):
        assert "–" not in D._sanitize("2024 – 2026")

    def test_curly_quotes_replaced(self):
        # Beide Varianten des deutschen Anführungszeichens werden ersetzt.
        assert '"' in D._sanitize("x“")  # schließendes (U+201C)
        assert '"' in D._sanitize("„x")  # öffnendes (U+201E)
        assert "“" not in D._sanitize("x“")
        assert "„" not in D._sanitize("„x")

    def test_empty_and_none(self):
        assert D._sanitize("") == ""
        assert D._sanitize(None) == ""

    def test_plain_text_unchanged(self):
        assert D._sanitize("CANape & CANoe") == "CANape & CANoe"


class TestEsc:
    def test_html_chars_escaped(self):
        # xml.sax.saxutils.escape ersetzt &, <, > — NICHT ". Das ist für
        # ReportLab-Paragraphs korrekt (kein Attribut-Kontext).
        assert "&amp;" in D.esc("A & B")
        assert "&lt;" in D.esc("<b>")
        assert "&gt;" in D.esc("a > b")

    def test_quote_not_escaped(self):
        assert '"' in D.esc('"x"')
        assert "&quot;" not in D.esc('"x"')

    def test_none_becomes_empty(self):
        assert D.esc(None) == ""

    def test_plain_text_unchanged(self):
        assert D.esc("CAN") == "CAN"


class TestCleanLabel:
    def test_lowercase_single_word_capitalized(self):
        assert D._clean_label("hardware") == "Hardware"

    def test_uppercase_unchanged(self):
        assert D._clean_label("Hardware") == "Hardware"

    def test_multiword_unchanged(self):
        assert D._clean_label("embedded systems") == "embedded systems"

    def test_cpp_capitalized(self):
        # "c++" ist ein Einzelwort ohne Leerzeichen/Bindestrich → wird nach
        # "C++" korrigiert (gewollt, damit Skill-Labels sauber aussehen).
        assert D._clean_label("c++") == "C++"

    def test_empty_unchanged(self):
        assert D._clean_label("") == ""


class TestSummarySkills:
    def _job(self, titel="Testingenieur", matched=None):
        return {"titel": titel, "firma": "X"}, {"matched_skills": matched or ["testing", "hil"]}

    def test_returns_list_of_str(self, demo):
        job, match = self._job()
        out = D._summary_skills(demo, job, match, "de", n=3)
        assert isinstance(out, list)
        assert all(isinstance(s, str) for s in out)

    def test_never_exceeds_n(self, demo):
        job, match = self._job(matched=["testing", "hil", "python", "can", "embedded"])
        assert len(D._summary_skills(demo, job, match, "de", n=2)) <= 2

    def test_no_generic_skills(self, demo):
        # "testing"/"software"/"engineer" sind generisch -> dürfen nicht auftauchen
        job, match = self._job(matched=["testing", "software", "engineer"])
        out = D._summary_skills(demo, job, match, "de", n=3)
        norm = {D.normalize(s) for s in out}
        assert "testing" not in norm
        assert "software" not in norm

    def test_chip_defaults_for_chip_role(self, demo):
        job = {"titel": "Embedded Engineer", "firma": "X"}
        match = {"matched_skills": ["embedded"]}
        out = D._summary_skills(demo, job, match, "en", n=4)
        # Sollte mindestens einen _CHIP_SUMMARY-Default enthalten (C/C++, etc.)
        assert any("C/C++" in s or "Embedded" in s for s in out)

    def test_english_vs_german_differ(self, demo):
        job, match = self._job(matched=["embedded"])
        de = D._summary_skills(demo, job, match, "de", n=3)
        en = D._summary_skills(demo, job, match, "en", n=3)
        # Sprachen sollten unterschiedliche Formulierungen liefern.
        assert de != en


class TestLetterIntro:
    def test_contains_position_and_company(self, demo):
        job = {"titel": "Test Engineer", "firma": "Acme GmbH"}
        match = {"matched_skills": []}
        intro = D._letter_intro(demo, job, match, "en")
        assert "Test Engineer" in intro
        assert "Acme GmbH" in intro

    def test_german_uses_sie(self, demo):
        job = {"titel": "Testingenieur", "firma": "Acme"}
        match = {"matched_skills": []}
        intro = D._letter_intro(demo, job, match, "de")
        assert "Ihnen" in intro


class TestCvProfileSummary:
    def test_english_mentions_mechanical_engineer(self, demo):
        job = {"titel": "Test", "firma": "X"}
        match = {"matched_skills": []}
        s = D._cv_profile_summary(demo, job, match, "en")
        assert "Mechanical engineer" in s

    def test_german_mentions_maschinenbau(self, demo):
        job = {"titel": "Test", "firma": "X"}
        match = {"matched_skills": []}
        s = D._cv_profile_summary(demo, job, match, "de")
        assert "Maschinenbau" in s
