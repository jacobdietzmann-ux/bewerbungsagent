"""Extraktion von **Eignungs**-Labels (Ground Truth) für die Evaluation.

## Grundregel

Der ``status`` eines Eintrags beschreibt den **Bewerbungsprozess**
(``research`` → ``docs`` → ``sent`` → ``interview`` → Absage/Abgelaufen) und
ist **kein Maß für Eignung**. Er darf deshalb *nicht* als Fit-Label dienen.
Siehe ``docs/DECISIONS.md`` → ADR-012.

Insbesondere gilt:
- ``sent`` / ``followup`` / ``interview`` / ``rejected`` = **alle**
  „beworben" (bei ``rejected`` wurde die Bewerbung von der **Firma**
  abgelehnt — das sagt nichts über die Eignung).
- Löschungen mit Begründung „Fit ≤ 60 %" sind **zirkulär** (das Modell würde
  gegen seine eigene Entscheidung gemessen).

## Verwendbare Quellen

1. **Explizite Eignungsurteile des Nutzers** — ``eval/labels.csv``
   (erzeugt mit ``eval/label_tool.py``). Das ist die belastbare Quelle.
2. **Grobe Negative aus dem Bestand**: Einträge, die als
   „Nicht passende Rolle (kein technisches Profil)" verworfen wurden. Das ist
   eine *inhaltliche* (nicht score-basierte) Ablehnung — brauchbar, aber grob
   (überwiegend Finance/HR/Controlling/Werkstudent).

Alles andere bleibt **unlabeled** und wird aus der Evaluation ausgeschlossen.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Verwurfsgrund, der ein *inhaltliches* Eignungsurteil darstellt.
EXPLICIT_NEGATIVE_REASON = "Nicht passende Rolle (kein technisches Profil)"

# Score-basierte Verwurfsgründe → zirkulär, NIE als Label verwenden.
CIRCULAR_DELETE_HINTS = ("fit unter", "fit <", "fit <=", "neubewertung",
                         "pendelzeit", "duplikat")

DEFAULT_LABELS_CSV = Path(__file__).parent / "labels.csv"


@dataclass(frozen=True)
class LabeledEntry:
    """Ein Datensatz mit Eignungs-Label: Score + Ground Truth."""

    key: str
    firma: str
    titel: str
    score: float
    label: bool
    source: str  # "manual" | "explicit_reject"
    has_description: bool

    @property
    def display(self) -> str:
        return f"{self.firma} — {self.titel}"[:80]


def fit_value(app) -> float:
    """Einheitlicher Fit-Wert: ``fit_pct`` (alt) hat Vorrang vor ``score`` (neu)."""
    raw = app.get("fit_pct")
    if raw is None:
        raw = app.get("score")
    try:
        return float(raw) if raw is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def entry_key(app: dict) -> str:
    return app.get("key") or f"{app.get('firma', '')}|{app.get('titel', '')}"


def load_state(path: str | Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    apps = data.get("applications", data) if isinstance(data, dict) else data
    return [a for a in apps if isinstance(a, dict)]


def load_manual_labels(path: str | Path = DEFAULT_LABELS_CSV) -> dict[str, bool]:
    """Liest manuell gesetzte Labels (``key`` → passt?).

    CSV-Format (Kopfzeile erforderlich):
        key,label
        "<firma>|<titel>",1

    ``label`` ∈ {1, 0, ja, nein, true, false, passt, passt_nicht}.
    """
    path = Path(path)
    if not path.exists():
        return {}
    truthy = {"1", "ja", "j", "true", "wahr", "passt", "yes", "y"}
    falsy = {"0", "nein", "n", "false", "falsch", "passt_nicht", "no"}
    out: dict[str, bool] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            key = (row.get("key") or "").strip()
            raw = (row.get("label") or "").strip().lower()
            if not key:
                continue
            if raw in truthy:
                out[key] = True
            elif raw in falsy:
                out[key] = False
    return out


def build_dataset(
    apps: list[dict],
    manual_labels: dict[str, bool] | None = None,
    include_explicit_rejects: bool = True,
) -> list[LabeledEntry]:
    """Erzeugt den gelabelten Datensatz aus *Eignungs*-Quellen.

    Manuelle Labels haben Vorrang vor abgeleiteten.
    """
    manual_labels = manual_labels or {}
    out: list[LabeledEntry] = []
    for a in apps:
        key = entry_key(a)
        has_desc = bool((a.get("beschreibung") or "").strip())
        if key in manual_labels:
            out.append(LabeledEntry(key, (a.get("firma") or "").strip(),
                                    (a.get("titel") or "").strip(),
                                    fit_value(a), manual_labels[key], "manual", has_desc))
        elif include_explicit_rejects and (a.get("deleted_reason") or "") == EXPLICIT_NEGATIVE_REASON:
            out.append(LabeledEntry(key, (a.get("firma") or "").strip(),
                                    (a.get("titel") or "").strip(),
                                    fit_value(a), False, "explicit_reject", has_desc))
    return out


def is_circular(app: dict) -> bool:
    """True, wenn die Löschung *score-basiert* ist → als Label unbrauchbar."""
    reason = (app.get("deleted_reason") or "").lower()
    return any(h in reason for h in CIRCULAR_DELETE_HINTS)


def diagnostics(apps: list[dict], manual_labels: dict[str, bool] | None = None) -> dict:
    """Kennzahlen zur Label-Lage — vor jeder Evaluation ausgeben."""
    from collections import Counter

    manual_labels = manual_labels or {}
    status_counts = Counter((a.get("status") or "").strip() for a in apps)
    n_applied = sum(1 for a in apps if (a.get("sentAt") or "").strip())
    explicit = [a for a in apps if (a.get("deleted_reason") or "") == EXPLICIT_NEGATIVE_REASON]
    circular = [a for a in apps if a.get("deleted") and is_circular(a)]
    ds = build_dataset(apps, manual_labels)
    return {
        "total_apps": len(apps),
        "status_counts": dict(status_counts),
        "applied_but_not_a_fit_label": n_applied,
        "explicit_reject_negatives": len(explicit),
        "circular_deletes_excluded": len(circular),
        "manual_labels": len(manual_labels),
        "dataset_size": len(ds),
        "dataset_positive": sum(1 for e in ds if e.label),
        "dataset_negative": sum(1 for e in ds if not e.label),
        "dataset_with_description": sum(1 for e in ds if e.has_description),
    }


def write_dataset_csv(entries: list[LabeledEntry], path: str | Path) -> None:
    """Schreibt den gelabelten Datensatz als CSV (Reproduzierbarkeit)."""
    path = Path(path)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["key", "firma", "titel", "score", "label", "source", "has_description"])
        for e in entries:
            w.writerow([e.key, e.firma, e.titel, f"{e.score:.0f}",
                        int(e.label), e.source, int(e.has_description)])


def append_manual_label(key: str, label: bool,
                        path: str | Path = DEFAULT_LABELS_CSV) -> None:
    """Hängt ein manuelles Label an die CSV an (Kopfzeile wird angelegt)."""
    path = Path(path)
    new_file = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        if new_file:
            w.writerow(["key", "label", "timestamp"])
        w.writerow([key, int(label), datetime.now().isoformat(timespec="seconds")])
