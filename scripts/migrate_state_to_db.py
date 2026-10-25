#!/usr/bin/env python3
"""Einmalige Migration: ``data/state.json`` → SQLite (``data/jobs.db``).

- Legt das Schema per Alembic an (``db.Store`` erledigt das automatisch).
- Sichert die alte ``state.json`` vorher als ``state.pre-sqlite-<stamp>.json``.
- Importiert alle Bewerbungen (Provider-/Nutzer-Felder werden getrennt gespeichert).
- Schreibt zum Abschluss einen abgeleiteten JSON-Snapshot zurück nach ``state.json``
  (bisync-sicherer Export, damit das bestehende Backup weiter funktioniert).

Idempotent: läuft die DB bereits mit Einträgen, wird nichts überschrieben.

Nutzung:
    python scripts/migrate_state_to_db.py [AGENT_DIR]
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Agent-Root = Ordner, der dieses Package enthält (Repo-Root).
AGENT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from bewerbungsagent.config import Config  # noqa: E402
from bewerbungsagent.db import Store  # noqa: E402


def main() -> int:
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    config = Config(config_path)
    state_path = config.state_path()
    db_path = config.db_path()

    store = Store(db_path)

    # Bereits migriert? Dann nicht überschreiben.
    existing = store.load_state()
    if existing.get("applications"):
        print(f"DB existiert bereits mit {len(existing['applications'])} Einträgen — "
              "überspringe Import (idempotent).")
        return 0

    if not state_path.exists():
        print(f"Keine state.json gefunden unter {state_path} — nichts zu migrieren.")
        return 1

    data = json.loads(state_path.read_text(encoding="utf-8"))
    apps = data.get("applications", []) if isinstance(data, dict) else []

    # Sicherung vor dem Import.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = state_path.with_name(f"state.pre-sqlite-{stamp}.json")
    shutil.copy2(state_path, backup)
    print(f"Sicherung: {backup.name}")

    store.save_state({"applications": apps, "updated": data.get("updated", "")})

    # Abgeleiteten Snapshot zurückschreiben (für bisync/Backup).
    store.export_json(state_path)

    print(f"Migration abgeschlossen: {len(apps)} Einträge → {db_path}")
    print("JSON-Snapshot aktualisiert unter:", state_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
