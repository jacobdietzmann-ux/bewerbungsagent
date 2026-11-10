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

_RECHTSFORM_RE = re.compile(
    r"\b(?:gmbh|mbh|ag|se|kg|co|ug|inc|ltd|llc|group|holding|deutschland|germany)\b")


def schluessel(name: str | None) -> str:
    text = re.split(r"\s[-–—|]\s", (name or "").lower())[0]
    text = _RECHTSFORM_RE.sub(" ", re.sub(r"[^a-z0-9]+", " ", text))
    return " ".join(text.split())


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
