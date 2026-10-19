"""Tests für den Research-Filter.

Der Research-Bestand war mit 165 Einträgen unübersichtlich. Behalten werden nur
Funde, die eine Entscheidung tragen:

1. Fit im Fenster 60–70 % (knapp unter der Unterlagen-Schwelle von 65 %),
2. Fit ≥ 80 % (ein sehr guter Treffer ist kein Rauschen),
3. Pendelweg knapp über der Grenze (30 + 10 = 40 min) als zweite Chance.

Alles andere wird nur als ``deleted`` markiert — nichts wird gelöscht.
"""

from __future__ import annotations

import json

import pytest

from bewerbungsagent.config import Config
from bewerbungsagent.pipeline import _apply_research_filter, research_keep_reason

SETTINGS = {"fit_min": 60, "fit_max": 70, "keep_high_fit": 80, "commute_grace_min": 10}


def _app(**overrides) -> dict:
    app = {
        "key": "k",
        "firma": "Acme",
        "titel": "Testingenieur",
        "status": "research",
        "fit_pct": 65,
        "pendelzeit_min": 25,
    }
    app.update(overrides)
    return app


class TestKeepReason:
    @pytest.mark.parametrize("fit", [60, 65, 70])
    def test_fit_im_fenster(self, fit):
        assert research_keep_reason(_app(fit_pct=fit), 30, SETTINGS)

    @pytest.mark.parametrize("fit", [59, 71, 79])
    def test_fit_ausserhalb_des_fensters(self, fit):
        assert research_keep_reason(_app(fit_pct=fit), 30, SETTINGS) == ""

    @pytest.mark.parametrize("fit", [80, 95])
    def test_sehr_hoher_fit_bleibt(self, fit):
        assert research_keep_reason(_app(fit_pct=fit), 30, SETTINGS)

    @pytest.mark.parametrize("km", [31, 35, 40])
    def test_knapp_ueber_der_pendelgrenze(self, km):
        app = _app(fit_pct=10, pendelzeit_min=km)
        assert research_keep_reason(app, 30, SETTINGS)

    def test_deutlich_ueber_der_pendelgrenze(self):
        app = _app(fit_pct=10, pendelzeit_min=41)
        assert research_keep_reason(app, 30, SETTINGS) == ""

    def test_ohne_pendelweg(self):
        app = _app(fit_pct=10, pendelzeit_min=None)
        assert research_keep_reason(app, 30, SETTINGS) == ""


def _config(tmp_path, **research) -> Config:
    data = {
        "data_dir": str(tmp_path / "data"),
        "profile_json": str(tmp_path / "p.json"),
        "research_filter": {"enabled": True, **research},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return Config(path)


class TestApplyFilter:
    def test_entfernt_nur_ausserhalb(self, tmp_path):
        apps = [
            _app(key="keep", fit_pct=65),
            _app(key="high", fit_pct=90),
            _app(key="near", fit_pct=10, pendelzeit_min=38),
            _app(key="drop", fit_pct=55),
        ]
        stats = _apply_research_filter(_config(tmp_path), apps)

        by_key = {a["key"]: a for a in apps}
        assert not by_key["keep"].get("deleted")
        assert not by_key["high"].get("deleted")
        assert not by_key["near"].get("deleted")
        assert by_key["drop"]["deleted"] is True
        assert by_key["drop"]["deleted_reason"].startswith("research-kriterium")
        assert stats == {"enabled": True, "kept": 3, "removed": 1, "restored": 0}

    def test_dokumentierte_stelle_bleibt(self, tmp_path):
        app = _app(fit_pct=10, dokumente={"anschreiben_de": "x.pdf"})
        _apply_research_filter(_config(tmp_path), [app])
        assert not app.get("deleted")

    def test_nicht_research_unangetastet(self, tmp_path):
        app = _app(status="sent", fit_pct=10)
        _apply_research_filter(_config(tmp_path), [app])
        assert not app.get("deleted")

    def test_ausblenden_ist_umkehrbar(self, tmp_path):
        """Ändert sich der Fit, kommt die Stelle beim nächsten Lauf zurück."""
        app = _app(fit_pct=55)
        config = _config(tmp_path)
        _apply_research_filter(config, [app])
        assert app["deleted"] is True

        app["fit_pct"] = 66
        stats = _apply_research_filter(config, [app])
        assert not app.get("deleted")
        assert stats["restored"] == 1

    def test_abschaltbar(self, tmp_path):
        data = {"data_dir": str(tmp_path / "d"), "profile_json": "p.json",
                "research_filter": {"enabled": False}}
        path = tmp_path / "config.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        app = _app(fit_pct=10)
        stats = _apply_research_filter(Config(path), [app])
        assert not app.get("deleted")
        assert stats["enabled"] is False

    def test_fenster_konfigurierbar(self, tmp_path):
        app = _app(fit_pct=55)
        _apply_research_filter(_config(tmp_path, fit_min=50, fit_max=70), [app])
        assert not app.get("deleted")
