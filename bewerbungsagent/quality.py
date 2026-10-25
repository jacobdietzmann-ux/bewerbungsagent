"""Unabhängige Qualitätsprüfung der erzeugten Bewerbungsunterlagen (P0b).

Warum ein eigener Prüfschritt: Anschreiben und Lebenslauf entstehen
deterministisch aus dem Profil — aber niemand hat bisher geprüft, ob das
Ergebnis das Profil auch *deckt*. Dieses Modul prüft die fertigen Unterlagen
gegen drei Quellen:

1. das Profil (Behauptungen, Zeiträume, Arbeitgeber),
2. die Stellenanzeige (werden die Anforderungen adressiert?),
3. die Datei selbst (existiert ein lesbares PDF mit plausibler Seitenzahl?).

Die Prüfung ist bewusst deterministisch und ohne Modell: Sie kann nicht
„überzeugt“ werden, und sie kostet nichts. Ein LLM-Check wäre eine Ergänzung
für Stil/Individualität, kein Ersatz — er ist hier nicht verdrahtet.

Befunde haben eine Schwere:

* ``fehler`` — die Unterlage enthält etwas, das nicht belegt ist, oder es
  fehlt ein Pflichtteil. Nicht versenden, bevor das geklärt ist.
* ``warnung`` — etwas ist auffällig (Anforderung nicht adressiert, Lücke nicht
  ausgewiesen), aber nicht zwingend falsch.
* ``hinweis`` — Kontext (z. B. Gehalt ist geschätzt), keine Handlung nötig.
"""

from __future__ import annotations

import re
from pathlib import Path

from .profile import Profile, normalize
from .storage import now_iso

VERSION = 1
MAX_BEFUNDE = 25

# Prüfungen, die nur die Datei betreffen — sie werden von ``run_quality``
# erneuert, ohne die Text-Befunde aus der Generierung zu verlieren.
ARTIFACT_CHECKS = ("PDF vorhanden", "PDF lesbar", "PDF Seitenzahl")

_SALUTATION = ("sehr geehrte", "dear ")
_CLOSING = ("mit freundlichen grussen", "mit freundlichen grüßen", "sincerely")
_TRANSPARENCY = ("transparenz zu anforderungen", "transparency on requirements")
_PERIOD_RE = re.compile(r"\b(\d{2})/(\d{4})\s*[–—\-]\s*(\d{2})/(\d{4})\b")
_EMPLOYER_RE = re.compile(
    r"\b(?:bei|at)[ \t]+(?:der[ \t]+|dem[ \t]+|the[ \t]+)?"
    r"([A-ZÄÖÜ][\w&\-]*(?:[ \t]+[A-ZÄÖÜ][\w&\-]*){0,2})"
)
_EMPLOYER_STOP = {
    "ihnen", "uns", "mir", "ihrem", "meinem", "der", "dem", "den", "dieser",
    "diesem", "team", "projekt", "unternehmen", "firma", "plattform",
    "kunde", "kunden", "lieferant", "lieferanten", "partner", "arbeitgeber",
    "standort", "bereich", "abteilung", "position", "stelle",
}


def _finding(schwere: str, pruefung: str, detail: str) -> dict:
    return {"schwere": schwere, "pruefung": pruefung, "detail": detail}


def _period_key(text: str) -> tuple[int, int, int, int] | None:
    m = _PERIOD_RE.search(text or "")
    if not m:
        return None
    return int(m.group(2)), int(m.group(1)), int(m.group(4)), int(m.group(3))


def _profile_periods(profile: Profile) -> set[tuple[int, int, int, int]]:
    out: set[tuple[int, int, int, int]] = set()
    for we in profile.work_experience:
        key = _period_key(str(we.get("period") or ""))
        if key:
            out.add(key)
    return out


def _profile_employers(profile: Profile) -> str:
    """Alle Namen, die im Profil als Arbeitgeber/Projekt auftauchen.

    ``employer_of_record`` und ``client`` sind die strukturierten Felder; die
    Erfahrungs-Bullets nennen zusätzlich Projektkunden („bei AIRBUS“), die
    ebenso belegt sind. Deshalb gehören sie in denselben Text.
    """
    parts: list[str] = [str(profile.personal.get("name") or "")]
    for we in profile.work_experience:
        parts.extend([str(we.get("employer_of_record") or ""),
                      str(we.get("client") or "")])
        for key in ("bullets_de", "bullets_en"):
            parts.extend(str(b) for b in (we.get(key) or []))
    return normalize(" ".join(parts))


def _profile_bullet_signatures(profile: Profile, lang: str) -> list[str]:
    from .documents import _claim_signature

    key = "bullets_en" if lang == "en" else "bullets_de"
    sigs: list[str] = []
    for we in profile.work_experience:
        for bullet in we.get(key) or []:
            if str(bullet).strip():
                sigs.append(_claim_signature(str(bullet)))
    return sigs


def _letter_lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _split_sections(lines: list[str]) -> tuple[list[str], list[str]]:
    """Trennt Behauptungs-Bullets von den Lücken-Bullets (Transparenz-Absatz)."""
    gap_idx = None
    for i, line in enumerate(lines):
        if line.lower().startswith(_TRANSPARENCY):
            gap_idx = i
            break
    if gap_idx is None:
        return [l for l in lines if l.startswith("•")], []
    return ([l for l in lines[:gap_idx] if l.startswith("•")],
            [l for l in lines[gap_idx:] if l.startswith("•")])


def _claim_parts(line: str) -> tuple[str, str] | None:
    """Zerlegt ``•  Label: Behauptung`` in (Label, Behauptung)."""
    body = line.lstrip("•").strip()
    if ": " not in body:
        return None
    label, claim = body.split(": ", 1)
    return label.strip(), claim.strip()


def check_letter(profile: Profile, job: dict, match: dict, config: dict,
                 lang: str, text: str) -> list[dict]:
    """Prüft den gerenderten Anschreiben-Text gegen Profil und Anzeige."""
    docs_cfg = (config or {}).get("documents") or {}
    findings: list[dict] = []
    low = (text or "").lower()

    # 1) Pflichtteile -------------------------------------------------------
    if not any(s in low for s in _SALUTATION):
        findings.append(_finding("fehler", "Pflichtteile", "Anrede fehlt"))
    if not any(s in low for s in _CLOSING):
        findings.append(_finding("fehler", "Pflichtteile", "Grußformel fehlt"))
    titel = normalize(job.get("titel") or "")
    if titel and titel[:30] not in normalize(text or ""):
        findings.append(_finding("fehler", "Pflichtteile",
                                 f"Stellentitel fehlt im Betreff: {job.get('titel')}"))

    # 2) Zeiträume ---------------------------------------------------------
    known = _profile_periods(profile)
    for m in _PERIOD_RE.finditer(text or ""):
        key = _period_key(m.group(0))
        if key and key not in known:
            findings.append(_finding("fehler", "Zeitraum",
                                     f"Zeitraum {m.group(0).strip()} steht nicht im Profil"))
            break

    # 3) Behauptungen ------------------------------------------------------
    claim_lines, gap_lines = _split_sections(_letter_lines(text))
    sigs = _profile_bullet_signatures(profile, lang)
    for line in claim_lines:
        parts = _claim_parts(line)
        if not parts:
            continue
        label, claim = parts
        from .documents import _claim_signature
        sig = _claim_signature(claim)
        if not sig:
            continue
        if any(sig == s or s.startswith(sig) or sig in s for s in sigs if s):
            continue
        findings.append(_finding("fehler", "Behauptung",
                                 f"Behauptung ohne Profil-Beleg ({label}): {claim[:90]}"))
        if len(findings) >= MAX_BEFUNDE:
            break

    # 4) Arbeitgeber-Nennungen --------------------------------------------
    employer_text = _profile_employers(profile)
    job_text = normalize(f"{job.get('firma') or ''} {job.get('titel') or ''}")
    for m in _EMPLOYER_RE.finditer(text or ""):
        candidate = m.group(1).strip().rstrip(".,;")
        first = normalize(candidate).split()[0] if normalize(candidate) else ""
        if not first or first in _EMPLOYER_STOP:
            continue
        # Der Projektkunde steht oft schon im Stellentitel („… bei AIRBUS“) —
        # das ist kein Widerspruch zum Profil, sondern die Anzeige selbst.
        if first in employer_text or first in job_text:
            continue
        findings.append(_finding("fehler", "Arbeitgeber",
                                 f"„{candidate}“ ist nicht im Profil oder in der Anzeige"))
        break

    # 5) Lücken transparent machen ---------------------------------------
    if docs_cfg.get("anschreiben_luecken", True):
        from .rag import gap_evidence
        gaps = gap_evidence(profile, job, lang)
        has_gap_section = any(line.lower().startswith(_TRANSPARENCY)
                              for line in _letter_lines(text))
        if gaps and not has_gap_section:
            findings.append(_finding("warnung", "Lücken",
                                     f"{len(gaps)} relevante Lücke(n) genannt, aber nicht ausgewiesen"))

    # 6) Anforderungen adressiert ----------------------------------------
    # Nur die Kernbegriffe aus dem *Titel* prüfen: `matched_skills` enthält
    # viele Nebenbegriffe, die kein Anschreiben vollständig aufgreifen kann.
    relevant = [str(s) for s in (match.get("title_hits") or match.get("matched_skills") or [])][:5]
    if relevant:
        covered = [s for s in relevant
                   if normalize(s) in low or normalize(profile.display_of(s)) in low]
        if not covered:
            # Hinweis, keine Warnung: Die Kernbegriffe sind eine Heuristik, und
            # ein englisches Anschreiben darf dieselbe Rolle anders benennen.
            findings.append(_finding("hinweis", "Anforderungen",
                                     "Keiner der Kernbegriffe aus dem Titel steht im Anschreiben — wirkt ggf. generisch"))

    # 7) Gehalt als Schätzung kennzeichnen -------------------------------
    if "gehaltsvorstellung" in low and (job.get("gehalt_quelle") or "") == "Schätzung":
        findings.append(_finding("hinweis", "Gehalt",
                                 "Gehaltsvorstellung stammt aus einer Schätzung, nicht aus der Anzeige"))

    return findings


def pdf_page_count(data: bytes) -> int:
    """Seitenzahl aus den PDF-Objekten (ReportLab schreibt ``/Type /Page``)."""
    return len(re.findall(rb"/Type\s*/Page(?!s)", data or b""))


def check_pdf(path: Path, *, max_pages: int | None = None,
              label: str = "PDF", missing_severity: str = "fehler") -> list[dict]:
    """Prüft, ob eine PDF-Datei existiert, lesbar ist und plausible Seiten hat.

    ``missing_severity`` unterscheidet den Fall „gerade erzeugt, muss da sein“
    (``fehler``) von „alte Bewerbung, Ordner wurde aufgeräumt“ (``hinweis``).
    """
    findings: list[dict] = []
    path = Path(path)
    if not path.exists():
        return [_finding(missing_severity, "PDF vorhanden", f"{label} fehlt: {path.name}")]
    data = path.read_bytes() if path.is_file() else b""
    if not data:
        return [_finding("fehler", "PDF lesbar", f"{label} ist leer: {path.name}")]
    if not data.startswith(b"%PDF"):
        return [_finding("fehler", "PDF lesbar", f"{label} ist kein PDF: {path.name}")]
    if len(data) < 1000:
        findings.append(_finding("warnung", "PDF lesbar",
                                 f"{label} ist ungewöhnlich klein ({len(data)} Bytes)"))
    pages = pdf_page_count(data)
    if pages < 1:
        findings.append(_finding("fehler", "PDF Seitenzahl",
                                 f"{label}: keine Seite im PDF gefunden"))
    elif max_pages and pages > max_pages:
        findings.append(_finding("warnung", "PDF Seitenzahl",
                                 f"{label} hat {pages} Seiten (erwartet ≤ {max_pages})"))
    return findings


def _sprache(key: str) -> str:
    """Sprachkürzel aus einem Text-Schlüssel (``anschreiben_en`` → ``en``).

    ``_generate_one`` übergibt die Brieftexte als ``anschreiben_de``/``anschreiben_en``.
    Vorher wurde dieser Schlüssel direkt als Sprache benutzt — der Abgleich der
    Behauptungen suchte dann ``bullets_anschreiben_en``, fand keine Profil-Belege
    und meldete **jede** Aussage des englischen Briefs als unbelegt (und in der
    Folge den ganzen Ordner als fehlerhaft).
    """
    tail = str(key or "").rsplit("_", 1)[-1]
    return tail if len(tail) == 2 else "de"


def check_application(profile: Profile, job: dict, match: dict, config: dict,
                      texte: dict[str, str] | None = None,
                      pdfs: dict[str, Path] | None = None,
                      anlagen: list[Path] | None = None) -> dict:
    """Führt alle Prüfungen aus und liefert den speicherbaren Befund-Dict."""
    findings: list[dict] = []
    texte = texte or {}
    pdfs = pdfs or {}

    for key, text in texte.items():
        lang = _sprache(key)
        for finding in check_letter(profile, job, match, config, lang, text):
            finding.setdefault("sprache", lang)
            finding["detail"] = f"[{lang.upper()}] {finding['detail']}"
            findings.append(finding)

    for label, path in pdfs.items():
        max_pages = 2 if label.startswith("anschreiben") else None
        findings.extend(check_pdf(path, max_pages=max_pages, label=label))

    for path in anlagen or []:
        if not Path(path).exists():
            findings.append(_finding("warnung", "Anlage",
                                     f"Anlage fehlt: {Path(path).name}"))

    findings = findings[:MAX_BEFUNDE]
    return {
        "ok": not any(f["schwere"] == "fehler" for f in findings),
        "befunde": findings,
        "umfang": "voll",
        "geprueft": now_iso(),
        "version": VERSION,
    }


def _resolve(rel: str) -> Path:
    from .config import AGENT_ROOT
    path = Path(rel)
    return path if path.is_absolute() else Path(AGENT_ROOT) / path


def run_quality(config) -> dict:
    """Prüft alle Bewerbungen mit Unterlagen erneut (Datei-Ebene).

    Text-Befunde aus der Generierung bleiben erhalten; nur die Datei-Prüfungen
    werden aufgefrischt. So kann die Prüfung jederzeit erneut laufen, ohne
    Dokumente neu zu erzeugen.
    """
    from .db import Store

    store = Store(config.db_path())
    state = store.load_state()
    apps = state.get("applications", [])
    geprueft = mit_befunden = 0
    details: list[dict] = []
    for app in apps:
        docs = app.get("dokumente") or {}
        if not docs or app.get("deleted"):
            continue
        existing = app.get("qualitaet") or {}
        keep = [f for f in (existing.get("befunde") or [])
                if f.get("pruefung") not in ARTIFACT_CHECKS]
        # Bei versendeten/abgeschlossenen Bewerbungen ist ein fehlendes PDF
        # meist der aufgeräumte Ordner, kein Fehler der Unterlagen.
        closed = (app.get("status") in ("sent", "followup", "interview", "rejected"))
        missing_severity = "hinweis" if closed else "fehler"
        neue: list[dict] = []
        for key, rel in docs.items():
            if not str(rel).lower().endswith(".pdf"):
                continue
            max_pages = 2 if str(key).startswith("anschreiben") else None
            neue.extend(check_pdf(_resolve(str(rel)), max_pages=max_pages,
                                  label=str(key), missing_severity=missing_severity))
        befunde = (keep + neue)[:MAX_BEFUNDE]
        app["qualitaet"] = {
            "ok": not any(f["schwere"] == "fehler" for f in befunde),
            "befunde": befunde,
            # „voll“ nur, wenn die Textprüfung bei der Generierung lief. Alte
            # Unterlagen haben sie nie gesehen — dann ist „ok“ nur die
            # Datei-Prüfung und wird im Dashboard auch so angezeigt.
            "umfang": "voll" if existing.get("umfang") == "voll" else "datei",
            "geprueft": now_iso(),
            "version": VERSION,
        }
        geprueft += 1
        if befunde:
            mit_befunden += 1
            details.append({
                "firma": app.get("firma"),
                "titel": app.get("titel"),
                "befunde": [f"{f.get('schwere')}: {f.get('detail')}" for f in befunde[:5]],
            })
    state["applications"] = apps
    state["updated"] = now_iso()
    store.save_state(state)
    store.export_json(config.state_path())
    return {"geprueft": geprueft, "mit_befunden": mit_befunden,
            "befunde": sum(len(a.get("qualitaet", {}).get("befunde") or []) for a in apps),
            "details": details[:20]}
