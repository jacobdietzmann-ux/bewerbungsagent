"""Tests für den Zustand der Such-Quellen (``provider_health.py``)."""

from __future__ import annotations

import json
from pathlib import Path

from bewerbungsagent import search as search_pkg
from bewerbungsagent.config import Config
from bewerbungsagent.profile import Profile
from bewerbungsagent.provider_health import (
    empty_entry,
    is_disabled,
    record,
    reset,
    set_enabled,
)

NOW = "2026-10-25T11:00:00"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


class TestRecord:
    def test_erfolg_zaehlt_funde_und_setzt_serie_zurueck(self):
        health = record({}, {"StepStone": {"gefunden": 12, "fehler": []}}, now=NOW)
        entry = health["StepStone"]
        assert entry["laeufe"] == 1
        assert entry["erfolge"] == 1
        assert entry["serie_fehler"] == 0
        assert entry["gefunden"] == 12
        assert entry["letzter_erfolg"] == NOW

    def test_null_funde_ohne_fehler_ist_erfolg(self):
        health = record({}, {"XING": {"gefunden": 0, "fehler": []}}, now=NOW)
        assert health["XING"]["erfolge"] == 1

    def test_fehler_in_folge_deaktiviert(self):
        health = {}
        for _ in range(3):
            health = record(health, {"jobspy": {"gefunden": 0, "fehler": ["HTTP 403"]}}, now=NOW)
        entry = health["jobspy"]
        assert entry["serie_fehler"] == 3
        assert entry["deaktiviert"] is True
        assert entry["deaktiviert_am"] == NOW
        assert is_disabled(health, "jobspy")

    def test_erfolg_zwischendurch_verhindert_abschaltung(self):
        health = record({}, {"x": {"gefunden": 0, "fehler": ["e1"]}}, now=NOW)
        health = record(health, {"x": {"gefunden": 4, "fehler": []}}, now=NOW)
        health = record(health, {"x": {"gefunden": 0, "fehler": ["e2"]}}, now=NOW)
        assert health["x"]["serie_fehler"] == 1
        assert health["x"]["deaktiviert"] is False

    def test_schwelle_konfigurierbar(self):
        health = record({}, {"x": {"gefunden": 0, "fehler": ["e"]}}, now=NOW, max_failures=1)
        assert health["x"]["deaktiviert"] is True

    def test_fehler_mit_treffern_ist_kein_ausfall(self):
        """StepStone: 2 von 28 Begriffen scheitern, 100 Stellen kommen an."""
        health = record({}, {"stepstone": {"gefunden": 100, "fehler": ["timeout"]}}, now=NOW)
        assert health["stepstone"]["erfolge"] == 1
        assert health["stepstone"]["serie_fehler"] == 0
        assert health["stepstone"]["deaktiviert"] is False

    def test_uebersprungene_quelle_zaehlt_nicht(self):
        health = record({"x": empty_entry()},
                        {"x": {"gefunden": 0, "fehler": [], "uebersprungen": "deaktiviert"}},
                        now=NOW)
        assert health["x"]["laeufe"] == 0
        assert health["x"]["deaktiviert"] is False


class TestManualSwitch:
    def test_aus_und_wieder_ein(self):
        health = record({}, {"x": {"gefunden": 0, "fehler": ["e"]}}, now=NOW)
        health = set_enabled(health, "x", False, now=NOW)
        assert is_disabled(health, "x")
        health = set_enabled(health, "x", True, now=NOW)
        assert not is_disabled(health, "x")
        assert health["x"]["serie_fehler"] == 0
        assert health["x"]["deaktiviert_am"] is None

    def test_reset_leert_die_historie(self):
        health = record({}, {"x": {"gefunden": 1, "fehler": []}}, now=NOW)
        assert reset(health) == {}


class TestSearchSkipsDisabled:
    def _config(self, tmp_path: Path) -> Config:
        (tmp_path / "data").mkdir(parents=True, exist_ok=True)
        (tmp_path / "profil-demo.json").write_text(
            (FIXTURES / "profil-demo.json").read_text(encoding="utf-8"), encoding="utf-8")
        cfg = {
            "profile_json": str(tmp_path / "profil-demo.json"),
            "data_dir": str(tmp_path / "data"),
            "output_dir": str(tmp_path / "output"),
            "search": {"enabled": True, "providers": ["arbeitnow"],
                       "query_terms": [], "location": "München"},
        }
        (tmp_path / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        return Config(tmp_path / "config.json")

    def _profile(self, tmp_path: Path) -> Profile:
        return Profile(json.loads((tmp_path / "profil-demo.json").read_text(encoding="utf-8")))

    def test_deaktivierte_quelle_wird_nicht_aufgerufen(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(search_pkg.arbeitnow, "search",
                            lambda **kw: calls.append(kw) or [])
        stats: dict = {}
        search_pkg.run_search(self._config(tmp_path), self._profile(tmp_path),
                              health={"arbeitnow": {"deaktiviert": True}}, stats=stats)
        assert calls == []
        assert stats["arbeitnow"]["uebersprungen"] == "deaktiviert"

    def test_aktive_quelle_zaehlt_funde(self, tmp_path, monkeypatch):
        job = {"titel": "Testingenieur (m/w/d)", "firma": "Beispiel GmbH",
               "url": "https://example.test/1", "quelle": "Arbeitnow"}
        monkeypatch.setattr(search_pkg.arbeitnow, "search", lambda **kw: [job])
        stats: dict = {}
        jobs, _errors, _rejected = search_pkg.run_search(
            self._config(tmp_path), self._profile(tmp_path), stats=stats)
        assert stats["arbeitnow"]["gefunden"] == 1
        assert stats["arbeitnow"]["fehler"] == []

    def test_fehler_landet_in_der_statistik(self, tmp_path, monkeypatch):
        def boom(**kw):
            raise RuntimeError("HTTP 403")
        monkeypatch.setattr(search_pkg.arbeitnow, "search", boom)
        stats: dict = {}
        _jobs, errors, _rejected = search_pkg.run_search(
            self._config(tmp_path), self._profile(tmp_path), stats=stats)
        assert stats["arbeitnow"]["fehler"]
        assert any("arbeitnow" in str(e) for e in errors)
