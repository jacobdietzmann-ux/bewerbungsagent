"""Tests für transparente Pendelweg-Fehler."""

from __future__ import annotations

from typing import ClassVar

from bewerbungsagent import commute


def test_failed_route_is_marked_as_not_determined(tmp_path, monkeypatch):
    class Geocoder:
        def __init__(self, _cache_path, _agent=None):
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


def test_user_agent_uses_contact_email_only_when_configured():
    """Die Kontaktadresse kommt aus der privaten Config, nicht aus dem Code."""
    assert "example.com" in commute.user_agent("ich@example.com")
    assert "example.com" not in commute.user_agent("")
    assert commute.user_agent("").startswith("Bewerbungsagent/1.0")


class _WackelGeocoder:
    """Liefert die Antworten der Reihe nach; ``None`` ohne Cache-Eintrag = Störung."""

    antworten: ClassVar[list] = []
    aufrufe = 0

    def __init__(self, _cache_path, _agent=None):
        self.cache: dict = {}

    def geocode(self, query):
        type(self).aufrufe += 1
        antwort = type(self).antworten.pop(0)
        if antwort == "unbekannt":
            self.cache[commute.normalize(query)] = None
            return None
        return antwort

    def save(self):
        pass


def _wackel(monkeypatch, antworten):
    _WackelGeocoder.antworten = list(antworten)
    _WackelGeocoder.aufrufe = 0
    monkeypatch.setattr(commute, "_Geocoder", _WackelGeocoder)
    monkeypatch.setattr(commute, "_HOME_RETRY_PAUSEN", (0, 0))
    monkeypatch.setattr(commute, "_route_driving", lambda *_a: None)


def test_wohnadresse_stoerung_bricht_den_lauf_nicht_ab(tmp_path, monkeypatch):
    """Nominatim nicht erreichbar → Pendelweg auslassen, nicht abbrechen.

    So endete der Tageslauf am 20.10. und 16.11.2026 nach dem Hochfahren.
    """
    _wackel(monkeypatch, [None, None, None])
    job = {"ort": "Beispielstadt", "pendelzeit_min": 25, "pendel_modus": "Auto"}

    stats = commute.enrich_commute([job], tmp_path, "Musterstraße 1, 12345 Musterstadt")

    assert stats["home_unavailable"] is True
    assert _WackelGeocoder.aufrufe == 3
    # Gespeicherte Werte bleiben stehen, der nächste Lauf rechnet nach.
    assert job["pendelzeit_min"] == 25
    assert job["pendel_modus"] == "Auto"


def test_wohnadresse_zweiter_versuch_reicht(tmp_path, monkeypatch):
    home = {"lat": 48.0, "lon": 11.0, "display_name": "Test"}
    _wackel(monkeypatch, [None, home, home])

    stats = commute.enrich_commute([{"ort": "Beispielstadt"}], tmp_path,
                                   "Musterstraße 1, 12345 Musterstadt")

    assert "home_unavailable" not in stats
    assert stats["failed"] == 1   # Route per Stub nicht ermittelt


def test_unbekannte_wohnadresse_bleibt_ein_klarer_fehler(tmp_path, monkeypatch):
    """Kennt Nominatim die Adresse nicht, hilft kein Wiederholen."""
    import pytest
    _wackel(monkeypatch, ["unbekannt"])
    with pytest.raises(RuntimeError, match="home_address"):
        commute.enrich_commute([], tmp_path, "Gibtsnicht 1, 00000 Nirgendwo")
    assert _WackelGeocoder.aufrufe == 1
