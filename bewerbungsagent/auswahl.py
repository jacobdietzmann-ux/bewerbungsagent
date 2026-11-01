"""Auswahl: welche Stellen bekommen Unterlagen, welche Funde sind sichtbar.

Hintergrund (Trichter-Auswertung vom 01.11.2026, 209 Bewerbungen):

* Im Oktober gingen 88 Bewerbungen raus, die meisten automatisch erzeugt. Bei
  einzelnen Firmen lagen gleichzeitig 7–11 Bewerbungen (ALTEN, Quantum-Systems,
  FERCHAU, ARX). Masse ersetzt keine gezielte Bewerbung — deshalb ein
  **Wochenbudget** für automatisch erzeugte Unterlagen und ein **Limit offener
  Bewerbungen pro Firma**. Beides gilt nur für den Mengenlauf; eine
  ausdrückliche Auswahl (``generate --ids``) bleibt frei.
* Zwei Treffer mit 82–84 % Fit (Gilching, 31 min) wurden gelöscht, weil sie eine
  Minute über der Pendelgrenze lagen. Die Kulanz ``commute_grace_min`` griff nie:
  der Pendel-Löschschritt lief vor dem Research-Filter. **Pendel knapp** hält
  solche Stellen jetzt als Research sichtbar — ohne automatische Unterlagen.
* Neue Funde wurden unabhängig von Fit und Rolle im Dashboard gezeigt
  („Director Sustainability Data & AI", „Digital IP Design Engineer"). Ein
  Neufund ist nur noch sichtbar, wenn der Titel eine Test-/Systemrolle belegt
  und der Fit die Ausblendegrenze erreicht.

Das Modul ist bewusst frei von DB-/Dashboard-Importen, damit es ohne
SQLAlchemy testbar bleibt.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta

from .matching import fit_value, has_role_signal

DEFAULT_MAX_AUTO_PER_WEEK = 8
DEFAULT_MAX_OFFEN_PRO_FIRMA = 2
DEFAULT_COMMUTE_GRACE_MIN = 10
DEFAULT_NEUFUND_MIN_FIT = 50

# Status, in denen eine Bewerbung bei der Firma „offen" ist. ``docs`` zählt nur
# mit vorhandenen Unterlagen (sonst ist es noch keine Bewerbung).
_OFFEN = ("sent", "followup", "interview")


def _parse(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.astimezone()


def commute_minutes(app: dict) -> float | None:
    """Pendelzeit in Minuten oder ``None`` (unbekannt/remote)."""
    roh = app.get("pendelzeit_min")
    if roh is None or roh == "":
        return None
    try:
        return float(roh)
    except (TypeError, ValueError):
        return None


def within_commute_grace(app: dict, limit: int, grace: int, min_fit: int) -> bool:
    """True, wenn die Stelle knapp über der Pendelgrenze liegt und stark genug ist.

    ``limit < Minuten <= limit + grace`` **und** Fit ≥ ``min_fit``. Solche
    Stellen bleiben als Research sichtbar; Unterlagen werden für sie nicht
    automatisch erzeugt (der Pendelweg bleibt für die Automatik eine harte Grenze).
    """
    if grace <= 0:
        return False
    minuten = commute_minutes(app)
    if minuten is None:
        return False
    return limit < minuten <= limit + grace and fit_value(app) >= min_fit


def neufund_relevant(app: dict, min_fit: int = DEFAULT_NEUFUND_MIN_FIT) -> bool:
    """Darf ein neuer Fund ohne Unterlagen im Dashboard erscheinen?"""
    return has_role_signal(app.get("titel")) and fit_value(app) >= min_fit


def auto_docs_last_days(apps: Iterable[dict], now: datetime | None = None,
                        days: int = 7) -> int:
    """Wie viele Unterlagen wurden in den letzten ``days`` Tagen automatisch erzeugt?"""
    jetzt = now or datetime.now().astimezone()
    grenze = jetzt - timedelta(days=days)
    n = 0
    for a in apps:
        ts = _parse(a.get("unterlagen_erzeugt_am"))
        if ts is not None and grenze <= ts <= jetzt:
            n += 1
    return n


def offene_pro_firma(apps: Iterable[dict], company_key: Callable[[str | None], str]) -> Counter:
    """Offene Bewerbungen je Firma (versendet oder Unterlagen vorhanden)."""
    zaehler: Counter = Counter()
    for a in apps:
        if a.get("deleted"):
            continue
        status = a.get("status")
        if status in _OFFEN or (status == "docs" and a.get("dokumente")):
            key = company_key(a.get("firma"))
            if key:
                zaehler[key] += 1
    return zaehler


def apply_limits(candidates: list[dict], apps: list[dict], *,
                 company_key: Callable[[str | None], str],
                 max_per_week: int | None = DEFAULT_MAX_AUTO_PER_WEEK,
                 max_per_company: int | None = DEFAULT_MAX_OFFEN_PRO_FIRMA,
                 now: datetime | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    """Wählt aus ``candidates`` die besten Stellen innerhalb der Limits.

    Rückgabe ``(ausgewaehlt, ueber_wochenbudget, ueber_firmenlimit)``.
    Sortiert wird nach Fit (absteigend), damit das Budget die besten Treffer
    trifft. ``None`` oder ``0`` schaltet ein Limit ab.
    """
    sortiert = sorted(candidates, key=fit_value, reverse=True)
    budget = None
    if max_per_week:
        budget = max(0, int(max_per_week) - auto_docs_last_days(apps, now))
    offen = offene_pro_firma(apps, company_key)

    ausgewaehlt: list[dict] = []
    ueber_budget: list[dict] = []
    ueber_firma: list[dict] = []
    for job in sortiert:
        firma = company_key(job.get("firma"))
        if max_per_company and firma and offen[firma] >= int(max_per_company):
            ueber_firma.append(job)
            continue
        if budget is not None and len(ausgewaehlt) >= budget:
            ueber_budget.append(job)
            continue
        ausgewaehlt.append(job)
        if firma:
            offen[firma] += 1
    return ausgewaehlt, ueber_budget, ueber_firma


def shortlist(apps: Iterable[dict], top: int = 8) -> list[dict]:
    """Bewerbungen mit fertigen Unterlagen, die noch nicht versendet sind.

    Das ist die Wochenauswahl: die besten ``top`` Stellen nach Fit, jeweils mit
    Hinweis, ob ein Ansprechpartner fehlt (persönliche Anrede, Anruf vorab).
    """
    offen = [a for a in apps
             if not a.get("deleted") and a.get("status") == "docs" and a.get("dokumente")]
    offen.sort(key=fit_value, reverse=True)
    return [{
        "firma": a.get("firma"), "titel": a.get("titel"), "ort": a.get("ort"),
        "fit": fit_value(a), "url": a.get("url"), "key": a.get("key"),
        "kontakt_fehlt": not (a.get("contact") or a.get("ansprechpartner")),
        "pendel_knapp": bool(a.get("pendel_knapp")),
    } for a in offen[:top]]
