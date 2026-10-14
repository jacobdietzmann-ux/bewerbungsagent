"""Tests für transparente Pendelweg-Fehler."""

from __future__ import annotations

from bewerbungsagent import commute


def test_failed_route_is_marked_as_not_determined(tmp_path, monkeypatch):
    class Geocoder:
        def __init__(self, _cache_path):
            pass

        def geocode(self, _query):
            return {"lat": 48.0, "lon": 11.0, "display_name": "Test"}

        def save(self):
            pass

    monkeypatch.setattr(commute, "_Geocoder", Geocoder)
    monkeypatch.setattr(commute, "_route_driving", lambda *_args: None)
    job = {"ort": "Beispielstadt"}

    stats = commute.enrich_commute([job], tmp_path, "Musterstraße 1, 12345 Musterstadt")

    assert stats["failed"] == 1
    assert job["pendel_modus"] == "Nicht ermittelt"
    assert job["pendelzeit_min"] is None
    assert job["pendeldistanz_km"] is None


def test_missing_home_address_raises_clear_error(tmp_path):
    """Ohne konfigurierte Adresse darf nicht still gerechnet werden."""
    import pytest
    with pytest.raises(RuntimeError, match="home_address"):
        commute.enrich_commute([], tmp_path, "")
