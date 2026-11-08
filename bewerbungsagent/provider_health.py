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
* Nach ``DEFAULT_RETRY_HOURS`` Stunden wird eine abgeschaltete Quelle einmal
  probeweise wieder zugelassen (``release_due``). Scheitert die Probe, bleibt
  der Fehlerzähler über der Grenze und die Quelle ist sofort wieder aus;
  gelingt sie, ist sie wieder aktiv. So schalten kurze Netzausfälle oder
  fehlende Browser-Binärdateien keine Quelle dauerhaft ab.
* ATS-Boards führen dieselbe Historie unter ``board_health``, werden aber nie
  abgeschaltet: Ein Board kostet nur eine Anfrage und fällt oft nur kurz aus.

``stoerungen`` und ``aenderungen_seit`` machen daraus die Meldungen des Digests,
``letzter_abruf`` den Bezugspunkt für „vermutlich abgelaufen“ (ADR-054).
"""

from __future__ import annotations

from datetime import datetime

DEFAULT_MAX_FAILURES = 3
DEFAULT_RETRY_HOURS = 24

AUSFALL = "ausfall"
ABGESCHALTET = "abgeschaltet"

# Anzeigen tragen in ``quelle`` den Anzeigenamen, die Historie den Providernamen.
_PROVIDER_JE_QUELLE = {
    "ATS": ("ats",),
    "StepStone": ("stepstone_browser", "stepstone"),
    "XING": ("xing",),
    "Indeed": ("indeed", "jobspy"),
    "LinkedIn": ("jobspy",),
    "Google Jobs": ("jobspy",),
    "Glassdoor": ("jobspy",),
    "JobSpy": ("jobspy",),
    "Arbeitnow": ("arbeitnow",),
    "JobLeads": ("jobleads",),
    "Labo": ("labo",),
}


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


def release_due(health: dict | None, *, now: str,
                retry_hours: float = DEFAULT_RETRY_HOURS) -> dict:
    """Lässt abgeschaltete Quellen nach ``retry_hours`` einmal probeweise zu.

    ``retry_hours <= 0`` schaltet die Wiederholung ab. Der Fehlerzähler bleibt
    unverändert, damit ein einziger weiterer Fehlschlag wieder abschaltet.
    """
    out = {name: dict(entry) for name, entry in (health or {}).items()}
    if retry_hours <= 0:
        return out
    try:
        current = datetime.fromisoformat(now)
    except ValueError:
        return out
    for entry in out.values():
        since = entry.get("deaktiviert_am")
        if not entry.get("deaktiviert") or not since:
            continue
        try:
            started = datetime.fromisoformat(since)
            hours = (current - started).total_seconds() / 3600
        except (ValueError, TypeError):
            continue
        if hours >= retry_hours:
            entry["deaktiviert"] = False
            entry["deaktiviert_am"] = None
    return out


def record(health: dict | None, stats: dict | None, *, now: str,
           max_failures: int | None = DEFAULT_MAX_FAILURES) -> dict:
    """Verrechnet die Ergebnisse eines Laufs und liefert ein neues Health-Dict.

    ``stats`` ist das, was ``search.run_search`` pro Quelle liefert:
    ``{"gefunden": n, "fehler": [texte], "uebersprungen": "grund"|None}``.
    Übersprungene Quellen zählen weder als Erfolg noch als Fehler.
    ``max_failures=None`` führt nur die Historie und schaltet nichts ab.
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
            if (max_failures is not None and entry["serie_fehler"] >= max_failures
                    and not entry["deaktiviert"]):
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


def letzter_abruf(app: dict, health: dict | None, boards: dict | None = None) -> str | None:
    """Letzter erfolgreicher Lauf der Quelle, aus der eine Stelle stammt.

    Fehlt eine Stelle in einem Lauf, ihre Quelle war aber ausgefallen oder
    abgeschaltet, sagt das nichts über die Anzeige. Maßstab ist deshalb nicht die
    Uhrzeit, sondern der letzte Lauf, in dem die Quelle wirklich geantwortet hat.
    Das gilt auch, wenn der Tageslauf einige Tage gar nicht lief. Eine Quelle ohne
    Historie (Import, Mail-Lead) vergleicht mit dem letzten Erfolg irgendeiner Quelle.
    """
    health = health or {}
    firma = app.get("firma")
    if app.get("quelle") == "ATS" and firma in (boards or {}):
        return boards[firma].get("letzter_erfolg")
    namen = [n for n in _PROVIDER_JE_QUELLE.get(app.get("quelle"), ()) if n in health]
    eintraege = [health[n] for n in namen] if namen else health.values()
    return max(filter(None, (e.get("letzter_erfolg") for e in eintraege)), default=None)


def stoerungen(health: dict | None, boards: dict | None = None) -> dict[str, dict]:
    """Aktuell gestörte Quellen: ``{name: {"zustand": …, "grund": text}}``.

    ``zustand`` ist ``ABGESCHALTET`` oder ``AUSFALL``. Ein Teilausfall zählt nicht:
    Hat eine Quelle trotz einzelner Fehler geliefert, trägt sie weiter bei.
    """
    out: dict[str, dict] = {}
    for name, entry in (health or {}).items():
        if entry.get("deaktiviert"):
            zustand = ABGESCHALTET
        elif entry.get("serie_fehler"):
            zustand = AUSFALL
        else:
            continue
        out[name] = {"zustand": zustand, "grund": entry.get("letzter_fehler_text")}
    for name, entry in (boards or {}).items():
        if entry.get("serie_fehler"):
            out[f"ATS-Board {name}"] = {"zustand": AUSFALL,
                                        "grund": entry.get("letzter_fehler_text")}
    return out


def aenderungen_seit(gemeldet: dict | None, aktuell: dict[str, dict]) -> tuple[dict, dict]:
    """Vergleicht den zuletzt gemeldeten Stand mit den aktuellen Störungen.

    Liefert ``(stand, aenderungen)``: ``stand`` ist ``{name: zustand}`` zum
    Speichern, ``aenderungen`` hat die Listen ``neu`` und ``abgeschaltet`` mit
    ``(name, grund)`` sowie ``wieder_da`` mit Namen. Ohne Änderung sind alle leer.

    Der Wechsel von ``ABGESCHALTET`` zu ``AUSFALL`` bleibt still: Das ist die
    Probe aus ``release_due`` nach einem Teillauf, die Quelle ist weiter gestört.
    """
    gemeldet = gemeldet or {}
    stand: dict[str, str] = {}
    neu: list[tuple[str, str | None]] = []
    abgeschaltet: list[tuple[str, str | None]] = []
    for name, eintrag in sorted(aktuell.items()):
        alt, zustand = gemeldet.get(name), eintrag["zustand"]
        if alt == ABGESCHALTET and zustand == AUSFALL:
            stand[name] = ABGESCHALTET
            continue
        stand[name] = zustand
        if zustand == alt:
            continue
        (neu if zustand == AUSFALL else abgeschaltet).append((name, eintrag.get("grund")))
    wieder_da = sorted(set(gemeldet) - set(aktuell))
    return stand, {"neu": neu, "abgeschaltet": abgeschaltet, "wieder_da": wieder_da}
