"""Bereinigt Einträge, deren Schlüssel nicht mehr zur heutigen Regel passen.

Der Schlüssel einer Bewerbung ist ``normalize(url)`` (bzw. ``firma|titel`` ohne
URL). Ändert sich ``normalize``, entstehen Waisen: Eine Zeile behält ihren alten
Schlüssel, während die heutige Regel für dieselbe Anzeige einen anderen Schlüssel
ergibt — der schon von einer zweiten Zeile belegt ist. Beide beschreiben dieselbe
Stelle, nur eine wird künftig noch aktualisiert.

Beispiel: StepStone liefert denselben Job einmal mit U+002D und einmal mit
U+2010 im Titel („c-uas" vs. „c‐uas"). Seit ``normalize`` die Strichvarianten
faltet, ist die versendete Zeile der Halter und die zweite Zeile eine Waise, die
nie wieder getroffen wird.

Die Waise wird nicht einfach gelöscht: Nutzerfelder, die dem Halter fehlen,
werden übernommen, Dokumentverweise zusammengeführt und ein weiter fortgeschrittener
Status gewinnt. Erst danach wird die Waise entfernt.

Aufruf: ``python scripts/dedupe_schluessel.py [--write]``
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = Path("/home/diejac/GoogleDrive/DOKUMENTE/Job/Bewerbung/2026/04_Agent/config.json")
sys.path.insert(0, str(CONFIG.parent))

from bewerbungsagent.config import Config  # noqa: E402
from bewerbungsagent.db import Store  # noqa: E402
from bewerbungsagent.profile import normalize  # noqa: E402
from bewerbungsagent.statuses import ORDER  # noqa: E402

# Felder, die nur der Nutzer setzt. Sie dürfen beim Zusammenführen nie verloren
# gehen — der Halter gewinnt, aber leere Felder werden aufgefüllt.
NUTZERFELDER = ("sentAt", "notes", "contact", "interviewDate", "statusChangedAt")


def _rang(status: str | None) -> int:
    try:
        return ORDER.index(status or "research")
    except ValueError:
        return 0


def main(dry_run: bool = True) -> int:
    config = Config(CONFIG)
    store = Store(config.db_path())
    state = store.load_state()
    apps = state["applications"]
    nach_key = {a.get("key"): a for a in apps}

    waisen = []
    for a in apps:
        kanonisch = normalize(a.get("url") or "")
        if not kanonisch or a.get("key") == kanonisch:
            continue
        halter = nach_key.get(kanonisch)
        if halter is not None:
            waisen.append((a, halter))

    print(f"{len(apps)} Zeilen, {len(waisen)} Waisen"
          f"{' (Probelauf)' if dry_run else ''}\n")
    for waise, halter in waisen:
        print(f"  Waise : {waise.get('status')} | {waise.get('firma')} — {waise.get('titel')}")
        print(f"  Halter: {halter.get('status')} | {halter.get('firma')} — {halter.get('titel')}")
        uebernommen = []
        for feld in NUTZERFELDER:
            if waise.get(feld) and not halter.get(feld):
                halter[feld] = waise[feld]
                uebernommen.append(feld)
        docs = dict(waise.get("dokumente") or {})
        for k, v in (halter.get("dokumente") or {}).items():
            docs[k] = v          # Halter gewinnt bei gleichem Dokumenttyp
        if docs:
            halter["dokumente"] = docs
        if _rang(waise.get("status")) > _rang(halter.get("status")):
            print(f"    Status angehoben: {halter.get('status')} -> {waise.get('status')}")
            halter["status"] = waise["status"]
        if uebernommen:
            print(f"    Nutzerfelder übernommen: {', '.join(uebernommen)}")
        if not dry_run:
            apps.remove(waise)
        print()

    if dry_run:
        print("Probelauf — nichts geschrieben. Mit --write ausführen.")
        return 0

    state["applications"] = apps
    store.save_state(state)
    store.export_json(config.state_path())
    print(f"Gespeichert: {len(apps)} Zeilen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(dry_run="--write" not in sys.argv))
