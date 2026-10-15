"""Tests für den CLI-Einstieg (``agent.py``).

Schwerpunkt: Ein frischer Klon darf beim ersten ``match`` keine nackte
Traceback werfen, sondern muss eine handlungsfähige Meldung ausgeben.
"""

from __future__ import annotations

import json
from pathlib import Path

import agent


def _config(tmp_path: Path, profile_json: str) -> Path:
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "profile_json": profile_json,
        "data_dir": str(tmp_path / "data"),
        "output_dir": str(tmp_path / "output"),
        "dashboard_file": "dashboard.html",
        "search": {"enabled": False, "providers": [], "location": "München",
                   "query_terms": []},
        "documents": {"languages": ["de"], "accent_color": "#000000",
                      "min_fit_for_generation": "hoch"},
    }), encoding="utf-8")
    return cfg


def test_missing_profile_prints_friendly_hint(tmp_path, capsys):
    """Regression: früher endete das mit ``FileNotFoundError``-Traceback."""
    cfg = _config(tmp_path, str(tmp_path / "gibt-es-nicht.json"))
    code = agent.main(["--config", str(cfg), "match"])
    assert code == 1
    out = capsys.readouterr().out
    assert "Profil nicht gefunden" in out
    assert "config.example.json" in out
    assert "Traceback" not in out


def test_config_flag_is_accepted(tmp_path):
    """``--config`` muss vor dem Unterbefehl stehen und akzeptiert werden."""
    cfg = _config(tmp_path, str(tmp_path / "x.json"))
    # profile fehlt → exit 1, aber die Meldung beweist, dass --config ankam.
    assert agent.main(["--config", str(cfg), "match"]) == 1
