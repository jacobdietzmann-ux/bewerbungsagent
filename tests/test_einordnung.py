"""Einordnung nach drei Regeln (Review 11.11.2026, Punkt 5).

1. Pendelweg über der Grenze: Research nur innerhalb der Kulanz und ab 65 %,
   sonst ausgeblendet.
2. Fit unter 65 %: ausgeblendet, außer bei ausdrücklich angeforderten Unterlagen.
3. Sonst sichtbar: bis 70 % Research, ab 71 % Unterlagen.

Ein ausgeblendeter Datensatz mit Fit-, Pendel- oder altem Research-Grund wird in
jedem Lauf nach denselben Regeln neu bewertet.
"""

from __future__ import annotations

import json

import pytest

from bewerbungsagent.config import Config
from bewerbungsagent.db import DELETE_FIT, DELETE_PENDEL, DELETE_RESEARCH, Store
from bewerbungsagent.pipeline import run_enrich


@pytest.fixture
def config(tmp_path, tmp_config) -> Config:
    tmp_config["max_pendelzeit_min"] = 30
    tmp_config["research_filter"] = {"commute_grace_min": 15}
    pfad = tmp_path / "config.json"
    pfad.write_text(json.dumps(tmp_config), encoding="utf-8")
    return Config(pfad)


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr("bewerbungsagent.pipeline.enrich_commute",
                        lambda apps, *_a, **_k: {"total": len(apps)})
    monkeypatch.setattr("bewerbungsagent.pipeline.enrich_salary", lambda apps: {})
    monkeypatch.setattr("bewerbungsagent.pipeline._generate_one", lambda *_a, **_k: [])


def _stelle(**mehr) -> dict:
    return {"key": "k1", "url": "https://example.test/k1", "firma": "Beispiel GmbH",
            "titel": "Testingenieur HiL (m/w/d)", "status": "research", "score": 67,
            "beschreibung": "Text", "pendel_modus": "Auto", "pendelzeit_min": 20, **mehr}


def _lauf(config, app) -> dict:
    Store(config.db_path()).save_state({"applications": [app]})
    run_enrich(config, None)
    return Store(config.db_path()).load_state()["applications"][0]


class TestFit:
    @pytest.mark.parametrize("fit", [65, 68, 70])
    def test_research_band_bleibt_sichtbar(self, config, fit):
        assert not _lauf(config, _stelle(score=fit)).get("deleted")

    @pytest.mark.parametrize("fit", [20, 50, 64])
    def test_unter_65_ausgeblendet(self, config, fit):
        app = _lauf(config, _stelle(score=fit))
        assert app["deleted"] is True
        assert app["deleted_code"] == DELETE_FIT

    def test_ohne_text_nennt_den_grund(self, config):
        app = _lauf(config, _stelle(score=12, beschreibung=""))
        assert app["deleted_reason"] == "FIT < 65 % (Text fehlt)"
        assert "text_fehlt" not in app

    def test_gewuenschte_unterlagen_bleiben_sichtbar(self, config):
        app = _lauf(config, _stelle(score=56, status="docs", unterlagen_gewuenscht=True,
                                    dokumente={"anschreiben_de": "x.pdf"}))
        assert not app.get("deleted")
        assert app["status"] == "docs"


class TestPendelweg:
    def test_innerhalb_der_kulanz_research(self, config):
        app = _lauf(config, _stelle(score=84, pendelzeit_min=41))
        assert not app.get("deleted")
        assert app["pendel_knapp"] is True

    def test_jenseits_der_kulanz_ausgeblendet(self, config):
        app = _lauf(config, _stelle(score=84, pendelzeit_min=50))
        assert app["deleted_code"] == DELETE_PENDEL

    def test_kulanz_braucht_65_prozent(self, config):
        app = _lauf(config, _stelle(score=60, pendelzeit_min=34))
        assert app["deleted_code"] == DELETE_PENDEL


class TestNeubewertung:
    @pytest.mark.parametrize("code", [DELETE_FIT, DELETE_PENDEL, DELETE_RESEARCH])
    def test_grund_entfallen_wird_eingeblendet(self, config, code):
        app = _lauf(config, _stelle(score=68, deleted=True, deleted_code=code,
                                    deleted_reason="alt"))
        assert not app.get("deleted")

    def test_grund_gilt_weiter(self, config):
        app = _lauf(config, _stelle(score=30, deleted=True, deleted_code=DELETE_FIT,
                                    deleted_reason="FIT < 50 %"))
        assert app["deleted"] is True
        assert app["deleted_reason"] == "FIT < 65 %"

    def test_nutzerentscheidung_bleibt(self, config):
        app = _lauf(config, _stelle(score=90, deleted=True, deleted_code="nutzer",
                                    deleted_reason="Im Dashboard entfernt"))
        assert app["deleted"] is True
