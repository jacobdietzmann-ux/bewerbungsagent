#!/usr/bin/env python3
"""Prüft als „abgelaufen" markierte Stellen erneut gegen die Live-Anzeige.

Warum: Die Erkennung abgelaufener Anzeigen läuft über Textmuster. Ändert sich
ein Muster (oder war eines zu grob — das nackte Wort „abgelaufen" erzeugte eine
Fehlalarmquote von 19/20), sind die bereits gespeicherten ``verfuegbar=False``
Flags veraltet. Dieses Skript liest genau diese Einträge, öffnet die Anzeige
erneut im Headless-Chromium und korrigiert den Flag.

Ausgabe:
- ``verfuegbar: True``  → Anzeige ist wieder erreichbar, Text wird als
  ``beschreibung`` übernommen sofern noch keine vorhanden ist.
- ``verfuegbar: False`` → bleibt abgelaufen, ``verfuegbar_grund`` wird auf das
  aktuell passende Muster gesetzt (macht den Fund nachvollziehbar).
- Fehler beim Laden lassen den Eintrag unverändert.

Nutzung:
    python scripts/recheck_expired.py            # nur prüfen, nichts schreiben
    python scripts/recheck_expired.py --apply    # Änderungen speichern
    python scripts/recheck_expired.py --apply --limit 5
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from bewerbungsagent.config import Config  # noqa: E402
from bewerbungsagent.db import Store  # noqa: E402
from bewerbungsagent.pipeline import _persist_state  # noqa: E402
from fetch_descriptions import (  # noqa: E402
    _extract_description,
    _is_expired,
    browser_page,
    load_page_text,
)


def _targets(apps: list[dict], limit: int | None) -> list[dict]:
    flagged = [a for a in apps if a.get("verfuegbar") is False and a.get("url")]
    return flagged[:limit] if limit else flagged


def recheck(config: Config, *, apply: bool = False,
            limit: int | None = None) -> dict:
    store = Store(config.db_path())
    state = store.load_state()
    apps = state.get("applications", [])
    targets = _targets(apps, limit)

    print(f"Als abgelaufen markiert: {len(targets)} Eintrag/Einträge.")
    if not targets:
        return {"checked": 0, "recovered": 0, "still_expired": 0, "errors": 0}

    recovered = still = errors = 0

    with browser_page() as page:
        for i, app in enumerate(targets, 1):
            name = str(app.get("titel") or app.get("firma") or "?")[:44]
            try:
                text = load_page_text(page, app["url"])
                marker = _is_expired(text)
                if marker:
                    app["verfuegbar"] = False
                    app["verfuegbar_grund"] = marker
                    still += 1
                    print(f"[{i}/{len(targets)}] bleibt abgelaufen  {name}  („{marker}“)")
                else:
                    app["verfuegbar"] = True
                    app.pop("verfuegbar_grund", None)
                    desc = _extract_description(text)
                    if desc and not (app.get("beschreibung") or "").strip():
                        app["beschreibung"] = desc
                    recovered += 1
                    print(f"[{i}/{len(targets)}] wieder verfügbar {name}  ({len(desc)} Zeichen)")
            except Exception as exc:
                errors += 1
                print(f"[{i}/{len(targets)}] nicht prüfbar    {name}  ({type(exc).__name__})")
            time.sleep(1.0)

    result = {"checked": len(targets), "recovered": recovered,
              "still_expired": still, "errors": errors}

    if apply and (recovered or still):
        state["applications"] = apps
        _persist_state(config, store, state)
        print(f"\nGespeichert: {recovered} korrigiert, {still} bleiben abgelaufen.")
    elif recovered or still:
        print("\nProbelauf — nichts geschrieben. Mit --apply übernehmen.")

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Abgelaufene Stellen erneut prüfen")
    parser.add_argument("--apply", action="store_true", help="Änderungen speichern")
    parser.add_argument("--limit", type=int, default=None, help="max. Anzahl prüfen")
    parser.add_argument("--config", default=None, help="Pfad zur config.json")
    args = parser.parse_args(argv)

    config = Config(Path(args.config)) if args.config else Config()
    recheck(config, apply=args.apply, limit=args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
