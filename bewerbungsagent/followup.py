"""Nachfassen: offene Bewerbungen, die eine Erinnerung verdienen.

Eine versendete Bewerbung ohne Reaktion ist kein Ergebnis. Dieses Modul
beantwortet deterministisch zwei Fragen: *Welche Bewerbung ist fällig?* und
*Was schreibe ich?* Es versendet nichts — die Entscheidung bleibt beim Nutzer.

Fällig ist:

* eine Bewerbung im Status ``sent``, deren ``sentAt`` mindestens
  ``after_days`` zurückliegt (Standard 14), oder
* eine Bewerbung im Status ``followup``, deren ``statusChangedAt``
  mindestens ``after_days`` zurückliegt (zweite Nachfrage).

Nicht fällig sind Bewerbungen mit ``interviewDate`` (es gibt eine Reaktion),
gelöschte Einträge und alles, was nie versendet wurde. Ein fehlendes Datum
macht eine Bewerbung nicht fällig — geraten wird nicht.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from .profile import Profile
from .storage import now_iso

DEFAULT_AFTER_DAYS = 14


def _parse_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _base_date(app: dict) -> date | None:
    """Datum, ab dem die Wartezeit läuft (Versand bzw. letzte Nachfrage)."""
    status = (app.get("status") or "").strip()
    if status == "followup":
        return _parse_date(app.get("statusChangedAt"))
    if status == "sent":
        return _parse_date(app.get("sentAt")) or _parse_date(app.get("statusChangedAt"))
    return None


def days_waiting(app: dict, today: date | None = None) -> int | None:
    """Tage seit Versand (bzw. letzter Nachfrage); ``None`` ohne Datum."""
    base = _base_date(app)
    if base is None:
        return None
    return ((today or date.today()) - base).days


def is_due(app: dict, *, after_days: int = DEFAULT_AFTER_DAYS,
           today: date | None = None) -> bool:
    if app.get("deleted") or app.get("interviewDate"):
        return False
    waiting = days_waiting(app, today)
    return waiting is not None and waiting >= after_days


def due_applications(apps: list[dict], *, after_days: int = DEFAULT_AFTER_DAYS,
                     today: date | None = None) -> list[dict]:
    """Fällige Bewerbungen, am längsten wartend zuerst."""
    due = [a for a in apps if is_due(a, after_days=after_days, today=today)]
    return sorted(due, key=lambda a: days_waiting(a, today) or 0, reverse=True)


def _de_date(value) -> str:
    d = _parse_date(value)
    return d.strftime("%d.%m.%Y") if d else ""


def followup_text(app: dict, profile: Profile, lang: str = "de") -> str:
    """Kurze, sachliche Nachfrage per E-Mail (kein PDF, kein Anhang)."""
    name = str(profile.personal.get("name") or "")
    titel = str(app.get("titel") or "")
    firma = str(app.get("firma") or "")
    datum = _de_date(app.get("sentAt") or app.get("statusChangedAt"))
    if lang == "en":
        return (
            f"Subject: Follow-up on my application as {titel}\n\n"
            "Dear Hiring Manager,\n\n"
            f"On {datum} I applied to {firma} for the position of {titel}. "
            "As I have not heard back yet, I would like to ask about the current "
            "status of my application.\n\n"
            "I would appreciate a short update and am happy to answer any questions.\n\n"
            "Sincerely,\n"
            f"{name}\n"
        )
    return (
        f"Betreff: Nachfrage zu meiner Bewerbung als {titel}\n\n"
        "Sehr geehrte Damen und Herren,\n\n"
        f"am {datum} habe ich mich bei {firma} als {titel} beworben. Da ich bislang "
        "keine Rückmeldung erhalten habe, möchte ich mich nach dem aktuellen Stand "
        "erkundigen.\n\n"
        "Über eine kurze Rückmeldung freue ich mich. Für Rückfragen stehe ich Ihnen "
        "gerne zur Verfügung.\n\n"
        "Mit freundlichen Grüßen\n"
        f"{name}\n"
    )


def write_followup(app: dict, profile: Profile, lang: str = "de") -> Path | None:
    """Schreibt die Nachfrage in den Bewerbungsordner (neben die Unterlagen).

    Der Ordner wird aus der ersten PDF-Referenz abgeleitet — so landet der Text
    dort, wo die Bewerbung liegt. Fehlt der Ordner, wird nichts geschrieben
    (und nichts geraten).
    """
    from .config import AGENT_ROOT

    for rel in (app.get("dokumente") or {}).values():
        if not str(rel).lower().endswith(".pdf"):
            continue
        path = Path(rel)
        if not path.is_absolute():
            path = Path(AGENT_ROOT) / path
        folder = path.parent
        if not folder.exists():
            return None
        out = folder / f"Follow-up_{lang}.txt"
        out.write_text(followup_text(app, profile, lang), encoding="utf-8")
        return out
    return None


def run_followup(config, profile: Profile, after_days: int | None = None,
                 write: bool = False) -> dict:
    """Listet fällige Bewerbungen; mit ``write`` werden Nachfrage-Texte abgelegt."""
    from .db import Store

    days = after_days or int((config.data.get("followup") or {}).get("after_days")
                             or DEFAULT_AFTER_DAYS)
    apps = Store(config.db_path()).load_state().get("applications", [])
    due = due_applications(apps, after_days=days)
    written: list[str] = []
    if write:
        for app in due:
            path = write_followup(app, profile)
            if path:
                written.append(str(path))
    return {
        "after_days": days,
        "due": [{"firma": a.get("firma"), "titel": a.get("titel"),
                 "tage": days_waiting(a)} for a in due],
        "written": written,
        "geprueft": now_iso(),
    }
