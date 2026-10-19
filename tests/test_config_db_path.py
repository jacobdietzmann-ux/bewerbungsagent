"""Tests für die DB-Pfad-Auflösung inkl. ``BEWERBUNGSAGENT_DB``-Override."""

from __future__ import annotations

import json
from pathlib import Path

from bewerbungsagent.config import Config


def _write_config(tmp_path: Path, tmp_config: dict) -> Config:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(tmp_config), encoding="utf-8")
    return Config(path)


def test_db_path_defaults_to_data_dir(tmp_path, tmp_config, monkeypatch):
    # Die Env-Variable ist auf diesem Rechner dauerhaft gesetzt; für den
    # Standard-Pfad muss sie im Test explizit fehlen.
    monkeypatch.delenv("BEWERBUNGSAGENT_DB", raising=False)
    cfg = _write_config(tmp_path, tmp_config)
    assert cfg.db_path() == Path(tmp_config["data_dir"]) / "jobs.db"


def test_db_path_respects_env_override(tmp_path, tmp_config, monkeypatch):
    """Der Override gilt für die produktive Config im Agent-Root."""
    from bewerbungsagent.config import AGENT_ROOT

    target = tmp_path / "local" / "jobs.db"
    monkeypatch.setenv("BEWERBUNGSAGENT_DB", str(target))
    # Produktive Config: kein expliziter Pfad -> AGENT_ROOT/config.json
    cfg = Config()
    assert cfg.path.resolve() == (AGENT_ROOT / "config.json").resolve()
    assert cfg.db_path() == target


def test_explizite_config_ignoriert_den_env_override(tmp_path, tmp_config, monkeypatch):
    """Regression (Datenverlust): Tests/Skripte mit eigener config.json dürfen
    niemals auf die produktive DB umgeleitet werden.

    ``BEWERBUNGSAGENT_DB`` ist auf diesem Rechner dauerhaft gesetzt. Griff der
    Override auch hier, schrieb ``Store(config.db_path()).save_state(...)`` aus
    einem Testlauf in die echte Datenbank — ``save_state`` ersetzt den Bestand
    vollständig, 342 Bewerbungen wurden zu einem Testeintrag.
    """
    target = tmp_path / "local" / "jobs.db"
    monkeypatch.setenv("BEWERBUNGSAGENT_DB", str(target))
    cfg = _write_config(tmp_path, tmp_config)
    assert cfg.db_path() == Path(tmp_config["data_dir"]) / "jobs.db"
    assert cfg.db_path() != target
