"""Tests für die Firmensitz-Überschreibung (``commute.office_overrides``).

Hintergrund: Die Anzeige nennt oft nur die Zentrale („München"), das Büro liegt
aber woanders — STARK Defence sitzt in Maisach. Ohne Überschreibung wird der
Pendelweg zu kurz berechnet und eine zu weit entfernte Stelle rutscht durch die
``max_pendelzeit_min``-Grenze.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from bewerbungsagent import commute


class TestOfficeOverride:
    def test_exakter_firmenname(self):
        assert commute.office_override("STARK Defence", {"STARK Defence": "Maisach"}) == "Maisach"

    def test_gross_kleinschreibung_egal(self):
        assert commute.office_override("stark defence", {"STARK Defence": "Maisach"}) == "Maisach"

    def test_unbekannte_firma(self):
        assert commute.office_override("Acme GmbH", {"STARK Defence": "Maisach"}) == ""

    def test_ohne_ueberschreibungen(self):
        assert commute.office_override("STARK Defence", None) == ""
        assert commute.office_override("STARK Defence", {}) == ""

    def test_leere_firma(self):
        assert commute.office_override("", {"STARK Defence": "Maisach"}) == ""


def test_enrich_commute_setzt_firmensitz(tmp_path, monkeypatch):
    """Die Ortsangabe der Anzeige wird durch den echten Firmensitz ersetzt."""
    job = {"firma": "STARK Defence", "ort": "München"}

    monkeypatch.setattr(commute._Geocoder, "geocode",
                        lambda self, q: {"lat": 48.0, "lon": 11.0, "display_name": q})
    monkeypatch.setattr(commute, "_route_driving", lambda *a, **k: (42.0, 37))

    commute.enrich_commute([job], tmp_path, "Musterstraße 1, 12345 Musterstadt",
                           None, {"STARK Defence": "Maisach"})

    assert job["ort"] == "Maisach"
    assert job["pendelzeit_min"] == 37
    assert job["pendeldistanz_km"] == 42.0


def test_enrich_commute_ohne_ueberschreibung_behaelt_ort(tmp_path, monkeypatch):
    job = {"firma": "STARK Defence", "ort": "München"}

    monkeypatch.setattr(commute._Geocoder, "geocode",
                        lambda self, q: {"lat": 48.0, "lon": 11.0, "display_name": q})
    monkeypatch.setattr(commute, "_route_driving", lambda *a, **k: (18.0, 25))

    commute.enrich_commute([job], tmp_path, "Musterstraße 1, 12345 Musterstadt")

    assert job["ort"] == "München"
