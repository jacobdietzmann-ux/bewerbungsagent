"""Lädt und normalisiert das Master-Profil (Profil-Datenbank.json).

Das Profil ist die *einzige* Quelle der Wahrheit für alle Lebenslauf-Fakten.
Dieses Modul stellt daraus normalisierte Schlüsselwörter und strukturierte
Zugriffe bereit, die Matching und Dokumentenerstellung gemeinsam nutzen.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

STOPWORDS = {
    "der", "die", "das", "und", "oder", "ein", "eine", "mit", "von", "für", "auf",
    "in", "im", "an", "bei", "zu", "zum", "zur", "the", "and", "for", "with", "of",
    "to", "in", "on", "a", "an", "m", "w", "d", "f", "gmbh", "ag", "se", "kg",
    # normalisierte deutsche Funktionswörter (Umlaute werden zu ASCII abgebaut)
    "fur", "fuer", "ueber", "unter", "nach", "vor", "ab", "nur", "mehr",
    "wie", "als", "auch", "eine", "einen", "einem", "einer", "aus", "bis",
}

# Generische Begriffe aus Rollentiteln/-beschreibungen, die als einzelnes
# Schlagwort nichts aussagen und das Matching verrauschen (z. B. "fahren",
# "assistance", "dynamic", "control", "heart", "software", "system").
# Diese werden NICHT als matchbare Profil-Keywords extrahiert — die konkreten,
# unterscheidungsstarken Begriffe (HiL, ADAS, AURIX, DOORS, Python, …) kommen
# bereits über ``skills`` und ``tags`` herein.
_ROLE_WORD_NOISE = {
    "fahren", "driving", "driver", "fahrer", "assistance", "assistenz",
    "fahrerassistenz", "fahrerassistenzsysteme", "dynamic", "dynamik",
    "control", "controller", "steuerung", "regelung", "stability",
    "stabilitaet", "heart", "joy", "projekt", "project", "integration",
    "systemintegration", "software", "system", "systems", "engineer",
    "ingenieur", "engineering", "domain", "entwicklung", "entwickler",
    "development", "testing", "test", "versuch", "coordinator",
    "klimatisierung", "climate", "audi", "bmw", "spezialist", "specialist",
    "produkt", "product", "arbeit", "team", "mitarbeiter", "verantwortung",
    "qualitaet", "qualitat", "quality", "sicherheit", "safety", "pruefung",
    "pruefungen", "bereich", "abteilung", "taetigkeit", "aufgabe", "aufgaben",
    "station", "fruehere", "frühere",
    # Qualifizierer / Prosa-Wörter, die als nacktes Schlagwort nichts aussagen.
    "erfahrung", "kennt", "kenntnisse", "grundkenntnisse", "studium", "praktikum",
    "zertifizierung", "zertifikat", "verstandnis", "verstaendnis",
    "vergleichbaren", "vergleichbar", "fundiert", "verhandlungssicher",
    "muttersprache", "standard", "office", "tools", "level", "next", "cause",
    "root", "wort", "schrift", "boot", "funktionale", "elektrische",
    "anforderungen", "sicherheit", "belastbares", "direkte", "strukturell",
    "vergleichbarer", "bestandteile", "eigenen", "eigene", "weitere", "inklusive",
    # weitere generische / verstümmelte Tokens
    "nicht", "analyse", "analysen", "elektr", "elektrische", "mehr", "alle",
    "ihr", "ihre", "ihren", "deine", "dein", "diese", "dieser", "diesen",
}


def normalize(text: str) -> str:
    """Kleinbuchstaben, Umlaute/ß auflösen, Diakritika entfernen."""
    if not text:
        return ""
    text = text.lower()
    text = text.replace("ß", "ss")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text


def _split_phrases(value: str) -> list[str]:
    """Teilt einen Skill-/Tag-String in brauchbare Schlüsselwort-Phrasen."""
    pieces = re.split(r"[,;&\n/|]", value)
    out = []
    for p in pieces:
        p = p.strip()
        p = re.sub(r"^[\s\-–—_*:·•]+|[\s\-–—_*:·•]+$", "", p)
        # Klammerzusätze separat führen (z. B. "ISO 26262 (funktionale Sicherheit)").
        # Wichtig: NICHT vorher die Klammern strippen, sonst entfernt ``strip("()")``
        # die schließende Klammer und der Split greift nicht mehr.
        m = re.match(r"^(.*?)\((.*)\)$", p)
        if m and len(m.group(1).strip()) >= 3:
            out.append(m.group(1).strip().strip("()[]\"'"))
            out.append(m.group(2).strip().strip("()[]\"'"))
        elif p:
            out.append(p.strip("()[]\"'"))
    return [x for x in out if x]


def _flatten_strings(obj, out: list[str]) -> None:
    if isinstance(obj, str):
        if obj.strip():
            out.append(obj.strip())
    elif isinstance(obj, dict):
        for v in obj.values():
            _flatten_strings(v, out)
    elif isinstance(obj, (list, tuple)):
        for x in obj:
            _flatten_strings(x, out)


class Profile:
    """Wrapper um die rohe ``Profil-Datenbank.json``."""

    def __init__(self, data: dict):
        self.data = data
        self.display_map: dict[str, str] = {}
        self.keyword_phrases = self._build_phrases()
        self.content_words = self._build_words()

    def display_of(self, normalized_keyword: str) -> str:
        """Schönere Anzeigeform (Original-Schreibweise) für ein normalisiertes Keyword."""
        return self.display_map.get(normalized_keyword, normalized_keyword)

    @classmethod
    def load(cls, path: Path) -> "Profile":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    # ---- Zugriffe auf Rohdaten -----------------------------------------
    @property
    def personal(self) -> dict:
        return self.data.get("personal", {})

    @property
    def work_experience(self) -> list[dict]:
        return self.data.get("work_experience", [])

    @property
    def education(self) -> list[dict]:
        return self.data.get("education", [])

    @property
    def certifications(self) -> list[str]:
        return self.data.get("certifications", [])

    @property
    def skills(self) -> dict:
        return self.data.get("skills", {})

    @property
    def languages(self) -> list[dict]:
        return self.data.get("skills", {}).get("sprachen", [])

    @property
    def tailoring_notes(self) -> str:
        return self.data.get("tailoring_notes", "")

    # ---- Keyword-Aufbereitung ------------------------------------------
    def _build_phrases(self) -> list[str]:
        phrases: list[str] = []
        _flatten_strings(self.data.get("skills", {}), phrases)
        role_terms: list[str] = []
        # Kuratierte Quellen (Skills + Tags): hier lohnt die Extraktion einzelner
        # Fachbegriffe, da sie konkrete Technologien enthalten.
        curated_terms: list[str] = []
        for we in self.work_experience:
            _flatten_strings(we.get("role_de"), phrases)
            _flatten_strings(we.get("role_en"), phrases)
            _flatten_strings(we.get("tags"), phrases)
            _flatten_strings(we.get("tags"), curated_terms)
            _flatten_strings(we.get("role_de"), role_terms)
            _flatten_strings(we.get("role_en"), role_terms)
        _flatten_strings(self.data.get("skills", {}), curated_terms)
        for cert in self.certifications:
            _flatten_strings(cert, phrases)

        norm: set[str] = set()
        for raw in phrases:
            for p in _split_phrases(raw):
                n = normalize(p)
                if len(n) >= 3:
                    norm.add(n)
                    if n not in self.display_map and p:
                        self.display_map[n] = p

        # Einzelne Fachbegriffe aus Skills + Tags (z. B. „Linux“ aus
        # „Linux (Arch/CachyOS, Ubuntu)“, „Embedded“ aus „Embedded Systems“),
        # damit ein Stellenprofil mit „Embedded Software“ oder „Linux“ auch dann
        # matcht, wenn der Begriff nur als Teil einer längeren Phrase vorliegt.
        for raw in curated_terms:
            for tok in re.findall(r"[a-z0-9]+", normalize(raw)):
                if len(tok) < 3 or tok.isdigit():
                    continue
                if tok in STOPWORDS or tok in _ROLE_WORD_NOISE:
                    continue
                norm.add(tok)
                if tok not in self.display_map:
                    self.display_map[tok] = tok

        # Einzelne signifikante Wörter aus den Rollen als Schlüsselbegriffe,
        # damit z. B. „Testingenieur“ oder „Systemingenieur“ im Stellentitel direkt matcht.
        # Generische Füllwörter („fahren“, „assistance“, „control“, …) werden über
        # ``_ROLE_WORD_NOISE`` ausgeschlossen, damit sie das Matching nicht verrauschen.
        for raw in role_terms:
            for tok in re.findall(r"[a-z0-9]+", normalize(raw)):
                if len(tok) >= 5 and tok not in STOPWORDS and tok not in _ROLE_WORD_NOISE:
                    norm.add(tok)
                    if tok not in self.display_map:
                        self.display_map[tok] = tok
        return sorted(norm)

    def _build_words(self) -> set[str]:
        words: set[str] = set()
        for phrase in self.keyword_phrases:
            for tok in re.findall(r"[a-z0-9]{3,}", phrase):
                if tok not in STOPWORDS and tok not in _ROLE_WORD_NOISE:
                    words.add(tok)
        return words

    def _words_of(self, text: str) -> set[str]:
        return {t for t in re.findall(r"[a-z0-9]{3,}", normalize(text))
                if t not in STOPWORDS and t not in _ROLE_WORD_NOISE}

    def keywords_in(self, text: str) -> list[str]:
        """Normalisierte Profil-Phrasen, die im Text vorkommen.

        Kurze Einzelwort-Schlüssel (2–4 Zeichen, z. B. „can“, „lin“, „ecu“,
        „hil“, „git“) werden mit Wortgrenzen gematcht, damit sie nicht fälschlich
        in längeren, unverwandten Wörtern aufscheinen („can“ in „candidate“,
        „ecu“ in „execute“, „lin“ in „online“). Längere Begriffe und
        Mehrwort-Phrasen bleiben beim Substring-Match.
        """
        n = normalize(text)
        hits: set[str] = set()
        for p in self.keyword_phrases:
            if not p:
                continue
            if re.fullmatch(r"[a-z0-9]{2,4}", p):
                if re.search(r"\b" + re.escape(p) + r"\b", n):
                    hits.add(p)
            elif p in n:
                hits.add(p)
        return sorted(hits)

    def words_in(self, text: str) -> set[str]:
        """Profil-Inhaltswörter, die im Text vorkommen (Wort-Overlap)."""
        return self.content_words & self._words_of(text)
