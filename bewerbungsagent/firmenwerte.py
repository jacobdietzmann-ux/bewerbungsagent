"""Gehaltszufriedenheit je Firma (Indeed „Gehaltszufriedenheit").

Anteil der Bewerter, die ihre Bezahlung für angemessen halten, samt Zahl der
Bewertungen. Handgepflegt aus den Indeed-Firmenseiten ``/cmp/<Firma>/salaries``;
Firmen ohne Eintrag zeigt das Dashboard einfach ohne Wert. Bewertungszahlen
unter ~20 sind wackelig, deshalb steht ``n`` immer mit dabei.

Reine Daten, keine Abhängigkeiten, keine personenbezogenen Angaben.
"""

from __future__ import annotations

import re

STAND = "2026-11-10"

# Schlüssel = Vergleichsform des Firmennamens (siehe ``schluessel``).
# Wert = (Prozent zufrieden, Anzahl Bewertungen).
GEHALTSZUFRIEDENHEIT: dict[str, tuple[int, int]] = {
    "infineon": (89, 50),
    "brunel": (70, 27),
    "man truck bus": (73, 152),
    "e on": (46, 102),
    "hays": (50, 74),
    "rohde schwarz": (85, 20),
    "astrazeneca": (81, 11),
    "ferchau": (54, 77),
    "alten": (48, 29),
    "edag": (36, 47),
    "akkodis": (30, 23),
}

# Kununu „Gehälter“ (Stand ``STAND``): Ø Bruttojahresgehalt der passendsten Rolle am
# Standort der Firma. Wert = (Rolle, T€, Anzahl Gehaltsangaben). Nur Firmen, deren
# Kununu-Profil eindeutig die richtige Firma ist (Namen vorher gegengeprüft).
KUNUNU_GEHALT: dict[str, tuple[str, float, int]] = {
    "nvidia": ("Ingenieur", 112.2, 2),
    "infineon": ("Ingenieur", 81.5, 63),
    "rohde schwarz": ("Systemingenieur", 76.2, 13),
    "quantum systems": ("Systemingenieur", 67.0, 4),
    "man truck bus": ("Testingenieur", 71.9, 13),
    "ferchau": ("Testingenieur", 60.1, 27),
    "alten": ("Testingenieur", 58.2, 11),
    "brunel": ("Testingenieur", 58.0, 15),
    "edag": ("Testingenieur", 54.2, 53),
}

_RECHTSFORM_RE = re.compile(
    r"\b(?:gmbh|mbh|ag|se|kg|co|ug|inc|ltd|llc|group|holding|deutschland|germany)\b")


def schluessel(name: str | None) -> str:
    text = re.split(r"\s[-–—|]\s", (name or "").lower())[0]
    text = _RECHTSFORM_RE.sub(" ", re.sub(r"[^a-z0-9]+", " ", text))
    return " ".join(text.split())


def _wortanfang_treffer(tabelle: dict, firma: str | None):
    key = schluessel(firma)
    worte = key.split()
    for laenge in range(len(worte), 0, -1):
        treffer = tabelle.get(" ".join(worte[:laenge]))
        if treffer:
            return treffer
    return None


def kununu_gehalt(firma: str | None) -> dict | None:
    """``{"rolle": "Testingenieur", "tEuro": 60.1, "n": 27}`` oder ``None``."""
    treffer = _wortanfang_treffer(KUNUNU_GEHALT, firma)
    if not treffer:
        return None
    return {"rolle": treffer[0], "tEuro": treffer[1], "n": treffer[2]}


def zufriedenheit(firma: str | None) -> dict | None:
    """``{"pct": 85, "n": 20}`` oder ``None``, wenn für die Firma nichts vorliegt.

    Ein Eintrag gilt auch für längere Namen, die ihn am Wortanfang tragen
    („ALTEN Consulting Services" → „alten").
    """
    key = schluessel(firma)
    if not key:
        return None
    worte = key.split()
    for laenge in range(len(worte), 0, -1):
        treffer = GEHALTSZUFRIEDENHEIT.get(" ".join(worte[:laenge]))
        if treffer:
            return {"pct": treffer[0], "n": treffer[1]}
    return None
