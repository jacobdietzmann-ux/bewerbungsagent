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
    "to", "on", "a", "m", "w", "d", "f", "gmbh", "ag", "se", "kg",
    # normalisierte deutsche Funktionswörter (Umlaute werden zu ASCII abgebaut)
    "fur", "fuer", "ueber", "unter", "nach", "vor", "ab", "nur", "mehr",
    "wie", "als", "auch", "einen", "einem", "einer", "aus", "bis",
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
    "anforderungen", "belastbares", "direkte", "strukturell",
    "vergleichbarer", "bestandteile", "eigenen", "eigene", "weitere", "inklusive",
    # weitere generische / verstümmelte Tokens
    "nicht", "analyse", "analysen", "elektr", "mehr", "alle",
    "ihr", "ihre", "ihren", "deine", "dein", "diese", "dieser", "diesen",
}


# Sprachvarianten zwischen Profil (teils deutsch) und Anzeigen (teils englisch).
# Schlüssel ist ein Fragment der *normalisierten* Profilphrase; die Werte sind
# gleichbedeutende Varianten, die zusätzlich als Schlüsselbegriff gelten.
# Bewusst klein und eindeutig gehalten: nur Begriffe, die der eigene Lebenslauf
# in beiden Sprachen verwendet (siehe ``documents.py``-Übersetzungen). Generische
# Wörter wie „requirement“ oder „interface“ bleiben absichtlich draußen — sie
# stünden in fast jeder Anzeige und würden den Score verwässern statt schärfen.
_SYNONYMS: dict[str, tuple[str, ...]] = {
    # EN-CV: „Test automation", Anzeigen: „Testautomation"/„Test automation".
    "testautomatisierung": ("test automation", "testautomation"),
    # „XiL-/HiL-Prüfstände" ↔ englische Anzeigen.
    "prufstand": ("test bench", "testbench", "test rig"),
    # „Anforderungsbasiertes Testen (DOORS)" ↔ „requirements-based testing".
    "anforderungsbasiertes testen": ("requirements based testing",),
    # „Fehleranalyse (Root-Cause-Analyse)" ↔ englische Schreibweisen.
    "fehleranalyse": ("root cause analyse", "fault analysis"),
}


# Unicode-Varianten des Bindestrichs. StepStone liefert denselben Job einmal mit
# U+002D und einmal mit U+2010 („c-uas" vs. „c‐uas") — daraus wurden zwei
# Schlüssel und damit zwei Einträge für dieselbe Stelle. Der zweite Eintrag war
# „neu", ohne Unterlagen; bei einer erneuten Erzeugung hätte die bereits
# versendete Bewerbung als frischer Fall erschienen.
_DASH_FOLD = str.maketrans({
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-",
    "\u2015": "-", "\u2212": "-", "\ufe63": "-", "\uff0d": "-",
    "\u00ad": "",          # weiches Trennzeichen: unsichtbar, gehört entfernt
})


def normalize(text: str) -> str:
    """Kleinbuchstaben, Umlaute/ß auflösen, Diakritika und Strichvarianten."""
    if not text:
        return ""
    text = text.lower()
    text = text.translate(_DASH_FOLD)
    text = text.replace("ß", "ss")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text


def _split_top_level(value: str) -> list[str]:
    """Teilt an ``,;&|``, Zeilenumbrüchen und `` - `` aus, **ignoriert Klammern**.

    Ohne den Klammer-Schutz zerlegte ein Wert wie
    ``"Fahrzeugarchitektur E/E (CAN, CAN-FD, LIN)"`` die Klammer mit und
    erzeugte Fragmente wie ``"e (can"`` — unbalancierte Klammern, die nie
    matchen können, aber die Trefferzahl aufblähen.

    Ein mit Leerzeichen umgebener Gedankenstrich trennt ebenfalls: In
    ``"ISO 26262 - DO-178C"`` sind das zwei Normen, während ``MIL-STD-810``
    ohne Leerzeichen ein einziger Begriff bleibt.
    """
    parts, buf, depth = [], [], 0
    for i, ch in enumerate(value):
        if ch == "(":
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
        spaced_dash = (
            depth == 0 and ch in "-–—"
            and buf and buf[-1].isspace()
            and i + 1 < len(value) and value[i + 1].isspace()
        )
        if depth == 0 and (ch in ",;&|\n" or spaced_dash):
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def _split_slashes(part: str) -> list[str]:
    """Teilt ``A/B`` nur, wenn beide Seiten eigenständige Begriffe sind.

    ``"E/E"`` und ``"C/C++"`` sind *ein* Begriff — ein Split hinterließe
    Ein-Buchstaben-Reste (``"Fahrzeugarchitektur E"``). ``"ISO 26262/LV124/GS
    95024"`` dagegen nennt drei Normen und wird geteilt.
    """
    pieces = [p.strip() for p in part.split("/")]
    if len(pieces) > 1 and all(
            len(p) >= 2 and len(p.split()[0]) >= 2 and len(p.split()[-1]) >= 2
            for p in pieces):
        return pieces
    return [part]


def _split_phrases(value: str) -> list[str]:
    """Teilt einen Skill-/Tag-String in brauchbare Schlüsselwort-Phrasen."""
    out: list[str] = []
    for raw in _split_top_level(value):
        raw = re.sub(r"^[\s\-–—_*:·•]+|[\s\-–—_*:·•]+$", "", raw.strip())
        if not raw:
            continue
        # Kategorie-Präfix abtrennen ("Sprachen: Englisch" → beide Begriffe).
        label = re.match(r"^([^:()]{4,}):\s*(.+)$", raw, re.S)
        if label:
            out.append(label.group(1).strip())
            out.extend(_split_phrases(label.group(2)))
            continue
        # Die Klammer MUSS vor dem "/"-Split abgetrennt werden. Sonst zerlegt
        # "…(TCP/UDP, serielle Schnittstellen)" die Klammer und es bleiben
        # unbalancierte Reste wie "udp, serielle schnittstellen" übrig.
        m = re.match(r"^(.*?)\s*\((.*)\)\s*$", raw, re.S)
        for part in _split_slashes(m.group(1) if m else raw):
            part = re.sub(r"^[\s\-–—_*:·•]+|[\s\-–—_*:·•]+$",
                          "", part.strip("()[]\"'"))
            if part:
                out.append(part)
        if m:
            out.extend(_split_phrases(m.group(2)))
    # Ein-Buchstaben-Reste, unbalancierte Klammern und Anführungszeichen
    # (aus Projektnamen wie `im Projekt "X"`) sind nie nützliche Keywords.
    return [x for x in out if x and len(x.strip()) >= 2
            and x.count("(") == x.count(")")
            and x.count('"') % 2 == 0]


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
    def load(cls, path: Path) -> Profile:
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
    def _gap_terms(self) -> tuple[set[str], set[str]]:
        """Begriffe, die laut ``confirmed_gaps_do_not_overclaim`` *nicht* vorhanden sind.

        Sie dürfen nie als Profil-Skill zählen. Beispiel: Das Profil nennt unter
        ``skills`` einen „Prozessnormen-Transfer … DO-178C, ECSS, DO-160,
        MIL-STD-810“ und führt dieselben Normen gleichzeitig als bestätigte
        Lücke. Ohne diese Sperre zählte das Matching sie als *positive* Treffer —
        bei einer Verteidigungs-Stelle waren 4 von 10 Text-Treffern solche
        Normen.

        Rückgabe: ``(Vollbegriffe, Einzelwörter)``. Die Einzelwörter sind nötig,
        weil die Token-Extraktion „MIL-STD-810“ zusätzlich als ``mil`` und ``std``
        in die Keyword-Liste schreibt.
        """
        full: set[str] = set()
        tokens: set[str] = set()
        for raw in self.data.get("gap_terms") or []:
            n = normalize(str(raw))
            if not n:
                continue
            full.add(n)
            # Generische Wörter nicht sperren: „Robot Operating System“ würde
            # sonst ``system`` blocken — und damit „Embedded Systems“,
            # „Echtzeitsysteme“ und ganze Rollentitel.
            tokens.update(t for t in re.findall(r"[a-z0-9]+", n)
                          if len(t) >= 3 and t not in STOPWORDS
                          and t not in _ROLE_WORD_NOISE)
        return full, tokens

    def _is_gap_term(self, keyword: str, blocked: tuple[set[str], set[str]]) -> bool:
        """Prüft, ob ein Keyword eine bestätigte Lücke ist oder eine enthält.

        Verglichen wird **exakt** — als ganzer Begriff (``mil``, ``178c``) oder
        als eines seiner Wörter (``sysml`` in ``sysml-modelle``). Eine
        Substring-Suche über alle Lückenbegriffe wäre zu grob: das Wort ``system``
        aus „Robot Operating System“ würde ``Embedded Systems``,
        ``Echtzeitsysteme`` und ``Fahrerassistenzsysteme`` mitlöschen.

        Ausnahme sind *unterscheidungskräftige* Begriffe mit Ziffer oder
        Bindestrich (``do-178c``). Nur sie dürfen als Teilphrase greifen, damit
        die alte Fehlextraktion ``"gs 95024 - do-178c"`` verschwindet.
        """
        full, tokens = blocked
        if keyword in full:
            return True
        if {t for t in re.findall(r"[a-z0-9]+", keyword) if len(t) >= 3} & tokens:
            return True
        return any(b in keyword for b in full
                   if len(b) >= 5 and ("-" in b or any(c.isdigit() for c in b)))

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

        # Sprachvarianten: Bewerber-Unterlagen sind zweisprachig, Anzeigen sind
        # es nicht. Die EN-Version des Lebenslaufs nennt z. B. „Test automation“,
        # während das Profil „Testautomatisierung“ führt — ohne diese Brücke fand
        # der Scorer die eigene Kernkompetenz in 7 Anzeigen nicht, darunter beide
        # Quantum-Systems-Testrollen. Angehängt wird nur, wenn der Grundbegriff
        # tatsächlich im Profil steht.
        for key, variants in _SYNONYMS.items():
            if not any(key in n for n in norm):
                continue
            for v in variants:
                nv = normalize(v)
                if len(nv) < 3:
                    continue
                norm.add(nv)
                self.display_map.setdefault(nv, v)

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

        # Bestätigte Lücken dürfen nie als Skill zählen (siehe ``_gap_terms``).
        blocked = self._gap_terms()
        if blocked:
            norm = {n for n in norm if not self._is_gap_term(n, blocked)}
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
        „ecu“ in „execute“, „lin“ in „online“).

        Mehrwort-Phrasen gelten auch dann als Treffer, wenn ihre Wörter im Text
        vorkommen, aber **nicht direkt hintereinander** — sonst verfehlte
        „test engineer“ den Titel „Test Automation Engineer“ oder „Flight Test
        Instrumentation Engineer“, obwohl beide exakt die gesuchte Rolle sind.
        """
        n = normalize(text)
        tokens = set(re.findall(r"[a-z0-9]+", n)) if " " in n else set()
        hits: set[str] = set()
        for p in self.keyword_phrases:
            if not p:
                continue
            if re.fullmatch(r"[a-z0-9]{2,4}", p):
                if re.search(r"\b" + re.escape(p) + r"\b", n):
                    hits.add(p)
            elif p in n:
                hits.add(p)
            elif tokens and " " in p:
                words = [w for w in re.findall(r"[a-z0-9]+", p) if len(w) >= 3]
                if words and set(words) <= tokens:
                    hits.add(p)
        return sorted(hits)

    def words_in(self, text: str) -> set[str]:
        """Profil-Inhaltswörter, die im Text vorkommen (Wort-Overlap)."""
        return self.content_words & self._words_of(text)
