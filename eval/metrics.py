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
from typing import Sequence


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


def roc_auc(labeled: list[tuple[float, bool]]) -> float:
    """Area under the ROC curve (schwellenunabhängige Rangfolge-Qualität).

    Interpretation: Die Wahrscheinlichkeit, dass eine zufällig gewählte
    **passende** Stelle einen höheren Score bekommt als eine zufällig gewählte
    **unpassende**.

    - 0.5 = Zufall (Score ohne Information)
    - 1.0 = perfekte Trennung
    - 0.0 = perfekt invertiert

    Berechnung über die Mann-Whitney-U-Statistik (rangbasiert, ohne Schwellen):
        AUC = (U - n1*(n1+1)/2) / (n1*n2)
    Bindungen (gleiche Scores) werden über Durchschnittsränge korrekt behandelt.

    **Warum das hier die richtige Metrik ist:** F1 hängt vom gewählten
    Schwellenwert ab und ist bei kleiner Stichprobe instabil. AUC misst, wie
    gut ein Verfahren die Klassen *sortiert* — unabhängig davon, wo man die
    Grenze zieht. Genau das ist bei Empfehlungssystemen die eigentliche Frage.
    """
    pos = [s for s, lab in labeled if lab]
    neg = [s for s, lab in labeled if not lab]
    n1, n2 = len(pos), len(neg)
    if n1 == 0 or n2 == 0:
        return 0.5  # undefiniert -> neutraler Wert

    # Durchschnittsränge über die gesamte Liste (Bindungen gleich behandeln).
    combined = sorted(labeled, key=lambda t: t[0])
    ranks: dict[int, float] = {}
    i = 0
    while i < len(combined):
        j = i
        while j + 1 < len(combined) and combined[j + 1][0] == combined[i][0]:
            j += 1
        avg_rank = (i + j) / 2 + 1  # Ränge sind 1-basiert
        for k in range(i, j + 1):
            ranks[k] = avg_rank
        i = j + 1

    rank_sum_pos = sum(ranks[k] for k, (_, lab) in enumerate(combined) if lab)
    u = rank_sum_pos - n1 * (n1 + 1) / 2
    return u / (n1 * n2)


def auc_interpretation(auc: float) -> str:
    """Verbale Einordnung eines AUC-Werts."""
    if auc >= 0.90:
        return "sehr gut"
    if auc >= 0.80:
        return "gut"
    if auc >= 0.70:
        return "brauchbar"
    if auc >= 0.60:
        return "schwach"
    if auc > 0.55:
        return "kaum besser als Zufall"
    return "ohne Aussagekraft (Zufallsniveau)"


def precision_at_k(scores: "Sequence[float]", labels: "Sequence[bool]", k: int) -> float:
    """Anteil passender unter den Top-k nach Score.

    Die betrieblich relevanteste Kennzahl für Empfehlungssysteme: „Wenn ich
    mir die besten k Stellen ansehe, wie viele passen wirklich?"

    Bewusst **ohne numpy** implementiert, damit dieses Modul abhängigkeitsfrei
    bleibt (die Vektor-Berechnungen der Experimente brauchen numpy, die
    Metriken nicht).
    """
    if k <= 0:
        raise ValueError("k muss > 0 sein")
    if len(scores) != len(labels):
        raise ValueError("scores und labels müssen gleich lang sein")
    n = len(scores)
    if n == 0:
        return 0.0
    k = min(k, n)
    order = sorted(range(n), key=lambda i: -scores[i])[:k]
    return sum(1 for i in order if labels[i]) / k


def mean_by_label(scores: "Sequence[float]", labels: "Sequence[bool]") -> tuple[float, float]:
    """Mittelwert der Scores getrennt nach Label (für die Trennkraft-Analyse)."""
    pos = [s for s, lab in zip(scores, labels) if lab]
    neg = [s for s, lab in zip(scores, labels) if not lab]
    return (sum(pos) / len(pos) if pos else 0.0,
            sum(neg) / len(neg) if neg else 0.0)
