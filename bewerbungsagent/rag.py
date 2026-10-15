"""Retrieval & Quellenangabe für das Anschreiben — das „R“ in RAG.

Das Anschreiben soll *belegen*, warum ein Skill-Anspruch stimmt (aus welcher
Station, welchem Zeitraum), statt nur Namen zu nennen. Und es soll *nicht*
behaupten, was laut Profil eine bestätigte Lücke ist. Beides ist „Context
Engineering“: der Kontext, den eine Behauptung stützt, wird explizit gemacht.

Die Generierung (das „G“ in RAG) bleibt davon getrennt. Der Bewerbungsagent
arbeitet dadurch auch ohne Sprachmodell nachvollziehbar — und ein späteres LLM
kann dieselbe Evidenzliste unverändert als Kontext bekommen.

Abhängigkeiten: nur ``profile`` (Keyword-Normalisierung). Die Rendering-Helfer
aus ``documents`` werden erst *zur Laufzeit* importiert, damit ``documents``
seinerseits dieses Modul nutzen kann (keine zirkulären Importe beim Laden).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .profile import normalize


@dataclass(frozen=True)
class Evidence:
    """Eine belegte Skill-Behauptung: Skill → Beleg-Bullet → Quelle (Station)."""

    skill: str        # normalisiertes Skill-Schlüsselwort
    label: str        # bereinigte Anzeigeform (z. B. „CAN“, „Testautomatisierung“)
    claim: str        # der belegende Erfahrungs-Bullet
    source: str       # Rollen-/Stationsbezeichnung („Testkoordinator …“)
    period: str       # Zeitraum der Station („01/2024 – 09/2026“)
    kind: str = "skill"


def retrieve_evidence(profile, match: dict, lang: str, max_claims: int = 4) -> list[Evidence]:
    """Liefert belegte Skill-Behauptungen mit Quelle und Zeitraum.

    Gleiche Selektionslogik wie die Schablonen-Bullets (generische Füllwörter
    ausschließen, redundante Labels/Belege deduplizieren) — zusätzlich wird die
    Herkunft eines jeden Belegs mitgeliefert, damit sie im Anschreiben als
    Quellenangabe erscheinen kann. Enthält auch den Fallback auf Rollen-Bullets
    aus unterschiedlichen Stationen, damit die Liste nie leer bleibt.
    """
    # Lazy-Import: documents importiert dieses Modul; umgekehrt würde ein
    # Modul-Import hier einen Zyklus beim Laden erzeugen.
    from .documents import (
        _GENERIC_SKILL_WORDS,
        _claim_for,
        _claim_signature,
        _clean_label,
        _is_filler_bullet,
        _role_label,
    )

    out: list[Evidence] = []
    used_claims: set[str] = set()
    used_signatures: set[str] = set()
    used_labels: list[str] = []
    used_stations: set[str] = set()

    def add(label: str, claim: str, source: str, period: str, skill: str = "") -> bool:
        nlabel = normalize(label)
        if any(nlabel in prev or prev in nlabel for prev in used_labels):
            return False
        ck = normalize(claim)
        sig = _claim_signature(claim)
        if ck in used_claims or sig in used_signatures:
            return False
        out.append(Evidence(skill=skill, label=label, claim=claim,
                            source=source, period=period))
        used_claims.add(ck)
        used_signatures.add(sig)
        used_labels.append(nlabel)
        return True

    for skill in match.get("matched_skills", []):
        norm = normalize(skill)
        if not norm or norm in _GENERIC_SKILL_WORDS:
            continue
        claim, we = _claim_for(profile, skill, lang)
        if not claim:
            continue
        label = _clean_label(profile.display_of(skill))
        source = _role_label(we, lang) if we else ""
        period = (we or {}).get("period", "")
        if add(label, claim, source, period, skill=norm):
            if we is not None:
                used_stations.add(normalize(_role_label(we, lang)))
            if len(out) >= max_claims:
                return out

    # Fallback: aussagekräftige Bullets aus *unterschiedlichen* Stationen,
    # damit nicht dreimal dieselbe "Heart of Joy"-Position wiederholt wird.
    if len(out) < 2:
        key = "bullets_en" if lang == "en" else "bullets_de"
        for we in profile.work_experience:
            station = normalize(_role_label(we, lang))
            if station in used_stations:
                continue
            for bullet in we.get(key, []):
                if _is_filler_bullet(bullet):
                    continue
                label = _role_label(we, lang)
                if add(label, bullet, label, we.get("period", "")):
                    used_stations.add(station)
                    break
            if len(out) >= max_claims:
                break
    return out


def citation(ev: Evidence, lang: str) -> str:
    """Quellenangabe zu einem Beleg (Station + Zeitraum)."""
    src = (ev.source or "").strip()
    if not src:
        return ""
    period = (ev.period or "").strip()
    if lang == "en":
        return "Evidenced by: " + src + (f" ({period})" if period else "")
    return "Belegt durch: " + src + (f" ({period})" if period else "")


# Bestätigte Lücken aus dem Profil, gruppiert zu menschlich lesbaren Aussagen.
# Der Schlüssel ist ein stabiler Gruppenname, der erste Listenwert ist die
# deutsche, der zweite die englische Formulierung.
_GAP_GROUPS: list[tuple[str, tuple[str, str]]] = [
    ("Luftfahrt-/Militär-Normen", (
        "Keine Luftfahrt-/Raumfahrt-/Militär-spezifischen Prozessnormen "
        "(DO-178C, ECSS, MIL-STD-810 …) — nur Automotive-Äquivalente (ISO 26262)",
        "No aerospace/defence-specific process standards (DO-178C, ECSS, "
        "MIL-STD-810 …) — only automotive equivalents (ISO 26262)",
    )),
    ("MBSE/SysML", (
        "Keine praktische MBSE-/SysML- oder PTC-Creo-Erfahrung",
        "No hands-on MBSE/SysML or PTC Creo experience",
    )),
    ("ROS", (
        "Keine ROS/ROS2-Erfahrung",
        "No ROS/ROS2 experience",
    )),
    ("Robot Framework", (
        "Keine Robot-Framework-Erfahrung",
        "No Robot Framework experience",
    )),
    ("Docker", (
        "Keine Docker-Erfahrung",
        "No Docker experience",
    )),
]

# Normalisierte Suchbegriffe je Gruppe, zugeordnet über den Index in _GAP_GROUPS.
_GAP_TERMS: list[tuple[str, ...]] = [
    ("do-178c", "ecss", "do-160", "mil-std-810", "mil-std-461", "easa cs-23",
     "easa cs-25", "stanag 4866", "stanag 4867", "stanag 4868"),
    ("mbse", "sysml", "ptc creo"),
    ("ros", "ros 2", "robot operating system"),
    ("robot framework",),
    ("docker",),
]


def _term_hit(norm_text: str, term: str) -> bool:
    """Prüft, ob ein Lücken-Begriff im Anzeigentext vorkommt.

    Kurze Einzelwörter (≤ 4 Zeichen, z. B. „ros“, „mbse“) mit Wortgrenzen —
    sonst würde „ros“ fälschlich in „crossing“ oder „across“ matchen.
    """
    if not term:
        return False
    if len(term) <= 4 or " " in term:
        return bool(re.search(r"\b" + re.escape(term) + r"\b", norm_text))
    return term in norm_text


def _group_of(norm_term: str) -> int | None:
    """Index der Lücken-Gruppe, zu der ein Begriff gehört (oder ``None``)."""
    for idx, terms in enumerate(_GAP_TERMS):
        if norm_term in terms:
            return idx
    return None


def gap_evidence(profile, job: dict, lang: str) -> list[str]:
    """Bestätigte Lücken, die für *diese* Stelle relevant sind.

    Die Lücken kommen aus dem Profil (``gap_terms``) — nicht aus dem Code. Für
    bekannte Cluster (Luftfahrt-/Militär-Normen, ROS, …) wird eine gebündelte,
    verständliche Aussage geliefert; unbekannte Begriffe werden wörtlich als
    „keine Erfahrung mit X“ benannt. Relevant ist eine Lücke nur, wenn die
    Anzeige den Begriff selbst nennt: Dann darf das Anschreiben diese Kompetenz
    nicht stillschweigend behaupten, sondern muss die Lücke transparent machen —
    genau der „nachvollziehbare Umgang mit fehlendem Kontext“.
    """
    text = normalize(f"{job.get('titel', '')} {job.get('beschreibung', '')}")
    if not text.strip():
        return []
    gaps = profile.data.get("gap_terms") or []
    out: list[str] = []
    seen_groups: set[int] = set()
    for raw in gaps:
        term = normalize(str(raw))
        if not term or not _term_hit(text, term):
            continue
        group_idx = _group_of(term)
        if group_idx is not None:
            if group_idx in seen_groups:
                continue
            seen_groups.add(group_idx)
            _name, (de, en) = _GAP_GROUPS[group_idx]
            out.append(en if lang == "en" else de)
        else:
            label = str(raw).strip()
            out.append(f"No experience with {label}" if lang == "en"
                       else f"Keine Erfahrung mit {label}")
    return out
