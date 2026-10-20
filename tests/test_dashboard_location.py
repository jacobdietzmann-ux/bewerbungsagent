"""Dashboard-Artefakt liegt in ``00_Dashboard``, der Code in ``04_Agent``.

Trennung von Code und Ausgabe: ``server.py`` und ``bewerbungsagent/dashboard.py``
bleiben in ``04_Agent`` (müssen importierbar sein), die erzeugte ``dashboard.html``
und die Starter liegen in ``00_Dashboard``.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from bewerbungsagent.config import Config


def test_standard_pfad_zeigt_nach_00_dashboard(tmp_path):
    from bewerbungsagent.config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["dashboard_file"] == "../00_Dashboard/dashboard.html"


def test_config_loest_relativ_zum_agent_root_auf(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"dashboard_file": "../00_Dashboard/dashboard.html"}),
                    encoding="utf-8")
    cfg = Config(path)
    assert cfg.dashboard_path.name == "dashboard.html"
    assert cfg.dashboard_path.parent.name == "00_Dashboard"


def test_server_liefert_den_neuen_pfad():
    import importlib.util
    import sys

    server = Path(__file__).resolve().parent.parent / "server.py"
    spec = importlib.util.spec_from_file_location("agent_server_paths", server)
    module = importlib.util.module_from_spec(spec)
    sys.modules["agent_server_paths"] = module
    spec.loader.exec_module(module)

    assert module.DASHBOARD_PATH == "/00_Dashboard/dashboard.html"
    # Das Artefakt liegt unter ROOT/00_Dashboard, der Code in SCRIPT_DIR.
    assert Path(module.DASHBOARD_OUT) == Path(module.ROOT) / "00_Dashboard" / "dashboard.html"


def test_launcher_verweisen_auf_den_neuen_pfad():
    root = Path(__file__).resolve().parent.parent
    ps1 = (root / "dashboard-oeffnen.ps1").read_text(encoding="utf-8")
    sh = (root / "dashboard-oeffnen.sh").read_text(encoding="utf-8")
    for text in (ps1, sh):
        assert "8766/00_Dashboard/dashboard.html" in text
        assert "8766/04_Agent/dashboard.html" not in text
    # Beide Starter finden den Server im Nachbarordner.
    assert "04_Agent" in ps1
    assert "04_Agent" in sh
