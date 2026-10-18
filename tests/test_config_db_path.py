"""Tests für die DB-Pfad-Auflösung inkl. ``BEWERBUNGSAGENT_DB``-Override."""

from __future__ import annotations

import json
from pathlib import Path

from bewerbungsagent.config import Config


def _write_config(tmp_path: Path, tmp_config: dict) -> Config:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(tmp_config), encoding="utf-8")
    return Config(path)


def test_db_path_defaults_to_data_dir(tmp_path, tmp_config):
    cfg = _write_config(tmp_path, tmp_config)
    assert cfg.db_path() == Path(tmp_config["data_dir"]) / "jobs.db"


def test_db_path_respects_env_override(tmp_path, tmp_config, monkeypatch):
    target = tmp_path / "local" / "jobs.db"
    monkeypatch.setenv("BEWERBUNGSAGENT_DB", str(target))
    cfg = _write_config(tmp_path, tmp_config)
    assert cfg.db_path() == target
