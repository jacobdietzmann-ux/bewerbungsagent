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
* Am 07.11.2026 tauchten 22 von 60 offenen Einträgen im Suchlauf nicht mehr auf,
  ohne dass der Bestand davon wusste. **Vermutlich abgelaufen** macht das
  sichtbar, gelöscht wird dadurch nichts (ADR-054).

Das Modul ist bewusst frei von DB-/Dashboard-Importen, damit es ohne
SQLAlchemy testbar bleibt.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta

from .matching import (
    fit_value,
    has_role_signal,
    is_development_role,
    is_software_role,
    is_student_role,
    is_technician_role,
)
from .profile import normalize
from .provider_health import letzter_abruf
from .statuses import normalize_status

DEFAULT_MAX_AUTO_PER_WEEK = 8
DEFAULT_MAX_OFFEN_PRO_FIRMA = 2
DEFAULT_COMMUTE_GRACE_MIN = 10
DEFAULT_NEUFUND_MIN_FIT = 50
DEFAULT_ABGELAUFEN_NACH_TAGEN = 7
# So lange versucht der Lauf, einen fehlenden Anzeigentext nachzuladen (ADR-055).
TEXT_NACHLADEN_TAGE = 30

# Status, in denen eine Bewerbung bei der Firma „offen" ist. ``docs`` zählt nur
# mit vorhandenen Unterlagen (sonst ist es noch keine Bewerbung).
_OFFEN = ("sent", "followup", "interview")

# Vorgänge, die keine offene Stelle mehr sind: Bei ihnen zählt die Anzeige nicht.
_ABGESCHLOSSEN = (*_OFFEN, "rejected")


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


def ohne_text(app: dict) -> bool:
    """True, wenn die Stelle keinen Anzeigentext hat und nur am Titel hängt."""
    return not (app.get("beschreibung") or "").strip()


def rollentreffer_ohne_text(app: dict) -> bool:
    """Titel belegt die Zielrolle, aber der Text für eine Bewertung fehlt.

    Ohne Text kann der Fit die 50 % nicht erreichen (0 von 341 geprüften Stellen,
    ADR-055). Mit Text kommen 24,6 % dieser Rollentreffer auf mindestens 65 %.
    Software-, Entwickler-, Studenten- und Technikerrollen fallen unabhängig vom
    Text weg oder sind gedeckelt, eine abgelaufene Anzeige liefert keinen Text mehr.
    """
    titel = app.get("titel")
    if not ohne_text(app) or app.get("verfuegbar") is False:
        return False
    if (is_student_role(titel) or is_technician_role(titel)
            or is_software_role(titel) or is_development_role(titel)):
        return False
    return has_role_signal(titel)


def juenger_als(app: dict, tage: int, now: datetime | None = None) -> bool:
    """True, wenn die Stelle vor weniger als ``tage`` Tagen in den Bestand kam."""
    erfasst = _parse(app.get("created"))
    if erfasst is None:
        return False
    return erfasst >= (now or datetime.now().astimezone()) - timedelta(days=tage)


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


def stelle_offen(app: dict) -> bool:
    """True, solange noch keine Bewerbung läuft und die Stelle nicht gelöscht ist."""
    return (not app.get("deleted")
            and normalize_status(app.get("status")) not in _ABGESCHLOSSEN)


def tage_vermisst(app: dict, quellen: dict | None) -> int | None:
    """Tage zwischen ``zuletzt_gesehen`` und dem letzten Erfolg der Quelle.

    ``quellen`` ist ``{"provider": …, "boards": …}`` aus der Historie. Gezählt wird
    in Kalendertagen, damit die Laufzeit des Tageslaufs das Ergebnis nicht kippt.
    ``None`` heißt: Es fehlt ein Zeitpunkt, also ist keine Aussage möglich.
    """
    gesehen = _parse(app.get("zuletzt_gesehen"))
    quellen = quellen or {}
    bezug = _parse(letzter_abruf(app, quellen.get("provider"), quellen.get("boards")))
    if gesehen is None or bezug is None:
        return None
    return (bezug.date() - gesehen.date()).days


def vermutlich_abgelaufen(app: dict, quellen: dict | None,
                          tage: int = DEFAULT_ABGELAUFEN_NACH_TAGEN) -> bool:
    """True, wenn eine offene Stelle seit ``tage`` Tagen in ihrer Quelle fehlt.

    Nur eine Vermutung: Eine Anzeige kann auch aus den ersten Treffern einer Börse
    gerutscht sein. Deshalb bleibt es eine Anzeige, die nichts löscht und jeder
    neue Fund wieder aufhebt. ``tage <= 0`` schaltet die Prüfung ab. Eine als
    abgelaufen geprüfte Anzeige (``verfuegbar`` ist ``False``) braucht sie nicht.
    """
    if tage <= 0 or not stelle_offen(app) or app.get("verfuegbar") is False:
        return False
    fehlt = tage_vermisst(app, quellen)
    return fehlt is not None and fehlt >= tage


def shortlist(apps: Iterable[dict], top: int = 8, *, quellen: dict | None = None,
              abgelaufen_tage: int = DEFAULT_ABGELAUFEN_NACH_TAGEN) -> list[dict]:
    """Bewerbungen mit fertigen Unterlagen, die noch nicht versendet sind.

    Das ist die Wochenauswahl: die besten ``top`` Stellen nach Fit, jeweils mit
    Hinweis, ob ein Ansprechpartner fehlt (persönliche Anrede, Anruf vorab) oder
    die Anzeige vermutlich abgelaufen ist. Solche Stellen bleiben in der Liste.
    """
    offen = [a for a in apps
             if not a.get("deleted") and a.get("status") == "docs" and a.get("dokumente")]
    offen.sort(key=fit_value, reverse=True)
    return [{
        "firma": a.get("firma"), "titel": a.get("titel"), "ort": a.get("ort"),
        "fit": fit_value(a), "url": a.get("url"), "key": a.get("key"),
        "kontakt_fehlt": not (a.get("contact") or a.get("ansprechpartner")),
        "pendel_knapp": bool(a.get("pendel_knapp")),
        "vermutlich_abgelaufen": vermutlich_abgelaufen(a, quellen, abgelaufen_tage),
    } for a in offen[:top]]


# ---------------------------------------------------------------------------
# Frühere Bewerbung auf eine ähnliche Stelle (19.11.2026)
#
# Der Digest meldete „(Senior) Systems Engineer mechatronische Sonderanlagen" bei
# „IABG Industrieanlagen-Betriebsgesellschaft mbH", auf die als „Senior Systems
# Engineer …" bei „IABG" schon eine Absage kam. Die Identität (Firma + Titel + Ort)
# griff nicht: Firmenname, „(Senior)", „oe" statt „ö" und eine volle Adresse statt
# des Ortes unterschieden sich. Bei 62 offenen Stellen gab es 7 solche Paare.
# Entscheidung des Nutzers: nur warnen, nichts ausblenden — eine ähnliche Stelle
# kann eine neue Ausschreibung sein.
# ---------------------------------------------------------------------------

AEHNLICH_AB = 0.6
_TITEL_FUELL = frozenset({
    "senior", "junior", "lead", "m", "w", "d", "f", "x", "gn", "div", "mwd", "und", "and",
    "fur", "for", "the", "der", "die", "das", "im", "in", "mit", "with", "zukunftige",
    "all", "genders", "gender"})
_STATUS_TEXT = {"sent": "beworben", "followup": "nachgefasst", "interview": "Interview",
                "rejected": "abgesagt"}
_TITEL_GENDER_RE = re.compile(r"\(\s*[mwfdx]\s*(?:[/\-|]\s*[a-z]+\s*){1,3}\)")


def _firma_kern(name: str | None) -> str:
    """Firmenkern ohne Zusatz nach „ - ", Rechtsform, Leer- und Satzzeichen."""
    text = re.split(r"\s[-–—|]\s", normalize(name or ""))[0]
    text = re.sub(r"\b(?:gmbh|mbh|ag|se|kg|co|ug|inc|ltd|llc|group|holding|deutschland|germany)\b",
                  " ", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def _gleiche_firma(a: str, b: str) -> bool:
    """„iabg" ~ „iabgindustrieanlagen", „agilerobots" ~ „agilerobotsse"."""
    if not a or not b:
        return False
    return a == b or (min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a)))


def _titel_woerter(titel: str | None) -> frozenset[str]:
    t = _TITEL_GENDER_RE.sub(" ", normalize(titel or ""))
    t = t.replace("ae", "a").replace("oe", "o").replace("ue", "u")
    return frozenset(w for w in re.findall(r"[a-z0-9+#]+", t)
                     if len(w) > 1 and w not in _TITEL_FUELL)


def bewerbungs_index(apps: Iterable[dict]) -> list[tuple[str, frozenset[str], dict]]:
    """Abgeschlossene Bewerbungen (beworben bis abgesagt) als Vergleichsbasis."""
    return [(_firma_kern(a.get("firma")), _titel_woerter(a.get("titel")), a)
            for a in apps
            if not a.get("deleted") and normalize_status(a.get("status")) in _ABGESCHLOSSEN]


def fruehere_bewerbung(app: dict, index: list[tuple[str, frozenset[str], dict]],
                       ab: float = AEHNLICH_AB) -> dict | None:
    """Ähnlichste frühere Bewerbung bei derselben Firma, sonst ``None``."""
    if normalize_status(app.get("status")) in _ABGESCHLOSSEN:
        return None
    firma, woerter = _firma_kern(app.get("firma")), _titel_woerter(app.get("titel"))
    if not woerter:
        return None
    bestes, wert = None, ab
    for f, w, frueher in index:
        if frueher is app or frueher.get("id") == app.get("id") or not w:
            continue
        if not _gleiche_firma(firma, f):
            continue
        j = len(woerter & w) / len(woerter | w)
        if j >= wert:
            bestes, wert = frueher, j
    return bestes


def frueher_text(frueher: dict, kurz: bool = False) -> str:
    """„abgesagt 15.11. (ID 1333)" bzw. mit Titel für Sparring und Dashboard."""
    status = normalize_status(frueher.get("status"))
    datum = (_parse(frueher.get("statusChangedAt")) if status == "rejected" else None) \
        or _parse(frueher.get("sentAt")) or _parse(frueher.get("statusChangedAt"))
    teile = [_STATUS_TEXT.get(status, status)]
    if datum:
        teile.append(f"{datum:%d.%m.}")
    text = f"{' '.join(teile)} (ID {frueher.get('id')})"
    if kurz:
        return text
    return f"{frueher.get('titel') or '?'} — {text}"
