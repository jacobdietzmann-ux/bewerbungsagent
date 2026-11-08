"""Die Schrittfolge aller Laufwege — hier und nirgends sonst (ADR-056).

``pipeline.run_full``, der Graph in ``orchestrator.py`` und ``scripts/jobwatch.py``
leiten ihre Schritte aus :data:`SCHRITTE` ab; die Shell-Skripte rufen
``agent.py ablauf`` auf und haben keine eigene Liste. Vorher führte jeder Laufweg
seine eigene Folge: ``run_full`` ließ ``fetch`` aus und bewertete neue Stellen nur
nach dem Titel, ``jobwatch`` kannte weder ``generate`` noch ``quality``.

Ein Schritt heißt überall gleich: ``name`` ist der Unterbefehl von ``agent.py``,
der Knoten im Graphen und der Schlüssel im Ergebnis eines Laufs.

Das Modul importiert nichts vom Projekt, damit ``jobwatch`` es ohne die schweren
Abhängigkeiten der Pipeline lesen kann.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")

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


def naechster_schritt(name: str) -> str:
    """Der Schritt nach ``name``; der letzte Schritt hat keinen Nachfolger."""
    return SCHRITT_NAMEN[SCHRITT_NAMEN.index(name) + 1]


def fuehre_aus(name: str, aufruf: Callable[[], T], fehler: dict[str, str]) -> T | None:
    """Führt einen Schritt aus: Nur ein optionaler Schritt darf scheitern.

    Der Fehler landet in ``fehler`` statt im Abbruch; jeder Laufweg kann ihn so am
    Ende melden. Ein Pflichtschritt reicht die Ausnahme weiter.
    """
    schritt = next(s for s in SCHRITTE if s.name == name)
    try:
        return aufruf()
    except Exception as exc:
        if not schritt.optional:
            raise
        fehler[name] = f"{type(exc).__name__}: {exc}"
        print(f"! Schritt {name} fehlgeschlagen, der Lauf geht weiter: {fehler[name]}")
        return None
