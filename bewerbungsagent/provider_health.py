"""Zustand der Such-Quellen: Erfolge, Fehler und automatische Abschaltung.

Warum: Ein Suchlauf über zwölf Quellen sieht immer „erfolgreich“ aus, auch
wenn drei davon seit Wochen nur 403 liefern. Ohne Historie lässt sich nicht
unterscheiden, ob eine Quelle nichts Passendes hatte oder gar nicht
funktioniert. Dieses Modul führt die Historie pro Quelle in der SQLite-Meta-
Tabelle (kein Schema-Umbau) und schaltet eine Quelle nach mehreren
Fehlläufen in Folge ab — **manuell** wieder einschaltbar.

Regeln:

* Ein Lauf ohne Fehler ist ein Erfolg, auch mit 0 Funden (0 ist legitim).
* Fehler in Folge zählen; ein Erfolg setzt den Zähler zurück.
* Ab ``max_failures`` Fehlläufen in Folge wird die Quelle deaktiviert.
* Ein deaktivierter Provider wird übersprungen (nicht als Fehler gezählt);
  ``agent.py providers --enable NAME`` schaltet ihn zurück.
"""

from __future__ import annotations

DEFAULT_MAX_FAILURES = 3


def empty_entry() -> dict:
    """Startwerte einer Quelle im Health-Dict."""
    return {
        "laeufe": 0,
        "erfolge": 0,
        "fehler": 0,
        "serie_fehler": 0,
        "gefunden": 0,
        "letzter_lauf": None,
        "letzter_erfolg": None,
        "letzter_fehler": None,
        "letzter_fehler_text": None,
        "deaktiviert": False,
        "deaktiviert_am": None,
    }


def is_disabled(health: dict | None, name: str) -> bool:
    return bool(((health or {}).get(name) or {}).get("deaktiviert"))


def record(health: dict | None, stats: dict | None, *, now: str,
           max_failures: int = DEFAULT_MAX_FAILURES) -> dict:
    """Verrechnet die Ergebnisse eines Laufs und liefert ein neues Health-Dict.

    ``stats`` ist das, was ``search.run_search`` pro Quelle liefert:
    ``{"gefunden": n, "fehler": [texte], "uebersprungen": "grund"|None}``.
    Übersprungene Quellen zählen weder als Erfolg noch als Fehler.
    """
    out = {name: dict(entry) for name, entry in (health or {}).items()}
    for name, result in (stats or {}).items():
        if result.get("uebersprungen"):
            continue
        entry = out.setdefault(name, empty_entry())
        entry["laeufe"] += 1
        entry["letzter_lauf"] = now
        found = int(result.get("gefunden") or 0)
        entry["gefunden"] += found
        errors = [str(e) for e in (result.get("fehler") or []) if str(e).strip()]
        # Ein Lauf mit Treffern ist ein Erfolg, auch wenn ein Teil der Anfragen
        # fehlschlug (StepStone: 2 von 28 Begriffen). Erst „Fehler **und**
        # nichts gefunden“ bedeutet: Diese Quelle trägt nichts mehr bei.
        if errors and found == 0:
            entry["fehler"] += 1
            entry["serie_fehler"] += 1
            entry["letzter_fehler"] = now
            entry["letzter_fehler_text"] = errors[0][:300]
            if entry["serie_fehler"] >= max_failures and not entry["deaktiviert"]:
                entry["deaktiviert"] = True
                entry["deaktiviert_am"] = now
        else:
            entry["erfolge"] += 1
            entry["serie_fehler"] = 0
            entry["letzter_erfolg"] = now
            entry["letzter_fehler_text"] = None
    return out


def set_enabled(health: dict | None, name: str, enabled: bool, *, now: str) -> dict:
    """Manuelles Ein-/Ausschalten; Einschalten setzt den Fehlerzähler zurück."""
    out = {key: dict(entry) for key, entry in (health or {}).items()}
    entry = out.setdefault(name, empty_entry())
    entry["deaktiviert"] = not enabled
    entry["deaktiviert_am"] = None if enabled else now
    if enabled:
        entry["serie_fehler"] = 0
    return out


def reset(health: dict | None = None) -> dict:
    """Löscht die gesamte Historie (alle Quellen wieder aktiv)."""
    return {}


def active(health: dict | None) -> list[str]:
    """Namen der Quellen, die aktuell nicht abgeschaltet sind."""
    return sorted(name for name in (health or {}) if not is_disabled(health, name))
