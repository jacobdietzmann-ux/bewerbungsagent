"""Code und Daten getrennt: ``BEWERBUNGSAGENT_HOME`` (ADR-057).

Ohne Variable bleibt alles wie zuvor (Daten neben dem Code). Mit Variable zeigen
``Config``, Server, ``jobwatch`` und die Eval-Skripte auf den Datenordner, der
Code kommt weiter aus dem Checkout. Geprüft wird in eigenen Prozessen, weil die
Pfade beim Import feststehen.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_PRUEFUNG = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import server
from bewerbungsagent.config import AGENT_ROOT, CODE_ROOT, Config
from eval import labels
import importlib.util
spec = importlib.util.spec_from_file_location("jw", sys.argv[1] + "/scripts/jobwatch.py")
jw = importlib.util.module_from_spec(spec); spec.loader.exec_module(jw)
c = Config()
print(json.dumps({
    "agent_root": str(AGENT_ROOT), "code_root": str(CODE_ROOT),
    "config": str(c.path), "data_dir": str(c.data_dir), "db": str(c.db_path()),
    "bewerbungen": str(c.bewerbungen_dir),
    "server_root": server.ROOT, "server_state": server.STATE_FILE,
    "server_src": server.DASHBOARD_SRC, "gesperrt": list(server._BLOCKED_PREFIXES),
    "jobwatch_daten": str(jw.DATA), "jobwatch_code": str(jw.CODE_DIR),
    "labels": str(labels.DEFAULT_LABELS_CSV),
}))
"""


def _pfade(tmp_path: Path, home: Path | None) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in ("BEWERBUNGSAGENT_HOME", "BEWERBUNGSAGENT_DB", "PYTEST_CURRENT_TEST")}
    env["PYTHONPATH"] = str(ROOT)
    if home is not None:
        env["BEWERBUNGSAGENT_HOME"] = str(home)
    ausgabe = subprocess.run([sys.executable, "-c", _PRUEFUNG, str(ROOT)], env=env,
                             cwd=tmp_path, capture_output=True, text=True, check=True)
    return json.loads(ausgabe.stdout.strip().splitlines()[-1])


@pytest.fixture
def datenordner(tmp_path) -> Path:
    """``2026/04_Agent`` mit einer config.json, die relative Pfade nutzt."""
    home = tmp_path / "2026" / "04_Agent"
    (home / "data").mkdir(parents=True)
    (home / "config.json").write_text(json.dumps({
        "data_dir": "data", "bewerbungen_dir": "../01_Bewerbungen",
        "dashboard_file": "../00_Dashboard/dashboard.html",
    }), encoding="utf-8")
    return home


def test_mit_variable_zeigt_alles_auf_den_datenordner(tmp_path, datenordner):
    p = _pfade(tmp_path, datenordner)
    home = datenordner.resolve()
    assert Path(p["agent_root"]) == home
    assert Path(p["code_root"]) == ROOT
    assert Path(p["config"]) == home / "config.json"
    assert Path(p["data_dir"]) == home / "data"
    assert Path(p["db"]) == home / "data" / "jobs.db"
    # Relative Pfade aus der config.json gelten weiter relativ zum Datenordner.
    assert Path(p["bewerbungen"]) == home.parent / "01_Bewerbungen"
    assert Path(p["server_root"]) == home.parent
    assert Path(p["server_state"]) == home / "data" / "state.json"
    assert Path(p["labels"]) == home / "eval" / "labels.csv"
    assert Path(p["jobwatch_daten"]) == home / "data"
    # Der Code bleibt im Checkout.
    assert Path(p["server_src"]) == ROOT / "bewerbungsagent" / "dashboard.py"
    assert Path(p["jobwatch_code"]) == ROOT


def test_server_sperrt_den_datenordner_auch_unter_anderem_namen(tmp_path):
    home = tmp_path / "Bewerbung" / "Agentdaten"
    home.mkdir(parents=True)
    gesperrt = _pfade(tmp_path, home)["gesperrt"]
    assert "agentdaten/config" in gesperrt and "agentdaten/data/" in gesperrt
    assert "04_agent/config" in gesperrt


def test_ohne_variable_wie_bisher(tmp_path):
    p = _pfade(tmp_path, None)
    assert Path(p["agent_root"]) == ROOT
    assert Path(p["config"]) == ROOT / "config.json"
    assert Path(p["server_root"]) == ROOT.parent
    assert Path(p["labels"]) == ROOT / "eval" / "labels.csv"


def test_testlauf_sieht_die_variable_nicht():
    """``conftest`` entfernt sie, sonst läse die Suite echte Daten."""
    from bewerbungsagent.config import AGENT_ROOT
    assert "BEWERBUNGSAGENT_HOME" not in os.environ
    assert AGENT_ROOT == ROOT


def test_jobwatch_ruft_agent_py_aus_dem_checkout(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("jobwatch_daten", ROOT / "scripts" / "jobwatch.py")
    jw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(jw)  # type: ignore[union-attr]
    monkeypatch.setattr(jw, "RUN_OUTPUT", tmp_path / "lauf.log")
    aufrufe = []
    monkeypatch.setattr(jw.subprocess, "run", lambda befehl, **k: aufrufe.append((befehl, k))
                        or subprocess.CompletedProcess(befehl, 0))
    jw.run_pipeline()
    befehl, optionen = aufrufe[0]
    assert Path(befehl[1]) == ROOT / "agent.py"
    assert optionen["env"]["PYTHONPATH"] == str(ROOT)


def test_einstiegsskripte_sind_installierbar():
    """Eine editierbare Installation findet sonst nur die Pakete."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'py-modules = ["agent", "fetch_descriptions", "server"]' in text
