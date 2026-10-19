"""Tests für den Geocoder-Cache.

Ein ``None`` bedeutet „hat nicht geklappt", nicht „gibt es nicht". Wurde es
mitgeschrieben, blieb der Ort für immer unauflösbar: ``geocode`` gab den
gespeicherten Fehlschlag zurück, ohne erneut zu fragen. So standen Gilching,
Poing und Erding dauerhaft auf „Nicht ermittelbar", obwohl sie auflösbar sind.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bewerbungsagent.commute import _Geocoder


@pytest.fixture
def cache_datei(tmp_path: Path) -> Path:
    return tmp_path / "geocode_cache.json"


class TestFehlschlaegeWerdenNichtGespeichert:
    def test_fehlschlag_landet_nicht_auf_der_platte(self, cache_datei, monkeypatch):
        g = _Geocoder(cache_datei)
        monkeypatch.setattr("bewerbungsagent.commute.requests.get",
                            lambda *a, **k: _Antwort(200, []))
        assert g.geocode("Nirgendwo") is None
        g.save()
        assert "nirgendwo" not in json.loads(cache_datei.read_text())

    def test_treffer_bleibt_gespeichert(self, cache_datei):
        cache_datei.write_text(json.dumps({"kaufering": {"lat": 48.0, "lon": 10.8}}))
        g = _Geocoder(cache_datei)
        g.save()
        assert json.loads(cache_datei.read_text())["kaufering"]["lat"] == 48.0

    def test_alte_fehlschlaege_werden_beim_speichern_entfernt(self, cache_datei):
        """Der Altbestand wird so automatisch bereinigt und neu versucht."""
        cache_datei.write_text(json.dumps({
            "gilching": {"lat": 48.1, "lon": 11.3},
            "kaufering nahe munchen": None,
        }))
        g = _Geocoder(cache_datei)
        g.save()
        gespeichert = json.loads(cache_datei.read_text())
        assert "gilching" in gespeichert
        assert "kaufering nahe munchen" not in gespeichert

    def test_im_lauf_wird_nicht_zweimal_gefragt(self, cache_datei, monkeypatch):
        """Innerhalb eines Laufs bleibt der Fehlschlag im Speicher-Cache."""
        aufrufe = []

        class _Antwort:
            status_code = 200

            def json(self):
                return []

        def fake_get(*a, **k):
            aufrufe.append(1)
            return _Antwort()

        monkeypatch.setattr("bewerbungsagent.commute.requests.get", fake_get)
        g = _Geocoder(cache_datei)
        monkeypatch.setattr(g, "_throttle", lambda: None)
        assert g.geocode("Nirgendwo") is None
        assert g.geocode("Nirgendwo") is None
        assert len(aufrufe) == 1


class _Antwort:
    def __init__(self, status: int, daten: list):
        self.status_code = status
        self._daten = daten

    def json(self):
        return self._daten
