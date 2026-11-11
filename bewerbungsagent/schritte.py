"""Die Schrittfolge des Tageslaufs — hier und nirgends sonst (ADR-056).

``scripts/jobwatch.py`` ruft jeden Schritt als ``agent.py <name>`` auf. ``name``
ist der Unterbefehl von ``agent.py`` und der Schlüssel im Lauf-Protokoll.

Das Modul importiert nichts vom Projekt, damit ``jobwatch`` es ohne die schweren
Abhängigkeiten der Pipeline lesen kann.
"""

from __future__ import annotations

from dataclasses import dataclass

# Anzeigen pro Lauf nachladen (Browser). 300 × ~2,5 s ≈ 12 Minuten; der Rest kommt
# im nächsten Lauf dran, weil geladene Texte im Bestand bleiben.
FETCH_LIMIT = 300


@dataclass(frozen=True)
class Schritt:
    """Ein Arbeitsschritt eines Laufs.

    ``argumente`` sind die Zusatzargumente für ``agent.py <name>``. Ein
    ``optional``-er Schritt darf scheitern, ohne die folgenden zu verhindern.
    """

    name: str
    argumente: tuple[str, ...] = ()
    optional: bool = False


SCHRITTE: tuple[Schritt, ...] = (
    Schritt("search"),
    # Ohne Text bewertet ``match`` nur den Titel; der nächste Lauf holt das nach.
    Schritt("fetch", ("--limit", str(FETCH_LIMIT)), optional=True),
    Schritt("match"),
    Schritt("enrich"),
    Schritt("generate", ("--all",)),
    # Die Prüfung ergänzt nur Befunde: Das Dashboard soll auch ohne sie entstehen.
    Schritt("quality", optional=True),
    Schritt("dashboard"),
)

SCHRITT_NAMEN: tuple[str, ...] = tuple(s.name for s in SCHRITTE)
