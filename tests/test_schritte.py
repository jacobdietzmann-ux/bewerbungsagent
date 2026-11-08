"""Alle Laufwege nutzen dieselbe Schrittliste (ADR-056).

Vorher führte jeder Laufweg seine eigene Folge. ``run_full`` ließ ``fetch`` aus und
bewertete neue Stellen nur nach dem Titel, ``jobwatch`` kannte weder ``generate``
noch ``quality``. Die Tests hier schlagen an, sobald ein Laufweg wieder eigene
Schritte führt.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
from pathlib import Path

import pytest

from bewerbungsagent import orchestrator, pipeline, schritte
from bewerbungsagent.config import Config
from bewerbungsagent.schritte import FETCH_LIMIT, SCHRITT_NAMEN, SCHRITTE, fuehre_aus

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("jobwatch_schritte",
                                               ROOT / "scripts" / "jobwatch.py")
jobwatch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(jobwatch)  # type: ignore[union-attr]


@pytest.fixture
def config(tmp_path) -> Config:
    daten = {"data_dir": str(tmp_path / "data"), "output_dir": str(tmp_path / "output"),
             "profile_json": str(tmp_path / "profil.json"),
             "dashboard_file": str(tmp_path / "dashboard.html"),
             "search": {"enabled": False, "providers": [], "query_terms": [],
                        "location": "München"}}
    pfad = tmp_path / "config.json"
    pfad.write_text(json.dumps(daten), encoding="utf-8")
    return Config(pfad)


def _pipeline_aufzeichnen(monkeypatch) -> list[str]:
    """Ersetzt die Schrittfunktionen und zeichnet die Reihenfolge auf."""
    weg: list[str] = []
    antworten = {"run_search": ("search", {}), "run_fetch": ("fetch", {}),
                 "run_match": ("match", {"matched": 0}),
                 "run_enrich": ("enrich", {"generated": [], "failed": []}),
                 "run_generate": ("generate", {"generated": [], "failed": []}),
                 "run_quality": ("quality", {}), "run_dashboard": ("dashboard", {})}
    for funktion, (name, antwort) in antworten.items():
        monkeypatch.setattr(pipeline, funktion,
                            lambda *_a, _n=name, _r=antwort, **_k: weg.append(_n) or _r)
    return weg


class TestListe:
    def test_reihenfolge(self):
        assert SCHRITT_NAMEN == ("search", "fetch", "match", "enrich", "generate",
                                 "quality", "dashboard")

    def test_nur_nachladen_und_pruefen_duerfen_scheitern(self):
        assert {s.name for s in SCHRITTE if s.optional} == {"fetch", "quality"}

    def test_fetch_ist_begrenzt(self):
        fetch = next(s for s in SCHRITTE if s.name == "fetch")
        assert fetch.argumente == ("--limit", str(FETCH_LIMIT))

    def test_kein_nachfolger_nach_dem_letzten_schritt(self):
        assert schritte.naechster_schritt("fetch") == "match"
        with pytest.raises(IndexError):
            schritte.naechster_schritt(SCHRITT_NAMEN[-1])

    @pytest.mark.parametrize("schritt", SCHRITTE, ids=lambda s: s.name)
    def test_jeder_schritt_ist_ein_befehl_von_agent_py(self, schritt, capsys):
        """``jobwatch`` ruft ``agent.py <name> <argumente>``: Das muss parsen."""
        pytest.importorskip("reportlab")
        import agent
        with pytest.raises(SystemExit) as beendet:
            agent.main([schritt.name, *schritt.argumente, "--help"])
        assert beendet.value.code == 0

    @pytest.mark.parametrize("name", ["fetch", "quality"])
    def test_optionaler_schritt_meldet_den_fehler(self, name, capsys):
        def kaputt():
            raise RuntimeError("Browser fehlt")

        fehler: dict[str, str] = {}
        assert fuehre_aus(name, kaputt, fehler) is None
        assert fehler == {name: "RuntimeError: Browser fehlt"}
        assert name in capsys.readouterr().out

    def test_pflichtschritt_bricht_ab(self):
        def kaputt():
            raise RuntimeError("DB weg")

        fehler: dict[str, str] = {}
        with pytest.raises(RuntimeError):
            fuehre_aus("match", kaputt, fehler)
        assert fehler == {}


class TestRunFull:
    def test_folgt_der_liste(self, config, monkeypatch):
        weg = _pipeline_aufzeichnen(monkeypatch)
        pipeline.run_full(config, None)
        assert tuple(weg) == SCHRITT_NAMEN

    def test_fetch_laeuft_vor_match(self, config, monkeypatch):
        """Ohne Text bewertet ``match`` nur den Titel (ADR-050)."""
        weg = _pipeline_aufzeichnen(monkeypatch)
        pipeline.run_full(config, None)
        assert weg.index("fetch") < weg.index("match")

    def test_fehlendes_nachladen_stoppt_den_lauf_nicht(self, config, monkeypatch):
        weg = _pipeline_aufzeichnen(monkeypatch)

        def kaputt(*_a, **_k):
            raise ImportError("playwright fehlt")

        monkeypatch.setattr(pipeline, "run_fetch", kaputt)
        ergebnis = pipeline.run_full(config, None)
        assert "fetch" not in weg
        assert weg[-1] == "dashboard"
        assert ergebnis["fehler"] == {"fetch": "ImportError: playwright fehlt"}

    def test_laedt_alle_fehlenden_texte(self, config, monkeypatch):
        import sys
        import types
        gerufen = []
        modul = types.ModuleType("fetch_descriptions")
        modul.fetch_descriptions = lambda cfg, **k: gerufen.append(k) or {}
        monkeypatch.setitem(sys.modules, "fetch_descriptions", modul)
        pipeline.run_fetch(config)
        assert gerufen == [{"limit": FETCH_LIMIT, "only_unsure": False}]


class TestGraph:
    def test_zu_jedem_schritt_gibt_es_einen_knoten(self):
        assert set(orchestrator.KNOTEN) == set(SCHRITT_NAMEN)

    @pytest.mark.parametrize("review", [True, False])
    def test_graph_enthaelt_genau_die_liste(self, review):
        pytest.importorskip("langgraph")
        knoten = set(orchestrator.build_graph(review=review).get_graph().nodes)
        steuerung = {"__start__", "__end__", "triage"} | ({"review"} if review else set())
        assert knoten - steuerung == set(SCHRITT_NAMEN)

    @pytest.mark.parametrize("review", [True, False])
    def test_lauf_folgt_der_liste(self, config, monkeypatch, review):
        """Offene Texte: Der Graph geht jeden Schritt in Listenfolge."""
        pytest.importorskip("langgraph")
        config.jobs_path().write_text(json.dumps([{"titel": "x", "url": "u"}]), encoding="utf-8")
        monkeypatch.setattr(orchestrator, "run_search", lambda *_a: {})
        monkeypatch.setattr(orchestrator, "run_match", lambda *_a: {"matched": 0})
        monkeypatch.setattr(orchestrator, "run_enrich", lambda *_a: {})
        monkeypatch.setattr(orchestrator, "run_generate", lambda *_a: {})
        monkeypatch.setattr(orchestrator, "run_quality", lambda *_a: {})
        monkeypatch.setattr(orchestrator, "run_dashboard", lambda *_a: {})

        def laden(cfg, nur_unsure):
            cfg.jobs_path().write_text(json.dumps([{"titel": "x", "url": "u",
                                                    "beschreibung": "Text"}]), encoding="utf-8")
            return {"fetched": 1}

        monkeypatch.setattr(orchestrator, "run_fetch", laden)
        ergebnis = orchestrator.run_abo(config, None, review=review, beschreibung="alle")
        steuerung = {"triage", "review"}
        assert tuple(k for k in ergebnis["weg"] if k not in steuerung) == SCHRITT_NAMEN
        assert ("review" in ergebnis["weg"]) is review

    def test_fehlender_browser_stoppt_den_graphen_nicht(self, config, monkeypatch):
        """Vorher brach ein Fehler beim Nachladen den ganzen Ablauf ab."""
        def kaputt(*_a, **_k):
            raise ImportError("playwright fehlt")

        monkeypatch.setattr(orchestrator, "run_fetch", kaputt)
        ergebnis = orchestrator.knoten_beschreibung({"config": config, "weg": []})
        assert ergebnis["fehler"] == {"fetch": "ImportError: playwright fehlt"}
        assert ergebnis["beschreibung_versuche"] == 1


class TestJobwatch:
    def _lauf(self, monkeypatch, tmp_path, fehlschlag=""):
        monkeypatch.setattr(jobwatch, "RUN_OUTPUT", tmp_path / "lauf.log")
        befehle: list[list[str]] = []

        def run(befehl, **_k):
            befehle.append(befehl)
            return subprocess.CompletedProcess(befehl, 1 if befehl[2] == fehlschlag else 0)

        monkeypatch.setattr(jobwatch.subprocess, "run", run)
        return jobwatch.run_pipeline(), [b[2:] for b in befehle]

    def test_ruft_jeden_schritt_mit_seinen_argumenten(self, monkeypatch, tmp_path):
        ok, befehle = self._lauf(monkeypatch, tmp_path)
        assert ok is True
        assert befehle == [[s.name, *s.argumente] for s in SCHRITTE]

    @pytest.mark.parametrize("name", [s.name for s in SCHRITTE if s.optional])
    def test_optionaler_schritt_stoppt_nicht(self, monkeypatch, tmp_path, name):
        ok, befehle = self._lauf(monkeypatch, tmp_path, fehlschlag=name)
        assert ok is False
        assert [b[0] for b in befehle] == list(SCHRITT_NAMEN)

    @pytest.mark.parametrize("name", [s.name for s in SCHRITTE if not s.optional])
    def test_pflichtschritt_stoppt(self, monkeypatch, tmp_path, name):
        ok, befehle = self._lauf(monkeypatch, tmp_path, fehlschlag=name)
        assert ok is False
        assert befehle[-1][0] == name


class TestShellSkripte:
    @pytest.mark.parametrize("lauf", ["tageslauf", "wochenlauf"])
    def test_rufen_nur_den_gemeinsamen_rahmen(self, lauf):
        text = (ROOT / "scripts" / f"{lauf}.sh").read_text(encoding="utf-8")
        assert f'lauf.sh" {lauf} "$@"' in text
        assert "agent.py" not in text.replace(f"scripts/{lauf}.sh", "")

    def test_rahmen_fuehrt_keine_eigene_schrittliste(self):
        text = (ROOT / "scripts" / "lauf.sh").read_text(encoding="utf-8")
        aufrufe = re.findall(r"agent\.py\s+([\w-]+)", text)
        assert set(aufrufe) == {"ablauf"}


class TestDoku:
    def test_kein_laufweg_nennt_die_alte_folge(self):
        """Die feste Liste und ihre Sonderregel dürfen nicht zurückkommen."""
        text = (ROOT / "scripts" / "jobwatch.py").read_text(encoding="utf-8")
        assert "OPTIONAL_STEPS" not in text
        assert 'steps = [' not in text
