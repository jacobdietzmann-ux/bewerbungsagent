"""Tests für den Ablauf-Graphen (``orchestrator.py``).

Geprüft wird die **Struktur** des Graphen, nicht die Arbeit der einzelnen
Stufen — die haben ihre eigenen Tests. Wichtig ist hier, dass die Verzweigungen
und Schleifen terminieren und den richtigen Weg nehmen.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bewerbungsagent import orchestrator as O
from bewerbungsagent.config import Config
from bewerbungsagent.profile import Profile

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def graph_mod():
    """Überspringt die Tests, wenn LangGraph nicht installiert ist."""
    pytest.importorskip("langgraph")
    return O


@pytest.fixture
def setup(tmp_path, demo_profile_data):
    """Minimale Konfiguration + Profil für einen kompletten Graphen-Lauf."""
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)
    (tmp_path / "profil.json").write_text(
        json.dumps(demo_profile_data, ensure_ascii=False), encoding="utf-8")
    cfg = {
        "profile_json": str(tmp_path / "profil.json"),
        "data_dir": str(tmp_path / "data"),
        "output_dir": str(tmp_path / "output"),
        "dashboard_file": str(tmp_path / "dashboard.html"),
        "search": {"enabled": False, "providers": ["manual"], "query_terms": [],
                   "location": "München"},
        "documents": {"languages": ["de"]},
    }
    (tmp_path / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    (tmp_path / "data" / "import_jobs.json").write_text(json.dumps([
        {"titel": "Senior Test Engineer (m/w/d)", "firma": "Acme",
         "ort": "München", "url": "https://a.test/1", "beschreibung": "HiL ECU Test"},
        {"titel": "Taxifahrer (m/w/d)", "firma": "Taxi GmbH",
         "ort": "München", "url": "https://a.test/2", "beschreibung": "Fahren"},
    ], ensure_ascii=False), encoding="utf-8")
    config = Config(tmp_path / "config.json")
    profile = Profile(demo_profile_data)
    return config, profile


class TestGraphStruktur:
    """Der Graph muss bauen, ohne dass Knoten fehlen."""

    def test_graph_baut(self, graph_mod):
        assert graph_mod.build_graph() is not None

    def test_graph_ohne_review_baut(self, graph_mod):
        assert graph_mod.build_graph(review=False) is not None

    def test_ohne_langgraph_klare_fehlermeldung(self, monkeypatch, graph_mod):
        """Fehlende Abhängigkeit darf nicht als Traceback enden."""
        import sys
        # Beide Moduleinträge entfernen: ``from langgraph.graph import …`` prüft
        # zuerst den Untermodul-Eintrag, ein leeres ``langgraph`` allein genügt nicht.
        monkeypatch.setitem(sys.modules, "langgraph", None)
        monkeypatch.setitem(sys.modules, "langgraph.graph", None)
        with pytest.raises(RuntimeError, match="LangGraph"):
            graph_mod.build_graph()


class TestAblaufLaeuft:
    """Ein kompletter Durchlauf mit echten Stufen (kein Netzwerk)."""

    def test_alle_knoten_werden_besucht(self, graph_mod, setup, monkeypatch):
        config, profile = setup
        monkeypatch.setattr("bewerbungsagent.pipeline.enrich_commute",
                            lambda apps, data_dir, *a, **k: {"total": len(apps)})
        monkeypatch.setattr("bewerbungsagent.pipeline.enrich_salary",
                            lambda apps: {"kept": 0, "estimated": 0})
        monkeypatch.setattr("bewerbungsagent.pipeline._generate_one",
                            lambda *a, **k: [])
        result = graph_mod.run_abo(config, profile)
        weg = result["weg"]
        assert weg[0] == "suche"
        assert "triage" in weg
        assert "match" in weg
        assert "dashboard" in weg
        assert weg[-1] == "dashboard"

    def test_review_wird_uebersprungen_wenn_gewuenscht(self, graph_mod, setup, monkeypatch):
        config, profile = setup
        monkeypatch.setattr("bewerbungsagent.pipeline.enrich_commute",
                            lambda apps, data_dir, *a, **k: {"total": len(apps)})
        monkeypatch.setattr("bewerbungsagent.pipeline.enrich_salary",
                            lambda apps: {"kept": 0, "estimated": 0})
        monkeypatch.setattr("bewerbungsagent.pipeline._generate_one",
                            lambda *a, **k: [])
        result = graph_mod.run_abo(config, profile, review=False)
        assert "review" not in result["weg"]
        assert result["weg"][-1] == "dashboard"

    def test_triage_verwirft_laerm_im_ablauf(self, graph_mod, setup, monkeypatch):
        config, profile = setup
        monkeypatch.setattr("bewerbungsagent.pipeline.enrich_commute",
                            lambda apps, data_dir, *a, **k: {"total": len(apps)})
        monkeypatch.setattr("bewerbungsagent.pipeline.enrich_salary",
                            lambda apps: {"kept": 0, "estimated": 0})
        monkeypatch.setattr("bewerbungsagent.pipeline._generate_one",
                            lambda *a, **k: [])
        result = graph_mod.run_abo(config, profile)
        assert result["search"]["count"] == 1
        assert result["triage_rejected"] == 1


class TestKantenEntscheidungen:
    """Die Verzweigungen müssen terminieren — Obergrenzen sind Pflicht."""

    def test_beschreibung_schleife_terminiert(self, graph_mod):
        """Wiederholt sich höchstens MAX_BESCHREIBUNG_VERSUCHE-mal."""
        state = {"triage_unsure_verbleibend": 5, "beschreibung_versuche": 0}
        assert graph_mod._braucht_beschreibung(state) == "beschreibung"
        state["beschreibung_versuche"] = graph_mod.MAX_BESCHREIBUNG_VERSUCHE
        assert graph_mod._braucht_beschreibung(state) == "match"

    def test_ohne_unsure_direkt_zum_match(self, graph_mod):
        assert graph_mod._braucht_beschreibung({"triage_unsure_verbleibend": 0}) == "match"

    def test_versuchszaehler_sind_begrenzt(self, graph_mod):
        """Ohne Obergrenze könnte die Nachlade-Schleife nie terminieren."""
        assert graph_mod.MAX_BESCHREIBUNG_VERSUCHE >= 1

    def test_generate_hat_keine_graph_schleife(self, graph_mod):
        """Regression: ein Graph-Retry für generate war reine Doppelarbeit.

        ``generate_anschreiben`` kürzt intern (4 → 3 → 2 Aufzählungspunkte).
        Ein erneuter Aufruf liefert dasselbe Ergebnis — er kostet nur Zeit.
        """
        assert not hasattr(graph_mod, "_braucht_kuerzung")
        assert not hasattr(graph_mod, "MAX_KUERZUNG_VERSUCHE")


class TestKnotenSindFunktional:
    def test_weg_wird_fortgeschrieben_nicht_ersetzt(self, graph_mod):
        state = {"weg": ["suche"]}
        out = graph_mod._notiere(state, "triage")
        assert out == ["suche", "triage"]

    def test_notiere_mutiert_den_eingang_nicht(self, graph_mod):
        state = {"weg": ["suche"]}
        graph_mod._notiere(state, "triage")
        assert state["weg"] == ["suche"]

    def test_review_knoten_ist_reiner_durchlauf(self, graph_mod):
        """Die Bewertung passiert im Dashboard, nicht im Terminal."""
        out = graph_mod.knoten_review({"weg": []})
        assert out["weg"] == ["review"]
        assert set(out) == {"weg"}


class TestGenerateIstIdempotent:
    """``run_generate`` darf bereits bediente Stellen nicht erneut bearbeiten.

    Das war ein echter Bug: ``run_generate`` liest ``matches.json``, die
    Dokument-Info steht aber nur in der DB. Ein zweiter Lauf erzeugte deshalb
    dieselben 36 Stellen erneut — im Graphen dreimal.
    """

    def _config(self, tmp_path, demo_profile_data):
        import json

        from bewerbungsagent.config import Config
        (tmp_path / "data").mkdir(parents=True, exist_ok=True)
        (tmp_path / "output").mkdir(parents=True, exist_ok=True)
        (tmp_path / "profil.json").write_text(
            json.dumps(demo_profile_data, ensure_ascii=False), encoding="utf-8")
        cfg = {
            "profile_json": str(tmp_path / "profil.json"),
            "data_dir": str(tmp_path / "data"),
            "output_dir": str(tmp_path / "output"),
            "search": {"enabled": False, "providers": [], "query_terms": [], "location": "München"},
            "documents": {"languages": ["de"]},
        }
        (tmp_path / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        return Config(tmp_path / "config.json")

    def _vorbereiten(self, config, monkeypatch):
        from bewerbungsagent.db import Store
        from bewerbungsagent.storage import save_json
        from tests.test_enrich_cleanup import _job
        save_json(config.matches_path(), [
            {"id": 1, "key": "k1", "firma": "A", "titel": "Test Engineer",
             "score": 80, "verfuegbar": True},
            {"id": 2, "key": "k2", "firma": "B", "titel": "System Test Engineer",
             "score": 80, "verfuegbar": True},
        ])
        # k1 hat schon Unterlagen, k2 nicht.
        Store(config.db_path()).save_state({"applications": [
            {**_job("k1", firma="A", titel="Test Engineer", score=80),
             "dokumente": {"de": {"anschreiben": "x.pdf"}}},
            _job("k2", firma="B", titel="System Test Engineer", score=80),
        ]})
        aufgerufen = []
        monkeypatch.setattr("bewerbungsagent.pipeline._generate_one",
                            lambda cfg, prof, job, template=None: (
                                aufgerufen.append(job.get("key")) or []))
        return aufgerufen

    def test_bereits_dokumentierte_werden_uebersprungen(self, tmp_path, demo_profile_data,
                                                        monkeypatch):
        from bewerbungsagent.pipeline import run_generate
        config = self._config(tmp_path, demo_profile_data)
        aufgerufen = self._vorbereiten(config, monkeypatch)
        result = run_generate(config, None)
        assert aufgerufen == ["k2"], "nur die Stelle ohne Unterlagen"
        assert result["skipped_existing"] == 1

    def test_ids_erzwingen_neuerzeugung(self, tmp_path, demo_profile_data, monkeypatch):
        """``--ids`` ist ein ausdrücklicher Wunsch und darf nicht übersprungen werden."""
        from bewerbungsagent.pipeline import run_generate
        config = self._config(tmp_path, demo_profile_data)
        aufgerufen = self._vorbereiten(config, monkeypatch)
        run_generate(config, None, job_ids=[1])
        assert aufgerufen == ["k1"]
