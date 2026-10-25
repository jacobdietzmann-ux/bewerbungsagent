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
    run_enrich,
    run_generate,
    run_match,
    run_search,
)
from .profile import Profile
from .quality import run_quality

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
    enrich: dict
    generate: dict
    qualitaet: dict
    dashboard: dict

    # Zähler und Entscheidungen
    triage_rejected: int
    triage_unsure_verbleibend: int
    beschreibung_versuche: int
    beschreibung_umfang: str      # "nur_unsure" | "alle"

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
    """Zählt offene Nachlade-Kandidaten im Bestand.

    ``run_search`` hat domänenfremde Treffer bereits verworfen. Was bleibt, sind
    ``relevant`` (der Fit entscheidet) und ``unsure`` (der Titel reichte nicht).

    Welche Stellen nachgeladen werden, steuert ``beschreibung_umfang``:

    * ``nur_unsure`` (Standard) — nur die unklaren Fälle. Spart Browseraufrufe,
      weil der Titel für die meisten Stellen schon entscheidet.
    * ``alle`` — jede Stelle ohne Text. Nötig für den Wochenlauf: nur mit
      vollständigem Anzeigentext ist der Fit präzise (er zählt Text-Treffer
      mit 4 statt 2 Punkten pro Begriff).
    """
    config = state["config"]
    umfang = state.get("beschreibung_umfang", "nur_unsure")
    jobs_path = config.jobs_path()
    jobs = json.loads(jobs_path.read_text(encoding="utf-8")) if jobs_path.exists() else []
    ohne_text = [j for j in jobs if not (j.get("beschreibung") or "").strip()]
    if umfang == "alle":
        offen = ohne_text
    else:
        offen = [j for j in ohne_text
                 if triage.verdict_for(j, config).label == triage.UNSURE]
    return {
        "triage_unsure_verbleibend": len(offen),
        "weg": _notiere(state, "triage"),
    }


def knoten_beschreibung(state: Ablauf) -> Ablauf:
    """Lädt fehlende Anzeigentexte per Browser nach (begrenzt wiederholt).

    Nur hier wird der teure Browser-Fetch ausgelöst — und nur für die Stellen,
    die ``beschreibung_umfang`` vorgibt. Das ist der Kern der Verzweigung: das
    Fließband lädt entweder alles oder nichts.
    """
    from fetch_descriptions import fetch_descriptions

    nur_unsure = state.get("beschreibung_umfang", "nur_unsure") != "alle"
    for kwargs in ({"only_unsure": nur_unsure}, {}):
        try:
            fetch_descriptions(state["config"], **kwargs)
            break
        except TypeError:
            # Ältere Signatur ohne ``only_unsure``: dann ohne den Parameter.
            continue
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
    """Pendelweg, Gehalt, Aufräumen (Fit-Filter, Research-Fenster) und Auto-Unterlagen.

    Dieser Knoten war lange ein reiner Durchlauf mit Notiz: Der Graph lief
    ``match → enrich → generate``, aber ``run_enrich`` wurde nie aufgerufen.
    Damit fehlten im Tagesablauf genau die Schritte, die den Bestand
    entscheidbar halten — die Ausblendung unter der Fit-Grenze, das
    Research-Fenster und die Gehaltsschätzung. Der lineare Weg
    (``agent.py pipeline`` → ``run_full``) ruft ``run_enrich`` ebenfalls nicht
    auf; dort erzeugt ``run_generate`` die Unterlagen, hier tut es der Knoten
    selbst und ``run_generate`` überspringt danach bereits dokumentierte Stellen.
    """
    result = run_enrich(state["config"], state["profile"])
    return {"enrich": result, "weg": _notiere(state, "enrich")}


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


def knoten_qualitaet(state: Ablauf) -> Ablauf:
    """Prüft die erzeugten Unterlagen unabhängig (Datei-Ebene).

    Text-Befunde entstehen bereits bei der Generierung (``_generate_one``);
    dieser Knoten frischt die Datei-Prüfungen auf, damit ein abgebrochener
    Lauf oder ein manuell gelöschtes PDF sichtbar wird.
    """
    result = run_quality(state["config"])
    return {"qualitaet": result, "weg": _notiere(state, "qualitaet")}


def knoten_dashboard(state: Ablauf) -> Ablauf:
    """Dashboard rendern (Endzustand der Sicht)."""
    result = run_dashboard(state["config"])
    return {"dashboard": result, "weg": _notiere(state, "dashboard")}


# --------------------------------------------------------------------------
# Kanten-Entscheidungen
# --------------------------------------------------------------------------

def _braucht_beschreibung(state: Ablauf) -> Literal["beschreibung", "match"]:
    """Schleife: nachladen, solange Kandidaten offen sind und Versuche bleiben.

    Die Obergrenze ist Pflicht: ohne sie könnte die Schleife nicht terminieren,
    wenn ein Browseraufruf dauerhaft fehlschlägt (z. B. kein Netz).
    """
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
    g.add_node("qualitaet", knoten_qualitaet)
    g.add_node("dashboard", knoten_dashboard)

    g.add_edge(START, "suche")
    g.add_edge("suche", "triage")
    g.add_conditional_edges("triage", _braucht_beschreibung,
                            {"beschreibung": "beschreibung", "match": "match"})
    # Schleife: nach dem Nachladen erneut die offenen unsure-Fälle zählen.
    g.add_edge("beschreibung", "triage")
    g.add_edge("match", "enrich")
    g.add_edge("enrich", "generate")
    g.add_edge("generate", "qualitaet")

    if review:
        g.add_node("review", knoten_review)
        g.add_edge("qualitaet", "review")
        g.add_edge("review", "dashboard")
    else:
        g.add_edge("qualitaet", "dashboard")

    g.add_edge("dashboard", END)
    return g.compile()


def run_abo(config: Config, profile: Profile, *, review: bool = True,
            beschreibung: str = "nur_unsure", graph=None) -> Ablauf:
    """Führt den Graphen aus.

    ``review=False`` überspringt den Freigabe-Knoten. Sinnvoll, wenn die
    Bewertung ohnehin im Dashboard passiert: dort werden die Stellen geprüft und
    entweder verwendet oder manuell gelöscht.

    ``beschreibung`` steuert den Umfang des Nachladens:

    * ``"nur_unsure"`` (Standard) — nur Stellen, deren Titel für die Triage
      nicht reicht. Sparsam, für den schnellen Zwischenlauf.
    * ``"alle"`` — jede Stelle ohne Anzeigentext. Nötig für den Wochenlauf,
      damit der Fit auf dem vollständigen Text beruht.
    """
    if beschreibung not in ("nur_unsure", "alle"):
        raise ValueError("beschreibung muss 'nur_unsure' oder 'alle' sein")
    app = graph if graph is not None else build_graph(review=review)
    return app.invoke({"config": config, "profile": profile, "weg": [],
                       "beschreibung_umfang": beschreibung})
