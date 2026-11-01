"""Tests für den Profil-Export (JSON → Markdown-Lesefassung).

Hintergrund: Bis 30.10.2026 gab es zwei handgepflegte Fassungen des Profils
(JSON + Markdown im Second Brain). Die Markdown-Fassung lief auseinander und
nannte noch „Python (erweiterte Grundkenntnisse)" und „C++ (Grundkenntnisse)",
während die JSON längst korrigiert war. Jetzt ist die JSON die einzige Quelle,
die Markdown-Datei ein erzeugtes Artefakt.
"""

from __future__ import annotations

import json

from bewerbungsagent.profile_export import (export_profile_markdown,
                                            profile_markdown_stale,
                                            render_profile_markdown)

PROFIL = {
    "_meta": {"created": "2026-09-06"},
    "personal": {
        "name": "Test Person",
        "birth_date": "01.01.1990",
        "birth_place": "Teststadt",
        "address": "Teststraße 1, 12345 Teststadt",
        "marital_status": "ledig",
    },
    "skills": {
        "programmierung": ["Python (Grundkenntnisse)"],
        "sprachen": [{"sprache": "Deutsch", "niveau": "Muttersprache"}],
    },
    "work_experience": [
        {"period": "01/2020 – 12/2021", "role_de": "Testingenieur",
         "employer_of_record": "Test GmbH", "client": "Kunde AG"},
    ],
    "education": [{"period": "09/2012", "title_de": "Diplom Maschinenbau"}],
    "certifications": ["ISTQB Certified Tester"],
    "confirmed_gaps_do_not_overclaim": ["Keine C++-Kenntnisse"],
    "tailoring_rules": ["Nur belegte Tools nennen", "Lücken nicht überformen"],
}


def _text() -> str:
    return render_profile_markdown(PROFIL, quelle="02_Profil-und-Assets\\Profil-Datenbank.json")


class TestRender:
    def test_kopf_ist_als_artefakt_markiert(self):
        text = _text()
        assert text.startswith("---\ntype: ressource")
        assert "Automatisch erzeugt" in text
        assert "Profil-Datenbank.json" in text

    def test_person_und_sprachen(self):
        text = _text()
        assert "| Name | Test Person, Jg. 1990 (Teststadt) |" in text
        assert "Deutsch (Muttersprache)" in text

    def test_kompetenzen_und_luecken(self):
        text = _text()
        assert "| Programmierung | Python (Grundkenntnisse) |" in text
        assert "- Keine C++-Kenntnisse" in text

    def test_berufserfahrung_und_ausbildung(self):
        text = _text()
        assert "| 01/2020 – 12/2021 | Testingenieur | Test GmbH / Kunde AG |" in text
        assert "ISTQB Certified Tester" in text

    def test_tailoring_regeln_nummeriert(self):
        text = _text()
        assert "1. Nur belegte Tools nennen." in text
        assert "2. Lücken nicht überformen." in text

    def test_render_ist_deterministisch(self):
        assert _text() == _text()


class TestExport:
    def test_export_schreibt_datei_und_ist_danach_aktuell(self, tmp_path):
        quelle = tmp_path / "02_Profil-und-Assets" / "Profil-Datenbank.json"
        quelle.parent.mkdir(parents=True)
        quelle.write_text(json.dumps(PROFIL, ensure_ascii=False), encoding="utf-8")
        ziel = tmp_path / "03 Ressourcen" / "Berufsprofil – Faktenbasis.md"

        export_profile_markdown(quelle, ziel)
        assert ziel.exists()
        assert not profile_markdown_stale(quelle, ziel)

    def test_aenderung_am_json_macht_die_datei_veraltet(self, tmp_path):
        quelle = tmp_path / "02_Profil-und-Assets" / "Profil-Datenbank.json"
        quelle.parent.mkdir(parents=True)
        quelle.write_text(json.dumps(PROFIL, ensure_ascii=False), encoding="utf-8")
        ziel = tmp_path / "Berufsprofil.md"
        export_profile_markdown(quelle, ziel)

        geaendert = dict(PROFIL)
        geaendert["confirmed_gaps_do_not_overclaim"] = ["Keine C++-Kenntnisse", "Keine Docker-Erfahrung"]
        quelle.write_text(json.dumps(geaendert, ensure_ascii=False), encoding="utf-8")
        assert profile_markdown_stale(quelle, ziel)

    def test_created_datum_bleibt_erhalten(self, tmp_path):
        quelle = tmp_path / "02_Profil-und-Assets" / "Profil-Datenbank.json"
        quelle.parent.mkdir(parents=True)
        quelle.write_text(json.dumps(PROFIL, ensure_ascii=False), encoding="utf-8")
        ziel = tmp_path / "Berufsprofil.md"
        ziel.write_text("---\ncreated: 2026-10-29\n---\n", encoding="utf-8")
        export_profile_markdown(quelle, ziel)
        assert "created: 2026-10-29" in ziel.read_text(encoding="utf-8")
