"""Stellenbezogenes Tailoring der Bewerbungsunterlagen.

Die Profil-Datenbank bleibt die Quelle der Wahrheit. Ein Tailoring-File wählt
nur aus, formuliert um und ordnet neu — es kann keine Kenntnisse erfinden.
Damit das nicht stillschweigend passiert, prüft :func:`unbacked_terms` jeden
Fachbegriff des Files gegen das Profil und meldet, was dort nicht belegt ist.

Ablage: ``Lebenslauf-Tailoring.json`` im Bewerbungsordner (Arbeitsartefakt,
nicht im Repo). Wird die Datei nicht gefunden, verhalten sich alle Aufrufer
unverändert.

Schema (alle Schlüssel optional)::

    {
      "stelle": "Lead Integration Engineer (m/w/d)",
      "firma": "x1F GmbH",
      "headline":   {"de": "...", "en": "..."},
      "profil":     {"de": "...", "en": "..."},
      "kernkompetenzen": {
        "de": [{"wert": "10+", "text": "Jahre Integration", "zusatz": "bis Serie"}],
        "en": [{"wert": "10+", "text": "years of integration", "zusatz": "to SoP"}]
      },
      "berufserfahrung": [
        {"index": 0,
         "rolle":   {"de": "...", "en": "..."},
         "bullets": {"de": ["...", "..."], "en": ["...", "..."]}}
      ],
      "skills": {
        "gruppen": [{"label": {"de": "Systemintegration",
                               "en": "Systems integration"},
                     "items": ["ADAS-Systemintegration", "..."]}],
        "weitere": ["..."]
      }
    }

``berufserfahrung[].index`` bezieht sich auf die **konsolidierte** Liste, die
der Lebenslauf zeigt (siehe ``documents._consolidate_experience``) — also
dieselbe Reihenfolge, in der die Stationen im PDF stehen.
"""

from __future__ import annotations

import json
from pathlib import Path

from .profile import Profile, normalize

FILENAME = "Lebenslauf-Tailoring.json"

# Schlüssel, die als sprachabhängige Strings bzw. Listen gelesen werden.
_TEXT_KEYS = ("headline", "profil")
_LIST_KEYS = ("kernkompetenzen",)


class TailoringError(ValueError):
    """Tailoring-Datei ist nicht lesbar oder hat die falsche Form."""


def load(path: str | Path) -> dict:
    """Liest eine Tailoring-Datei und prüft die Grundform."""
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TailoringError(f"{p.name}: kein gültiges JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise TailoringError(f"{p.name}: erwartet wird ein JSON-Objekt")
    return data


def for_application(folder: str | Path) -> dict | None:
    """Tailoring eines Bewerbungsordners (``None``, wenn keine Datei liegt)."""
    path = Path(folder) / FILENAME
    if not path.is_file():
        return None
    return load(path)


def text(data: dict | None, key: str, lang: str, default: str | None = None) -> str | None:
    """Sprachabhängiger Text (``key`` = ``{"de": ..., "en": ...}``).

    Fällt auf Deutsch zurück, wenn die gewünschte Sprache fehlt — eine
    englische Bewerbung ohne englische Headline soll nicht leer bleiben.
    """
    if not data:
        return default
    entry = data.get(key)
    if isinstance(entry, str):
        return entry or default
    if isinstance(entry, dict):
        value = entry.get(lang) or entry.get("de")
        return value or default
    return default


def items(data: dict | None, key: str, lang: str) -> list[str]:
    """Sprachabhängige Liste einfacher Strings."""
    if not data:
        return []
    entry = data.get(key)
    if isinstance(entry, dict):
        entry = entry.get(lang) or entry.get("de")
    if not isinstance(entry, list):
        return []
    return [str(x) for x in entry if str(x).strip()]


def role_overrides(data: dict | None) -> dict[int, dict]:
    """Station-Überschreibungen als ``{index: {...}}``."""
    out: dict[int, dict] = {}
    for entry in (data or {}).get("berufserfahrung") or []:
        if not isinstance(entry, dict):
            continue
        try:
            index = int(entry.get("index"))
        except (TypeError, ValueError):
            continue
        if index >= 0:
            out[index] = entry
    return out


def skill_groups(data: dict | None, lang: str) -> list[tuple[str, list[str]]] | None:
    """Explizit getailorte Fähigkeitsgruppen (``None`` = Standardauswahl).

    Die Reihenfolge im File ist die Reihenfolge im Lebenslauf.
    """
    skills = (data or {}).get("skills") or {}
    raw = skills.get("gruppen")
    if not isinstance(raw, list) or not raw:
        return None
    out: list[tuple[str, list[str]]] = []
    for group in raw:
        if not isinstance(group, dict):
            continue
        label = group.get("label")
        if isinstance(label, dict):
            label = label.get(lang) or label.get("de")
        entries = [str(x) for x in (group.get("items") or []) if str(x).strip()]
        if label and entries:
            out.append((str(label), entries))
    return out or None


def extra_skills(data: dict | None, lang: str) -> list[str]:
    """Die „Weitere Kenntnisse"-Zeile, falls das File sie festlegt."""
    skills = (data or {}).get("skills") or {}
    raw = skills.get("weitere")
    if isinstance(raw, dict):
        raw = raw.get(lang) or raw.get("de")
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw if str(x).strip()]


def competencies(data: dict | None, lang: str) -> list[tuple[str, str, str]] | None:
    """Kernkompetenz-Karten als ``(gross, mitte, klein)``."""
    if not data:
        return None
    entry = data.get("kernkompetenzen")
    if isinstance(entry, dict):
        entry = entry.get(lang) or entry.get("de")
    if not isinstance(entry, list):
        return None
    out: list[tuple[str, str, str]] = []
    for card in entry:
        if isinstance(card, dict):
            out.append((str(card.get("wert", "")), str(card.get("text", "")),
                        str(card.get("zusatz", ""))))
        elif isinstance(card, (list, tuple)) and len(card) == 3:
            out.append(tuple(str(x) for x in card))
    return out or None


# --------------------------------------------------------------------------
# Prüfung gegen das Profil
# --------------------------------------------------------------------------

def _profile_vocabulary(profile: Profile) -> set[str]:
    """Alle Fähigkeits-Bezeichnungen des Profils, normalisiert."""
    from .documents import _flatten_skill_values

    vocab: set[str] = set()
    for key, value in (profile.skills or {}).items():
        if key == "sprachen":
            continue
        for item in _flatten_skill_values(value):
            if item:
                vocab.add(normalize(item))
    return vocab


def unbacked_terms(data: dict | None, profile: Profile) -> list[str]:
    """Fachbegriffe des Tailorings, die im Profil nicht belegt sind.

    Geprüft werden nur die Fähigkeitslisten (``skills.gruppen[].items``,
    ``skills.weitere``): Headline und Profiltext sind Fließtext und werden
    bewusst nicht wortgleich abgeglichen. Ein Treffer hier heißt **nicht**
    automatisch „falsch" — aber jeder Eintrag muss begründbar sein, und
    ``gap_terms`` (bestätigte Lücken) sind ein hartes Ausschlusskriterium.
    """
    vocab = _profile_vocabulary(profile)
    full_gaps, _tokens = profile._gap_terms()
    gaps = {g for g in full_gaps if g}

    terms: list[str] = []
    for _label, entries in (skill_groups(data, "de") or []):
        terms.extend(entries)
    terms.extend(extra_skills(data, "de"))

    unbekannt: list[str] = []
    for term in terms:
        norm = normalize(term)
        if not norm:
            continue
        # Teilstring in beide Richtungen: „CAN-Trace-Analyse" deckt
        # „CAN-Trace-Analyse" und „Trace-Analyse" ab, „Git" nicht „GitHub".
        known = any(norm == v or norm in v or v in norm for v in vocab if len(v) >= 3)
        if known:
            continue
        if any(norm == g or g in norm for g in gaps if g):
            unbekannt.append(f"{term} (bestätigte Lücke)")
        else:
            unbekannt.append(term)
    return unbekannt
