"""Erzeugt massgeschneiderte Bewerbungsunterlagen als PDF (ReportLab).

Zwei Dokumente werden pro Stelle erzeugt:
- Anschreiben (Cover Letter) — auf die Stelle zugeschnitten.
- Lebenslauf (CV) — mit einem auf die Stelle abgestimmten Profil-Absatz.

Das Design orientiert sich an den bestehenden Generatoren (Akzentfarbe #0B3D5C,
klare Typografie) und nutzt ausschliesslich eingebaute Helvetica-Schriften, damit
keine Font-Dateien benötigt werden.
"""

from __future__ import annotations

import re
from datetime import date
from xml.sax.saxutils import escape as _xmlescape

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .config import AGENT_ROOT
from .profile import Profile, normalize

ACCENT = HexColor("#0B3D5C")
ACCENT_DARK = HexColor("#1B3A5C")   # Name + Sektionsüberschriften (Vorlage)
ACCENT_BLUE = HexColor("#1F6FB2")   # Marker + Arbeitgeber (Vorlage)
TEXT_DARK = HexColor("#1A1A1A")
TEXT_GRAY = HexColor("#4A4A4A")
TEXT_MUTED = HexColor("#555555")    # Zeiträume/Meta (Vorlage)
LINE = HexColor("#D0D7DE")

# Professionelle Headline unter dem Namen (identisch zur Vorlage-Aktuell).
PROFESSIONAL_HEADLINE_DE = "Testingenieur · Testkoordinator · HiL / XiL · ADAS · Domaincontroller"
PROFESSIONAL_HEADLINE_EN = "Test Engineer · Test Coordinator · HiL / XiL · ADAS · Domain Controller"

# Job-spezifische Headline-Variante für Hardware-/Chip-/Embedded-Rollen.
PROFESSIONAL_HEADLINE_CHIP_DE = "Hardware- & Embedded-Ingenieur · Elektronik / ECU · Test & Integration"
PROFESSIONAL_HEADLINE_CHIP_EN = "Hardware & Embedded Engineer · Electronics / ECU · Test & Integration"

# Keywords, die eine Hardware-/Chip-/Embedded-Ausrichtung signalisieren.
_CHIP_HINTS = (
    "hardware", "embedded", "mikrocontroller", "ecu", "aurix", "fpga", "chip",
    "elektronik", "electr", "steuergerat", "steuergeraet", "schaltung", "firmware",
    "leistungselektronik", "platine", "leiterplatte",
)


def _headline(job: dict, match: dict, lang: str) -> str:
    """Wählt die passende Profil-Headline (Test vs. Hardware/Embedded)."""
    if _is_chip_role(job, match):
        return PROFESSIONAL_HEADLINE_CHIP_EN if lang == "en" else PROFESSIONAL_HEADLINE_CHIP_DE
    return PROFESSIONAL_HEADLINE_EN if lang == "en" else PROFESSIONAL_HEADLINE_DE


def _is_chip_role(job: dict, match: dict) -> bool:
    """True, wenn die Stelle Hardware-/Chip-/Embedded-Ausrichtung signalisiert."""
    text = normalize(
        f"{job.get('titel', '')} {job.get('firma', '')} {' '.join(match.get('matched_skills', []))}"
    )
    return any(h in text for h in _CHIP_HINTS)

LINKEDIN_URL = "https://www.linkedin.com/in/jacob-dietzmann/"

GERMAN_MONTHS = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]
ENGLISH_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

_SKILL_LABELS = {
    "test_datenauswertung_automatisierung": "Test, Datenauswertung & Automatisierung",
    "diagnose_flashtools_bmw_audi": "Diagnose- & Flashtools (BMW/Audi)",
    "requirements_testmanagement": "Requirements- & Testmanagement",
    "standardprogramme_entwicklung": "Standardprogramme & Entwicklung",
    "programmierung": "Programmierung",
    "ki_gestuetzte_entwicklung": "KI-gestützte Entwicklung",
    "normen_prozesse": "Normen & Prozesse",
    "sprachen": "Sprachen",
    "sonstiges": "Sonstiges",
    "hardware_embedded_chip": "Hardware, Chip & Embedded",
}

_SKILL_LABELS_EN = {
    "test_datenauswertung_automatisierung": "Test, Data Analysis & Automation",
    "diagnose_flashtools_bmw_audi": "Diagnostic & Flash Tools (BMW/Audi)",
    "requirements_testmanagement": "Requirements & Test Management",
    "standardprogramme_entwicklung": "Standard Software & Development",
    "programmierung": "Programming",
    "ki_gestuetzte_entwicklung": "AI-Assisted Development",
    "normen_prozesse": "Standards & Processes",
    "sprachen": "Languages",
    "sonstiges": "Other",
    "hardware_embedded_chip": "Hardware, Chip & Embedded",
}


def _translate(text: str, mapping: dict, lang: str) -> str:
    """Übersetzt deutsche Bezeichner für englische Dokumente (Fallback: Original)."""
    if lang != "en" or not text:
        return text
    return mapping.get(text, text)


# Deutsch → Englisch für einzelne Skill-Einträge (Schlüssel: Original-Schreibweise).
_SKILL_TRANSLATIONS_EN = {
    "UDS-Protokolle": "UDS protocols",
    "CAN-Trace-Analyse": "CAN trace analysis",
    "Regressions- & Release-Testing (agil)": "Regression & release testing (agile)",
    "ADAS-Systemintegration": "ADAS system integration",
    "XiL-/HiL-Prüfstände": "XiL / HiL test benches",
    "Fahrzeugarchitektur E/E (CAN, CAN-FD, LIN, FlexRay, Automotive Ethernet)":
        "Vehicle E/E architecture (CAN, CAN-FD, LIN, FlexRay, automotive Ethernet)",
    "Netzwerk- & Kommunikationsprotokolle (TCP/UDP, serielle Schnittstellen)":
        "Network & communication protocols (TCP/UDP, serial interfaces)",
    "AUTOSAR ARXML, DBC, FIBEX (Kommunikationsmatrizen)":
        "AUTOSAR ARXML, DBC, FIBEX (communication matrices)",
    "Nachrichtenkataloge & Restbussimulation": "Message catalogs & residual bus simulation",
    "Flash- & Boot-Up-Analysen": "Flash & boot-up analyses",
    "Defect Tracking & Fehlermanagement (Jira, Octane)": "Defect tracking & fault management (Jira, Octane)",
    "Microsoft Office (Fortgeschritten)": "Microsoft Office (advanced)",
    "Python (fundiert)": "Python (proficient)",
    "C++ (Grundkenntnisse)": "C++ (basic knowledge)",
    "Vibe Coding (> 1 Jahr Praxis)": "Vibe Coding (> 1 year of practice)",
    "AI Agents (agentische / Multi-Agent-Workflows)": "AI Agents (agentic / multi-agent workflows)",
    "KI als aktives Entwicklungswerkzeug (Scripting & Dokumentation)":
        "AI as an active development tool (scripting & documentation)",
    "ISO 26262 (funktionale Sicherheit)": "ISO 26262 (functional safety)",
    "ASPICE (Grundkenntnisse)": "ASPICE (basic knowledge)",
    "LV124/ISO 16750 (Umweltpruefungen)": "LV124/ISO 16750 (environmental tests)",
    "Prozessnormen-Transfer: ISO 26262/LV124/GS 95024 - DO-178C, ECSS, DO-160, MIL-STD-810, EASA CS23/25":
        "Process standards transfer: ISO 26262/LV124/GS 95024 - DO-178C, ECSS, DO-160, MIL-STD-810, EASA CS23/25",
    "Hochvolt-/E-Antriebs-Erfahrung (BMW Domaincontroller)":
        "High-voltage / e-drive experience (BMW domain controller)",
    "EFK Fahrzeugtechnik / elektr. Sicherheit (FuP 1S/1E)":
        "EFK vehicle technology / electrical safety (FuP 1S/1E)",
    "ECU-/Steuergeräte-Hardwareentwicklung": "ECU / control unit hardware development",
    "Hardware-Software-Integration am Steuergerät": "Hardware-software integration on the control unit",
    "Hardware-Verständnis: Elektrotechnik, Mechatronik, Physik":
        "Hardware understanding: electrical engineering, mechatronics, physics",
    "Embedded Systems, Echtzeitsysteme, C/C++ & Python":
        "Embedded systems, real-time systems, C/C++ & Python",
    "Elektronik- und Schaltungsverständnis": "Electronics and circuit understanding",
}

# Deutsch → Englisch für Sprachnamen und Niveaustufen.
_LANGUAGE_TRANSLATIONS_EN = {
    "Deutsch": "German",
    "Englisch": "English",
    "Russisch": "Russian",
}
_LANGUAGE_LEVEL_TRANSLATIONS_EN = {
    "Muttersprache": "native speaker",
    "Verhandlungssicher in Wort und Schrift": "business fluent in speech and writing",
    "Grundkenntnisse": "basic knowledge",
}

# Deutsch → Englisch für Zertifizierungen.
_CERTIFICATION_TRANSLATIONS_EN = {
    "FuP (Fachkundig unterwiesene Person) Stufe 1S/1E - elektrische Sicherheit / EFK Fahrzeugtechnik":
        "FuP (electrically instructed person) Level 1S/1E - electrical safety / EFK vehicle technology",
}


def _en_place(text: str, lang: str) -> str:
    """Übersetzt Ortsnamen (z. B. München → Munich) für englische Dokumente."""
    if lang != "en" or not text:
        return text
    return text.replace("München", "Munich").replace("Muenchen", "Munich")


def _sanitize(value: str) -> str:
    """Ersetzt Zeichen, die Helvetica (Latin-1) nicht darstellen kann.

    z. B. geschütztes Trennzeichen (U+2011) → normaler Bindestrich, typografische
    Anführungszeichen/Striche → ASCII-Varianten. Verhindert „■"-Boxen im PDF.
    """
    if not value:
        return ""
    replacements = {
        "\u2011": "-",   # non-breaking hyphen
        "\u2010": "-",   # hyphen
        "\u2013": "-",   # en dash
        "\u2014": "-",   # em dash
        "\u2018": "'", "\u2019": "'",
        "\u201c": '"', "\u201d": '"',
        "\u00a0": " ",   # non-breaking space
        "\u2192": "-",   # Pfeil → (nicht in Helvetica Latin-1)
        "\u2190": "-",   # Pfeil ←
        "\u2022": "-",   # Bullet •
        "\u00b7": "·",   # Mittelpunkt (in Latin-1 vorhanden, sicherheitshalber)
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    return value


def esc(value) -> str:
    return _xmlescape(_sanitize(str(value if value is not None else "")))


def _styles() -> dict[str, ParagraphStyle]:
    return {
        "name": ParagraphStyle("name", fontName="Helvetica-Bold", fontSize=16,
                               textColor=ACCENT_DARK, leading=19),
        "headline": ParagraphStyle("headline", fontName="Helvetica-Bold", fontSize=10.5,
                                   textColor=ACCENT_BLUE, leading=14),
        "contact": ParagraphStyle("contact", fontName="Helvetica", fontSize=8.5,
                                  textColor=TEXT_GRAY, leading=12),
        "section": ParagraphStyle("section", fontName="Helvetica-Bold", fontSize=12,
                                  textColor=ACCENT_DARK, leading=14, spaceBefore=6),
        "sectionmarker": ParagraphStyle("sectionmarker", fontName="Helvetica-Bold", fontSize=12,
                                        textColor=ACCENT_BLUE, leading=14, spaceBefore=6),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9.5,
                               leading=13.5, textColor=TEXT_GRAY, alignment=TA_JUSTIFY),
        "bullet": ParagraphStyle("bullet", fontName="Helvetica", fontSize=9.3,
                                 leading=12.8, textColor=TEXT_DARK, alignment=TA_LEFT,
                                 leftIndent=5 * mm, bulletIndent=0),
        "role": ParagraphStyle("role", fontName="Helvetica-Bold", fontSize=10,
                               leading=13, textColor=TEXT_DARK),
        "company": ParagraphStyle("company", fontName="Helvetica", fontSize=9,
                                  textColor=ACCENT_BLUE, leading=12),
        "period": ParagraphStyle("period", fontName="Helvetica", fontSize=9,
                                 textColor=TEXT_MUTED, leading=12, alignment=2),
        "meta": ParagraphStyle("meta", fontName="Helvetica", fontSize=9,
                               textColor=TEXT_MUTED, leading=12),
        "subject": ParagraphStyle("subject", fontName="Helvetica-Bold", fontSize=10.5,
                                  textColor=ACCENT_DARK, leading=14),
    }


def _page_decorator(accent=ACCENT):
    def draw(canv, doc):
        w, h = A4
        canv.saveState()
        canv.setFillColor(accent)
        canv.rect(0, h - 6 * mm, w, 6 * mm, fill=1, stroke=0)
        canv.rect(0, 0, w, 3 * mm, fill=1, stroke=0)
        canv.restoreState()
    return draw


def _section(story, st, title: str, accent=ACCENT_DARK) -> None:
    """Sektionsüberschrift im Vorlagen-Stil: blaues „■" + dunkelblaue Kapitälchen."""
    story.append(Paragraph(f'<font color="#1F6FB2">■</font>  <b>{esc(title.upper())}</b>', st["sectionmarker"]))
    story.append(HRFlowable(width="100%", thickness=0.7, color=accent, spaceAfter=1.5 * mm))


def _role_period_table(st, role: str, period: str, company: str) -> Table:
    """Rolle linksbündig, Zeitraum rechtsbündig (wie in der Vorlage), Firma darunter."""
    row = [Paragraph(f"<b>{esc(role)}</b>", st["role"]), Paragraph(esc(period), st["period"])]
    t = Table([[row[0], row[1]]], colWidths=[130 * mm, 40 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def _de_date() -> str:
    d = date.today()
    return f"Garching, {d.day}. {GERMAN_MONTHS[d.month - 1]} {d.year}"


def _en_date() -> str:
    d = date.today()
    return f"Garching, {ENGLISH_MONTHS[d.month - 1]} {d.day}, {d.year}"


def _asset_path(profile: Profile, key: str):
    """Absoluter Pfad zu einem Profil-Asset (Foto/Unterschrift), relativ zum Agent-Root."""
    rel = profile.personal.get(key)
    if not rel:
        return None
    p = (AGENT_ROOT / rel).resolve()
    return p if p.exists() else None


def _photo_image(profile: Profile, width_mm: float = 25.0):
    """Bewerbungsfoto als rechtsbündiges Bild (Standard: ~25 mm breit)."""
    p = _asset_path(profile, "foto")
    if not p:
        return None
    from PIL import Image as _PIL
    with _PIL.open(p) as im:
        w, h = im.size
    height_mm = width_mm * h / w
    return Image(str(p), width=width_mm * mm, height=height_mm * mm)


def _signature_image(profile: Profile, width_mm: float = 38.0):
    """Unterschrift als Bild (linksbündig, Standard: ~38 mm breit)."""
    p = _asset_path(profile, "unterschrift")
    if not p:
        return None
    from PIL import Image as _PIL
    with _PIL.open(p) as im:
        w, h = im.size
    height_mm = width_mm * h / w
    return Image(str(p), width=width_mm * mm, height=height_mm * mm, hAlign="LEFT")


def _job_reference_id(job: dict) -> str:
    """Zieht eine Stellen-/Kennziffer aus der URL (z. B. StepStone ``--12345678-inline``)."""
    url = (job.get("url") or "").strip()
    if not url:
        return ""
    m = re.search(r"--(\d{6,})-(?:inline)?", url)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=(\d+)", url)
    if m:
        return m.group(1)
    return ""


def _merge_period(a: str, b: str) -> str:
    """Zwei Zeiträume zu einem zusammenfassen (frühester Start, spätestes Ende).

    Unterstützt ``"seit 01/2024"``, ``"10/2018 – 12/2023"`` und ``"seit 10/2012
    (frühere Station)"``.
    """
    def _ym(s: str):
        m = re.search(r"(\d{2})/(\d{4})", s or "")
        return (int(m.group(2)), int(m.group(1))) if m else None

    def _range(s: str):
        m = re.search(r"(\d{2}/\d{4})\s*–\s*(\d{2}/\d{4})", s or "")
        return (m.group(1), m.group(2)) if m else None

    ra = _range(a)
    rb = _range(b)
    starts, ends = [], []
    if ra:
        starts.append(_ym(ra[0]))
        ends.append(_ym(ra[1]))
    if rb:
        starts.append(_ym(rb[0]))
        ends.append(_ym(rb[1]))
    # "seit X" => offener Start (nur Start, kein Ende).
    for p in (a, b):
        m = re.search(r"seit\s+(\d{2}/\d{4})", p or "")
        if m:
            starts.append(_ym(m.group(1)))

    if not starts:
        return a or b
    start = min(starts)
    start_s = f"{start[1]:02d}/{start[0]}"
    if ends:
        end = max(ends)
        return f"{start_s} – {end[1]:02d}/{end[0]}"
    return f"seit {start_s}"


def _consolidate_experience(we_list: list[dict]) -> list[dict]:
    """Führt Stationen für eine kompaktere CV-Darstellung zusammen.

    Regeln:
    - Gleiches Projekt (identische Rolle, z. B. die beiden "Heart of Joy"-Einträge
      über IGEL und HAYS) wird zu einer Station verschmolzen.
    - Eine "frühere Station" (kurzer Zeitraum davor, gleicher Endkunde) wird in die
      darauffolgende Station integriert (z. B. ADAS + Klimatisierung bei AUDI).
    """
    import copy
    merged: list[dict] = []
    for we in we_list:
        if not merged:
            merged.append(copy.deepcopy(we))
            continue
        last = merged[-1]
        same_role = normalize(_role_label(last, "de")) == normalize(_role_label(we, "de"))
        same_client = normalize(last.get("client", "")) == normalize(we.get("client", ""))
        is_early = "(frühere Station" in (we.get("period", "") or "") or "(fruehere Station" in (we.get("period", "") or "")

        if same_role or (same_client and is_early):
            for _lang, key in (("de", "bullets_de"), ("en", "bullets_en")):
                seen = set()
                combined = []
                for b in last.get(key, []) + we.get(key, []):
                    nb = normalize(b)
                    if nb and nb in seen:
                        continue
                    seen.add(nb)
                    combined.append(b)
                last[key] = combined
            last["period"] = _merge_period(we.get("period", ""), last.get("period", ""))
            # Arbeitgeberkette zusammenführen (nur neue, nicht doppelte).
            emp = last.get("employer_of_record", "")
            if emp and we.get("employer_of_record") and we["employer_of_record"] not in emp:
                last["employer_of_record"] = f"{emp} / {we['employer_of_record']}"
            # Rolle: die aktuellere behalten; bei "frühere Station" bleibt die erste.
            if is_early:
                last["role_de"] = f"{last.get('role_de','')} & {we.get('role_de','')}"
                last["role_en"] = f"{last.get('role_en','')} & {we.get('role_en','')}"
        else:
            merged.append(copy.deepcopy(we))
    return merged




# --------------------------------------------------------------------------
# Tailoring-Helfer
# --------------------------------------------------------------------------

def _is_filler_bullet(bullet: str) -> bool:
    """Erkennt inhaltsleere „Fortführung"-Notizen, die als Beleg nichts taugen."""
    b = (bullet or "").strip().lower()
    return b.startswith(("fortführung", "fortfuehrung", "fortsetzung", "continuation"))


def _claim_for(profile: Profile, skill: str, lang: str):
    """Findet einen passenden Erfahrungs-Bullet zu einem (normalisierten) Skill."""
    key = "bullets_en" if lang == "en" else "bullets_de"
    norm = normalize(skill)
    for we in profile.work_experience:
        for bullet in we.get(key, []):
            if _is_filler_bullet(bullet):
                continue
            if norm and norm in normalize(bullet):
                return bullet, we
    return None, None


def _tailored_bullets(profile: Profile, match: dict, lang: str, max_bullets: int = 4):
    bullets: list[tuple[str, str]] = []
    used_claims: set[str] = set()
    used_stations: set[str] = set()
    for skill in match.get("matched_skills", []):
        if normalize(skill) in _GENERIC_SKILL_WORDS:
            continue
        claim, we = _claim_for(profile, skill, lang)
        label = _clean_label(profile.display_of(skill))
        if not claim:
            continue
        ck = normalize(claim)
        if ck in used_claims:
            continue
        bullets.append((label, claim))
        used_claims.add(ck)
        if we is not None:
            used_stations.add(normalize(_role_label(we, lang)))
        if len(bullets) >= max_bullets:
            break

    # Fallback: aussagekräftige Bullets aus *unterschiedlichen* Stationen,
    # damit nicht dreimal dieselbe "Heart of Joy"-Position wiederholt wird.
    if len(bullets) < 2:
        key = "bullets_en" if lang == "en" else "bullets_de"
        for we in profile.work_experience:
            station = normalize(_role_label(we, lang))
            if station in used_stations:
                continue
            for bullet in we.get(key, []):
                if _is_filler_bullet(bullet):
                    continue
                nb = normalize(bullet)
                if nb not in used_claims:
                    bullets.append((_role_label(we, lang), bullet))
                    used_claims.add(nb)
                    break
            if len(bullets) >= max_bullets:
                break
    return bullets


def _role_label(we: dict, lang: str) -> str:
    return we.get("role_en" if lang == "en" else "role_de") or ""


def _clean_label(label: str) -> str:
    """Schreibt einzelne, rein kleingeschriebene Wort-Labels korrekt groß.

    Behebt Labels wie ``hardware`` → ``Hardware``, die aus der Single-Word-
    Keyword-Extraktion stammen. Mehrwortige/phrasierte Labels bleiben unverändert.
    """
    s = (label or "").strip()
    if not s or " " in s or "-" in s or "/" in s or "(" in s:
        return s
    if s and s[0].islower():
        return s[0].upper() + s[1:]
    return s


# Generische Füllwörter, die als "zentrale Stärke" nichts aussagen und deshalb bei
# der Auswahl der Top-Skills übersprungen werden.
_GENERIC_SKILL_WORDS = {
    "deutsch", "englisch", "russisch", "engineer", "software", "system", "projekt",
    "integration", "testing", "testingenieur", "systemingenieur", "entwicklung",
    "engineering", "test", "hil", "automation", "testmanager", "qualitat",
    "verification", "requirements", "validierung", "anforderung", "management",
    "development", "arbeit", "stellenangebot", "team", "munchen", "garching",
    # Einzelwort-/Füll-Begriffe, die als "zentrale Stärke" nichts aussagen.
    "dynamic", "control", "controller", "driver", "driving", "root-cause",
    "root cause", "heart", "systems", "systemintegration", "lin", "ecu", "dsc",
    "fahren", "audi", "bmw", "project", "grundkenntnisse", "deutschkenntnisse",
}

_DEFAULT_SKILL_LINE = "Test, Systemintegration & Qualitätssicherung"

# Konkrete, "harte" Skills, die als Profil-Schwerpunkte etwas aussagen.
# Nur Treffer aus dieser Whitelist erscheinen im Profil-Absatz; alles andere
# (z. B. "assistance", "fahren", "agil") wird als Rauschen verworfen.
_STRONG_SKILL_HINTS = (
    "python", "c++", "c /", "embedded", "aurix", "ecu", "hil", "xil", "sil",
    "mikrocontroller", "fpga", "can", "flexray", "ethernet", "uds", "autosar",
    "arxml", "dbc", "fibex", "doors", "istqb", "iso 26262", "iso 21434",
    "aspice", "testautomatisierung", "test automation", "adas", "regression",
    "anforderung", "requirements", "traceability", "canape", "canoe",
    "ecu-test", "wireshark", "linux", "octane", "codebeamer", "confluence",
    "ki-gestuetzte", "llm", "prompting", "copilot", "leistungselektronik",
    "echtzeit", "firmware", "schaltung", "restbussimulation",
)

# Rollenabhängige Fallback-Schwerpunkte (falls zu wenige harte Treffer).
_CHIP_SUMMARY = {
    "de": ["Embedded Systems", "C/C++ & Python", "Mikrocontroller / ECU (AURIX)", "Test & Integration"],
    "en": ["Embedded systems", "C/C++ & Python", "Microcontroller / ECU (AURIX)", "Test & integration"],
}
_TEST_SUMMARY = {
    "de": ["Testautomatisierung", "HiL / XiL-Prüfstände", "Anforderungsbasiertes Testen (DOORS)", "ADAS / E/E-Systeme"],
    "en": ["Test automation", "HiL / XiL test benches", "Requirements-based testing (DOORS)", "ADAS / E/E systems"],
}


def _summary_skills(profile: Profile, job: dict, match: dict, lang: str, n: int = 3) -> list[str]:
    """Saubere, rollenabhängige Profil-Schwerpunkte (ohne Matching-Rauschen)."""
    strong = [
        profile.display_of(s)
        for s in match.get("matched_skills", [])
        if normalize(s) not in _GENERIC_SKILL_WORDS
        and any(h in normalize(s) for h in _STRONG_SKILL_HINTS)
    ]
    seen: set[str] = set()
    out: list[str] = []
    for s in strong:
        k = normalize(s)
        if k and k not in seen:
            seen.add(k)
            out.append(s)
        if len(out) >= n:
            return out
    defaults = _CHIP_SUMMARY[lang] if _is_chip_role(job, match) else _TEST_SUMMARY[lang]
    for d in defaults:
        k = normalize(d)
        if k in seen:
            continue
        # Redundanz vermeiden: Default überspringen, wenn er einen bereits
        # gewählten Begriff enthält (z. B. "C/C++ & Python" nach "Python").
        if any(prev in k or k in prev for prev in list(seen)):
            continue
        seen.add(k)
        out.append(d)
        if len(out) >= n:
            break
    return out


# --------------------------------------------------------------------------
# Anschreiben
# --------------------------------------------------------------------------

def _letter_intro(profile: Profile, job: dict, match: dict, lang: str) -> str:
    title = job.get("titel", "")
    firma = job.get("firma", "")
    skills = ", ".join(_summary_skills(profile, job, match, lang, n=3))
    if lang == "en":
        return (
            f"your advertised position as <b>{esc(title)}</b> at <b>{esc(firma)}</b> "
            f"combines core strengths of my profile: {esc(skills)}. As a mechanical engineer "
            f"(Diplom) with many years of experience in test coordination, system integration "
            f"and test automation in the automotive environment, I cover exactly these areas."
        )
    return (
        f"die von Ihnen ausgeschriebene Position als <b>{esc(title)}</b> bei <b>{esc(firma)}</b> "
        f"verbindet zentrale Stärken meines Profils: {esc(skills)}. Als Diplom-Ingenieur "
        f"Maschinenbau mit langjähriger Erfahrung in Testkoordination, Systemintegration und "
        f"Testautomatisierung im automotiven Umfeld decke ich genau diese Themen ab."
    )


def _letter_current(profile: Profile, lang: str) -> str | None:
    if not profile.work_experience:
        return None
    we = profile.work_experience[0]
    role = _role_label(we, lang)
    employer = we.get("employer_of_record", "")
    client = we.get("client", "")
    key = "bullets_en" if lang == "en" else "bullets_de"
    bullets = we.get(key, [])
    # Bevorzuge einen inhaltlichen Bullet gegenüber einer reinen „Fortführung“-Notiz.
    first_bullet = next(
        (b for b in bullets if not b.lower().startswith(("fortführung", "continuation"))),
        bullets[0] if bullets else "",
    )
    if lang == "en":
        return (
            f"In my current role as <b>{esc(role)}</b> ({esc(_en_place(employer, lang))}"
            f"{', for ' + esc(_en_place(client, lang)) if client else ''}), {esc(first_bullet)}"
        )
    return (
        f"In meiner aktuellen Rolle als <b>{esc(role)}</b> ({esc(employer)}"
        f"{', für ' + esc(client) if client else ''}) {esc(first_bullet)}"
    )


def _letter_story(profile: Profile, job: dict, match: dict, config: dict, lang: str,
                  max_bullets: int = 4) -> list:
    st = _styles()
    personal = profile.personal
    accent = HexColor(config["documents"].get("accent_color", "#0B3D5C"))

    include_salary = bool(config["documents"].get("gehalt_angeben"))
    include_anlagen = config["documents"].get("anlagen_zeile", True)

    story: list = []
    story.append(Paragraph(esc(personal.get("name", "")), st["name"]))
    contact = " · ".join(x for x in [
        personal.get("address"), personal.get("phone"), personal.get("email")
    ] if x)
    story.append(Paragraph(esc(contact), st["contact"]))
    story.append(Spacer(1, 6 * mm))

    # Empfänger
    story.append(Paragraph(esc(job.get("firma", "")), st["body"]))
    if job.get("ort"):
        story.append(Paragraph(esc(_en_place(job.get("ort", ""), lang)), st["body"]))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(esc(_de_date() if lang == "de" else _en_date()), st["meta"]))
    story.append(Spacer(1, 4 * mm))

    subject_de = f"Bewerbung als {job.get('titel', '')}"
    subject_en = f"Application for {job.get('titel', '')}"
    story.append(HRFlowable(width="100%", thickness=0.6, color=LINE))
    story.append(Spacer(1, 1.5 * mm))
    story.append(Paragraph(esc(subject_de if lang == "de" else subject_en), st["subject"]))
    # Referenz (Quelle der Ausschreibung + ggf. Stellen-ID), wie in der Vorlage.
    quelle = (job.get("quelle") or "").strip()
    referenz = []
    if quelle:
        referenz.append(f"Reference: {quelle}" if lang == "en" else f"Referenz: {quelle}")
    jid = _job_reference_id(job)
    if jid:
        referenz.append(f"Job ID: {jid}" if lang == "en" else f"Stellen-ID: {jid}")
    for r in referenz:
        story.append(Paragraph(esc(r), st["meta"]))
    story.append(Spacer(1, 1.5 * mm))
    story.append(HRFlowable(width="100%", thickness=0.6, color=LINE))
    story.append(Spacer(1, 5 * mm))

    salutation = "Sehr geehrte Damen und Herren," if lang == "de" else "Dear Hiring Manager,"
    story.append(Paragraph(esc(salutation), st["body"]))
    story.append(Spacer(1, 3 * mm))

    story.append(Paragraph(_letter_intro(profile, job, match, lang), st["body"]))
    story.append(Spacer(1, 3 * mm))

    current = _letter_current(profile, lang)
    if current:
        story.append(Paragraph(current, st["body"]))
        story.append(Spacer(1, 3 * mm))

    bullets = _tailored_bullets(profile, match, lang, max_bullets=max_bullets)
    if bullets:
        if lang == "de":
            story.append(Paragraph("Ihre Anforderungen decke ich wie folgt ab:", st["body"]))
        else:
            story.append(Paragraph("I cover your requirements as follows:", st["body"]))
        story.append(Spacer(1, 2 * mm))
        for label, claim in bullets:
            story.append(Paragraph(f"•  <b>{esc(label)}:</b> {esc(claim)}", st["bullet"]))
        story.append(Spacer(1, 3 * mm))

    closing_de = (
        "Über die Gelegenheit, Ihnen meine Erfahrung in einem persönlichen Gespräch "
        "vorzustellen, freue ich mich sehr."
    )
    closing_en = (
        "I would be delighted to present my experience to you in a personal conversation."
    )
    story.append(Paragraph(esc(closing_de if lang == "de" else closing_en), st["body"]))
    story.append(Spacer(1, 3 * mm))

    # Verfügbarkeit.
    avail_de = ("Mein Projekt bei BMW ist zum September 2026 abgeschlossen, sodass "
                "ich ab sofort zur Verfügung stehe.")
    avail_en = ("My project at BMW concluded in September 2026, so I am available "
                "to start immediately.")
    story.append(Paragraph(esc(avail_de if lang == "de" else avail_en), st["body"]))

    # Optional: Gehaltsvorstellung (aus der Schätzung, nur wenn aktiviert).
    if include_salary and job.get("gehalt"):
        sal_de = f"Meine Gehaltsvorstellung liegt bei ca. {esc(job['gehalt'])} (Jahresbrutto)."
        sal_en = f"My salary expectation is approximately {esc(job['gehalt'])} (annual gross)."
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(esc(sal_de if lang == "de" else sal_en), st["body"]))

    story.append(Spacer(1, 8 * mm))

    story.append(Paragraph(esc("Mit freundlichen Grüßen" if lang == "de" else "Sincerely,"), st["body"]))
    story.append(Spacer(1, 4 * mm))
    sig = _signature_image(profile)
    if sig:
        story.append(sig)
        story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(esc(personal.get("name", "")), st["role"]))

    # Anlagen-Zeile.
    if include_anlagen:
        anlagen_de = "Anlagen: Lebenslauf, Zeugnisse, Referenzschreiben (BMW)"
        anlagen_en = "Enclosures: CV, certificates, reference letter (BMW)"
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph(esc(anlagen_de if lang == "de" else anlagen_en), st["meta"]))
    return story, accent


# --------------------------------------------------------------------------
# Lebenslauf
# --------------------------------------------------------------------------

def _cv_profile_summary(profile: Profile, job: dict, match: dict, lang: str) -> str:
    skills = ", ".join(_summary_skills(profile, job, match, lang, n=4))
    is_chip = _is_chip_role(job, match)
    if lang == "en":
        tail = (
            "Main activities in hardware/software integration of ECUs and embedded systems, "
            "test automation and validation."
            if is_chip else
            "Main activities in test coordination, HiL/XiL test benches and test automation in the automotive/ADAS domain."
        )
        return (
            f"Mechanical engineer (Diplom) with many years of experience in the validation and "
            f"integration of complex E/E systems — focus areas: {esc(skills)}. {tail}"
        )
    tail = (
        "Tätigkeitsschwerpunkte in Hardware-/Software-Integration von Steuergeräten und Embedded "
        "Systemen, Testautomatisierung und Absicherung."
        if is_chip else
        "Tätigkeitsschwerpunkte in Testkoordination, HiL-/XiL-Prüfständen und Testautomatisierung im Automotive-/ADAS-Umfeld."
    )
    return (
        f"Diplom-Ingenieur Maschinenbau mit langjähriger Erfahrung in der Absicherung und "
        f"Integration komplexer E/E-Systeme – Schwerpunkte: {esc(skills)}. {tail}"
    )


def _cv_story(profile: Profile, job: dict, match: dict, config: dict, lang: str) -> list:
    st = _styles()
    personal = profile.personal
    accent = HexColor(config["documents"].get("accent_color", "#0B3D5C"))
    is_en = lang == "en"

    story: list = []
    contact = " · ".join(x for x in [
        personal.get("address"), personal.get("phone"), personal.get("email"), LINKEDIN_URL
    ] if x)
    photo = _photo_image(profile)

    if photo:
        left = Paragraph(
            f"<b>{esc(personal.get('name', ''))}</b><br/>"
            f"{esc(_headline(job, match, lang))}<br/>"
            f"{esc(contact)}",
            st["contact"],
        )
        header_table = Table([[left, photo]], colWidths=[138 * mm, 32 * mm])
        header_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(header_table)
    else:
        story.append(Paragraph(esc(personal.get("name", "")), st["name"]))
        story.append(Paragraph(esc(_headline(job, match, lang)), st["headline"]))
        story.append(Paragraph(esc(contact), st["contact"]))
    story.append(Spacer(1, 5 * mm))

    # Profil
    _section(story, st, "Profile" if is_en else "Profil", accent)
    story.append(Paragraph(_cv_profile_summary(profile, job, match, lang), st["body"]))
    story.append(Spacer(1, 4 * mm))

    # Berufserfahrung
    _section(story, st, "Work Experience" if is_en else "Berufserfahrung", accent)
    for we in _consolidate_experience(profile.work_experience):
        role = _role_label(we, lang)
        employer = we.get("employer_of_record", "")
        client = we.get("client", "")
        where = f"{employer} · {client}" if client else employer
        where = _en_place(where, lang)
        story.append(_role_period_table(st, role, we.get("period", ""), where))
        story.append(Paragraph(esc(where), st["company"]))
        key = "bullets_en" if is_en else "bullets_de"
        bullets = [b for b in we.get(key, []) if not _is_filler_bullet(b)][:5]
        for bullet in bullets:
            story.append(Paragraph(f"•  {esc(bullet)}", st["bullet"]))
        story.append(Spacer(1, 3 * mm))

    # Ausbildung
    _section(story, st, "Education" if is_en else "Ausbildung", accent)
    for edu in profile.education:
        title = edu.get("title_en" if is_en else "title_de", "")
        detail = edu.get("detail_en" if is_en else "detail_de", "")
        story.append(_role_period_table(st, title, edu.get("period", ""), ""))
        if detail:
            story.append(Paragraph(esc(detail), st["meta"]))
        story.append(Spacer(1, 1.5 * mm))
    story.append(Spacer(1, 2 * mm))

    # Fachkenntnisse & Software (2-Spalten)
    _section(story, st, "Skills & Software" if is_en else "Fachkenntnisse & Software", accent)
    story.append(_skills_two_columns(profile, st, lang, match))
    story.append(Spacer(1, 3 * mm))

    # Sprachen & Zertifizierung
    _section(story, st, "Languages & Certification" if is_en else "Sprachen & Zertifizierung", accent)
    langs = []
    for entry in profile.languages:
        if isinstance(entry, dict):
            sprache = _translate(entry.get("sprache", ""), _LANGUAGE_TRANSLATIONS_EN, lang)
            niveau = _translate(entry.get("niveau", ""), _LANGUAGE_LEVEL_TRANSLATIONS_EN, lang)
            langs.append(f"{sprache} ({niveau})")
        else:
            langs.append(_translate(str(entry), _LANGUAGE_TRANSLATIONS_EN, lang))
    story.append(Paragraph(esc(" · ".join(langs)), st["body"]))
    for cert in profile.certifications:
        story.append(Paragraph(f"<b>{esc(_translate(cert, _CERTIFICATION_TRANSLATIONS_EN, lang))}</b>", st["body"]))
    story.append(Spacer(1, 4 * mm))

    # Kernkompetenzen auf einen Blick
    story.append(_key_competencies(story, st, lang))
    return story, accent


def _skills_two_columns(profile: Profile, st: dict, lang: str, match: dict | None = None) -> Table:
    """Fähigkeitsgruppen in zwei Spalten (Vorlagen-Layout).

    Passende Skills (aus ``match['matched_skills']``) werden hervorgehoben.
    Die Gruppen werden nach ihrem Textumfang auf beide Spalten verteilt, damit
    die Spalten annähernd gleich hoch sind und keine großen Lücken entstehen
    (die frühere Zeilen-Paarung einer 19-Punkte-Gruppe mit einer 4-Punkte-Gruppe
    erzeugte große Leerstellen).
    """
    groups = profile.skills
    labels = _SKILL_LABELS_EN if lang == "en" else _SKILL_LABELS
    matched_norm = {normalize(s) for s in (match or {}).get("matched_skills", [])}

    blocks: list[tuple[int, str]] = []
    for key in groups:
        if key == "sprachen":
            continue
        flat = _flatten_skill_values(groups[key])
        if not flat:
            continue
        label = labels.get(key, key.replace("_", " ").capitalize())
        parts = []
        for item in flat:
            item_display = _translate(item, _SKILL_TRANSLATIONS_EN, lang)
            item_norm = normalize(item)
            hit = any(item_norm == m or m in item_norm or item_norm in m
                      for m in matched_norm if m)
            parts.append(f"<b>{esc(item_display)}</b>" if hit else esc(item_display))
        block = f"<b>{esc(label)}</b><br/>{' · '.join(parts)}"
        blocks.append((len(block), block))

    # Nach Umfang absteigend auf zwei Spalten verteilen (immer zur kürzeren).
    left: list[str] = []
    right: list[str] = []
    left_w = right_w = 0
    for weight, block in sorted(blocks, key=lambda x: -x[0]):
        if left_w <= right_w:
            left.append(block)
            left_w += weight
        else:
            right.append(block)
            right_w += weight

    col_paras = [
        [Paragraph("<br/><br/>".join(left), st["body"]) if left else Paragraph("", st["body"]),
         Paragraph("<br/><br/>".join(right), st["body"]) if right else Paragraph("", st["body"])]
    ]
    t = Table(col_paras, colWidths=[85 * mm, 85 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def _key_competencies(story, st: dict, lang: str):
    """Vier Kernkompetenz-Karten am CV-Ende (Vorlagen-Stil)."""
    is_en = lang == "en"
    cards = (
        [
            ("10+", "years automotive", "test & integration"),
            ("HiL / XiL", "test benches, automation", "& Python tools"),
            ("Domain controller", "test coordination", "up to SoP"),
            ("Safety", "ISO 26262 ·", "safety-critical E/E"),
        ]
        if is_en else
        [
            ("10+", "Jahre Automotive", "Test & Integration"),
            ("HiL / XiL", "Prüfstände, Automation", "& Python-Tools"),
            ("Domaincontroller", "Testkoordination", "bis SoP"),
            ("Safety", "ISO 26262 ·", "sicherheitskritische E/E"),
        ]
    )
    card_paras = []
    for big, mid, small in cards:
        cell = (
            f'<font color="#1F6FB2"><b>{esc(big)}</b></font><br/>'
            f'<b>{esc(mid)}</b><br/>{esc(small)}'
        )
        card_paras.append(Paragraph(cell, st["meta"]))
    t = Table([card_paras], colWidths=[42.5 * mm, 42.5 * mm, 42.5 * mm, 42.5 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.5, ACCENT_BLUE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, HexColor("#E4EDF5")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F4F8FB")),
    ]))
    return t


def _flatten_skill_values(values) -> list[str]:
    out: list[str] = []
    if isinstance(values, str):
        out.append(values)
    elif isinstance(values, (list, tuple)):
        for v in values:
            if isinstance(v, str):
                out.append(v)
            elif isinstance(v, dict):
                out.append(v.get("sprache") or ", ".join(str(x) for x in v.values()))
    elif isinstance(values, dict):
        for v in values.values():
            out.extend(_flatten_skill_values(v))
    return out


# --------------------------------------------------------------------------
# Öffentliche API
# --------------------------------------------------------------------------

def _reference_letter_path(profile: Profile):
    """Pfad zum Referenzschreiben (BMW), falls vorhanden."""
    return _asset_path(profile, "referenzschreiben")


def copy_reference_letter(profile: Profile, folder) -> str | None:
    """Kopiert das Referenzschreiben als Anlage in den Bewerbungsordner."""
    src = _reference_letter_path(profile)
    if not src:
        return None
    import shutil
    dst = folder / f"Referenzschreiben_{profile.personal.get('name', '').replace(' ', '_')}.pdf"
    if dst.resolve() != src.resolve():
        shutil.copyfile(src, dst)
    return str(dst)


def generate_anschreiben(profile: Profile, job: dict, match: dict, out_path, config: dict, lang: str = "de") -> str:
    """Erzeugt das Anschreiben; kürzt automatisch, falls es > 1 Seite wird."""
    decor = _page_decorator(HexColor(config["documents"].get("accent_color", "#0B3D5C")))

    def _build(max_bullets: int) -> int:
        story, _accent = _letter_story(profile, job, match, config, lang, max_bullets=max_bullets)
        doc = SimpleDocTemplate(
            str(out_path), pagesize=A4,
            leftMargin=22 * mm, rightMargin=22 * mm, topMargin=20 * mm, bottomMargin=18 * mm,
            title=f"Anschreiben {job.get('firma', '')}", author=profile.personal.get("name", ""),
        )
        doc.build(story, onFirstPage=decor, onLaterPages=decor)
        return int(getattr(doc, "page", 1) or 1)

    pages = _build(4)
    if pages > 1:
        pages = _build(3)
    if pages > 1:
        _build(2)
    return str(out_path)


def generate_lebenslauf(profile: Profile, job: dict, match: dict, out_path, config: dict, lang: str = "de") -> str:
    story, accent = _cv_story(profile, job, match, config, lang)
    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=22 * mm, rightMargin=22 * mm, topMargin=20 * mm, bottomMargin=18 * mm,
        title=f"Lebenslauf {profile.personal.get('name', '')}", author=profile.personal.get("name", ""),
    )
    decor = _page_decorator(accent)
    doc.build(story, onFirstPage=decor, onLaterPages=decor)
    return str(out_path)
