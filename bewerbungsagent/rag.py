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


# Wörter, die als Schlüsselbegriff aus erklärenden Klammertexten der Profil-Skills
# stammen („(inkl. Leiterplatten-/PCB-Test)", „(Dashboards … nutzen)") und als
# Zwischenüberschrift im Anschreiben nichts aussagen. Am 20.11.2026 standen
# „Inkl:" und „Prufstande:" als Überschriften in Anschreiben an MAN und CONSILIO.
_KEIN_LABEL = frozenset({
    "inkl", "jahr", "jahre", "nutzen", "wichtig", "unterstutzung", "aktives", "multi",
    "code", "workflows", "praxis", "end", "line", "documents", "agent", "bereitschaft",
    "begleitet", "testen", "steuerung", "reporting", "interface", "klasse", "prufungen",
    "tracking", "monitoring", "monitoring nutzen", "rest", "scripting", "pipelines",
    "microsoft", "microsoft office", "vs code", "deutsch", "englisch", "elektrotechnik",
    "mechatronik", "fahrzeugtechnik", "maschinenbau", "dokumentation",
})


def _anzeigeform(profile, skill: str) -> str:
    """Originalschreibweise eines normalisierten Begriffs („prufstande" → „Prüfstände").

    ``display_of`` liefert für Einzelwörter aus Klammertexten nur die normalisierte
    Form. Dann wird das Wort in den Profil-Skills und -Stationen gesucht.
    """
    anzeige = profile.display_of(skill)
    if anzeige.lower() != skill or " " in skill:
        return anzeige
    texte: list[str] = []

    def sammeln(wert) -> None:
        if isinstance(wert, str):
            texte.append(wert)
        elif isinstance(wert, dict):
            for v in wert.values():
                sammeln(v)
        elif isinstance(wert, list):
            for v in wert:
                sammeln(v)

    sammeln(profile.data.get("skills"))
    sammeln(profile.work_experience)
    # Erst ganze Begriffe („ECU-Test"), dann Teile („HiL-Prüfstände" → „Prüfstände").
    for muster in (r"[\wÄÖÜäöüß+#-]+", r"[\wÄÖÜäöüß+#]+"):
        for text in texte:
            for treffer in re.finditer(muster, text):
                wort = treffer.group(0)
                if normalize(wort.rstrip("-")) != skill:
                    continue
                if wort.endswith("-"):
                    # Ergänzungsstrich („Regressions- & Release-Testing"): ganze Wendung.
                    rest = re.split(r"[(,;]", text[treffer.start():], maxsplit=1)[0]
                    return rest.strip()
                return wort
    return anzeige


def _stationszeitraum(profile, we: dict | None) -> str:
    """Zeitraum der Station, wie sie im Lebenslauf steht.

    Der Lebenslauf führt Einträge desselben Projekts zusammen („Heart of Joy" über
    HAYS 01/2024 – 12/2025 und IGEL 01/2026 – 09/2026). Das Anschreiben nannte
    dagegen je nach Beleg den einen oder den anderen Zeitraum (20.11.2026).
    """
    if not we:
        return ""
    from .documents import _consolidate_experience, _role_label

    rolle = normalize(_role_label(we, "de"))
    for station in _consolidate_experience(profile.work_experience):
        teile = [normalize(t) for t in _role_label(station, "de").split(" & ")]
        if rolle in teile or rolle == normalize(_role_label(station, "de")):
            return station.get("period", "") or we.get("period", "")
    return we.get("period", "")


def retrieve_evidence(profile, match: dict, lang: str, max_claims: int = 4,
                      ausschluss: list[str] | tuple[str, ...] = ()) -> list[Evidence]:
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

    gesperrt = _KEIN_LABEL | {normalize(str(w)) for w in ausschluss if str(w).strip()}
    for skill in match.get("matched_skills", []):
        norm = normalize(skill)
        if not norm or norm in _GENERIC_SKILL_WORDS or norm in gesperrt:
            continue
        claim, we = _claim_for(profile, skill, lang)
        if not claim:
            continue
        label = _clean_label(_anzeigeform(profile, norm))
        source = _role_label(we, lang) if we else ""
        period = _stationszeitraum(profile, we)
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
                if add(label, bullet, label, _stationszeitraum(profile, we)):
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
