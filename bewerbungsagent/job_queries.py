"""Lesende Abfragen auf den Bewerbungsbestand für den MCP-Server.

Öffnet die SQLite-Datenbank ausschließlich im Modus ``ro``. ``db.Store`` passt
hier nicht: Beim Öffnen legt es das Schema an und holt Migrationen nach, schreibt
also. Nur Standardbibliothek, damit die Minimal-CI ohne Zusatzpakete läuft.

``status`` ist ein Prozess-Zustand, kein Eignungsmaß: ``rejected`` heißt „beworben,
von der Firma abgelehnt“, nicht „passt nicht“ (ADR-012).
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

LISTEN_FELDER = (
    "key", "firma", "titel", "ort", "status", "score", "fit_geschaetzt",
    "statusChangedAt", "sentAt", "interviewDate", "url",
)
DETAIL_FELDER = (
    *LISTEN_FELDER, "quelle", "gehalt", "homeoffice", "branche", "pendelzeit_min",
    "matched_skills", "stack_missing", "begruendung", "contact", "notes", "deleted",
    "deleted_reason", "absage_grund", "absage_talentpool",
)
MAX_BESCHREIBUNG = 2000
MAX_TREFFER = 100


def lade_bewerbungen(db_path: str | Path) -> list[dict]:
    """Lädt alle Bewerbungen schreibgeschützt; Nutzerfelder überlagern Provider-Felder."""
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        zeilen = conn.execute("select key, provider, user, updated_at from applications").fetchall()
    finally:
        conn.close()
    apps = []
    for key, provider, user, updated_at in zeilen:
        app = {**json.loads(provider or "{}"), **json.loads(user or "{}")}
        app.update(key=key, updated_at=updated_at)
        apps.append(app)
    return apps


def _kurz(app: dict) -> dict:
    return {f: app[f] for f in LISTEN_FELDER if app.get(f) not in (None, "")}


def _begrenze(limit: int) -> int:
    return max(1, min(int(limit), MAX_TREFFER))


def _score(app: dict) -> int:
    wert = app.get("score")
    return wert if isinstance(wert, (int, float)) else -1


def statistik(apps: list[dict]) -> dict:
    """Zählt sichtbare Einträge je Status sowie die ausgeblendeten."""
    sichtbar = [a for a in apps if not a.get("deleted")]
    aenderungen = [a.get("updated_at") for a in apps if a.get("updated_at")]
    return {
        "gesamt": len(apps),
        "sichtbar": len(sichtbar),
        "ausgeblendet": len(apps) - len(sichtbar),
        "nach_status": dict(Counter(str(a.get("status")) for a in sichtbar).most_common()),
        "letzte_aenderung": max(aenderungen) if aenderungen else None,
    }


def suche(
    apps: list[dict],
    text: str = "",
    status: str | None = None,
    firma: str | None = None,
    min_score: int | None = None,
    mit_ausgeblendeten: bool = False,
    limit: int = 25,
) -> dict:
    """Filtert den Bestand; Treffer absteigend nach Score."""
    nadel = text.strip().lower()
    firma_nadel = (firma or "").strip().lower()
    treffer = []
    for app in apps:
        if app.get("deleted") and not mit_ausgeblendeten:
            continue
        if status and app.get("status") != status:
            continue
        if firma_nadel and firma_nadel not in str(app.get("firma", "")).lower():
            continue
        if min_score is not None and _score(app) < min_score:
            continue
        if nadel:
            felder = (app.get(f, "") for f in ("titel", "firma", "ort", "beschreibung"))
            if not any(nadel in str(wert).lower() for wert in felder):
                continue
        treffer.append(app)
    treffer.sort(key=_score, reverse=True)
    return {"anzahl": len(treffer), "treffer": [_kurz(a) for a in treffer[:_begrenze(limit)]]}


def aenderungen(
    apps: list[dict],
    tage: int = 7,
    status: str | None = None,
    heute: date | None = None,
    limit: int = 50,
) -> dict:
    """Sichtbare Einträge, deren Status sich in den letzten ``tage`` Tagen änderte."""
    grenze = ((heute or date.today()) - timedelta(days=max(0, int(tage)))).isoformat()
    treffer = [
        a for a in apps
        if not a.get("deleted")
        and str(a.get("statusChangedAt") or "")[:10] >= grenze
        and (not status or a.get("status") == status)
    ]
    treffer.sort(key=lambda a: str(a.get("statusChangedAt")), reverse=True)
    return {"seit": grenze, "anzahl": len(treffer),
            "treffer": [_kurz(a) for a in treffer[:_begrenze(limit)]]}


def details(apps: list[dict], key: str) -> dict | None:
    """Liefert einen Eintrag; die Stellenbeschreibung wird gekürzt."""
    app = next((a for a in apps if a.get("key") == key), None)
    if app is None:
        return None
    out = {f: app[f] for f in DETAIL_FELDER if app.get(f) not in (None, "")}
    text = str(app.get("beschreibung") or "")
    if text:
        out["beschreibung"] = text[:MAX_BESCHREIBUNG]
        out["beschreibung_gekuerzt"] = len(text) > MAX_BESCHREIBUNG
    return out
