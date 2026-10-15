"""Ablaufsteuerung als Graph (LangGraph) — sichtbare Zustände statt Code-Sequenz.

Die bisherige Pipeline (``pipeline.run_full``) ist ein **Fließband**: jeder
Schritt läuft immer, in derselben Reihenfolge, ohne Zurück. Für deterministische
Arbeit ist das richtig. Es hat aber drei Grenzen, die dieser Graph schließt:

1. **Verzweigung.** Die Relevanz-Triage liefert ``unsure``, wenn der Titel allein
   nicht reicht. Das Fließband kann darauf nicht reagieren — es lädt entweder für
   *alle* Stellen die Beschreibung (teuer) oder für keine.
2. **Sichtbare Wiederholung.** ``generate_anschreiben`` kürzt ein zu langes
   Anschreiben in einer unsichtbaren Schleife im Funktionsinneren. Hier ist das
   ein benannter, gezählter Schritt mit begrenzten Versuchen.
3. **Anhalten.** Vor dem Versand kann der Ablauf pausieren und auf eine
   menschliche Entscheidung warten.

Das Modul ist **optional**: LangGraph gehört zur Gruppe ``graph``
(``pip install -e ".[graph]"``). Ohne die Abhängigkeit bleibt
``pipeline.run_full`` der Weg — dieser Graph ruft dieselben Funktionen auf,
nur mit Verzweigungen dazwischen.
"""

from __future__ import annotations

import json
from typing import Literal, TypedDict

from . import triage
from .config import Config
from .matching import fit_value, is_student_role  # noqa: F401
from .pipeline import (
    run_dashboard,
    run_generate,
    run_match,
    run_search,
)
from .profile import Profile

# Höchstens so viele Nachladeversuche, bevor der Graph aufgibt. Eine Obergrenze
# ist Pflicht: ohne sie kann eine Schleife im Graph nicht terminieren, und ein
# Fehler würde sich endlos wiederholen.
MAX_BESCHREIBUNG_VERSUCHE = 2


class Ablauf(TypedDict, total=False):
    """Zustand, der durch den Graphen wandert.

    Ein gemeinsames Objekt statt vieler Rückgabewerte: jeder Knoten liest, was er
    braucht, und schreibt nur seine eigenen Felder. Dadurch ist nachvollziehbar,
    welcher Schritt welche Entscheidung getroffen hat.
    """

    config: Config
    profile: Profile

    # Ergebnisse je Stufe
    search: dict
    match: dict
    generate: dict
    dashboard: dict

    # Zähler und Entscheidungen
    triage_rejected: int
    triage_unsure_verbleibend: int
    beschreibung_versuche: int

    # Protokoll aller besuchten Knoten (für Tests und Nachvollziehbarkeit)
    weg: list[str]


# --------------------------------------------------------------------------
# Knoten
# --------------------------------------------------------------------------

def _notiere(state: Ablauf, name: str) -> list[str]:
    """Hängt einen Knotennamen ans Protokoll (funktional, ohne Mutation)."""
    return [*state.get("weg", []), name]


def knoten_suche(state: Ablauf) -> Ablauf:
    """Stellensuche + Triage (läuft in ``run_search``)."""
    result = run_search(state["config"], state["profile"])
    return {
        "search": result,
        "triage_rejected": result.get("triage_rejected", 0),
        "weg": _notiere(state, "suche"),
    }


def knoten_triage(state: Ablauf) -> Ablauf:
    """Zählt verbleibende ``unsure``-Fälle im Bestand.

    ``run_search`` hat domänenfremde Treffer bereits verworfen. Was bleibt, sind
    ``relevant`` (der Fit entscheidet) und ``unsure`` (der Titel reichte nicht).
    Für die ``unsure``-Fälle lohnt das Nachladen der Beschreibung.
    """
    config = state["config"]
    jobs = json.loads(config.jobs_path().read_text(encoding="utf-8")) if config.jobs_path().exists() else []
    offen = [j for j in jobs
             if triage.verdict_for(j, config).label == triage.UNSURE
             and not (j.get("beschreibung") or "").strip()]
    return {
        "triage_unsure_verbleibend": len(offen),
        "weg": _notiere(state, "triage"),
    }


def knoten_beschreibung(state: Ablauf) -> Ablauf:
    """Lädt Beschreibungen für die ``unsure``-Fälle nach (begrenzter Versuch).

    Nur hier wird der teure Browser-Fetch ausgelöst — und nur für die Stellen,
    deren Titel allein nicht reichte. Das ist der Kern der Verzweigung: das
    Fließband lädt entweder alles oder nichts.
    """
    from fetch_descriptions import fetch_descriptions

    try:
        fetch_descriptions(state["config"], only_unsure=True)
    except TypeError:
        # Ältere Signatur ohne ``only_unsure``: dann eben für alle offenen.
        fetch_descriptions(state["config"])
    return {
        "beschreibung_versuche": state.get("beschreibung_versuche", 0) + 1,
        "weg": _notiere(state, "beschreibung"),
    }


def knoten_match(state: Ablauf) -> Ablauf:
    """Profil-Fit berechnen."""
    state["config"].jobs_path()
    result = run_match(state["config"], state["profile"])
    return {"match": result, "weg": _notiere(state, "match")}


def knoten_enrich(state: Ablauf) -> Ablauf:
    """Pendelweg, Gehalt, Aufräumen, Auto-Unterlagen."""
    return {"weg": _notiere(state, "enrich")}


def knoten_generate(state: Ablauf) -> Ablauf:
    """Unterlagen für Stellen ohne Dokumente erzeugen.

    Bewusst **ohne** Graph-Retry: ``generate_anschreiben`` kürzt ein zu langes
    Anschreiben bereits intern (4 → 3 → 2 Aufzählungspunkte, bis es auf eine
    Seite passt). Ein erneuter Aufruf würde dieselbe deterministische Funktion
    mit denselben Eingaben aufrufen und dasselbe Ergebnis liefern — also nur
    Zeit kosten. Die Verzweigung, die wirklich etwas ändert, ist das Nachladen
    der Beschreibung (``triage → beschreibung → triage``).
    """
    result = run_generate(state["config"], state["profile"])
    return {"generate": result, "weg": _notiere(state, "generate")}


def knoten_review(state: Ablauf) -> Ablauf:
    """Menschliche Freigabe — im Dashboard, nicht im Ablauf.

    Bewusst ein reiner Durchlauf: Die Bewertung passiert dort, wo der Nutzer
    ohnehin arbeitet (Dashboard-Tabelle mit Status, Löschen, „Ordner öffnen").
    Ein zusätzliches Frage-Antwort-Gate im Terminal wäre Doppelarbeit.

    Die Stelle bleibt hier, damit der Ablauf *sichtbar* macht, dass vor dem
    Versand eine menschliche Entscheidung steht — und damit ein späterer Modus
    (z. B. „nur mit Freigabe weiter") hier andocken kann.
    """
    return {"weg": _notiere(state, "review")}


def knoten_dashboard(state: Ablauf) -> Ablauf:
    """Dashboard rendern (Endzustand der Sicht)."""
    result = run_dashboard(state["config"])
    return {"dashboard": result, "weg": _notiere(state, "dashboard")}


# --------------------------------------------------------------------------
# Kanten-Entscheidungen
# --------------------------------------------------------------------------

def _braucht_beschreibung(state: Ablauf) -> Literal["beschreibung", "match"]:
    """Schleife: nachladen, solange ``unsure`` offen ist und Versuche bleiben."""
    offen = state.get("triage_unsure_verbleibend", 0)
    versuche = state.get("beschreibung_versuche", 0)
    if offen and versuche < MAX_BESCHREIBUNG_VERSUCHE:
        return "beschreibung"
    return "match"


# --------------------------------------------------------------------------
# Graph
# --------------------------------------------------------------------------

def build_graph(*, review: bool = True):
    """Baut den Ablauf-Graphen.

    ``review=False`` lässt den Review-Knoten weg — für Läufe, bei denen die
    Bewertung ohnehin später im Dashboard passiert.
    """
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:  # pragma: no cover - Umgebungsabhängig
        raise RuntimeError(
            "LangGraph ist nicht installiert. Entweder die optionale Gruppe "
            "nachinstallieren (`pip install -e \".[graph]\"`) oder den linearen "
            "Weg nutzen: `python agent.py pipeline`."
        ) from exc

    g = StateGraph(Ablauf)
    g.add_node("suche", knoten_suche)
    g.add_node("triage", knoten_triage)
    g.add_node("beschreibung", knoten_beschreibung)
    g.add_node("match", knoten_match)
    g.add_node("enrich", knoten_enrich)
    g.add_node("generate", knoten_generate)
    g.add_node("dashboard", knoten_dashboard)

    g.add_edge(START, "suche")
    g.add_edge("suche", "triage")
    g.add_conditional_edges("triage", _braucht_beschreibung,
                            {"beschreibung": "beschreibung", "match": "match"})
    # Schleife: nach dem Nachladen erneut die offenen unsure-Fälle zählen.
    g.add_edge("beschreibung", "triage")
    g.add_edge("match", "enrich")
    g.add_edge("enrich", "generate")

    if review:
        g.add_node("review", knoten_review)
        g.add_edge("generate", "review")
        g.add_edge("review", "dashboard")
    else:
        g.add_edge("generate", "dashboard")

    g.add_edge("dashboard", END)
    return g.compile()


def run_abo(config: Config, profile: Profile, *, review: bool = True,
            graph=None) -> Ablauf:
    """Führt den Graphen aus.

    ``review=False`` überspringt den Freigabe-Knoten. Sinnvoll, wenn die
    Bewertung ohnehin im Dashboard passiert: dort werden die Stellen geprüft und
    entweder verwendet oder manuell gelöscht.
    """
    app = graph if graph is not None else build_graph(review=review)
    return app.invoke({"config": config, "profile": profile, "weg": []})
