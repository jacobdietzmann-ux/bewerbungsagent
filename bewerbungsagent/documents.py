"""Erzeugt massgeschneiderte Bewerbungsunterlagen als PDF (ReportLab).

Zwei Dokumente werden pro Stelle erzeugt:
- Anschreiben (Cover Letter) — auf die Stelle zugeschnitten.
- Lebenslauf (CV) — mit einem auf die Stelle abgestimmten Profil-Absatz.

Der Lebenslauf unterstützt mehrere Vorlagen (``CV_TEMPLATES``, wählbar über
``config.json`` → ``documents.lebenslauf_template`` oder CLI ``--template``).
Die Vorlagen sind originalgetreue ReportLab-Ports bekannter Open-Source-Templates
(Design, Farben und Layout aus dem jeweiligen Quellcode übernommen):

- ``classic``  — einspaltig, klare Sektionen mit Akzentlinien (ATS-freundlich).
- ``awesome``  — zweifarbiger Name, akzentfarbene Sektionstitel (Awesome-CV).
- ``deedy``    — großer zentrierter Name, zwei Spalten (Deedy-Resume).
- ``mcdowell`` — Serifen-Typografie, zentrierter Name, 3-spaltige Einträge.
- ``sidebar``  — dunkle Seitenleiste mit Foto/Kontakt/Skills (latexcv).
- ``elegant``  — zentrierter Kopf, datierte Einträge (billryan/resume).
- ``clean``    — minimaler Einspalter mit Titel-Regeln (devcelio/resume-template).

Das Design orientiert sich an den bestehenden Generatoren (Akzentfarbe #0B3D5C,
klare Typografie) und nutzt ausschliesslich eingebaute Helvetica-Schriften, damit
keine Font-Dateien benötigt werden.
"""

from __future__ import annotations

import io
import re
from datetime import date
from xml.sax.saxutils import escape as _xmlescape

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
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


def _headline(job: dict, match: dict, lang: str, config: dict | None = None) -> str:
    """Wählt die passende Profil-Headline (Test vs. Hardware/Embedded).

    Liest zuerst aus ``config["documents"]["personal"]["headline_<lang>[_chip]"]``.
    Fallback auf die hardkodierten Module-Konstanten (Abwärtskompatibilität).
    """
    if config is not None:
        personal = config.get("documents", {}).get("personal", {})
        key = f"headline_{'chip_' if _is_chip_role(job, match) else ''}{lang}"
        value = personal.get(key, "")
        if value:
            return value
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
        "\u201e": '"', "\u201f": '"',  # deutsches öffnendes Anführungszeichen „ (U+201E)
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


def _role_period_table(st, role: str, period: str, company: str,
                       width: float = 166 * mm) -> Table:
    """Rolle linksbündig, Zeitraum rechtsbündig (wie in der Vorlage), Firma darunter."""
    row = [Paragraph(f"<b>{esc(role)}</b>", st["role"]), Paragraph(esc(period), st["period"])]
    t = Table([[row[0], row[1]]], colWidths=[width - 40 * mm, 40 * mm])
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


# Zielauflösung für eingebettete Bilder. Ein Foto mit 25 mm Breite braucht bei
# 300 dpi rund 295 px. Das Profil-Foto hatte 700 px und wurde mit 25 mm gedruckt
# (≈711 dpi): der Lebenslauf wuchs dadurch auf 1,75 MB, ohne dass man auf dem
# Papier einen Unterschied sieht. 300 dpi ist die übliche Druckauflösung.
EMBED_DPI = 300


def _image_for_pdf(path, width_mm: float, *, dpi: int = EMBED_DPI,
                   jpeg: bool = True):
    """Bildquelle für ReportLab, auf die tatsächliche Druckgröße reduziert.

    Gibt den Pfad zurück, wenn das Bild schon klein genug ist, sonst einen
    ``BytesIO`` mit dem verkleinerten Bild. ``jpeg`` eignet sich für Fotos
    (keine Transparenz, deutlich kleiner); Unterschriften bleiben PNG, damit
    ein transparenter Hintergrund erhalten bleibt.
    """
    try:
        from PIL import Image as _PIL
    except ImportError:  # pragma: no cover - Pillow ist optional
        return str(path)
    with _PIL.open(path) as im:
        w, h = im.size
        target_w = max(1, round(width_mm / 25.4 * dpi))
        if w <= target_w:
            return str(path)
        target_h = max(1, round(h * target_w / w))
        canvas = im.convert("RGB") if jpeg else im.copy()
        canvas = canvas.resize((target_w, target_h), _PIL.LANCZOS)
        buf = io.BytesIO()
        if jpeg:
            canvas.save(buf, format="JPEG", quality=90, optimize=True,
                        progressive=True)
        else:
            canvas.save(buf, format="PNG", optimize=True)
        buf.seek(0)
    return buf


def _photo_image(profile: Profile, width_mm: float = 25.0):
    """Bewerbungsfoto als rechtsbündiges Bild (Standard: ~25 mm breit)."""
    p = _asset_path(profile, "foto")
    if not p:
        return None
    from PIL import Image as _PIL
    with _PIL.open(p) as im:
        w, h = im.size
    height_mm = width_mm * h / w
    source = _image_for_pdf(p, width_mm, jpeg=True)
    return Image(source, width=width_mm * mm, height=height_mm * mm)


def _signature_image(profile: Profile, width_mm: float = 38.0):
    """Unterschrift als Bild (linksbündig, Standard: ~38 mm breit)."""
    p = _asset_path(profile, "unterschrift")
    if not p:
        return None
    from PIL import Image as _PIL
    with _PIL.open(p) as im:
        w, h = im.size
    height_mm = width_mm * h / w
    # PNG behält einen transparenten Hintergrund (Unterschrift auf weißem Papier).
    source = _image_for_pdf(p, width_mm, jpeg=False)
    return Image(source, width=width_mm * mm, height=height_mm * mm, hAlign="LEFT")


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
    """Findet einen passenden Erfahrungs-Bullet zu einem (normalisierten) Skill.

    Kurze Skills (2–4 Zeichen, z. B. ``can``, ``std``, ``mil``) werden nur mit
    Wortgrenzen verglichen. Ohne diese Regel matcht ``std`` als Teilstring in
    „Te**std**urchführung“ und erzeugt einen sinnlosen Anschreiben-Punkt.
    """
    key = "bullets_en" if lang == "en" else "bullets_de"
    norm = normalize(skill)
    if not norm:
        return None, None
    short = bool(re.fullmatch(r"[a-z0-9]{2,4}", norm))
    for we in profile.work_experience:
        for bullet in we.get(key, []):
            if _is_filler_bullet(bullet):
                continue
            nb = normalize(bullet)
            if short:
                if re.search(r"\b" + re.escape(norm) + r"\b", nb):
                    return bullet, we
            elif norm in nb:
                return bullet, we
    return None, None


def _claim_signature(claim: str) -> str:
    """Vergleichssignatur eines Erfahrungs-Bullets.

    Entfernt einleitende Füllwörter („Verantwortung für die …") und kürzt auf den
    aussagekräftigen Anfang. Damit werden Bullets erkannt, die denselben
    Sachverhalt beschreiben, aber unterschiedlich lang zitiert sind
    (z. B. „Testkoordination zur Absicherung der Hardware- und Software-Integration."
    vs. „Verantwortung für die Testkoordination zur Absicherung der Hardware- und
    Software-Integration im Projekt …").
    """
    sig = normalize(claim)
    sig = re.sub(r"^(verantwortung fur|verantwortlich fur|zustandig fur|durchfuhrung von"
                 r"|responsibility for|responsible for|leading|led)\s+", "", sig)
    sig = re.sub(r"^(die|der|das|den|dem)\s+", "", sig)
    return sig[:60]


def _tailored_bullets(profile: Profile, match: dict, lang: str, max_bullets: int = 4):
    bullets: list[tuple[str, str]] = []
    used_claims: set[str] = set()
    used_signatures: set[str] = set()
    used_labels: list[str] = []
    used_stations: set[str] = set()
    for skill in match.get("matched_skills", []):
        if normalize(skill) in _GENERIC_SKILL_WORDS:
            continue
        claim, we = _claim_for(profile, skill, lang)
        label = _clean_label(profile.display_of(skill))
        if not claim:
            continue
        nlabel = normalize(label)
        # Redundante Labels unterdrücken: „Embedded Systems" fällt weg, wenn
        # „Embedded" schon gewählt wurde (und umgekehrt).
        if any(nlabel in prev or prev in nlabel for prev in used_labels):
            continue
        ck = normalize(claim)
        sig = _claim_signature(claim)
        if ck in used_claims or sig in used_signatures:
            continue
        bullets.append((label, claim))
        used_claims.add(ck)
        used_signatures.add(sig)
        used_labels.append(nlabel)
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
                if nb in used_claims or _claim_signature(bullet) in used_signatures:
                    continue
                bullets.append((_role_label(we, lang), bullet))
                used_claims.add(nb)
                used_signatures.add(_claim_signature(bullet))
                break
            if len(bullets) >= max_bullets:
                break
    return bullets


def _role_label(we: dict, lang: str) -> str:
    return we.get("role_en" if lang == "en" else "role_de") or ""


# Akronyme, die aus der Keyword-Extraktion als Kleinschreibung zurückkommen
# (z. B. "can" aus "CAN"), aber als Abkürzung GROSS geschrieben werden müssen.
_ACRONYMS = {
    "can", "iso", "ecu", "hil", "adas", "lin", "uds", "sil", "xil", "dbc",
    "fibex", "arxml", "api", "rtos", "mcu", "fpga", "jira", "gmsl", "autosar",
    "istqb", "aspice", "sae", "dsc", "sop", "ivvq", "fusa", "mbse",
}


def _clean_label(label: str) -> str:
    """Schreibt einzelne, rein kleingeschriebene Wort-Labels korrekt groß.

    Behebt Labels wie ``hardware`` → ``Hardware`` oder ``can`` → ``CAN``, die
    aus der Single-Word-Keyword-Extraktion stammen. Mehrwortige/phrasierte
    Labels bleiben unverändert.
    """
    s = (label or "").strip()
    if not s or " " in s or "-" in s or "/" in s or "(" in s:
        return s
    # Nur VOLLSTÄNDIG kleingeschriebene Akronyme forcieren (can→CAN, iso→ISO).
    # Bereits gemischte Schreibung (HiL, ECU) bleibt erhalten.
    if s.lower() in _ACRONYMS and s == s.lower():
        return s.upper()
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
    "de": ["Embedded Systems", "C/C++ & Python", "Mikrocontroller / ECU", "Test & Integration"],
    "en": ["Embedded systems", "C/C++ & Python", "Microcontroller / ECU", "Test & integration"],
}
_TEST_SUMMARY = {
    "de": ["Testautomatisierung", "HiL / XiL-Prüfstände", "Anforderungsbasiertes Testen (DOORS)", "ADAS / E/E-Systeme"],
    "en": ["Test automation", "HiL / XiL test benches", "Requirements-based testing (DOORS)", "ADAS / E/E systems"],
}


def _summary_skills(profile: Profile, job: dict, match: dict, lang: str, n: int = 3) -> list[str]:
    """Saubere, rollenabhängige Profil-Schwerpunkte (ohne Matching-Rauschen)."""
    strong = [
        _clean_label(profile.display_of(s))
        for s in match.get("matched_skills", [])
        if normalize(s) not in _GENERIC_SKILL_WORDS
        and any(h in normalize(s) for h in _STRONG_SKILL_HINTS)
    ]
    seen: set[str] = set()
    out: list[str] = []
    for s in strong:
        k = normalize(s)
        if not k:
            continue
        # Redundanz vermeiden: „Embedded Systems" überspringen, wenn „Embedded"
        # bereits gewählt ist (und umgekehrt).
        if any(k in prev or prev in k for prev in seen):
            continue
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
            f"{', for ' + esc(_en_place(client, lang)) if client else ''}), "
            f"I am responsible for: {esc(first_bullet)}"
        )
    return (
        f"In meiner aktuellen Rolle als <b>{esc(role)}</b> ({esc(employer)}"
        f"{', für ' + esc(client) if client else ''}) bin ich verantwortlich für: "
        f"{esc(first_bullet)}"
    )


def _append_gaps(story: list, st: dict, profile: Profile, job: dict, lang: str) -> None:
    """RAG-Anreicherung: bestätigte Lücken, die für diese Stelle relevant sind.

    Statt eine verlangte Kompetenz (z. B. DO-178C) stillschweigend zu behaupten,
    wird sie transparent als nicht vorhanden benannt. Das ist glaubwürdiger als
    jede Übertreibung und gehört zum „nachvollziehbaren Umgang mit fehlendem
    Kontext“.
    """
    from .rag import gap_evidence

    gaps = gap_evidence(profile, job, lang)
    if not gaps:
        return
    story.append(Spacer(1, 2 * mm))
    if lang == "de":
        story.append(Paragraph("Transparenz zu Anforderungen außerhalb meines Profils:", st["body"]))
    else:
        story.append(Paragraph("Transparency on requirements outside my profile:", st["body"]))
    story.append(Spacer(1, 2 * mm))
    for gap in gaps:
        story.append(Paragraph(f"•  {esc(gap)}", st["meta"]))
    story.append(Spacer(1, 3 * mm))


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

    # RAG-Anreicherung (opt-in): belegte Skills mit Quellenangabe statt der
    # pauschalen Bullets. Der Beleg ist *dieselbe* Liste — zusätzlich mit
    # Station und Zeitraum, damit der Leser nachvollziehen kann, woher ein
    # Anspruch stammt. Bleibt abschaltbar (bestehende Briefe unverändert).
    if config["documents"].get("anschreiben_quellen"):
        from .rag import citation, retrieve_evidence
        evidence = retrieve_evidence(profile, match, lang, max_claims=max_bullets)
        if evidence:
            if lang == "de":
                story.append(Paragraph("Ihre Anforderungen decke ich wie folgt ab:", st["body"]))
            else:
                story.append(Paragraph("I cover your requirements as follows:", st["body"]))
            story.append(Spacer(1, 2 * mm))
            for ev in evidence:
                story.append(Paragraph(f"•  <b>{esc(ev.label)}:</b> {esc(ev.claim)}", st["bullet"]))
                src = citation(ev, lang)
                if src:
                    story.append(Paragraph(
                        f'<font color="#64748b" size="7">&nbsp;&nbsp;{esc(src)}</font>', st["meta"]))
            story.append(Spacer(1, 3 * mm))
    else:
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

    if config["documents"].get("anschreiben_luecken"):
        _append_gaps(story, st, profile, job, lang)

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
        specialization = (
            "hardware/software integration of ECUs and embedded systems, "
            "test automation and validation"
            if is_chip else
            "test coordination, HiL/XiL test benches and test automation in the "
            "automotive/ADAS domain"
        )
        return (
            f"Mechanical engineer (Diplom) with many years of experience in the validation and "
            f"integration of complex E/E systems. Specialised in {specialization} — core "
            f"strengths: {esc(skills)}."
        )
    specialization = (
        "Hardware-/Software-Integration von Steuergeräten und Embedded Systemen, "
        "Testautomatisierung und Absicherung"
        if is_chip else
        "Testkoordination, HiL-/XiL-Prüfstände und Testautomatisierung im Automotive-/ADAS-Umfeld"
    )
    return (
        f"Diplom-Ingenieur Maschinenbau mit langjähriger Erfahrung in der Absicherung und "
        f"Integration komplexer E/E-Systeme. Spezialisiert auf {specialization} – "
        f"Kernkompetenzen: {esc(skills)}."
    )


def _cv_story_classic(profile: Profile, job: dict, match: dict, config: dict, lang: str) -> list:
    """Vorlage „Klassisch": einspaltig, klare Sektionen mit Akzentlinien."""
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


# --------------------------------------------------------------------------
# Gemeinsame Bausteine für die alternativen Lebenslauf-Vorlagen
# --------------------------------------------------------------------------

def _section_functional(story: list, st: dict, title: str, accent) -> None:
    """Sektionsüberschrift im funktionalen Stil: kurze, kräftige Akzentlinie links."""
    story.append(Paragraph(f"<b>{esc(title.upper())}</b>", st["sectionmarker"]))
    story.append(HRFlowable(width=26 * mm, thickness=1.4, color=accent,
                            hAlign="LEFT", spaceAfter=1.5 * mm))


def _languages_line(profile: Profile, lang: str) -> str:
    langs = []
    for entry in profile.languages:
        if isinstance(entry, dict):
            sprache = _translate(entry.get("sprache", ""), _LANGUAGE_TRANSLATIONS_EN, lang)
            niveau = _translate(entry.get("niveau", ""), _LANGUAGE_LEVEL_TRANSLATIONS_EN, lang)
            langs.append(f"{sprache} ({niveau})")
        else:
            langs.append(_translate(str(entry), _LANGUAGE_TRANSLATIONS_EN, lang))
    return " · ".join(langs)


def _contact_string(personal: dict) -> str:
    return " · ".join(x for x in [
        personal.get("address"), personal.get("phone"), personal.get("email"), LINKEDIN_URL
    ] if x)


def _split_name(personal: dict) -> tuple[str, str]:
    """Teilt den vollen Namen in Vor- und Nachname (für zweifarbige Namenszeilen)."""
    name = (personal.get("name") or "").strip()
    if " " in name:
        first, last = name.rsplit(" ", 1)
        return first, last
    return name, ""


def _contact_lines(personal: dict) -> list[str]:
    return [x for x in [
        personal.get("address", ""), personal.get("phone", ""),
        personal.get("email", ""), LINKEDIN_URL,
    ] if x]


def _dated_line(st: dict, left: str, right: str, left_w: float = 125 * mm) -> Table:
    """Zweispaltige Zeile: links fett, rechts (Zeitraum) ausgerichtet."""
    t = Table([[Paragraph(left, st["role"]), Paragraph(right, st["period"])]],
              colWidths=[left_w, 166 * mm - left_w])
    t.setStyle(_role_period_table_style())
    return t


def _role_period_table_style() -> TableStyle:
    return TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ])


def _cv_entry_two_rows(st: dict, title: str, right1: str, subtitle: str, right2: str) -> Table:
    """Zweizeiliger Eintrag (devcelio/„clean"-Stil): Titel|Ort, Rolle|Zeitraum."""
    t = Table([
        [Paragraph(f"<b>{esc(title)}</b>", st["role"]), Paragraph(esc(right1), st["period"])],
        [Paragraph(f"<i>{esc(subtitle)}</i>", st["meta"]), Paragraph(f"<i>{esc(right2)}</i>", st["period"])],
    ], colWidths=[116 * mm, 50 * mm])
    t.setStyle(_role_period_table_style())
    return t


# Obergrenzen für die Fachkenntnisse-Darstellung im Lebenslauf: Das Profil enthält
# bewusst mehr Einträge (sie fließen ins Matching ein), aber im CV werden nur die
# relevantesten gezeigt — überzählige wandern in eine kompakte „Weitere"-Zeile.
_MAX_CV_SKILLS = 30
_MAX_SKILLS_PER_GROUP = 6
_MAX_CV_OVERFLOW_SHOWN = 12


def _curate_skill_groups(profile: Profile, match: dict | None, lang: str):
    """Kürzt die Fachkenntnisse auf die relevantesten Einträge.

    Pro Gruppe werden stellenrelevante (gematchte) Skills zuerst gezeigt, danach
    die restlichen in Original-Reihenfolge. Die Gesamtzahl wird auf
    ``_MAX_CV_SKILLS`` begrenzt; der Rest landet in ``overflow`` (kompakte
    „Weitere"-Zeile). Das zugrunde liegende Profil bleibt unverändert.
    """
    labels = _SKILL_LABELS_EN if lang == "en" else _SKILL_LABELS
    matched_norm = {normalize(s) for s in (match or {}).get("matched_skills", [])}

    groups: list = []
    overflow: list[str] = []
    total = 0

    for key in profile.skills:
        if key == "sprachen":
            continue
        flat = _flatten_skill_values(profile.skills[key])
        if not flat:
            continue
        label = labels.get(key, key.replace("_", " ").capitalize())
        items = []
        for item in flat:
            display = _translate(item, _SKILL_TRANSLATIONS_EN, lang)
            item_norm = normalize(item)
            hit = any(item_norm == m or m in item_norm or item_norm in m
                      for m in matched_norm if m)
            items.append((display, hit))
        # Stellenrelevante zuerst (stabile Sortierung, Original-Reihenfolge bleibt).
        items.sort(key=lambda x: 0 if x[1] else 1)
        kept = items[:_MAX_SKILLS_PER_GROUP]
        rest = items[_MAX_SKILLS_PER_GROUP:]

        remaining = _MAX_CV_SKILLS - total
        if remaining <= 0:
            overflow.extend(d for d, _ in items)
            continue
        if len(kept) > remaining:
            overflow.extend(d for d, _ in kept[remaining:] + rest)
            kept = kept[:remaining]
        else:
            overflow.extend(d for d, _ in rest)

        if kept:
            groups.append((label, kept))
            total += len(kept)

    return groups, overflow


def _overflow_paragraph(overflow: list[str], st: dict, lang: str) -> Paragraph | None:
    """Komprimierte Einzeiler-Angabe für überzählige Fachkenntnisse."""
    if not overflow:
        return None
    prefix = "Weitere Kenntnisse" if lang == "de" else "Further skills"
    shown = overflow[:_MAX_CV_OVERFLOW_SHOWN]
    text = " · ".join(shown)
    if len(overflow) > len(shown):
        remaining = len(overflow) - len(shown)
        text += f" (+{remaining} weitere)" if lang == "de" else f" (+{remaining} more)"
    return Paragraph(
        f'<font color="#777777">{esc(prefix)}: {esc(text)}</font>',
        st["meta"],
    )


def _skill_group_blocks(profile: Profile, st: dict, lang: str, match: dict | None = None) -> list[list]:
    """Fähigkeitsgruppen als einzelne Blöcke (eine Gruppe pro Element)."""
    groups, overflow = _curate_skill_groups(profile, match, lang)
    out: list[list] = []
    for label, items in groups:
        parts = []
        for display, hit in items:
            parts.append(f"<b>{esc(display)}</b>" if hit else esc(display))
        out.append([Paragraph(f"<b>{esc(label)}</b><br/>{' · '.join(parts)}", st["body"])])
    extra = _overflow_paragraph(overflow, st, lang)
    if extra is not None:
        out.append([extra])
    return out


def _skills_stacked(profile: Profile, st: dict, lang: str, match: dict | None = None) -> list:
    """Fähigkeitsgruppen als gestapelte Blöcke (für schmale/kompetenzorientierte Layouts)."""
    out: list = []
    for block in _skill_group_blocks(profile, st, lang, match):
        out.extend(block)
        out.append(Spacer(1, 1.5 * mm))
    return out


def _experience_entries(profile: Profile, st: dict, lang: str,
                        width: float = 166 * mm) -> list[list]:
    """Berufserfahrung als Liste von Einträgen (ein Eintrag pro Element)."""
    is_en = lang == "en"
    entries: list[list] = []
    for we in _consolidate_experience(profile.work_experience):
        role = _role_label(we, lang)
        employer = we.get("employer_of_record", "")
        client = we.get("client", "")
        where = f"{employer} · {client}" if client else employer
        where = _en_place(where, lang)
        cell: list = [_role_period_table(st, role, we.get("period", ""), where, width=width)]
        cell.append(Paragraph(esc(where), st["company"]))
        key = "bullets_en" if is_en else "bullets_de"
        for bullet in [b for b in we.get(key, []) if not _is_filler_bullet(b)][:5]:
            cell.append(Paragraph(f"•  {esc(bullet)}", st["bullet"]))
        cell.append(Spacer(1, 3 * mm))
        entries.append(cell)
    return entries


def _experience_blocks(profile: Profile, st: dict, lang: str,
                       width: float = 166 * mm) -> list:
    """Berufserfahrung als Flussliste (gemeinsam für moderne/funktionale Vorlagen)."""
    out: list = []
    for cell in _experience_entries(profile, st, lang, width=width):
        out.extend(cell)
    return out


def _education_entries(profile: Profile, st: dict, lang: str,
                       width: float = 166 * mm) -> list[list]:
    is_en = lang == "en"
    entries: list[list] = []
    for edu in profile.education:
        title = edu.get("title_en" if is_en else "title_de", "")
        detail = edu.get("detail_en" if is_en else "detail_de", "")
        cell: list = [_role_period_table(st, title, edu.get("period", ""), "", width=width)]
        if detail:
            cell.append(Paragraph(esc(detail), st["meta"]))
        cell.append(Spacer(1, 1.5 * mm))
        entries.append(cell)
    return entries


def _education_blocks(profile: Profile, st: dict, lang: str,
                      width: float = 166 * mm) -> list:
    out: list = []
    for cell in _education_entries(profile, st, lang, width=width):
        out.extend(cell)
    return out


def _modern_sidebar(profile: Profile, job: dict, match: dict, st: dict, lang: str) -> list:
    """Seitenleiste der modernen Vorlage: Kontakt, Kompetenzen, Sprachen, Zertifikate."""
    is_en = lang == "en"
    personal = profile.personal
    out: list = []

    def block(title: str, body: list) -> None:
        out.append(Paragraph(f"<b>{esc(title.upper())}</b>", st["sectionmarker"]))
        out.extend(body)
        out.append(Spacer(1, 3 * mm))

    contact_lines = [x for x in [
        personal.get("address", ""), personal.get("phone", ""),
        personal.get("email", ""), LINKEDIN_URL,
    ] if x]
    block("Kontakt" if not is_en else "Contact",
          [Paragraph("<br/>".join(esc(x) for x in contact_lines), st["meta"])])

    skills = _summary_skills(profile, job, match, lang, n=6)
    block("Kernkompetenzen" if not is_en else "Core Skills",
          [Paragraph("•  " + esc(s), st["bullet"]) for s in skills])

    block("Sprachen" if not is_en else "Languages",
          [Paragraph(esc(_languages_line(profile, lang)), st["meta"])])

    if profile.certifications:
        block("Zertifizierungen" if not is_en else "Certifications",
              [Paragraph(esc(_translate(c, _CERTIFICATION_TRANSLATIONS_EN, lang)), st["meta"])
               for c in profile.certifications])
    return out


def _cv_story_modern(profile: Profile, job: dict, match: dict, config: dict, lang: str) -> list:
    """Vorlage „Modern": zweispaltig mit farbiger Seitenleiste und Akzent-Banner."""
    st = _styles()
    personal = profile.personal
    accent = HexColor(config["documents"].get("accent_color", "#0B3D5C"))
    is_en = lang == "en"

    story: list = []
    contact = " · ".join(x for x in [
        personal.get("address"), personal.get("phone"), personal.get("email"), LINKEDIN_URL
    ] if x)
    photo = _photo_image(profile, width_mm=24.0)

    # Kopf-Banner: Name + Headline auf Akzentfarbe, Foto rechts daneben.
    banner_name = Paragraph(
        f'<font color="#FFFFFF"><b>{esc(personal.get("name", ""))}</b></font><br/>'
        f'<font color="#D7E6F2">{esc(_headline(job, match, lang, config))}</font>',
        ParagraphStyle("mname", parent=st["name"], fontSize=17, leading=21,
                       textColor=HexColor("#FFFFFF")),
    )
    header_cells = [[banner_name, photo]] if photo else [[banner_name]]
    header_widths = [137 * mm, 24 * mm] if photo else [161 * mm]
    header = Table(header_cells, colWidths=header_widths)
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), accent),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(header)
    story.append(Paragraph(esc(contact), st["contact"]))
    story.append(Spacer(1, 3 * mm))

    # Rumpf als EINE mehrzeilige Tabelle: pro Abschnitt/Eintrag eine kurze Zeile,
    # damit ReportLab sauber zwischen den Zeilen umbrechen kann (eine einzelne,
    # seitenhohe Zeile lässt sich nicht teilen). Die Seitenleiste sitzt in Zeile 0.
    sidebar_width, main_width = 52 * mm, 109 * mm

    def title_cell(title: str) -> list:
        cell: list = []
        _section(cell, st, title, accent)
        return cell

    rows: list = []
    # 1) Seitenleiste + Profil.
    profile_col = title_cell("Profile" if is_en else "Profil")
    profile_col.append(Paragraph(_cv_profile_summary(profile, job, match, lang), st["body"]))
    profile_col.append(Spacer(1, 3 * mm))
    rows.append([_modern_sidebar(profile, job, match, st, lang), profile_col])

    # 2) Berufserfahrung — ein Eintrag pro Zeile.
    rows.append([[], title_cell("Work Experience" if is_en else "Berufserfahrung")])
    for cell in _experience_entries(profile, st, lang):
        rows.append([[], cell])

    # 3) Ausbildung — ein Eintrag pro Zeile.
    rows.append([[], title_cell("Education" if is_en else "Ausbildung")])
    for cell in _education_entries(profile, st, lang):
        rows.append([[], cell])

    # 4) Fachkenntnisse & Software — eine Gruppe pro Zeile.
    rows.append([[], title_cell("Skills & Software" if is_en else "Fachkenntnisse & Software")])
    for block in _skill_group_blocks(profile, st, lang, match):
        rows.append([[], [*block, Spacer(1, 1.5 * mm)]])

    body = Table(rows, colWidths=[sidebar_width, main_width])
    body.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 6),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("BACKGROUND", (0, 0), (0, 0), HexColor("#F2F6FA")),
    ]))
    story.append(body)
    return story, accent


def _cv_story_functional(profile: Profile, job: dict, match: dict, config: dict, lang: str) -> list:
    """Vorlage „Funktional": kompetenzorientiert — Fähigkeiten zuerst, kompakte Chronologie."""
    st = _styles()
    personal = profile.personal
    accent = HexColor(config["documents"].get("accent_color", "#0B3D5C"))
    is_en = lang == "en"

    story: list = []
    story.append(Paragraph(esc(personal.get("name", "")), st["name"]))
    story.append(Paragraph(esc(_headline(job, match, lang, config)), st["headline"]))
    contact = " · ".join(x for x in [
        personal.get("address"), personal.get("phone"), personal.get("email"), LINKEDIN_URL
    ] if x)
    story.append(Paragraph(esc(contact), st["contact"]))
    story.append(Spacer(1, 2 * mm))
    story.append(HRFlowable(width="100%", thickness=1.4, color=accent, spaceAfter=3 * mm))

    # 1) Kompetenzen zuerst (Kernaussage der funktionalen Vorlage).
    _section_functional(story, st, "Core Competencies" if is_en else "Kernkompetenzen", accent)
    story.append(_key_competencies(story, st, lang))
    story.append(Spacer(1, 3 * mm))

    _section_functional(story, st, "Skills & Software" if is_en else "Fachkenntnisse & Software", accent)
    story.extend(_skills_stacked(profile, st, lang, match))
    story.append(Spacer(1, 2 * mm))

    # 2) Profil.
    _section_functional(story, st, "Profile" if is_en else "Profil", accent)
    story.append(Paragraph(_cv_profile_summary(profile, job, match, lang), st["body"]))
    story.append(Spacer(1, 3 * mm))

    # 3) Berufserfahrung (kompakt).
    _section_functional(story, st, "Work Experience" if is_en else "Berufserfahrung", accent)
    story.extend(_experience_blocks(profile, st, lang))

    # 4) Ausbildung.
    _section_functional(story, st, "Education" if is_en else "Ausbildung", accent)
    story.extend(_education_blocks(profile, st, lang))
    story.append(Spacer(1, 2 * mm))

    # 5) Sprachen & Zertifizierung.
    _section_functional(story, st, "Languages & Certification" if is_en else "Sprachen & Zertifizierung", accent)
    story.append(Paragraph(esc(_languages_line(profile, lang)), st["body"]))
    for cert in profile.certifications:
        story.append(Paragraph(f"<b>{esc(_translate(cert, _CERTIFICATION_TRANSLATIONS_EN, lang))}</b>", st["body"]))
    story.append(Spacer(1, 3 * mm))
    return story, accent


# --------------------------------------------------------------------------
# GitHub-inspirierte Lebenslauf-Vorlagen (originalgetreue ReportLab-Ports)
# --------------------------------------------------------------------------

_FULL_WIDTH = 166 * mm
_NAME_GRAY = HexColor("#5D5D5D")
_DARK = HexColor("#333333")
_HEADINGS_GRAY = HexColor("#6A6A6A")
_LIGHT_GRAY = HexColor("#999999")


def _accent_hex(color) -> str:
    return f"#{int(color.red * 255):02X}{int(color.green * 255):02X}{int(color.blue * 255):02X}"


def _languages_blocks(profile: Profile, st: dict, lang: str) -> list:
    """Sprachen + Zertifikate als Flussliste."""
    out: list = [Paragraph(esc(_languages_line(profile, lang)), st["body"])]
    for cert in profile.certifications:
        out.append(Paragraph(
            f"<b>{esc(_translate(cert, _CERTIFICATION_TRANSLATIONS_EN, lang))}</b>",
            st["body"],
        ))
    return out


def _section_awesome(story: list, st: dict, title: str, accent) -> None:
    """Awesome-CV: erste 3 Zeichen in Akzentfarbe, graue Trennlinie darunter."""
    t = title.upper()
    if len(t) > 3:
        html = (f'<font color="{_accent_hex(accent)}"><b>{esc(t[:3])}</b></font>'
                f'<b>{esc(t[3:])}</b>')
    else:
        html = f'<font color="{_accent_hex(accent)}"><b>{esc(t)}</b></font>'
    story.append(Paragraph(html, ParagraphStyle("asec", parent=st["sectionmarker"],
                                                 fontSize=15, leading=18)))
    story.append(HRFlowable(width="100%", thickness=0.9, color=_NAME_GRAY,
                            spaceAfter=2 * mm))


def _section_mcdowell(story: list, st: dict, title: str) -> None:
    """McDowell: fette Serifen-Kapitälchen + volle Trennlinie."""
    p = ParagraphStyle("msec", parent=st["sectionmarker"], fontName="Times-Bold", fontSize=12)
    story.append(Paragraph(esc(title.upper()), p))
    story.append(HRFlowable(width="100%", thickness=0.6, color=TEXT_DARK,
                            spaceAfter=1.5 * mm))


def _section_deedy(story: list, st: dict, title: str) -> None:
    """Deedy: graue Kapitälchen, linksbündig."""
    p = ParagraphStyle("dsec", parent=st["sectionmarker"], fontSize=12, leading=15,
                       textColor=_HEADINGS_GRAY)
    story.append(Paragraph(f"<b>{esc(title.upper())}</b>", p))


def _section_billryan(story: list, st: dict, title: str, accent) -> None:
    """billryan: Marker + Titel (FontAwesome-Ersatz), dünne Trennlinie."""
    story.append(Paragraph(
        f'<font color="{_accent_hex(accent)}">›</font>  <b>{esc(title)}</b>',
        st["sectionmarker"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=LINE, spaceAfter=1.5 * mm))


def _section_clean(story: list, st: dict, title: str) -> None:
    """devcelio/„clean": fetter Titel + volle Trennlinie (titlerule)."""
    p = ParagraphStyle("csec", parent=st["sectionmarker"], fontSize=12.5)
    story.append(Paragraph(f"<b>{esc(title)}</b>", p))
    story.append(HRFlowable(width="100%", thickness=0.7, color=TEXT_DARK,
                            spaceAfter=1.5 * mm))


def _three_col_row(st: dict, left: str, center: str, right: str,
                   widths: list[float]) -> Table:
    """Dreispaltige Zeile (McDowell-Unterabschnitt: Rolle|Firma|Zeitraum)."""
    t = Table([
        [Paragraph(f"<b>{esc(left)}</b>", st["role"]),
         Paragraph(esc(center), st["meta"]),
         Paragraph(esc(right), st["period"])],
    ], colWidths=list(widths))
    t.setStyle(_role_period_table_style())
    return t


def _section_band(story: list, st: dict, title: str, accent,
                  width: float = _FULL_WIDTH) -> None:
    """Vollbreiter, akzentfarbener Sektionsbalken (latexcv-Stil)."""
    p = Paragraph(
        f'<font color="#FFFFFF"><b>{esc(title.upper())}</b></font>',
        ParagraphStyle("band", parent=st["sectionmarker"], leading=13,
                       textColor=HexColor("#FFFFFF")),
    )
    t = Table([[p]], colWidths=[width])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), accent),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t)
    story.append(Spacer(1, 2 * mm))


# --- Awesome-CV (posquit0/Awesome-CV, ~29k Stars) --------------------------

def _cv_story_awesome(profile: Profile, job: dict, match: dict, config: dict, lang: str) -> list:
    st = _styles()
    personal = profile.personal
    accent = HexColor(config["documents"].get("accent_color", "#0B3D5C"))
    is_en = lang == "en"
    first, last = _split_name(personal)

    story: list = []
    name_html = (f'<font color="#5D5D5D">{esc(first)}</font> '
                 f'<font color="#333333"><b>{esc(last)}</b></font>') if last else \
                f'<font color="#333333"><b>{esc(first)}</b></font>'
    story.append(Paragraph(name_html, ParagraphStyle("aname", parent=st["name"],
                                                     fontSize=24, leading=28)))
    story.append(Paragraph(esc(_headline(job, match, lang)),
                           ParagraphStyle("apos", parent=st["headline"],
                                          textColor=accent, fontSize=10, leading=13)))
    story.append(Spacer(1, 1.5 * mm))
    story.append(Paragraph(esc(personal.get("address", "")),
                           ParagraphStyle("aaddr", parent=st["contact"],
                                          textColor=_LIGHT_GRAY)))
    story.append(Paragraph(esc(" · ".join(x for x in [
        personal.get("phone", ""), personal.get("email", ""), LINKEDIN_URL] if x)),
        ParagraphStyle("asoc", parent=st["contact"], fontSize=8, leading=11)))
    story.append(Spacer(1, 4 * mm))

    _section_awesome(story, st, "Profile" if is_en else "Profil", accent)
    story.append(Paragraph(_cv_profile_summary(profile, job, match, lang), st["body"]))
    story.append(Spacer(1, 3 * mm))

    _section_awesome(story, st, "Work Experience" if is_en else "Berufserfahrung", accent)
    story.extend(_experience_blocks(profile, st, lang))

    _section_awesome(story, st, "Education" if is_en else "Ausbildung", accent)
    story.extend(_education_blocks(profile, st, lang))
    story.append(Spacer(1, 2 * mm))

    _section_awesome(story, st, "Skills & Software" if is_en else "Fachkenntnisse & Software", accent)
    story.append(_skills_two_columns(profile, st, lang, match))
    story.append(Spacer(1, 3 * mm))

    _section_awesome(story, st, "Languages & Certification" if is_en else "Sprachen & Zertifizierung", accent)
    story.extend(_languages_blocks(profile, st, lang))
    story.append(Spacer(1, 3 * mm))
    return story, accent


# --- Deedy-Resume (deedy/Deedy-Resume, ~5k Stars) --------------------------

def _stacked_entry(st: dict, heading: str, descriptor: str, meta: str) -> list:
    """Vertikal gestapelter Eintrag (Deedy-Stil): fette Überschrift, darunter Grau-Zeilen."""
    cell: list = [Paragraph(
        f"<b>{esc(heading.upper())}</b>",
        ParagraphStyle("dh", parent=st["role"], fontSize=10.5, leading=13,
                       textColor=_DARK))]
    if descriptor:
        cell.append(Paragraph(esc(descriptor),
                              ParagraphStyle("dd", parent=st["meta"], leading=12)))
    if meta:
        cell.append(Paragraph(esc(meta),
                              ParagraphStyle("dm", parent=st["meta"], fontSize=8.5,
                                             leading=11, textColor=_HEADINGS_GRAY)))
    return cell


def _deedy_experience_entries(profile: Profile, st: dict, lang: str) -> list[list]:
    is_en = lang == "en"
    out: list[list] = []
    for we in _consolidate_experience(profile.work_experience):
        role = _role_label(we, lang)
        employer = we.get("employer_of_record", "")
        client = we.get("client", "")
        meta = " | ".join(x for x in [we.get("period", ""), client] if x)
        cell = _stacked_entry(st, employer, role, meta)
        key = "bullets_en" if is_en else "bullets_de"
        for bullet in [b for b in we.get(key, []) if not _is_filler_bullet(b)][:5]:
            cell.append(Paragraph("•  " + esc(bullet), st["bullet"]))
        cell.append(Spacer(1, 2.5 * mm))
        out.append(cell)
    return out


def _deedy_education_entries(profile: Profile, st: dict, lang: str) -> list[list]:
    is_en = lang == "en"
    out: list[list] = []
    for edu in profile.education:
        title = edu.get("title_en" if is_en else "title_de", "")
        detail = edu.get("detail_en" if is_en else "detail_de", "")
        cell = _stacked_entry(st, title, detail, edu.get("period", ""))
        cell.append(Spacer(1, 1 * mm))
        out.append(cell)
    return out


def _cv_story_deedy(profile: Profile, job: dict, match: dict, config: dict, lang: str) -> list:
    st = _styles()
    personal = profile.personal
    accent = HexColor(config["documents"].get("accent_color", "#0B3D5C"))
    is_en = lang == "en"
    left_w, right_w = 52 * mm, 114 * mm

    story: list = []
    story.append(Paragraph(esc(personal.get("name", "")),
                           ParagraphStyle("dname", parent=st["name"], fontSize=26,
                                          leading=30, alignment=TA_CENTER)))
    story.append(Paragraph(esc(_headline(job, match, lang)),
                           ParagraphStyle("dhead", parent=st["headline"],
                                          alignment=TA_CENTER, textColor=_HEADINGS_GRAY)))
    story.append(Paragraph(esc(_contact_string(personal)),
                           ParagraphStyle("dcont", parent=st["contact"],
                                          alignment=TA_CENTER, textColor=_HEADINGS_GRAY)))
    story.append(Spacer(1, 1 * mm))
    story.append(HRFlowable(width="100%", thickness=0.6, color=_HEADINGS_GRAY,
                            spaceAfter=3 * mm))

    # Linke Spalte in drei kurze Blöcke aufteilen (je Zeile einer), damit
    # ReportLab sauber umbrechen kann.
    edu_cell: list = []
    _section_deedy(edu_cell, st, "Education" if is_en else "Ausbildung")
    for cell in _deedy_education_entries(profile, st, lang):
        edu_cell.extend(cell)

    skills_cell: list = []
    _section_deedy(skills_cell, st, "Skills" if is_en else "Fachkenntnisse")
    for s in _summary_skills(profile, job, match, lang, n=8):
        skills_cell.append(Paragraph("•  " + esc(s), st["bullet"]))

    langs_cell: list = []
    _section_deedy(langs_cell, st, "Languages" if is_en else "Sprachen")
    langs_cell.append(Paragraph(esc(_languages_line(profile, lang)), st["meta"]))

    profile_cell: list = []
    _section_deedy(profile_cell, st, "Profile" if is_en else "Profil")
    profile_cell.append(Paragraph(_cv_profile_summary(profile, job, match, lang), st["body"]))
    profile_cell.append(Spacer(1, 3 * mm))

    exp_cells = _deedy_experience_entries(profile, st, lang)

    exp_title: list = []
    _section_deedy(exp_title, st, "Experience" if is_en else "Erfahrung")

    rows: list = [[edu_cell, profile_cell]]
    rows.append([skills_cell, exp_title + (exp_cells[0] if exp_cells else [])])
    rows.append([langs_cell, exp_cells[1] if len(exp_cells) > 1 else []])
    for cell in exp_cells[2:]:
        rows.append([[], cell])

    body = Table(rows, colWidths=[left_w, right_w])
    body.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 8),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(body)
    return story, accent


# --- McDowell CV (dnl-blkv/mcdowell-cv, ~2.7k Stars) -----------------------

def _cv_story_mcdowell(profile: Profile, job: dict, match: dict, config: dict, lang: str) -> list:
    st = _styles()
    personal = profile.personal
    accent = HexColor(config["documents"].get("accent_color", "#0B3D5C"))
    is_en = lang == "en"

    story: list = []
    addr = personal.get("address", "")
    contacts = " · ".join(x for x in [personal.get("phone", ""), personal.get("email", "")] if x)
    name_p = Paragraph(esc(personal.get("name", "").upper()),
                       ParagraphStyle("mname", parent=st["name"], fontName="Times-Bold",
                                      fontSize=15, alignment=TA_CENTER))
    header = Table([
        [Paragraph(esc(addr), st["meta"]),
         name_p,
         Paragraph(esc(contacts), ParagraphStyle("mcont", parent=st["meta"], alignment=TA_RIGHT))],
    ], colWidths=[48 * mm, 69 * mm, 48 * mm])
    header.setStyle(_role_period_table_style())
    story.append(header)
    story.append(Spacer(1, 3 * mm))

    _section_mcdowell(story, st, "Profile" if is_en else "Profil")
    story.append(Paragraph(_cv_profile_summary(profile, job, match, lang), st["body"]))
    story.append(Spacer(1, 3 * mm))

    _section_mcdowell(story, st, "Work Experience" if is_en else "Berufserfahrung")
    for we in _consolidate_experience(profile.work_experience):
        role = _role_label(we, lang)
        employer = we.get("employer_of_record", "")
        client = we.get("client", "")
        where = (f"{employer} · {client}" if client else employer)
        where = _en_place(where, lang)
        story.append(_three_col_row(st, role, where, we.get("period", ""),
                                    [90 * mm, 40 * mm, 35 * mm]))
        key = "bullets_en" if is_en else "bullets_de"
        for bullet in [b for b in we.get(key, []) if not _is_filler_bullet(b)][:5]:
            story.append(Paragraph(f"•  {esc(bullet)}", st["bullet"]))
        story.append(Spacer(1, 2.5 * mm))

    _section_mcdowell(story, st, "Education" if is_en else "Ausbildung")
    for edu in profile.education:
        title = edu.get("title_en" if is_en else "title_de", "")
        detail = edu.get("detail_en" if is_en else "detail_de", "")
        story.append(_three_col_row(st, title, detail, edu.get("period", ""),
                                    [90 * mm, 40 * mm, 35 * mm]))
        story.append(Spacer(1, 1 * mm))
    story.append(Spacer(1, 2 * mm))

    _section_mcdowell(story, st, "Skills & Software" if is_en else "Fachkenntnisse & Software")
    story.append(_skills_two_columns(profile, st, lang, match))
    story.append(Spacer(1, 3 * mm))

    _section_mcdowell(story, st, "Languages & Certification" if is_en else "Sprachen & Zertifizierung")
    story.extend(_languages_blocks(profile, st, lang))
    story.append(Spacer(1, 3 * mm))
    return story, accent


# --- latexcv „sidebar" (jankapunkt/latexcv, ~3.4k Stars) -------------------

def _dark_sidebar(profile: Profile, job: dict, match: dict, st: dict, lang: str) -> list:
    is_en = lang == "en"
    personal = profile.personal
    out: list = []

    def dark_para(text: str, style_name: str, parent: ParagraphStyle, **kw) -> Paragraph:
        ps = ParagraphStyle(style_name, parent=parent, textColor=HexColor("#FFFFFF"), **kw)
        return Paragraph(text, ps)

    photo = _photo_image(profile, width_mm=30.0)
    if photo:
        out.append(photo)
        out.append(Spacer(1, 3 * mm))

    out.append(dark_para(f"<b>{esc(personal.get('name', ''))}</b>", "sname",
                         st["name"], fontSize=13, leading=16))
    out.append(Paragraph(esc(_headline(job, match, lang)),
                         ParagraphStyle("shead", parent=st["headline"],
                                        textColor=HexColor("#D7E6F2"))))
    out.append(Spacer(1, 3 * mm))

    out.append(dark_para(f"<b>{esc('Contact' if is_en else 'Kontakt').upper()}</b>",
                         "sc1", st["sectionmarker"], fontSize=11, leading=13))
    out.append(Paragraph("<br/>".join(esc(x) for x in _contact_lines(personal)),
                         ParagraphStyle("smeta", parent=st["meta"],
                                        textColor=HexColor("#EAF2F8"))))
    out.append(Spacer(1, 3 * mm))

    out.append(dark_para(f"<b>{esc('Skills' if is_en else 'Fachkenntnisse').upper()}</b>",
                         "sc2", st["sectionmarker"], fontSize=11, leading=13))
    for s in _summary_skills(profile, job, match, lang, n=8):
        out.append(Paragraph("•  " + esc(s),
                             ParagraphStyle("sbullet", parent=st["bullet"],
                                            textColor=HexColor("#FFFFFF"))))
    out.append(Spacer(1, 3 * mm))

    out.append(dark_para(f"<b>{esc('Languages' if is_en else 'Sprachen').upper()}</b>",
                         "sc3", st["sectionmarker"], fontSize=11, leading=13))
    out.append(Paragraph(esc(_languages_line(profile, lang)),
                         ParagraphStyle("slang", parent=st["meta"],
                                        textColor=HexColor("#EAF2F8"))))
    return out


def _cv_story_sidebar(profile: Profile, job: dict, match: dict, config: dict, lang: str) -> list:
    st = _styles()
    accent = HexColor(config["documents"].get("accent_color", "#0B3D5C"))
    is_en = lang == "en"
    left_w, right_w = 52 * mm, 113 * mm

    story: list = []

    profile_col: list = []
    _section_band(profile_col, st, "Profile" if is_en else "Profil", accent, width=right_w)
    profile_col.append(Paragraph(_cv_profile_summary(profile, job, match, lang), st["body"]))
    profile_col.append(Spacer(1, 3 * mm))

    rows: list = [[_dark_sidebar(profile, job, match, st, lang), profile_col]]

    exp_title: list = []
    _section_band(exp_title, st, "Work Experience" if is_en else "Berufserfahrung", accent, width=right_w)
    rows.append([[], exp_title])
    for cell in _experience_entries(profile, st, lang, width=right_w):
        rows.append([[], cell])

    edu_title: list = []
    _section_band(edu_title, st, "Education" if is_en else "Ausbildung", accent, width=right_w)
    rows.append([[], edu_title])
    for cell in _education_entries(profile, st, lang, width=right_w):
        rows.append([[], cell])

    cert_title: list = []
    _section_band(cert_title, st, "Languages & Certification" if is_en else "Sprachen & Zertifizierung", accent, width=right_w)
    rows.append([[], cert_title + _languages_blocks(profile, st, lang)])

    body = Table(rows, colWidths=[left_w, right_w])
    body.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (0, 0), 8),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("BACKGROUND", (0, 0), (0, -1), accent),
    ]))
    story.append(body)
    return story, accent


# --- billryan/resume (~11.5k Stars) ----------------------------------------

def _cv_story_elegant(profile: Profile, job: dict, match: dict, config: dict, lang: str) -> list:
    st = _styles()
    personal = profile.personal
    accent = HexColor(config["documents"].get("accent_color", "#0B3D5C"))
    is_en = lang == "en"

    story: list = []
    story.append(Paragraph(esc(personal.get("name", "")),
                           ParagraphStyle("bname", parent=st["name"], alignment=TA_CENTER)))
    story.append(Paragraph(esc(_headline(job, match, lang)),
                           ParagraphStyle("bhead", parent=st["headline"], alignment=TA_CENTER)))
    story.append(Paragraph(esc(_contact_string(personal)),
                           ParagraphStyle("bcont", parent=st["contact"], alignment=TA_CENTER)))
    story.append(Spacer(1, 3 * mm))

    _section_billryan(story, st, "Profile" if is_en else "Profil", accent)
    story.append(Paragraph(_cv_profile_summary(profile, job, match, lang), st["body"]))
    story.append(Spacer(1, 3 * mm))

    _section_billryan(story, st, "Experience" if is_en else "Berufserfahrung", accent)
    for we in _consolidate_experience(profile.work_experience):
        role = _role_label(we, lang)
        employer = we.get("employer_of_record", "")
        client = we.get("client", "")
        where = (f"{employer} · {client}" if client else employer)
        where = _en_place(where, lang)
        story.append(_dated_line(st, f"<b>{esc(where)}</b>", we.get("period", "")))
        story.append(Paragraph(f"<i>{esc(role)}</i>", st["meta"]))
        key = "bullets_en" if is_en else "bullets_de"
        for bullet in [b for b in we.get(key, []) if not _is_filler_bullet(b)][:5]:
            story.append(Paragraph(f"•  {esc(bullet)}", st["bullet"]))
        story.append(Spacer(1, 2.5 * mm))

    _section_billryan(story, st, "Education" if is_en else "Ausbildung", accent)
    for edu in profile.education:
        title = edu.get("title_en" if is_en else "title_de", "")
        detail = edu.get("detail_en" if is_en else "detail_de", "")
        story.append(_dated_line(st, f"<b>{esc(title)}</b>", edu.get("period", "")))
        if detail:
            story.append(Paragraph(esc(detail), st["meta"]))
        story.append(Spacer(1, 1 * mm))
    story.append(Spacer(1, 2 * mm))

    _section_billryan(story, st, "Skills & Software" if is_en else "Fachkenntnisse & Software", accent)
    story.append(_skills_two_columns(profile, st, lang, match))
    story.append(Spacer(1, 3 * mm))

    _section_billryan(story, st, "Languages & Certification" if is_en else "Sprachen & Zertifizierung", accent)
    story.extend(_languages_blocks(profile, st, lang))
    story.append(Spacer(1, 3 * mm))
    return story, accent


# --- devcelio/resume-template (1721 Stars, „clean"-Trend) ------------------

def _cv_story_clean(profile: Profile, job: dict, match: dict, config: dict, lang: str) -> list:
    st = _styles()
    personal = profile.personal
    accent = HexColor(config["documents"].get("accent_color", "#0B3D5C"))
    is_en = lang == "en"

    story: list = []
    story.append(Paragraph(f"<b>{esc(personal.get('name', ''))}</b>",
                           ParagraphStyle("clname", parent=st["name"], fontSize=15,
                                          alignment=TA_CENTER)))
    story.append(Paragraph(esc(_contact_string(personal)),
                           ParagraphStyle("clcont", parent=st["contact"], alignment=TA_CENTER)))
    story.append(Spacer(1, 3 * mm))

    _section_clean(story, st, "Profile" if is_en else "Profil")
    story.append(Paragraph(_cv_profile_summary(profile, job, match, lang), st["body"]))
    story.append(Spacer(1, 3 * mm))

    _section_clean(story, st, "Experience" if is_en else "Berufserfahrung")
    for we in _consolidate_experience(profile.work_experience):
        role = _role_label(we, lang)
        employer = we.get("employer_of_record", "")
        client = we.get("client", "")
        where = (f"{employer} · {client}" if client else employer)
        where = _en_place(where, lang)
        story.append(_cv_entry_two_rows(st, employer, client or "", role, we.get("period", "")))
        key = "bullets_en" if is_en else "bullets_de"
        for bullet in [b for b in we.get(key, []) if not _is_filler_bullet(b)][:5]:
            story.append(Paragraph(f"•  {esc(bullet)}", st["bullet"]))
        story.append(Spacer(1, 2.5 * mm))

    _section_clean(story, st, "Education" if is_en else "Ausbildung")
    for edu in profile.education:
        title = edu.get("title_en" if is_en else "title_de", "")
        detail = edu.get("detail_en" if is_en else "detail_de", "")
        story.append(_cv_entry_two_rows(st, title, "", detail, edu.get("period", "")))
        story.append(Spacer(1, 1 * mm))
    story.append(Spacer(1, 2 * mm))

    _section_clean(story, st, "Skills & Software" if is_en else "Fachkenntnisse & Software")
    story.append(_skills_two_columns(profile, st, lang, match))
    story.append(Spacer(1, 3 * mm))

    _section_clean(story, st, "Languages & Certification" if is_en else "Sprachen & Zertifizierung")
    story.extend(_languages_blocks(profile, st, lang))
    story.append(Spacer(1, 3 * mm))
    return story, accent


# --------------------------------------------------------------------------
# Lebenslauf-Vorlagen (Registrierung + Auswahl)
# --------------------------------------------------------------------------

CV_TEMPLATES: dict[str, dict] = {
    "classic": {
        "label": "Klassisch",
        "description": "Einspaltig mit klaren Sektionen und Akzentlinien — ATS-freundlich und zurückhaltend.",
    },
    "awesome": {
        "label": "Awesome",
        "description": "Zweifarbiger Name, akzentfarbene Sektionstitel (Awesome-CV, ~29k Stars).",
    },
    "deedy": {
        "label": "Deedy",
        "description": "Großer zentrierter Name, zwei Spalten mit linker Spalte (Deedy-Resume).",
    },
    "mcdowell": {
        "label": "McDowell",
        "description": "Serifen-Typografie, zentrierter Name, 3-spaltige Einträge (mcdowell-cv).",
    },
    "sidebar": {
        "label": "Sidebar",
        "description": "Dunkle Seitenleiste mit Foto/Kontakt/Skills (latexcv-Sidebar).",
    },
    "elegant": {
        "label": "Elegant",
        "description": "Zentrierter Kopf, datierte Einträge (billryan/resume, ~11k Stars).",
    },
    "clean": {
        "label": "Clean",
        "description": "Minimaler Einspalter mit Titel-Regeln und 2-Zeilen-Einträgen (devcelio, 1.7k Stars).",
    },
}

DEFAULT_CV_TEMPLATE = "classic"

_CV_BUILDERS = {
    "classic": _cv_story_classic,
    "awesome": _cv_story_awesome,
    "deedy": _cv_story_deedy,
    "mcdowell": _cv_story_mcdowell,
    "sidebar": _cv_story_sidebar,
    "elegant": _cv_story_elegant,
    "clean": _cv_story_clean,
}



def _cv_story(profile: Profile, job: dict, match: dict, config: dict, lang: str,
              template: str = DEFAULT_CV_TEMPLATE) -> list:
    builder = _CV_BUILDERS.get(template)
    if builder is None:
        raise ValueError(
            f"Unbekannte Lebenslauf-Vorlage: {template!r} "
            f"(verfügbar: {', '.join(CV_TEMPLATES)})"
        )
    return builder(profile, job, match, config, lang)


def _skills_two_columns(profile: Profile, st: dict, lang: str, match: dict | None = None) -> Table:
    """Fähigkeitsgruppen in zwei Spalten (Vorlagen-Layout).

    Passende Skills (aus ``match['matched_skills']``) werden hervorgehoben. Die
    Menge wird über ``_curate_skill_groups`` begrenzt; überzählige Einträge
    erscheinen als kompakte „Weitere"-Zeile unterhalb der Spalten.
    """
    groups, overflow = _curate_skill_groups(profile, match, lang)

    blocks: list[tuple[int, str]] = []
    for label, items in groups:
        parts = []
        for display, hit in items:
            parts.append(f"<b>{esc(display)}</b>" if hit else esc(display))
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
    extra = _overflow_paragraph(overflow, st, lang)
    if extra is not None:
        col_paras.append([extra, ""])

    t = Table(col_paras, colWidths=[83 * mm, 83 * mm])
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]
    if extra is not None:
        style.append(("SPAN", (0, 1), (1, 1)))
        style.append(("TOPPADDING", (0, 1), (1, 1), 2))
    t.setStyle(TableStyle(style))
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
    t = Table([card_paras], colWidths=[41.5 * mm, 41.5 * mm, 41.5 * mm, 41.5 * mm])
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


def generate_anschreiben(profile: Profile, job: dict, match: dict, out_path, config: dict, lang: str = "de",
                         text_out: list[str] | None = None) -> str:
    """Erzeugt das Anschreiben; kürzt automatisch, falls es > 1 Seite wird.

    ``text_out`` (optional) fängt den gerenderten Klartext der letzten
    (endgültigen) Fassung ein — Grundlage der Qualitätsprüfung in ``quality.py``.
    """
    decor = _page_decorator(HexColor(config["documents"].get("accent_color", "#0B3D5C")))

    def _build(max_bullets: int) -> int:
        story, _accent = _letter_story(profile, job, match, config, lang, max_bullets=max_bullets)
        if text_out is not None:
            text_out.clear()
            for flowable in story:
                try:
                    text_out.append(flowable.getPlainText())
                except AttributeError:
                    continue
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


def _profile_heading(lang: str) -> str:
    """Überschrift des Profil-Absatzes in der eigenen DOCX-Vorlage."""
    return "PROFILE" if lang == "en" else "PROFIL"


def _replace_profile_paragraph(doc, summary: str, lang: str) -> None:
    """Ersetzt den Profil-Absatz (direkt nach der „■ PROFIL/PROFILE“-Zeile).

    Der erste Absatz nach der Überschrift ist in der Vorlage genau der
    Profiltext. Wir behalten dessen Formatierung bei, indem wir nur den
    Text des ersten Runs austauschen (bzw. einen Run mit gleicher Größe
    anlegen, falls keiner existiert).
    """
    heading = _profile_heading(lang)
    for idx, para in enumerate(doc.paragraphs):
        if heading in para.text.upper():
            target = doc.paragraphs[idx + 1] if idx + 1 < len(doc.paragraphs) else None
            if target is None:
                return
            if target.runs:
                target.runs[0].text = summary
                for extra in target.runs[1:]:
                    extra.text = ""
            else:
                from docx.shared import Pt
                run = target.add_run(summary)
                # Vorlagen-Standardgröße des Profiltexts (10 pt).
                run.font.size = Pt(10)
            return


def generate_lebenslauf_vorlage(profile: Profile, job: dict, match: dict, out_path, config: dict, lang: str = "de", template: str | None = None) -> str:
    """Lebenslauf aus der eigenen DOCX-Vorlage (statt ReportLab-Generierung).

    Kopiert die aktuelle Lebenslauf-DOCX, ersetzt nur den Profil-Absatz durch
    den auf die Stelle zugeschnittenen Text und konvertiert zu PDF (soffice).
    Fällt auf ``generate_lebenslauf`` zurück, wenn keine Vorlage konfiguriert
    ist, die Datei fehlt oder die Konvertierung scheitert.
    """
    def _fallback():
        return generate_lebenslauf(profile, job, match, out_path, config, lang, template=template)

    vorlage = (config.get("documents", {}) or {}).get("lebenslauf_vorlage") or {}
    rel = vorlage.get(lang) or vorlage.get("de")
    if not rel:
        return _fallback()

    src = (AGENT_ROOT / rel).resolve()
    if not src.exists() or src.suffix.lower() != ".docx":
        return _fallback()

    summary = _cv_profile_summary(profile, job, match, lang)

    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    from docx import Document

    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            work_docx = tmpdir / "Lebenslauf.docx"
            shutil.copyfile(src, work_docx)

            doc = Document(str(work_docx))
            _replace_profile_paragraph(doc, summary, lang)
            # Die DOCX-Quelle ist US-Letter; die versendeten PDFs sind A4.
            # Wir stellen daher das Seitenformat auf A4, damit das Ergebnis
            # der bisherigen Version entspricht.
            from docx.shared import Mm
            for section in doc.sections:
                section.page_width = Mm(210)
                section.page_height = Mm(297)
            doc.save(str(work_docx))

            out_dir = tmpdir / "pdf"
            out_dir.mkdir()
            subprocess.run(
                ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(work_docx)],
                check=True, capture_output=True, timeout=180,
            )
            pdf = out_dir / "Lebenslauf.pdf"
            if not pdf.exists():
                candidates = list(out_dir.glob("*.pdf"))
                if not candidates:
                    return _fallback()
                pdf = candidates[0]
            shutil.copyfile(pdf, out_path)
    except Exception:
        return _fallback()

    return str(out_path)


def generate_lebenslauf(profile: Profile, job: dict, match: dict, out_path, config: dict, lang: str = "de", template: str | None = None) -> str:
    template = template or (config.get("documents", {}).get("lebenslauf_template") or DEFAULT_CV_TEMPLATE)
    story, accent = _cv_story(profile, job, match, config, lang, template=template)
    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=22 * mm, rightMargin=22 * mm, topMargin=20 * mm, bottomMargin=18 * mm,
        title=f"Lebenslauf {profile.personal.get('name', '')}", author=profile.personal.get("name", ""),
    )
    decor = _page_decorator(accent)
    doc.build(story, onFirstPage=decor, onLaterPages=decor)
    return str(out_path)
