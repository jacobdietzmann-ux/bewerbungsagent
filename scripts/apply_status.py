"""Setzt Statusänderungen aus einer JSON-Datei (Aufruf aus dem Mailcheck).

Die Datei enthält eine Liste von Einträgen mit ``key``, ``status``,
``statusChangedAt`` und optional ``notes``. Geschrieben wird über
``Store.apply_overlay`` — also ausschließlich in die Nutzerfelder, ohne die
Provider-Daten anzufassen.

Aufruf (Projekt-venv, cwd = Projektordner):
    python scripts/apply_status.py /pfad/zu/status.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from bewerbungsagent.config import Config  # noqa: E402
from bewerbungsagent.db import Store  # noqa: E402


def main(path: str) -> int:
    daten = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(daten, list) or not daten:
        print(json.dumps({"applied": 0, "reason": "leer"}))
        return 0
    store = Store(Config(PROJECT / "config.json").db_path())
    overlay = {}
    for e in daten:
        key = e.get("key")
        if not key:
            continue
        eintrag = {"status": e["status"]}
        if e.get("statusChangedAt"):
            eintrag["statusChangedAt"] = e["statusChangedAt"]
        if "notes" in e:
            eintrag["notes"] = e["notes"]
        overlay[key] = eintrag
    store.apply_overlay(overlay)
    print(json.dumps({"applied": len(overlay)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
