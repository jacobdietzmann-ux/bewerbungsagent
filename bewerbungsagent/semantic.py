"""Semantisches Matching: Vergleich von Profil und Stellen über Embeddings.

## Status: EXPERIMENTELL — Hypothese widerlegt (ADR-015)

Getestet wurde die Annahme, semantische Ähnlichkeit schlage das
Keyword-Matching. **Ergebnis: nein.** Auf den harten Labels (technische, aber
unpassende Stellen):

| Verfahren | AUC | Precision@5 |
|---|---|---|
| Keyword-Fit | **0.715** | **100 %** |
| Semantisch (e5-base, Einzel-Vektor) | 0.550 | 40 % |

AUC 0.550 entspricht **Zufallsniveau**. Das Modul bleibt als Experiment
erhalten, ist aber nicht für Empfehlungen geeignet.

## Warum es scheitert (die eigentliche Lehre)

1. **Ein einzelner Profil-Vektor verwischt die Unterscheidungskraft.**
   Das Profil wird zu einem generischen „technischen Ingenieur"-Vektor. Der
   passt auf *jede* technische Stelle — ob Testautomotive, SAP-Testmanagement
   oder Embedded-Entwicklung. Genau die Details, die unterscheiden, sind im
   Mittelwert verschwunden.

2. **Kosinus-Ähnlichkeit ist ein grobes Maß.** Gemessenes Band über 230
   Stellen: 0.79–0.88. Die Rangfolge innerhalb dieses Bandes ist kaum
   aussagekräftig.

3. **Ein echter Silent Bug** (behoben): E5 schneidet bei 512 Token ab.
   Der ursprüngliche Profil-Text hatte ~1484 Token — es wurde also nur die
   erste Station eingebettet, der Rest verschwand stillschweigend. Fix: eine
   kompakte Profil-Anfrage (``build_profile_query``). Das hob die AUC von
   0.776 auf ~0.93 — der größte Einzeleffekt im ganzen Experiment.

## Was das über die Methodik lehrt

- **Eingabe-Aufbereitung schlägt Modellwahl.** Bevor man ein größeres Modell
  probiert, muss die Anfrage zum Trainings-Setup des Modells passen.
- **Ein Ergebnis „es funktioniert nicht" ist ein Ergebnis.** Es hat drei Tage
  an Fehlannahmen erspart.
- **Confound prüfen:** Die 212 groben Negative des Bestands sind
  *nicht-technische* Berufe (Finance, HR, Schweißlehrer). Beide Verfahren
  trennen die mühelos — das täuscht über die Schwäche bei *technischen*
  Fehlpaarungen hinweg.

## Ausblick

Bessere Ansätze als ein Einzel-Vektor:

- **Cross-Encoder-Reranking:** Profil und Stelle werden *gemeinsam* durch das
  Modell geschickt (statt zwei getrennte Vektoren). Deutlich präziser, aber
  ein Forward-Pass pro Paar — nur für die Top-K sinnvoll.
- **Facetten-Matching:** nicht ein Profil-Vektor, sondern je Anforderung
  („HiL-Test", „Python", „Automotive") ein eigener Vergleich.
- **Hybrid:** Keyword als Recall-Filter, Semantik als Reranker.

## Funktionsprinzip (technisch)

1. Text → Token → Transformer → Vektor fester Länge (z. B. 768 Zahlen).
2. Ähnlichkeit = Kosinus (längenunabhängig).
3. E5 erwartet Präfixe: ``"query: "`` für die Anfrage, ``"passage: "`` für
   Dokumente. Fehlen sie, sinkt die Qualität deutlich.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

DEFAULT_MODEL = "intfloat/multilingual-e5-base"

# Modelle mit E5-Konvention benötigen query:/passage:-Präfixe.
_E5_MODELS = ("e5",)


def _needs_e5_prefix(model_name: str) -> bool:
    return any(tag in model_name.lower() for tag in _E5_MODELS)


def build_profile_query(profile_data: dict, max_chars: int = 900) -> str:
    """Baut eine **kompakte** Profil-Anfrage für das semantische Matching.

    Warum kompakt? Gemessen wurde (ADR-015):

    - Voller Profil-Dump (5939 Zeichen) → AUC 0.776
    - Kompakte Anfrage (~700 Zeichen)   → AUC 0.980

    Ursache: E5 ist auf **kurze Anfragen gegen lange Dokumente** trainiert und
    schneidet bei 512 Token ab. Ein 1484-Token-Profil wird also abgeschnitten
    (nur die erste Station bleibt übrig) und driftet zu einem generischen
    Mittelwert, der auf fast alles passt.

    Die Funktion erzeugt die Anfrage **aus den Profildaten** (nicht
    hartkodiert): zuerst die aktuellsten Rollen, dann die wichtigsten
    Fachbegriffe, dann Ausbildung — auf ``max_chars`` begrenzt.
    """
    parts: list[str] = []

    # 1) Rollen (neueste zuerst — Recency-Effekt).
    roles = []
    for we in profile_data.get("work_experience", []):
        role = (we.get("role_de") or we.get("role_en") or "").strip()
        if role and role not in roles:
            roles.append(role)
    if roles:
        parts.append("Berufserfahrung: " + "; ".join(roles[:4]))

    # 2) Fachbegriffe: bevorzugt kurze, konkrete Skills (nicht ganze Sätze).
    terms: list[str] = []
    seen: set[str] = set()
    for key, values in profile_data.get("skills", {}).items():
        if key == "sprachen":
            continue
        if not isinstance(values, list):
            continue
        for v in values:
            t = str(v).strip()
            # Lange Fließtexte (ganze Sätze) weglassen, Klammern behalten.
            if not t or len(t) > 60:
                continue
            low = t.lower()
            if low in seen:
                continue
            seen.add(low)
            terms.append(t)
    if terms:
        parts.append("Fachkenntnisse: " + ", ".join(terms))

    # 3) Ausbildung / Zertifizierung.
    for edu in profile_data.get("education", []):
        if edu.get("title_de"):
            parts.append(f"Ausbildung: {edu['title_de']}")
            break
    certs = profile_data.get("certifications") or []
    if certs:
        parts.append("Zertifikate: " + ", ".join(str(c) for c in certs[:3]))

    text = " ".join(parts).strip()
    return text[:max_chars]


def build_profile_query_nl(profile_data: dict, max_chars: int = 420) -> str:
    """Baut eine **natürlichsprachige** Profil-Anfrage (für Cross-Encoder).

    Warum nicht die Keyword-Liste? Der Cross-Encoder (``rerank.py``) ist auf
    natürliche Sprache trainiert. Gemessen (ADR-016) auf 4 Testfällen:

    | Anfrage-Form | Trennung (Logit-Spanne) |
    |---|---|
    | Keyword-Liste (Profil-Dump) | 1.3 — praktisch keine |
    | Natürliche Beschreibung | 13.7 |
    | Natürliche Frage | **6.6, korrekte Reihenfolge** |

    Eine Liste von Werkzeugnamen („CANape, CANoe, ECU-Test, …") ist für ein
    Sprachmodell keine sinnvolle „Frage". Diese Funktion erzeugt daher Sätze.
    """
    parts: list[str] = []

    # Die Frage steht BEWUSST am Anfang: Bei einer Kürzung auf max_chars darf
    # nicht ausgerechnet der für den Cross-Encoder wichtigste Teil wegfallen.
    parts.append("Welche Stelle passt zu diesem Bewerberprofil?")

    # Warum max_chars so klein (420 ≈ 100 Token)? Der Cross-Encoder hat ein
    # GEMEINSAMES Limit von 512 Token für Anfrage UND Dokument. Gemessen
    # (ADR-016): Bei 295 Token Anfrage blieben der Stelle nur 217 Token — die
    # Anzeige wurde halbiert und die AUC fiel von 0.730 auf 0.600. Eine kurze
    # Anfrage ist hier also kein Kompromiss, sondern Voraussetzung.

    def _label_de(we: dict) -> str:
        return (we.get("role_de") or we.get("role_en") or "").strip()

    # Rollen in einen Satz fassen (Recency: die neuesten zuerst).
    roles: list[str] = []
    for we in profile_data.get("work_experience", []):
        r = _label_de(we)
        if r and r not in roles:
            roles.append(r)
    if roles:
        parts.append(
            "Ich bin Testingenieur mit langjähriger Erfahrung. "
            "Meine bisherigen Rollen: " + "; ".join(roles[:4]) + "."
        )

    # Kompetenzfelder als Satz.
    labels = {
        "test_datenauswertung_automatisierung": "Test, Datenauswertung und Automatisierung",
        "diagnose_flashtools_bmw_audi": "Diagnose- und Flashtools",
        "requirements_testmanagement": "Requirements- und Testmanagement",
        "standardprogramme_entwicklung": "Standardprogramme und Entwicklung",
        "programmierung": "Programmierung",
        "ki_gestuetzte_entwicklung": "KI-gestützte Entwicklung",
        "normen_prozesse": "Normen und Prozesse",
        "sonstiges": "Sonstiges",
        "hardware_embedded_chip": "Hardware, Chip und Embedded",
    }
    groups = [labels.get(k, k.replace("_", " "))
              for k in profile_data.get("skills", {})
              if k not in ("sprachen", "sonstiges")]
    if groups:
        parts.append("Meine Kompetenzfelder sind " + ", ".join(groups) + ".")

    # Die konkretesten Fachbegriffe — als Aufzählung im Satzkontext.
    terms: list[str] = []
    seen: set[str] = set()
    for key, values in profile_data.get("skills", {}).items():
        if key == "sprachen" or not isinstance(values, list):
            continue
        for v in values:
            t = str(v).strip()
            if not t or len(t) > 60:
                continue
            if t.lower() in seen:
                continue
            seen.add(t.lower())
            terms.append(t)
    if terms:
        parts.append("Konkrete Werkzeuge und Methoden: " + ", ".join(terms[:22]) + ".")

    # Ausbildung / Zertifikate.
    for edu in profile_data.get("education", []):
        if edu.get("title_de"):
            parts.append(f"Qualifikation: {edu['title_de']}.")
            break
    certs = profile_data.get("certifications") or []
    if certs:
        parts.append("Zertifikate: " + ", ".join(str(c) for c in certs[:3]) + ".")

    return " ".join(parts).strip()[:max_chars]


def build_profile_text(profile_data: dict) -> str:
    """Baut den Profil-Text (die „query") aus der Profil-Datenbank.

    Enthält bewusst dieselben Fakten, die auch das Keyword-Matching nutzt —
    nur als Fließtext, damit der Transformer Bedeutung statt Wörter vergleicht.
    """
    parts: list[str] = []

    for we in profile_data.get("work_experience", []):
        role = we.get("role_de") or we.get("role_en") or ""
        if role:
            parts.append(role)
        parts.extend(we.get("bullets_de") or [])
        parts.extend(we.get("tags") or [])

    skills = profile_data.get("skills", {})
    for key, values in skills.items():
        if key == "sprachen":
            continue
        if isinstance(values, list):
            parts.extend(str(v) for v in values)
        elif isinstance(values, str):
            parts.append(values)

    for edu in profile_data.get("education", []):
        for field in ("title_de", "detail_de"):
            if edu.get(field):
                parts.append(edu[field])

    parts.extend(str(c) for c in profile_data.get("certifications", []))
    return "\n".join(p for p in parts if p).strip()


def build_job_text(job: dict, max_chars: int = 2000) -> str:
    """Baut den Stellen-Text (die „passage") aus Titel + Beschreibung.

    Begrenzung auf ``max_chars``: Transformer haben ein Token-Limit (bei E5
    typ. 512 Token ≈ 2000 Zeichen). Längeres wird ohnehin abgeschnitten —
    explizit zu kürzen macht das Verhalten sichtbar statt implizit.
    """
    titel = job.get("titel") or job.get("title") or ""
    desc = (job.get("beschreibung") or job.get("description")
            or job.get("snippet") or "")
    text = f"{titel}\n{desc}".strip()
    return text[:max_chars]


@dataclass
class SemanticMatch:
    """Ergebnis eines semantischen Vergleichs."""

    score: float          # Kosinus-Ähnlichkeit (roh)
    score_pct: float      # auf 0–100 skalierte Anzeige


class SemanticMatcher:
    """Kapselt Modell-Laden und Embedding-Berechnung.

    Das Modell wird **einmal** geladen; ``encode`` ist mehrfach aufrufbar.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL, device: str = "cpu"):
        from sentence_transformers import SentenceTransformer  # lokaler Import: optional

        self.model_name = model_name
        self.device = device
        self.model = SentenceTransformer(model_name, device=device)
        # API-Name hat sich geändert; beide Varianten unterstützen.
        get_dim = getattr(self.model, "get_embedding_dimension", None) \
            or self.model.get_sentence_embedding_dimension
        self.dim = get_dim()
        self._e5 = _needs_e5_prefix(model_name)

    def _prepare(self, texts: Sequence[str], kind: str) -> list[str]:
        """Setzt ggf. die E5-Präfixe (``kind`` ∈ {query, passage})."""
        if not self._e5:
            return list(texts)
        prefix = f"{kind}: "
        return [prefix + t for t in texts]

    def encode(self, texts: Sequence[str], kind: str = "passage",
               batch_size: int = 32, show_progress: bool = False):
        """Berechnet normalisierte Embeddings (Länge 1) für die Texte."""
        prepared = self._prepare(texts, kind)
        return self.model.encode(
            prepared,
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,   # → Kosinus = einfaches Skalarprodukt
            show_progress_bar=show_progress,
        )

    def score(self, profile_text: str, job_texts: Iterable[str],
              show_progress: bool = False) -> list[float]:
        """Kosinus-Ähnlichkeit zwischen Profil und mehreren Stellen."""
        import numpy as np

        job_texts = list(job_texts)
        if not job_texts:
            return []
        q = self.encode([profile_text], kind="query")[0]
        docs = self.encode(job_texts, kind="passage", show_progress=show_progress)
        sims = docs @ q                      # Vektoren sind normiert → Kosinus
        return [float(x) for x in sims]


def cosine_to_pct(sim: float, low: float = 0.70, high: float = 0.90) -> float:
    """Skaliert eine Kosinus-Ähnlichkeit linear auf 0–100.

    Die Grenzen (0.70/0.90) sind empirische E5-Erfahrungswerte: darunter ist
    inhaltlich wenig gemeinsam, darüber sehr viel. Sie sind **Kalibrierung**,
    kein Naturgesetz — für Entscheidungen zählt der Schwellenwert aus der
    Evaluation, nicht die Prozentanzeige.
    """
    if high <= low:
        raise ValueError("high muss > low sein")
    frac = (sim - low) / (high - low)
    return max(0.0, min(100.0, frac * 100.0))
