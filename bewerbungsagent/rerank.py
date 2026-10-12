"""Cross-Encoder-Reranking als Alternative zum Einzel-Vektor-Matching.

## Der Unterschied (das Kernkonzept)

**Bi-Encoder** (``semantic.py``): Profil und Stelle werden **getrennt** zu
Vektoren. Die Ähnlichkeit berechnet man danach per Kosinus.

```
Profil  ──▶ Transformer ──▶ Vektor ┐
                                   ├─▶ Kosinus
Stelle  ──▶ Transformer ──▶ Vektor ┘
```

**Cross-Encoder** (dieses Modul): Profil und Stelle gehen **gemeinsam** durch
den Transformer. Jedes Token der einen Seite kann auf jedes Token der anderen
schauen (full attention) — das Modell bewertet also direkt „passt diese Stelle
zu diesem Profil?".

```
[Profil | Stelle] ──▶ Transformer ──▶ Relevanz-Score
```

**Warum das präziser ist:** Beim Bi-Encoder müssen alle Informationen in *einen*
Vektor pro Text — Details gehen verloren. Das war genau das Problem aus
ADR-015: der Profil-Vektor wurde zu einem generischen „technischen
Ingenieur"-Vektor, der auf jede technische Stelle passt. Der Cross-Encoder
behält alle Details und kann sie gezielt vergleichen.

**Warum es trotzdem nicht immer die Lösung ist:** Der Score lässt sich nicht
vorberechnen. Für jede Kombination (Profil, Stelle) ist ein Forward-Pass nötig
— bei 836 Stellen und 150 ms pro Paar sind das ~2 Minuten pro Profiländerung.
Beim Bi-Encoder berechnet man die Stellen-Vektoren **einmal** und vergleicht
dann blitzschnell.

**Typische Architektur daher zweistufig:**
1. *Recall* (billig): Keyword oder Bi-Encoder filtert z. B. 800 → 50 Kandidaten.
2. *Rerank* (teuer, präzise): Cross-Encoder sortiert die 50.

## Modellwahl

``BAAI/bge-reranker-base`` (278M Parameter) ist multilingual und damit für
deutsche Stellenanzeigen und deutsche Profiltexte geeignet. Die
``ms-marco``-Reranker sind englisch trainiert und für diesen Datensatz
ungeeignet.
"""

from __future__ import annotations

from typing import Iterable, Sequence

DEFAULT_MODEL = "BAAI/bge-reranker-base"


class Reranker:
    """Cross-Encoder für die präzise Bewertung von (Profil, Stelle)-Paaren."""

    def __init__(self, model_name: str = DEFAULT_MODEL, device: str = "cpu",
                 max_length: int | None = 512):
        from sentence_transformers import CrossEncoder  # lokaler Import: optional

        self.model_name = model_name
        self.device = device
        # max_length begrenzt die Tokenzahl pro Paar. Das war der Silent Bug
        # aus ADR-015 — hier wird er explizit gesetzt statt implizit geerbt.
        kwargs = {"max_length": max_length} if max_length else {}
        self.model = CrossEncoder(model_name, device=device, **kwargs)
        self.max_length = max_length

    def score(self, profile_text: str, job_texts: Iterable[str],
              batch_size: int = 16, show_progress: bool = False) -> list[float]:
        """Relevanz-Score je Stelle (roh, modellabhängige Skala).

        Werte sind Logits: typischerweise hoch positiv = relevant, negativ =
        irrelevant. Die absolute Skala ist nicht kalibriert — für Entscheidungen
        zählt die Rangfolge bzw. ein per Evaluation bestimmter Schwellenwert.
        """
        job_texts = list(job_texts)
        if not job_texts:
            return []
        pairs = [(profile_text, t) for t in job_texts]
        out = self.model.predict(
            pairs, batch_size=batch_size, show_progress_bar=show_progress
        )
        return [float(x) for x in out]


def hybrid_rerank(keyword_scores: Sequence[float], rerank_scores: Sequence[float],
                  top_k: int = 50, weight: float = 1.0) -> list[tuple[int, float]]:
    """Zweistufig: Keyword wählt die Top-K aus, der Cross-Encoder sortiert sie.

    Gibt ``(index, score)``-Paare zurück — sortiert nach Rerank-Score.

    Durch das Vorfiltern spart man den Großteil der teuren Forward-Passes,
    ohne Recall zu verlieren, solange das Recall-Verfahren großzügig filtert.
    """
    if len(keyword_scores) != len(rerank_scores):
        raise ValueError("keyword_scores und rerank_scores müssen gleich lang sein")
    if top_k <= 0:
        raise ValueError("top_k muss > 0 sein")

    # Stufe 1: Recall über den Keyword-Score.
    candidates = sorted(range(len(keyword_scores)),
                        key=lambda i: -keyword_scores[i])[:top_k]
    # Stufe 2: Rerank innerhalb der Kandidaten.
    ranked = sorted(candidates, key=lambda i: -rerank_scores[i])
    return [(i, float(rerank_scores[i]) * weight) for i in ranked]
