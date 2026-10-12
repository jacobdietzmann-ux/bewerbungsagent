"""Extraktion von Labels (Ground Truth) aus ``state.json``.

## Label-Semantik

Die Statuswerte stammen aus dem manuell gepflegten Tracking-Dashboard. Die
Bedeutung wurde anhand der Tracking-Tabelle verifiziert:

- **positiv** (`sent`, `followup`, `interview`) — die Stelle wurde verfolgt,
  es wurden also Unterlagen versendet.
- **negativ** (`rejected` = „Abgelehnt/Abgelaufen") — die Stelle wurde
  **vom Nutzer verworfen** oder ist abgelaufen.

Beleg für diese Lesart: In der Tracking-Tabelle sind Stellen mit **87 %** und
**78 %** Profil-Fit als „Abgelehnt/Abgelaufen" markiert, während Stellen mit
71 % auf „Dokumente erstellt" stehen. Hohe Fit-Werte, die trotzdem nicht
verfolgt wurden, können keine Firmen-Absagen sein (es wurde nie beworben,
`sentAt` fehlt) — es sind Triage-Entscheidungen des Nutzers.

Nicht verwendet (unlabeled): `research`, `docs`, `neu` — hier steht die
Entscheidung noch aus; sie als negativ zu werten würde die Evaluation
systematisch verfälschen.

## Label-Rauschen

Ein Teil der `rejected`-Einträge sind **abgelaufene** Anzeigen, keine echten
Nutzerentscheidungen. Das ist bekanntes Label-Rauschen und eine Obergrenze für
die erreichbare Precision (siehe ``noise_estimate``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

POSITIVE_STATUSES = {"sent", "followup", "interview"}
NEGATIVE_STATUSES = {"rejected"}
UNLABELED_STATUSES = {"research", "docs", "neu", "passend"}

# Gründe für automatisches Löschen (keine Nutzerentscheidung → nicht als Label
# verwenden, auch wenn der Status theoretisch passt).
_AUTO_DELETE_REASON_HINTS = ("fit unter", "fit <", "fit <=", "fit <=",
                            "neubewertung", "duplikat", "pendelzeit")


@dataclass(frozen=True)
class LabeledEntry:
    """Ein gelabelter Datensatz: Vorhersage-Score + Ground-Truth-Label."""

    key: str
    firma: str
    titel: str
    status: str
    score: float
    label: bool
    has_description: bool
    auto_deleted: bool

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


def _is_auto_deleted(app) -> bool:
    if not app.get("deleted"):
        return False
    reason = (app.get("deleted_reason") or "").lower()
    return any(h in reason for h in _AUTO_DELETE_REASON_HINTS)


def load_state(path: str | Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    apps = data.get("applications", data) if isinstance(data, dict) else data
    return [a for a in apps if isinstance(a, dict)]


def build_dataset(apps: list[dict], include_auto_deleted: bool = False) -> list[LabeledEntry]:
    """Erzeugt den gelabelten Datensatz (nur eindeutig gelabelte Einträge)."""
    out: list[LabeledEntry] = []
    for a in apps:
        status = (a.get("status") or "").strip()
        if status in POSITIVE_STATUSES:
            label = True
        elif status in NEGATIVE_STATUSES:
            label = False
        else:
            continue
        forced = _is_auto_deleted(a)
        if forced and not include_auto_deleted:
            continue
        out.append(
            LabeledEntry(
                key=a.get("key") or f"{a.get('firma', '')}|{a.get('titel', '')}",
                firma=(a.get("firma") or "").strip(),
                titel=(a.get("titel") or "").strip(),
                status=status,
                score=fit_value(a),
                label=label,
                has_description=bool((a.get("beschreibung") or "").strip()),
                auto_deleted=forced,
            )
        )
    return out


def label_diagnostics(apps: list[dict]) -> dict:
    """Kennzahlen zur Label-Qualität — vor jeder Evaluation ausgeben!"""
    from collections import Counter

    status_counts = Counter((a.get("status") or "").strip() for a in apps)
    dataset = build_dataset(apps)
    with_desc = [e for e in dataset if e.has_description]
    noise = noise_estimate(dataset)
    return {
        "total_apps": len(apps),
        "status_counts": dict(status_counts),
        "labeled": len(dataset),
        "labeled_positive": sum(1 for e in dataset if e.label),
        "labeled_negative": sum(1 for e in dataset if not e.label),
        "labeled_with_description": len(with_desc),
        "labeled_with_description_positive": sum(1 for e in with_desc if e.label),
        "label_noise_estimate": noise,
    }


def noise_estimate(dataset: list[LabeledEntry]) -> dict:
    """Schätzt Label-Rauschen über verworfene Stellen mit hohem Fit.

    Heuristik: Eine *verworfene* Stelle mit sehr hohem Score (>= 70) ist
    entweder ein Modellfehler oder eine abgelaufene Anzeige. Beides sind
    Grenzen der erreichbaren Precision.
    """
    rejected_high = [e for e in dataset if not e.label and e.score >= 70]
    positives = [e for e in dataset if e.label]
    return {
        "rejected_with_high_score": len(rejected_high),
        "positives": len(positives),
        "note": "Verworfene Stellen mit Score >= 70 (abgelaufen oder Modellfehler)",
    }


def description_available(dataset: list[LabeledEntry]) -> int:
    return sum(1 for e in dataset if e.has_description)
