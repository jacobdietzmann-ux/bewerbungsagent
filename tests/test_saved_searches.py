"""Tests für gespeicherte Suchen (``saved_searches.py``)."""

from __future__ import annotations

import json

import pytest

from bewerbungsagent.saved_searches import (
    default_search,
    find_saved_search,
    load_saved_searches,
    save_saved_searches,
    to_definition,
)


@pytest.fixture
def config(tmp_path):
    from bewerbungsagent.config import Config

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "profile_json": "profil.json",
        "data_dir": str(tmp_path / "data"),
        "search": {
            "query_terms": ["Testingenieur", "ADAS Test"],
            "location": "München",
            "providers": ["stepstone", "duckduckgo"],
        },
    }, ensure_ascii=False), encoding="utf-8")
    return Config(path=cfg_path)


class TestDefaultSearch:
    def test_derived_from_config(self, config):
        d = default_search(config)
        assert d["name"] == "Standard"
        assert d["query_terms"] == ["Testingenieur", "ADAS Test"]
        assert d["location"] == "München"
        assert d["providers"] == ["stepstone", "duckduckgo"]


class TestLoadSave:
    def test_no_file_returns_default(self, config):
        assert load_saved_searches(config) == [default_search(config)]

    def test_roundtrip(self, config):
        searches = [
            {"name": "Test", "query_terms": ["Testingenieur"], "location": "München",
             "providers": ["stepstone"]},
            {"name": "Embedded", "query_terms": ["Embedded"], "location": "Garching",
             "providers": ["jobspy"]},
        ]
        save_saved_searches(config, searches)
        assert load_saved_searches(config) == searches

    def test_dict_wrapper_supported(self, config):
        path = config.data_dir / "saved_searches.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"searches": [
            {"name": "X", "query_terms": ["a"], "providers": []}]}), encoding="utf-8")
        names = [s["name"] for s in load_saved_searches(config)]
        assert names == ["X"]

    def test_corrupt_file_returns_default(self, config):
        path = config.data_dir / "saved_searches.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not valid json", encoding="utf-8")
        assert load_saved_searches(config) == [default_search(config)]


class TestFind:
    def test_find_exact_name(self, config):
        save_saved_searches(config, [
            {"name": "Test", "query_terms": ["x"], "providers": []},
        ])
        assert find_saved_search(config, "Test")["name"] == "Test"
        assert find_saved_search(config, "Unbekannt") is None


class TestToDefinition:
    def test_maps_override_fields(self):
        s = {"name": "T", "query_terms": ["a", "b"], "location": "München",
             "providers": ["stepstone"]}
        assert to_definition(s) == {
            "query_terms": ["a", "b"], "location": "München", "providers": ["stepstone"],
        }
