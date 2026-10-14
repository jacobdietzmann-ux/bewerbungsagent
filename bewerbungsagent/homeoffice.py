"""Erkennung des Homeoffice-Anteils aus der Stellenbeschreibung.

Viele Anzeigen nennen den Homeoffice-Umfang nicht als eigenes Feld, sondern im
Fließtext („hybrides Arbeitsmodell", „bis zu 2 Tage Homeoffice pro Woche",
„100 % remote"). Dieses Modul klassifiziert die Stelle in eine von fünf
Stufen, damit das Dashboard den Anteil transparent anzeigen kann.

Die Reihenfolge ist bewusst von *spezifisch* nach *generisch*: „100 % remote"
schlägt ein allgemeines „remote", und ein allgemeines „remote/homeoffice"
schlägt „vor Ort" — eine Stelle, die Homeoffice nennt, ist kein reiner
Präsenzjob.
"""

from __future__ import annotations

import re

from .profile import normalize

# Von spezifisch nach generisch. Jede Stufe liefert Kategorie + Anzeige-Label.
_RULES: list[tuple[str, str, str]] = [
    # (Kategorie, Label, Muster)
    ("Voll-Remote", "100 % remote",
     r"100\s*%\s*remote|fully\s+remote|voll(?:ständig)?\s*remote|remote[- ]?first"),
    ("Hybrid", "hybrid",
     r"\bhybrid(?:es|e)?\b|\d+\s*(?:tage?)\s+(?:home\s?-?office|remote)"),
    # Bewusst NICHT das nackte ``remote``: in englischen Anzeigen heißt das oft
    # „remote test sites" (entfernte Prüfstandorte), nicht Homeoffice.
    ("Homeoffice möglich", "homeoffice möglich",
     r"home\s?-?office|\bmobiles?\s+arbeiten|work(?:ing)?\s+from\s+home|"
     r"remote\s+(?:work|working|option|m[öo]glich)|teilweise\s+(?:im\s+)?home"),
    ("Vor Ort", "vor Ort",
     r"on\s?-?site|\bvor\s+ort\b|\bpr[äa]senz|onsite"),
]


def detect_home_office(job: dict) -> str:
    """Klassifiziert den Homeoffice-Anteil aus Titel und Beschreibung.

    Rückgabe ist eine der fünf Stufen: ``Voll-Remote``, ``Hybrid``,
    ``Homeoffice möglich``, ``Vor Ort`` oder ``Unbekannt``.
    """
    text = normalize(f"{job.get('titel', '')} {job.get('beschreibung', '')}")
    if not text.strip():
        return "Unbekannt"
    for category, _label, pattern in _RULES:
        if re.search(pattern, text):
            return category
    return "Unbekannt"


def home_office_grund(job: dict) -> str:
    """Der konkret gefundene Beleg (für Nachvollziehbarkeit im Dashboard)."""
    text = job.get("beschreibung", "") or ""
    low = text.lower()
    for _category, _label, pattern in _RULES:
        m = re.search(pattern, low)
        if m:
            s = text[max(0, m.start() - 30): m.end() + 40]
            return " ".join(s.split())
    return ""
