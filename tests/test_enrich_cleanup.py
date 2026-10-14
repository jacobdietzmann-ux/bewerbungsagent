"""Tests für die Bereinigung des Bestands (``run_enrich``).

Regel: Stellen, für die bereits Unterlagen erzeugt wurden, sind eine bewusste
Entscheidung und werden **nicht** wegen eines niedrigen FIT ausgeblendet.
Die harte Pendelweg-Grenze gilt weiterhin für alle.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bewerbungsagent.config import Config
from bewerbungsagent.db import Store
from bewerbungsagent.pipeline import run_enrich


def _job(key: str, **over) -> dict:
    app = {
        "key": key,
        "firma": "Beispiel GmbH",
        "titel": "Testingenieur",
        "url": f"https://example.test/{key}",
        "status": "docs",
        "score": 30,
        "pendel_modus": "Auto",
        "pendelzeit_min": 25,
        "pendeldistanz_km": 20.0,
    }
    app.update(over)
    return app


@pytest.fixture
def config(tmp_path: Path, tmp_config: dict) -> Config:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(tmp_config), encoding="utf-8")
    return Config(path)


@pytest.fixture(autouse=True)
def _kein_netzwerk(monkeypatch):
    """Pendelweg/Gehalt nicht neu berechnen — der Test setzt die Werte selbst.

    ``run_enrich`` würde sonst per Nominatim/OSRM arbeiten und die vorgegebene
    Pendelzeit überschreiben (ohne ``ort`` sogar auf ``None``).
    """
    monkeypatch.setattr("bewerbungsagent.pipeline.enrich_commute",
                        lambda apps, data_dir: {"total": len(apps)})
    monkeypatch.setattr("bewerbungsagent.pipeline.enrich_salary",
                        lambda apps: {"kept": 0, "estimated": 0})


def _run(config: Config, apps: list[dict]) -> dict:
    Store(config.db_path()).save_state({"applications": apps})
    return run_enrich(config, None)


class TestDocumentedJobsKeepVisible:
    def test_niedriger_fit_ohne_unterlagen_wird_ausgeblendet(self, config):
        result = _run(config, [_job("ohne-unterlagen")])
        assert result["deleted_fit_under_50"] == 1

    def test_niedriger_fit_mit_unterlagen_bleibt_sichtbar(self, config):
        """Kernregel: erzeugte Dokumente = bewusste Entscheidung."""
        apps = [_job("mit-unterlagen", dokumente={"de": {"anschreiben": "x.pdf"}})]
        result = _run(config, apps)
        assert result["deleted_fit_under_50"] == 0
        state = Store(config.db_path()).load_state()
        assert not state["applications"][0].get("deleted")

    def test_bereits_ausgeblendete_dokumentierte_werden_zurueckgeholt(self, config):
        """Einmalige Reparatur: frühere Läufe haben sie allein wegen FIT versteckt."""
        apps = [_job("alt", deleted=True, dokumente={"de": {}})]
        result = _run(config, apps)
        assert result["restored_documented"] == 1
        state = Store(config.db_path()).load_state()
        assert not state["applications"][0].get("deleted")
        assert not state["applications"][0].get("deleted_reason")

    def test_pendelweg_bleibt_harte_grenze(self, config):
        """Auch mit Unterlagen: zu weiter Pendelweg bleibt ausgeblendet."""
        apps = [_job("weit", pendelzeit_min=200, dokumente={"de": {}})]
        result = _run(config, apps)
        state = Store(config.db_path()).load_state()
        assert state["applications"][0].get("deleted") is True
        assert "Pendelweg" in state["applications"][0].get("deleted_reason", "")
        assert result["restored_documented"] == 0

    def test_versendete_stellen_werden_nicht_angefasst(self, config):
        apps = [_job("gesendet", status="sent", score=5)]
        result = _run(config, apps)
        assert result["deleted_fit_under_50"] == 0
        state = Store(config.db_path()).load_state()
        assert not state["applications"][0].get("deleted")
