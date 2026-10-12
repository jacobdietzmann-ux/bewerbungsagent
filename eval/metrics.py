"""Reine Metrik-Funktionen für die Offline-Evaluation.

Bewusst ohne Abhängigkeiten und ohne Seiteneffekte — dadurch vollständig
unit-testbar. Alle Funktionen arbeiten auf Zählwerten bzw. flachen Listen.

Begriffe:
- **Positive Klasse** = „Stelle wurde weiterverfolgt" (der Nutzer hat sich beworben).
- **Negative Klasse** = „Stelle wurde verworfen/abgelehnt/abgelaufen".
- **Vorhersage** = `score >= threshold` → positiv.

Warnung: Bei stark unbalancierten Daten (hier ~86 % negativ) ist *Accuracy*
irreführend. Ein Modell, das immer „negativ" sagt, erreicht hohe Accuracy bei
Recall 0. Deshalb sind Precision/Recall/F1 die Leitmetriken.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Counts:
    """Konfusionsmatrix-Zähler (tp/fp/fn/tn)."""

    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    @property
    def total(self) -> int:
        return self.tp + self.fp + self.fn + self.tn

    @property
    def positives(self) -> int:
        return self.tp + self.fn

    @property
    def negatives(self) -> int:
        return self.tn + self.fp


def confusion_matrix(y_true: list[bool], y_pred: list[bool]) -> Counts:
    """Berechnet die Konfusionsmatrix zweier gleich langer Bool-Listen."""
    if len(y_true) != len(y_pred):
        raise ValueError("y_true und y_pred müssen gleich lang sein")
    tp = fp = fn = tn = 0
    for t, p in zip(y_true, y_pred):
        if t and p:
            tp += 1
        elif not t and p:
            fp += 1
        elif t and not p:
            fn += 1
        else:
            tn += 1
    return Counts(tp, fp, fn, tn)


def precision(c: Counts) -> float:
    """Anteil korrekter unter den als positiv vorhergesagten."""
    denom = c.tp + c.fp
    return c.tp / denom if denom else 0.0


def recall(c: Counts) -> float:
    """Anteil erkannter unter den tatsächlich positiven (Sensitivität)."""
    denom = c.tp + c.fn
    return c.tp / denom if denom else 0.0


def f1(c: Counts) -> float:
    """Harmonisches Mittel aus Precision und Recall."""
    p, r = precision(c), recall(c)
    return 2 * p * r / (p + r) if (p + r) else 0.0


def accuracy(c: Counts) -> float:
    """Anteil korrekter Vorhersagen gesamt (bei Imbalance irreführend!)."""
    return (c.tp + c.tn) / c.total if c.total else 0.0


def specificity(c: Counts) -> float:
    """Anteil korrekt erkannter Negativer (True Negative Rate)."""
    denom = c.tn + c.fp
    return c.tn / denom if denom else 0.0


def balanced_accuracy(c: Counts) -> float:
    """Mittel aus Recall und Specificity — robust gegen Klassen-Ungleichgewicht."""
    return (recall(c) + specificity(c)) / 2


def evaluate_at(labeled: list[tuple[float, bool]], threshold: float) -> Counts:
    """Wertet (score, label)-Paare bei einem Schwellenwert aus."""
    y_true = [lab for _, lab in labeled]
    y_pred = [score >= threshold for score, _ in labeled]
    return confusion_matrix(y_true, y_pred)


def threshold_sweep(
    labeled: list[tuple[float, bool]], thresholds: list[float] | None = None
) -> list[tuple[float, Counts]]:
    """Wertet alle Schwellenwerte aus (Standard: 0..100 in 5er-Schritten)."""
    if thresholds is None:
        thresholds = [float(t) for t in range(0, 101, 5)]
    return [(t, evaluate_at(labeled, t)) for t in thresholds]


def best_by_f1(sweep: list[tuple[float, Counts]]) -> tuple[float, Counts]:
    """Schwellenwert mit dem höchsten F1 (Tie-Break: höherer Schwellenwert)."""
    return max(sweep, key=lambda tc: (f1(tc[1]), tc[0]))


def majority_baseline(labeled: list[tuple[float, bool]]) -> Counts:
    """Baseline: sagt immer die häufigere Klasse vorher (hier i. d. R. negativ)."""
    n_pos = sum(1 for _, lab in labeled if lab)
    n_neg = len(labeled) - n_pos
    always_positive = n_pos > n_neg
    y_true = [lab for _, lab in labeled]
    y_pred = [always_positive] * len(labeled)
    return confusion_matrix(y_true, y_pred)
