"""Nutzerfelder überleben einen laufenden Hintergrundprozess.

Ein Lauf (Wochenlauf/Graph) lädt den Zustand, arbeitet minutenlang und schreibt
am Ende zurück. Änderungen, die der Nutzer währenddessen im Dashboard macht,
wurden dabei überschrieben — ein bereits versendeter Bewerbungseintrag fiel
dadurch auf ``docs`` zurück.

Deshalb gilt beim Voll-Schreibvorgang: die DB ist die frischere Quelle für
Felder, die der Lauf nicht selbst setzt.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bewerbungsagent.db import Store


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "jobs.db")


def _app(key: str, **over) -> dict:
    app = {"key": key, "firma": "Beispiel GmbH", "titel": "Testingenieur", "status": "neu"}
    app.update(over)
    return app


class TestForeignFieldsSurviveStaleWrite:
    """``sentAt``/Notizen/Kontakt gehören dem Nutzer, nicht dem Lauf."""

    @pytest.mark.parametrize("field, value", [
        ("sentAt", "2026-10-14T18:30:00"),
        ("notes", "Ansprechpartner: Frau Meier"),
        ("contact", "karriere@stark-defence.de"),
        ("interviewDate", "2026-11-03"),
        ("statusChangedAt", "2026-10-14T18:30:00"),
    ])
    def test_feld_bleibt_erhalten(self, store: Store, field: str, value: str):
        store.save_state({"applications": [_app("a", **{field: value})]})
        # Der Lauf kennt die Änderung nicht (veralteter In-Memory-Zustand).
        store.save_state({"applications": [_app("a", status="docs")]})
        assert store.load_state()["applications"][0].get(field) == value

    def test_leere_werte_ueberschreiben_nichts(self, store: Store):
        store.save_state({"applications": [_app("a", notes="bleibt")]})
        store.save_state({"applications": [_app("a", notes="")]})
        assert store.load_state()["applications"][0].get("notes") == "bleibt"


class TestHandledStatusIsNotDowngraded:
    """Was der Nutzer als erledigt markiert hat, stuft ein Lauf nicht zurück."""

    @pytest.mark.parametrize("status", ["sent", "followup", "interview", "rejected"])
    def test_status_bleibt(self, store: Store, status: str):
        store.save_state({"applications": [_app("a", status=status)]})
        store.save_state({"applications": [_app("a", status="docs")]})
        assert store.load_state()["applications"][0]["status"] == status

    def test_normaler_fortschritt_funktioniert_weiter(self, store: Store):
        """``neu`` → ``docs`` ist der legitime Weg der Dokumenterzeugung."""
        store.save_state({"applications": [_app("a", status="neu")]})
        store.save_state({"applications": [_app("a", status="docs")]})
        assert store.load_state()["applications"][0]["status"] == "docs"

    def test_nutzer_kann_status_zuruecksetzen(self, store: Store):
        """Über das Dashboard (``apply_overlay``) bleibt alles möglich."""
        store.save_state({"applications": [_app("a", status="sent", sentAt="2026-10-14T18:30:00")]})
        store.apply_overlay({"a": {"status": "docs", "sentAt": None}})
        assert store.load_state()["applications"][0]["status"] == "docs"

    def test_neue_eintraege_sind_unbetroffen(self, store: Store):
        store.save_state({"applications": [_app("a", status="sent")]})
        store.save_state({"applications": [_app("a", status="sent"), _app("b", status="docs")]})
        stati = {a["key"]: a["status"] for a in store.load_state()["applications"]}
        assert stati == {"a": "sent", "b": "docs"}
