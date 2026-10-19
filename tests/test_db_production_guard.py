"""Schutzsperre: Tests dürfen nicht in die produktive Datenbank schreiben.

Vorfall vom 19.10.2026: ``BEWERBUNGSAGENT_DB`` war dauerhaft gesetzt und der
Pfad-Override griff auch für Test-Configs. Ein Testlauf schrieb mit
``save_state`` (Voll-Replace) in die echte DB — 342 Bewerbungen wurden durch
einen Testeintrag ersetzt.
"""

from __future__ import annotations

import pytest

from bewerbungsagent.db import Store


def test_store_verweigert_produktions_db_im_test(tmp_path, monkeypatch):
    prod = tmp_path / "prod" / "jobs.db"
    monkeypatch.setenv("BEWERBUNGSAGENT_DB", str(prod))
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_guard.py::test")
    with pytest.raises(RuntimeError, match="produktive Datenbank"):
        Store(prod)


def test_store_erlaubt_eigene_db_im_test(tmp_path, monkeypatch):
    monkeypatch.setenv("BEWERBUNGSAGENT_DB", str(tmp_path / "prod" / "jobs.db"))
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_guard.py::test")
    store = Store(tmp_path / "test.db")
    assert store.load_state() == {"applications": [], "updated": ""}


def test_store_ohne_produktions_override_bleibt_offen(tmp_path, monkeypatch):
    monkeypatch.delenv("BEWERBUNGSAGENT_DB", raising=False)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_guard.py::test")
    store = Store(tmp_path / "test.db")
    assert store.load_state()["applications"] == []
