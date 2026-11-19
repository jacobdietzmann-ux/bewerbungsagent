"""Getailerter Lebenslauf je Stelle (ADR-062).

Seit der Umstellung auf Qualität statt Masse bekommt jede Bewerbung einen
Lebenslauf, der auf die Stelle zugeschnitten ist. Das Tailoring entsteht im
wöchentlichen Sparring und liegt als ``Lebenslauf-Tailoring.json`` im
Bewerbungsordner. ``documents`` setzt es in die DOCX-Vorlage ein.

Die Profil-Datenbank bleibt die Quelle der Wahrheit: Das Tailoring wählt aus,
ordnet und formuliert um, erfindet aber nichts. :func:`pruefen` meldet jeden
Fachbegriff, der im Profil nicht belegt ist, und jede bestätigte Lücke. Mit
Befunden entsteht kein Lebenslauf.

Schema (alle Schlüssel optional, Texte je Sprache ``de``/``en``)::

    {
      "stelle": "Systemingenieur (w/m/d) Defence",
      "firma": "Akkodis",
      "headline": {"de": "...", "en": "..."},
      "profil":   {"de": "...", "en": "..."},
      "stationen": [{"index": 0, "bullets": {"de": ["..."], "en": ["..."]}}],
      "skills": {"de": [{"gruppe": "...", "eintraege": ["...", "..."]}, ... genau 4],
                 "en": [...]},
      "kernkompetenzen": {"de": [{"wert": "10+ Jahre", "text": "..."}, ... genau 4],
                          "en": [...]}
    }

``stationen[].index`` zählt die Stationen in der Reihenfolge der Vorlage (0 = oberste).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .profile import Profile, normalize

DATEINAME = "Lebenslauf-Tailoring.json"
SPRACHEN = ("de", "en")
ANZAHL_SKILLGRUPPEN = 4
ANZAHL_KERNKOMPETENZEN = 4

# Fachbegriffe in Fließtext: Akronyme, Wörter mit Ziffern, Binnen-Großbuchstaben
# (wie ``sparring._BEGRIFF_RE``).
_BEGRIFF_RE = re.compile(
    r"\b(?:[A-Z]{2,}[A-Za-z0-9+/-]*|[A-Za-z]+[0-9][A-Za-z0-9-]*|[a-z]+[A-Z][A-Za-z]+)\b")
# Allgemeine Abkürzungen ohne Fachbehauptung.
_KEIN_FACHBEGRIFF = frozenset({"AG", "SE", "GMBH", "BMW", "AUDI", "IAV", "IGEL", "HAYS", "SOP",
                               "DE", "EN", "ISO"})


class TailoringFehler(ValueError):
    """Tailoring-Datei fehlt, ist kaputt oder passt nicht zur Vorlage."""


def pfad(ordner: str | Path) -> Path:
    return Path(ordner) / DATEINAME


def laden(ordner: str | Path) -> dict | None:
    """Tailoring eines Bewerbungsordners, ``None`` ohne Datei."""
    datei = pfad(ordner)
    if not datei.is_file():
        return None
    try:
        daten = json.loads(datei.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TailoringFehler(f"{datei.name}: kein gültiges JSON ({exc})") from exc
    if not isinstance(daten, dict):
        raise TailoringFehler(f"{datei.name}: erwartet wird ein JSON-Objekt")
    return daten


def text(daten: dict | None, schluessel: str, lang: str) -> str:
    eintrag = (daten or {}).get(schluessel)
    if isinstance(eintrag, dict):
        eintrag = eintrag.get(lang) or ""
    return str(eintrag or "").strip()


def stationen(daten: dict | None, lang: str) -> dict[int, list[str]]:
    """``{index: [Punkte]}`` für die Stationen, die das Tailoring überschreibt."""
    out: dict[int, list[str]] = {}
    for eintrag in (daten or {}).get("stationen") or []:
        if not isinstance(eintrag, dict):
            continue
        try:
            index = int(eintrag.get("index"))
        except (TypeError, ValueError):
            continue
        punkte = (eintrag.get("bullets") or {}).get(lang) or []
        punkte = [str(p).strip() for p in punkte if str(p).strip()]
        if punkte:
            out[index] = punkte
    return out


def skills(daten: dict | None, lang: str) -> list[tuple[str, list[str]]]:
    gruppen = ((daten or {}).get("skills") or {}).get(lang) or []
    out = []
    for g in gruppen:
        if isinstance(g, dict) and g.get("gruppe"):
            eintraege = [str(e).strip() for e in g.get("eintraege") or [] if str(e).strip()]
            out.append((str(g["gruppe"]).strip(), eintraege))
    return out


def kernkompetenzen(daten: dict | None, lang: str) -> list[tuple[str, str]]:
    karten = ((daten or {}).get("kernkompetenzen") or {}).get(lang) or []
    return [(str(k.get("wert", "")).strip(), str(k.get("text", "")).strip())
            for k in karten if isinstance(k, dict)]


# --------------------------------------------------------------------------
# Prüfung gegen das Profil
# --------------------------------------------------------------------------

def _belegt(begriff: str, beleg: str) -> bool:
    """Belegt, wenn der Begriff oder bei Zusammensetzungen („CANoe-Erfahrung“)
    jeder fachliche Teil im Beleg vorkommt."""
    norm = normalize(begriff)
    if norm and norm in beleg:
        return True
    teile = [x for x in begriff.split("-") if _BEGRIFF_RE.fullmatch(x)]
    if len(teile) and len(teile) < len(begriff.split("-")):
        return all(normalize(x) in beleg for x in teile)
    return False


def _luecken(profile: Profile) -> set[str]:
    voll, _tokens = profile._gap_terms()
    return {g for g in voll if g}


def vorlage_als_text(geruest: dict) -> str:
    """Alle Texte eines Gerüsts (siehe ``documents.tailoring_geruest``) als ein String."""
    teile: list[str] = []

    def sammeln(wert) -> None:
        if isinstance(wert, str):
            teile.append(wert)
        elif isinstance(wert, dict):
            for v in wert.values():
                sammeln(v)
        elif isinstance(wert, list):
            for v in wert:
                sammeln(v)

    sammeln(geruest)
    return " · ".join(teile)


def pruefen(daten: dict, profile: Profile, vorlage_text: str = "",
            harte_luecken: list[str] | tuple[str, ...] = ()) -> list[str]:
    """Befunde: unbelegte Fachbegriffe, bestätigte Lücken, falsche Form. Leer = in Ordnung.

    Belegt ist, was in der Profil-Datenbank **oder** in der freigegebenen DOCX-Vorlage
    steht (``vorlage_text``): Die Vorlage ist dein eigener, geprüfter Lebenslauf.
    Geprüft wird also nur, was das Tailoring neu hinzubringt.
    """
    vorlage = normalize(vorlage_text)
    beleg = f"{profile.evidence_text} {vorlage}"
    luecken = {g for g in _luecken(profile) if g not in vorlage}
    # Harte Lücken aus ``matching.hard_gaps`` (z. B. C++) im Rohtext prüfen:
    # ``normalize`` zerlegt „C++" zu „c", das Begriffsmuster trifft es nicht.
    harte = [h for h in harte_luecken if h and not re.search(
        rf"(?<![\w]){re.escape(h)}(?![\w+])", vorlage_text, re.IGNORECASE)]
    befunde: list[str] = []

    def fliesstext(stelle: str, inhalt: str) -> None:
        norm = normalize(inhalt)
        for lueck in luecken:
            if re.search(rf"(?<![a-z0-9]){re.escape(lueck)}(?![a-z0-9])", norm):
                befunde.append(f"{stelle}: bestätigte Lücke „{lueck}“")
        for hart in harte:
            if re.search(rf"(?<![\w]){re.escape(hart)}(?![\w+])", inhalt, re.IGNORECASE):
                befunde.append(f"{stelle}: harte Lücke „{hart}“")
        for begriff in _BEGRIFF_RE.findall(inhalt):
            begriff = begriff.strip("-/")
            if begriff.upper() in _KEIN_FACHBEGRIFF or len(begriff) < 2:
                continue
            if not _belegt(begriff, beleg):
                befunde.append(f"{stelle}: „{begriff}“ ist im Profil nicht belegt")

    for lang in SPRACHEN:
        for schluessel in ("headline", "profil"):
            if text(daten, schluessel, lang):
                fliesstext(f"{schluessel} ({lang})", text(daten, schluessel, lang))
        for index, punkte in stationen(daten, lang).items():
            for nr, punkt in enumerate(punkte, 1):
                fliesstext(f"Station {index} Punkt {nr} ({lang})", punkt)
        gruppen = skills(daten, lang)
        if gruppen and len(gruppen) != ANZAHL_SKILLGRUPPEN:
            befunde.append(f"skills ({lang}): genau {ANZAHL_SKILLGRUPPEN} Gruppen nötig, "
                           f"nicht {len(gruppen)}")
        for gruppe, eintraege in gruppen:
            for eintrag in eintraege:
                norm = normalize(eintrag)
                if any(norm == g or g in norm for g in luecken):
                    befunde.append(f"skills ({lang}): „{eintrag}“ ist eine bestätigte Lücke")
                elif not _belegt(eintrag, beleg):
                    # Mehrwortige Einträge: jeder Fachbegriff darin muss belegt sein.
                    fremd = [b for b in _BEGRIFF_RE.findall(eintrag)
                             if b.upper() not in _KEIN_FACHBEGRIFF and not _belegt(b, beleg)]
                    if fremd or not _BEGRIFF_RE.findall(eintrag):
                        befunde.append(f"skills ({lang}, {gruppe}): „{eintrag}“ ist im Profil "
                                       "nicht belegt")
        karten = kernkompetenzen(daten, lang)
        if karten and len(karten) != ANZAHL_KERNKOMPETENZEN:
            befunde.append(f"kernkompetenzen ({lang}): genau {ANZAHL_KERNKOMPETENZEN} Karten "
                           f"nötig, nicht {len(karten)}")
        for wert, beschreibung in karten:
            fliesstext(f"kernkompetenzen ({lang})", f"{wert} {beschreibung}")
    return befunde
