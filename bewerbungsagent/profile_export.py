"""Export des Profils als Obsidian-Markdown — aus der JSON, nicht von Hand.

Die ``Profil-Datenbank.json`` ist die einzige Quelle der Wahrheit. Die
Markdown-Fassung im Second Brain ist eine **Lesefassung** daraus; sie wurde
bisher von Hand gepflegt und lief dadurch auseinander (Stand 29.10.2026 nannte
sie noch „Python (erweiterte Grundkenntnisse)" und „C++ (Grundkenntnisse)",
während die JSON längst korrigiert war).

Deshalb: ``render_profile_markdown()`` erzeugt den Text deterministisch aus der
JSON, ``export_profile_markdown()`` schreibt ihn, ``profile_markdown_stale()``
meldet Abweichungen (für ``agent.py profile-export --check`` und den Cron).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

# Reihenfolge und Überschriften der Kompetenzmatrix. Die Schlüssel stammen aus
# ``skills`` der Profil-Datenbank; unbekannte Gruppen werden hinten angehängt,
# damit ein neuer Skill-Block nicht stillschweigend verschwindet.
SKILL_GROUPS: list[tuple[str, str]] = [
    ("test_datenauswertung_automatisierung", "Test & Datenauswertung"),
    ("requirements_testmanagement", "Requirements & Testmanagement"),
    ("diagnose_flashtools_bmw_audi", "Diagnose & Flash"),
    ("programmierung", "Programmierung"),
    ("standardprogramme_entwicklung", "Plattformen"),
    ("ki_gestuetzte_entwicklung", "KI-gestützte Entwicklung"),
    ("normen_prozesse", "Normen & Prozesse"),
    ("hardware_embedded_chip", "Hardware & Embedded"),
    ("sonstiges", "Sonstiges"),
]

# Vault-Nachbarn; reine Verlinkung, keine Profildaten.
VERWANDT = [
    "Beruf & Karriere",
    "Jobsuche 2026 – Bilanz & Pipeline",
    "Google Drive – Archivlandkarte",
]

KOPF = """---
type: ressource
created: {created}
tags:
  - ressource
  - beruf
  - profil
---
# Berufsprofil – Faktenbasis

> [!info] Automatisch erzeugt — nicht hier bearbeiten
> Lesefassung der `Profil-Datenbank.json` (einzige Quelle der Wahrheit). Änderungen
> gehören in die JSON; dieses Dokument wird mit `agent.py profile-export` neu erzeugt.

**Quelle:** `{quelle}` (Stand {stand})
"""


def _zelle(wert) -> str:
    """Tabellenzelle: Pipes und Zeilenumbrüche entschärfen."""
    text = str(wert or "").replace("|", "\\|").replace("\n", " ").strip()
    return text or "—"


def _liste(werte) -> str:
    return ", ".join(str(w).strip() for w in (werte or []) if str(w).strip())


def _person(profile: dict) -> str:
    p = profile.get("personal") or {}
    jahr = ""
    geboren = str(p.get("birth_date") or "")
    if geboren:
        jahr = geboren.split(".")[-1] if "." in geboren else geboren[:4]
    name = str(p.get("name") or "").strip()
    herkunft = str(p.get("birth_place") or "").strip()
    name_zelle = name + (f", Jg. {jahr}" if jahr else "")
    if herkunft:
        name_zelle += f" ({herkunft})"
    sprachen = _liste(
        f"{s.get('sprache')} ({s.get('niveau')})"
        for s in (profile.get("skills") or {}).get("sprachen") or []
        if isinstance(s, dict)
    )
    zeilen = [
        "| Feld | Wert |",
        "|---|---|",
        f"| Name | {_zelle(name_zelle)} |",
        f"| Anschrift | {_zelle(p.get('address'))} |",
        f"| Familienstand | {_zelle(p.get('marital_status'))} |",
        f"| Sprachen | {_zelle(sprachen)} |",
    ]
    return "## Person\n" + "\n".join(zeilen) + "\n"


def _kompetenzen(profile: dict) -> str:
    skills = profile.get("skills") or {}
    zeilen = ["| Gruppe | Inhalt |", "|---|---|"]
    bekannt = set()
    for key, label in SKILL_GROUPS:
        werte = skills.get(key)
        if not werte:
            continue
        inhalt = _liste(w.get("sprache") if isinstance(w, dict) else w for w in werte)
        if not inhalt:
            continue
        zeilen.append(f"| {label} | {_zelle(inhalt)} |")
        bekannt.add(key)
    for key, werte in skills.items():
        if key in bekannt or key == "sprachen" or not werte:
            continue
        inhalt = _liste(w.get("sprache") if isinstance(w, dict) else w for w in werte)
        if inhalt:
            zeilen.append(f"| {_zelle(key)} | {_zelle(inhalt)} |")
    return "## Kompetenzmatrix\n" + "\n".join(zeilen) + "\n"


def _beruf(profile: dict) -> str:
    stationen = profile.get("work_experience") or []
    if not stationen:
        return ""
    zeilen = ["| Zeitraum | Rolle | Arbeitgeber / Kunde |", "|---|---|---|"]
    for s in stationen:
        rolle = s.get("role_de") or s.get("role_en") or ""
        arbeitgeber = " / ".join(x for x in (s.get("employer_of_record"), s.get("client")) if x)
        zeilen.append(f"| {_zelle(s.get('period'))} | {_zelle(rolle)} | {_zelle(arbeitgeber)} |")
    return "## Berufserfahrung\n" + "\n".join(zeilen) + "\n"


def _ausbildung(profile: dict) -> str:
    zeilen: list[str] = []
    for s in profile.get("education") or []:
        titel = s.get("title_de") or s.get("title_en") or ""
        zeilen.append(f"- **{s.get('period', '').strip()}** — {titel}".rstrip(" —"))
    for z in profile.get("certifications") or []:
        zeilen.append(f"- {z}")
    if not zeilen:
        return ""
    return "## Ausbildung & Zertifikate\n" + "\n".join(zeilen) + "\n"


def _luecken(profile: dict) -> str:
    luecken = [str(g).strip() for g in profile.get("confirmed_gaps_do_not_overclaim") or []
               if str(g).strip()]
    if not luecken:
        return ""
    return ("## Was NICHT behauptet werden darf (bestätigte Lücken)\n"
            + "\n".join(f"- {g}" for g in luecken) + "\n")


def _tailoring(profile: dict) -> str:
    regeln = [str(r).strip() for r in profile.get("tailoring_rules") or [] if str(r).strip()]
    if not regeln:
        # Fallback: der Fließtext wird zu einem Satz pro Zeile.
        text = str(profile.get("tailoring_notes") or "").strip()
        regeln = [s.strip() for s in text.split(". ") if s.strip()]
    if not regeln:
        return ""
    return ("## Tailoring-Regel (für jede Bewerbung)\n"
            + "\n".join(f"{i}. {r.rstrip('.')}." for i, r in enumerate(regeln, start=1)) + "\n")


def render_profile_markdown(profile: dict, *, quelle: str,
                            created: str | None = None,
                            stand: str | None = None) -> str:
    """Erzeugt die Markdown-Lesefassung aus dem Profil-Dict."""
    stand = stand or date.today().strftime("%d.%m.%Y")
    created = created or str((profile.get("_meta") or {}).get("created") or date.today().isoformat())
    teile = [KOPF.format(created=created, quelle=quelle, stand=stand)]
    for block in (_person(profile), _kompetenzen(profile), _beruf(profile),
                  _ausbildung(profile), _luecken(profile), _tailoring(profile)):
        if block:
            teile.append(block)
    if VERWANDT:
        teile.append("## Verwandt\n" + "\n".join(f"- [[{v}]]" for v in VERWANDT) + "\n")
    return "\n".join(teile).rstrip() + "\n"


def _bestehendes_created(ziel: Path) -> str | None:
    """``created`` aus der vorhandenen Datei übernehmen (Datum bleibt stabil)."""
    try:
        text = ziel.read_text(encoding="utf-8")
    except OSError:
        return None
    for zeile in text.splitlines()[:8]:
        if zeile.lower().startswith("created:"):
            return zeile.split(":", 1)[1].strip()
    return None


def _quelle_anzeige(profile_path: Path) -> str:
    """Kurze, stabile Quellenangabe für den Kopf (kein absoluter Pfad)."""
    return f"{profile_path.parent.name}\\{profile_path.name}"


def export_profile_markdown(profile_path: Path, ziel: Path, *,
                            quelle: str | None = None) -> Path:
    """Schreibt die Markdown-Fassung aus der JSON (Elternordner wird angelegt)."""
    profile = json.loads(Path(profile_path).read_text(encoding="utf-8"))
    ziel = Path(ziel)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    text = render_profile_markdown(
        profile,
        quelle=quelle or _quelle_anzeige(Path(profile_path)),
        created=_bestehendes_created(ziel),
    )
    ziel.write_text(text, encoding="utf-8", newline="\n")
    return ziel


def profile_markdown_stale(profile_path: Path, ziel: Path) -> bool:
    """True, wenn die Markdown-Datei nicht dem aktuellen JSON-Stand entspricht."""
    ziel = Path(ziel)
    if not ziel.exists():
        return True
    profile = json.loads(Path(profile_path).read_text(encoding="utf-8"))
    erwartet = render_profile_markdown(
        profile,
        quelle=_quelle_anzeige(Path(profile_path)),
        created=_bestehendes_created(ziel),
        stand=_stand_aus_datei(ziel),
    )
    return ziel.read_text(encoding="utf-8").strip() != erwartet.strip()


def _stand_aus_datei(ziel: Path) -> str | None:
    """Das in der Datei stehende Datum, damit ein reiner Tageswechsel nicht
    als inhaltliche Abweichung gemeldet wird."""
    try:
        text = ziel.read_text(encoding="utf-8")
    except OSError:
        return None
    marker = "(Stand "
    i = text.find(marker)
    if i < 0:
        return None
    return text[i + len(marker):].split(")", 1)[0].strip() or None
