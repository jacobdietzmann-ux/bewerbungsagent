"""Qualität statt Masse (ADR-062): keine Automatik, Sparring-Liste, getailerter Lebenslauf."""

from __future__ import annotations

import json

import pytest

from bewerbungsagent import pipeline, sparring, tailoring
from bewerbungsagent.config import Config
from bewerbungsagent.db import Store
from bewerbungsagent.profile import Profile


@pytest.fixture
def config_standard(tmp_path, tmp_config) -> Config:
    """Konfiguration mit den neuen Standardwerten (Automatik aus, Tailoring Pflicht)."""
    tmp_config["documents"].pop("automatisch", None)
    tmp_config["documents"].pop("tailoring_pflicht", None)
    pfad = tmp_path / "config.json"
    pfad.write_text(json.dumps(tmp_config), encoding="utf-8")
    return Config(pfad)


def _stelle(**mehr) -> dict:
    return {"key": "k1", "id": 1, "url": "https://example.test/k1", "firma": "Beispiel GmbH",
            "titel": "Testingenieur HiL (m/w/d)", "status": "research", "score": 84,
            "beschreibung": "HiL-Test mit CANoe und Python. Erfahrung mit MBSE und AUTOSAR.",
            "pendel_modus": "Auto", "pendelzeit_min": 20, **mehr}


class TestKeineAutomatik:
    def test_mengenlauf_erzeugt_nichts(self, config_standard, monkeypatch):
        aufrufe = []
        monkeypatch.setattr(pipeline, "_generate_sicher", lambda *a, **k: aufrufe.append(a) or [])
        ergebnis = pipeline.run_generate(config_standard, None)
        assert ergebnis["automatik_aus"] is True
        assert aufrufe == []

    def test_enrich_erzeugt_nichts(self, config_standard, monkeypatch):
        monkeypatch.setattr(pipeline, "enrich_commute", lambda apps, *a, **k: {"total": len(apps)})
        monkeypatch.setattr(pipeline, "enrich_salary", lambda apps: {})
        aufrufe = []
        monkeypatch.setattr(pipeline, "_generate_one", lambda *a, **k: aufrufe.append(a) or [])
        Store(config_standard.db_path()).save_state({"applications": [_stelle()]})
        ergebnis = pipeline.run_enrich(config_standard, None)
        assert ergebnis["generated_count"] == 0 and aufrufe == []

    def test_ids_markiert_als_gewuenscht(self, config_standard):
        Store(config_standard.db_path()).save_state({"applications": [_stelle()]})
        pipeline._record_docs(config_standard, _stelle(), {"lebenslauf_de": "x.pdf"}, auto=False)
        app = Store(config_standard.db_path()).load_state()["applications"][0]
        assert app["unterlagen_gewuenscht"] is True and app["status"] == "docs"

    def test_ids_sind_bestands_ids(self, config_standard, monkeypatch, tmp_path):
        """19.11.2026: „771" traf in matches.json eine fremde Stelle."""
        from bewerbungsagent.storage import save_json
        save_json(config_standard.matches_path(), [_stelle(key="fremd", id=771, firma="Fremd AG")])
        Store(config_standard.db_path()).save_state({"applications": [_stelle(id=771)]})
        erzeugt = []
        monkeypatch.setattr(pipeline, "_generate_sicher",
                            lambda c, p, job, f, **k: erzeugt.append(job["firma"]) or [])
        pipeline.run_generate(config_standard, None, job_ids=[771])
        assert erzeugt == ["Beispiel GmbH"]

    def test_ohne_tailoring_entsteht_kein_lebenslauf(self, config_standard, demo_profile):
        with pytest.raises(tailoring.TailoringFehler, match="fehlt"):
            pipeline._generate_one(config_standard, demo_profile, _stelle(), auto=False)


class TestSparringListe:
    def test_kandidaten(self):
        apps = [_stelle(),
                _stelle(key="k2", titel="Staff Computer Vision Engineer", score=94),
                _stelle(key="k3", score=68),
                _stelle(key="k4", status="sent"),
                _stelle(key="k5", titel="Systemingenieur Defence", score=74)]
        keys = [a["key"] for a in sparring.kandidaten(apps)]
        assert keys == ["k1", "k5"]

    def test_fehlende_begriffe(self, demo_profile):
        fehlend = sparring.fehlende_begriffe(_stelle(), demo_profile)
        assert "MBSE" in fehlend
        assert "CANoe" not in fehlend   # im Demo-Profil belegt

    def test_markdown_nennt_id_und_luecken(self, demo_profile):
        text = sparring.als_markdown([_stelle()], demo_profile)
        assert "ID 1" in text and "Nicht im Profil:" in text


class TestTailoringPruefung:
    def test_belegter_text_ist_in_ordnung(self, demo_profile):
        daten = {"profil": {"de": "Testingenieur mit HiL- und CANoe-Erfahrung."}}
        assert tailoring.pruefen(daten, demo_profile) == []

    def test_unbelegter_fachbegriff(self, demo_profile):
        daten = {"profil": {"de": "Erfahren in MBSE."}}
        assert any("MBSE" in b for b in tailoring.pruefen(daten, demo_profile))

    def test_harte_luecke(self, demo_profile):
        daten = {"stationen": [{"index": 0, "bullets": {"de": ["Entwicklung in C++"]}}]}
        befunde = tailoring.pruefen(daten, demo_profile, harte_luecken=["C++"])
        assert any("harte Lücke" in b for b in befunde)

    def test_vorlage_gilt_als_beleg(self, demo_profile):
        daten = {"profil": {"de": "Erfahren mit DIADEM."}}
        assert tailoring.pruefen(daten, demo_profile, vorlage_text="DIADEM · CANape") == []

    def test_form_der_skills(self, demo_profile):
        daten = {"skills": {"de": [{"gruppe": "A", "eintraege": ["HiL"]}]}}
        assert any("genau 4 Gruppen" in b for b in tailoring.pruefen(daten, demo_profile))


class TestDocxEinsetzen:
    def _vorlage(self):
        from docx import Document
        doc = Document()
        kopf = doc.add_table(rows=1, cols=2)
        kopf.rows[0].cells[0].paragraphs[0].text = "Name"
        kopf.rows[0].cells[0].add_paragraph("Alte Headline")
        doc.add_table(rows=1, cols=1)
        doc.add_paragraph("■ BERUFSERFAHRUNG")
        doc.add_paragraph("Testingenieur\t01/2020 – 12/2023")
        for t in ("alt 1", "alt 2", "alt 3"):
            doc.add_paragraph(t, style="List Bullet")
        skills = doc.add_table(rows=1, cols=2)
        for zelle in skills.rows[0].cells:
            zelle.paragraphs[0].text = "G"
            for _ in range(3):
                zelle.add_paragraph("x")
        karten = doc.add_table(rows=1, cols=4)
        for zelle in karten.rows[0].cells:
            zelle.paragraphs[0].text = "W"
            zelle.add_paragraph("T")
        return doc

    def test_punkte_skills_karten(self):
        from bewerbungsagent.documents import _stationsbloecke, _tailoring_einsetzen
        doc = self._vorlage()
        daten = {"headline": {"de": "Neue Headline"},
                 "stationen": [{"index": 0, "bullets": {"de": ["neu 1", "neu 2"]}}],
                 "skills": {"de": [{"gruppe": f"G{i}", "eintraege": ["a", "b"]} for i in range(4)]},
                 "kernkompetenzen": {"de": [{"wert": f"W{i}", "text": f"T{i}"} for i in range(4)]}}
        _tailoring_einsetzen(doc, daten, "de")
        assert doc.tables[0].rows[0].cells[0].paragraphs[1].text == "Neue Headline"
        assert [a.text for a in _stationsbloecke(doc)[0]] == ["neu 1", "neu 2"]
        assert doc.tables[2].rows[0].cells[1].paragraphs[3].text == "a · b"
        assert doc.tables[3].rows[0].cells[2].paragraphs[0].text == "W2"

    def test_mehr_punkte_als_vorlage(self):
        from bewerbungsagent.documents import _stationsbloecke, _tailoring_einsetzen
        doc = self._vorlage()
        punkte = [f"p{i}" for i in range(5)]
        _tailoring_einsetzen(doc, {"stationen": [{"index": 0, "bullets": {"de": punkte}}]}, "de")
        assert [a.text for a in _stationsbloecke(doc)[0]] == punkte

    def test_unbekannte_station(self):
        from bewerbungsagent.documents import _tailoring_einsetzen
        with pytest.raises(tailoring.TailoringFehler, match="Station 3"):
            _tailoring_einsetzen(self._vorlage(),
                                 {"stationen": [{"index": 3, "bullets": {"de": ["x"]}}]}, "de")


def test_demo_profil_ist_ein_profil(demo_profile):
    assert isinstance(demo_profile, Profile)
