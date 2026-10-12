"""Tests für das SQLite-Backend (``db.py``) inkl. Provider-/Nutzer-Feldtrennung."""

from __future__ import annotations

import json

import pytest

from bewerbungsagent.db import USER_FIELDS, Store, _merge, _split


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "jobs.db")


def _app(**overrides):
    app = {
        "key": "https://example.test/job/1",
        "titel": "Test Engineer",
        "firma": "Acme GmbH",
        "ort": "München",
        "url": "https://example.test/job/1",
        "quelle": "LinkedIn",
        "score": 66,
        "fit_geschaetzt": "hoch",
        "matched_skills": ["python", "can"],
        "dokumente": {"lebenslauf_de": "../01_Bewerbungen/x/Lebenslauf.pdf"},
        "status": "research",
        "contact": "",
        "notes": "",
        "deleted": False,
        "sentAt": "",
    }
    app.update(overrides)
    return app


class TestSplitMerge:
    def test_user_fields_go_to_user_part(self):
        provider, user = _split(_app(status="sent", notes="hallo", contact="Frau X"))
        assert "status" not in provider
        assert "notes" not in provider
        assert user["status"] == "sent"
        assert user["notes"] == "hallo"

    def test_provider_fields_go_to_provider_part(self):
        provider, user = _split(_app())
        assert provider["titel"] == "Test Engineer"
        assert provider["score"] == 66
        assert "titel" not in user

    def test_key_is_never_in_either_part(self):
        provider, user = _split(_app())
        assert "key" not in provider
        assert "key" not in user

    def test_merge_roundtrip(self):
        app = _app(status="interview", notes="Runde 2")
        provider, user = _split(app)
        merged = _merge(app["key"], provider, user)
        assert merged == app

    def test_user_fields_are_the_editable_set(self):
        # Die Nutzer-Felder müssen exakt die Dashboard-Overlay-Felder umfassen.
        assert {"status", "contact", "notes", "deleted", "interviewDate",
                "statusChangedAt", "sentAt"} <= set(USER_FIELDS)


class TestStore:
    def test_roundtrip(self, store):
        store.save_state({"applications": [_app()], "updated": "2026-10-12T10:00:00+02:00"})
        loaded = store.load_state()
        assert len(loaded["applications"]) == 1
        a = loaded["applications"][0]
        assert a["titel"] == "Test Engineer"
        assert a["score"] == 66
        assert a["matched_skills"] == ["python", "can"]
        assert a["status"] == "research"

    def test_apply_overlay_only_touches_user_fields(self, store):
        store.save_state({"applications": [_app()], "updated": ""})
        store.apply_overlay({"https://example.test/job/1": {"status": "sent", "notes": "beworben"}})
        a = store.load_state()["applications"][0]
        assert a["status"] == "sent"
        assert a["notes"] == "beworben"
        # Provider-Felder unangetastet.
        assert a["score"] == 66
        assert a["titel"] == "Test Engineer"

    def test_apply_overlay_ignores_unknown_keys_and_non_editable(self, store):
        store.save_state({"applications": [_app()], "updated": ""})
        # Unbekannter Key + Versuch, ein Provider-Feld zu ändern.
        store.apply_overlay({
            "https://unbekannt.test": {"status": "sent"},
            "https://example.test/job/1": {"status": "interview", "score": 999},
        })
        a = store.load_state()["applications"][0]
        assert a["status"] == "interview"
        assert a["score"] == 66  # Provider-Feld NICHT verändert

    def test_get_overlay_returns_user_fields(self, store):
        store.save_state({"applications": [_app(status="docs", notes="notiz")], "updated": ""})
        overlay = store.get_overlay()
        assert overlay["https://example.test/job/1"]["status"] == "docs"
        assert overlay["https://example.test/job/1"]["notes"] == "notiz"
        assert "titel" not in overlay["https://example.test/job/1"]

    def test_save_state_upserts_existing_key(self, store):
        store.save_state({"applications": [_app(score=66)], "updated": ""})
        # Erneuter Scrape mit neuem Score, aber identischem Key.
        store.save_state({"applications": [_app(score=75, titel="Senior Test Engineer")], "updated": ""})
        loaded = store.load_state()
        assert len(loaded["applications"]) == 1
        assert loaded["applications"][0]["score"] == 75
        assert loaded["applications"][0]["titel"] == "Senior Test Engineer"

    def test_export_json_matches_load_state(self, store, tmp_path):
        store.save_state({"applications": [_app()], "updated": "2026-10-12T10:00:00+02:00"})
        snapshot = tmp_path / "state.json"
        store.export_json(snapshot)
        data = json.loads(snapshot.read_text(encoding="utf-8"))
        assert len(data["applications"]) == 1
        assert data["applications"][0]["titel"] == "Test Engineer"

    def test_store_reopen_is_idempotent(self, tmp_path):
        db = tmp_path / "jobs.db"
        Store(db).save_state({"applications": [_app()], "updated": ""})
        # Zweites Öffnen darf weder das Schema noch die Daten zerstören.
        s2 = Store(db)
        assert len(s2.load_state()["applications"]) == 1

    def test_empty_load(self, store):
        assert store.load_state() == {"applications": [], "updated": ""}
