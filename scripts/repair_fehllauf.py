"""Einmalige Reparatur: Status zurücksetzen für Stellen aus dem Fehllauf.

Der Graph rief ``run_generate`` ohne Rollen-Schutz auf. Für 20 Rollen ohne
Test-/Absicherungsbezug entstanden Unterlagen, und ``_record_docs`` setzte den
Status von ``neu`` auf ``docs``.

Dieses Skript setzt Status und Dokumentverweise auf den Stand vom 15.10.2026
09:51 zurück und verschiebt die erzeugten Ordner in eine Quarantäne — nichts
wird gelöscht.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = Path("/home/diejac/GoogleDrive/DOKUMENTE/Job/Bewerbung/2026/04_Agent/config.json")

# ``AGENT_ROOT`` ist der Ordner des importierten Pakets. Für den Live-Bestand
# muss deshalb das Live-Paket importiert werden, nicht das im Repo — sonst
# zeigt jeder Pfad auf ``~/git/bewerbungsagent``.
sys.path.insert(0, str(CONFIG.parent))

from bewerbungsagent.config import Config  # noqa: E402
from bewerbungsagent.db import Store  # noqa: E402
from bewerbungsagent.matching import has_role_signal  # noqa: E402

BACKUP = Path("/home/diejac/backups/bewerbungsagent-state/20261015-095105/data/state.json")


def _ordner(config: Config, docs: dict) -> Path | None:
    """Bewerbungsordner aus einem gespeicherten Dokumentpfad ableiten."""
    for rel in docs.values():
        teile = Path(str(rel)).parts
        if "01_Bewerbungen" in teile:
            rest = teile[teile.index("01_Bewerbungen") + 1:]
            if rest:
                basis = Path(config.data["bewerbungen_dir"]).resolve().parent
                return basis / "01_Bewerbungen" / rest[0]
    return None


def main(dry_run: bool = True) -> int:
    # Relative Pfade in config.json (``data``, ``output``) gelten ab dem
    # Verzeichnis der Konfiguration, nicht ab dem des Skripts.
    os.chdir(CONFIG.parent)
    config = Config(CONFIG)
    store = Store(config.db_path())
    if not config.db_path().exists():
        raise SystemExit(f"Keine Datenbank unter {config.db_path()}")
    alt = {(a.get("firma"), a.get("titel")): a
           for a in json.loads(BACKUP.read_text())["applications"]}
    state = store.load_state()
    if not state["applications"]:
        raise SystemExit(f"Datenbank {config.db_path()} ist leer — falscher Pfad?")

    quotaene = config.data_dir / "quarantaene" / datetime.now().strftime("%Y%m%d-%H%M%S")
    betroffen = []
    for a in state["applications"]:
        vorher = alt.get((a.get("firma"), a.get("titel")))
        if not vorher or vorher.get("status") == a.get("status"):
            continue
        if a.get("status") != "docs" or has_role_signal(a.get("titel")):
            continue
        betroffen.append(a)

    print(f"{len(betroffen)} Einträge werden zurückgesetzt"
          f"{' (Probelauf)' if dry_run else ''}:\n")
    for a in betroffen:
        alt_status = alt[(a.get("firma"), a.get("titel"))].get("status", "neu")
        docs = a.pop("dokumente", None) or {}
        a["status"] = alt_status
        print(f"  {str(a.get('firma'))[:22]:24s} alt={alt_status:5s} {(a.get('titel') or '')[:44]}")
        if dry_run:
            continue
        ordner = _ordner(config, docs)
        if ordner and ordner.is_dir() and quotaene not in ordner.parents:
            ziel = quotaene / ordner.name
            ziel.parent.mkdir(parents=True, exist_ok=True)
            if not ziel.exists():
                shutil.move(str(ordner), str(ziel))

    if dry_run:
        print("\nProbelauf — nichts geschrieben.")
        return 0

    store.save_state(state)
    store.export_json(config.state_path())
    print(f"\nGespeichert. Quarantäne: {quotaene}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(dry_run="--write" not in sys.argv))
