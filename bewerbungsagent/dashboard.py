"""Erzeugt das interaktive Bewerbungs-Dashboard (einzelne HTML-Datei).

Angelehnt an das alte ``00_Dashboard/Bewerbungs-Dashboard.html`` mit:
- Suche (Firma/Position/Branche), Profil-Fit-Filter, Status-Sichtfilter (Checkboxen)
- KPI-Karten (Versand-Quote, Interview-Quote, Ø Fit, Aktiv)
- Status-Verteilungs-Balkendiagramm + gestapeltes Wochen-Balkendiagramm
- sortierbare Tabelle mit editierbarem Status-Dropdown, Interview-Termin,
  Versand-Datum (auto), Löschen, Ordner öffnen, Dokument-Links
- Persistenz über einen lokalen Helfer-Server (GET/POST ``/state``), siehe server.py

Sichtbar sind Stellen mit Bewerbungsdokumenten und einem Pendelweg innerhalb der
konfigurierten Grenze (``max_pendelzeit_min``, Standard 30 min) — zusätzlich die
zuletzt gefundenen Stellen, auch ohne Unterlagen, damit das Label „neu gefunden"
überhaupt zu sehen ist. Das Zeitfenster dafür steht in der ``meta``-Tabelle der
Datenbank (``letzter_fund``).

Aus den Kennzahlen (KPIs) und dem Wochenverlauf bleiben ``research``-Einträge
(reine Funde) ausgenommen; die Status-Verteilung folgt der Tabelle, damit
Diagramm und Tabelle dieselben Zahlen zeigen. Der Wochenverlauf behält die übrige
Historie, damit frühere Wochen nicht leer erscheinen.

Die Daten werden als JSON in die HTML eingebettet (``const DATA``); der Server ist
die führende Quelle für Status-/Kontakt-/Notiz-Änderungen.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

from .commute import MAX_COMMUTE_MINUTES, exceeds_commute_limit
from .config import AGENT_ROOT
from .db import USER_DELETE_REASON
from .matching import fit_value
from .statuses import ORDER, STATUS, normalize_status
from .storage import now_iso

# Server-Root = eine Ebene über dem Agent (der alte Bewerbungsordner 2026/),
# damit sowohl 01_Bewerbungen/ als auch 04_Agent/output/ erreichbar sind.
ROOT = AGENT_ROOT.parent

_APPLICATION_DOCUMENT_KEYS = {
    "anschreiben_de", "lebenslauf_de", "anschreiben_en", "lebenslauf_en",
    "cover_letter_en", "cv_en",
}

# Das Alt-Dashboard speicherte die Dokumente unter ihren *Anzeige*-Labels statt
# unter technischen Keys. Solche Einträge galten als „ohne Bewerbungsunterlagen"
# und fielen aus Tabelle und Status-Verteilung (53 Einträge, u. a. 6 von 7
# Interviews). Beim Lesen werden die Labels auf die kanonischen Keys abgebildet.
_LEGACY_DOC_KEYS = {
    "Anschreiben": "anschreiben_de",
    "Lebenslauf": "lebenslauf_de",
    "Anschreiben (EN)": "anschreiben_en",
    "Cover Letter (EN)": "cover_letter_en",
    "CV (EN)": "cv_en",
    "Lebenslauf (EN)": "lebenslauf_en",
    "Stellenanzeige": "stellenanzeige",
    "Referenzschreiben": "referenzschreiben",
    "Referenzschreiben (BMW)": "referenzschreiben",
    "Briefing (PDF)": "briefing",
    "Briefing (PDF, EN)": "briefing_en",
    "Briefing (Interview)": "briefing",
    "Briefing (Markdown)": "briefing_md",
}


def _canonical_doc_key(key: str) -> str:
    """Bildet Legacy-Anzeige-Labels auf die technischen Dokument-Keys ab."""
    return _LEGACY_DOC_KEYS.get(key, key)

GERMAN_MONTHS = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]


def _doc_label(key: str) -> str:
    mapping = {
        "anschreiben_de": "Anschreiben",
        "lebenslauf_de": "Lebenslauf",
        "anschreiben_en": "Cover Letter (EN)",
        "lebenslauf_en": "CV (EN)",
        "cover_letter_en": "Cover Letter (EN)",
        "cv_en": "CV (EN)",
        "stellenanzeige": "Stellenanzeige",
        "referenzschreiben": "Referenzschreiben (BMW)",
        "briefing": "Briefing (PDF)",
        "briefing_en": "Briefing (PDF, EN)",
    }
    return mapping.get(key, key)


def _root_rel(stored_rel: str) -> str:
    """Wandelt einen relativ zu ``04_Agent`` gespeicherten Pfad in einen relativ zu ROOT um."""
    # Immer mit ``/`` als Trenner: Backslashes aus Windows-Pfaden sind in einem
    # URL-Pfad nicht zuverlässig und brachen einzelne Dokument-Links.
    return os.path.normpath(os.path.join(AGENT_ROOT.name, stored_rel)).replace(os.sep, "/")


def _existing_documents(app: dict) -> list[tuple[str, str]]:
    documents = []
    seen: set[str] = set()
    for key, stored in (app.get("dokumente") or {}).items():
        if not isinstance(stored, str) or not stored.strip():
            continue
        path = Path(stored)
        if not path.is_absolute():
            path = AGENT_ROOT / path
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        if path.is_file() and stat.st_size > 0:
            canonical = _canonical_doc_key(key)
            # Kanonischer Key gewinnt gegen ein Legacy-Label desselben Dokuments.
            if canonical in seen:
                continue
            seen.add(canonical)
            documents.append((canonical, stored))
    return documents


_BRIEFING_NAME_RE = re.compile(r"^briefing.*\.(pdf|md)$", re.IGNORECASE)


def _briefing_label(name: str) -> str:
    """Sprechendes Label aus dem Dateinamen (Deutsch/Englisch unterscheiden)."""
    low = name.lower()
    english = bool(re.search(r"(^|[_\-.])en([_\-.]|$)", low))
    return "Briefing (PDF, EN)" if english else "Briefing (PDF)"


def _briefing_documents(app: dict) -> list[dict]:
    """Briefings im Bewerbungsordner als zusätzliche Links.

    Das Briefing entsteht erst nach der Bewerbung (Interview-Vorbereitung) und
    steht deshalb nicht im ``dokumente``-Feld der DB. Es wird daher über den
    Ordner der vorhandenen Unterlagen gefunden: ``Briefing*.pdf`` zählt, eine
    Markdown-Datei nur, wenn kein PDF mit demselben Namen existiert.
    """
    folders: list[Path] = []
    for _key, stored in _existing_documents(app):
        path = Path(stored)
        if not path.is_absolute():
            path = AGENT_ROOT / path
        if path.parent not in folders:
            folders.append(path.parent)

    found: list[dict] = []
    seen: set[str] = set()
    for folder in folders:
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        pdfs: dict[str, Path] = {}
        markdown: dict[str, Path] = {}
        for entry in entries:
            if not _BRIEFING_NAME_RE.match(entry.name) or not entry.is_file():
                continue
            stem = entry.stem.lower()
            if entry.suffix.lower() == ".pdf":
                pdfs[stem] = entry
            else:
                markdown[stem] = entry
        chosen = sorted(pdfs.values()) + [p for k, p in sorted(markdown.items())
                                         if k not in pdfs]
        for entry in chosen:
            href = "/" + os.path.relpath(entry, ROOT).replace(os.sep, "/")
            if href in seen:
                continue
            seen.add(href)
            found.append({"label": _briefing_label(entry.name), "href": href})
    return found


def documented_applications(applications: list[dict]) -> list[dict]:
    """Bewerbungen mit mindestens einem vorhandenen Anschreiben oder Lebenslauf."""
    result = []
    for app in applications:
        if any(key in _APPLICATION_DOCUMENT_KEYS for key, _ in _existing_documents(app)):
            result.append(app)
    return result


def _exceeds_dashboard_commute_limit(app: dict, limit: int = MAX_COMMUTE_MINUTES) -> bool:
    return exceeds_commute_limit(app, limit=limit)


# Status, ab denen die Bewerbung tatsächlich rausgegangen ist. Ab hier ist der
# Eintrag ein Faktum im Prozess: fehlende Unterlagen im Ordner oder ein zu
# weiter Pendelweg dürfen ihn nicht aus Tabelle und Statistik entfernen.
# Vorher verschwanden 56 abgeschlossene Bewerbungen (7× sent, 49× rejected) —
# die damalige Absagen-Quote rechnete dadurch nur auf einer Teilmenge.
_PROGRESSED_STATUSES = {"sent", "followup", "interview", "rejected"}


def dashboard_applications(applications: list[dict],
                           limit: int = MAX_COMMUTE_MINUTES) -> list[dict]:
    """Für Tabelle und Statistik relevante Bewerbungen.

    Drei Regeln:

    1. **Bereits beworben** (``sent`` und weiter): immer sichtbar. Der Eintrag
       dokumentiert einen Vorgang, nicht eine Option.
    2. **Ausdrücklich freigegebene Research-Funde** (``research_sichtbar``): auch
       ohne Unterlagen sichtbar — aber nur innerhalb der Pendelzeit-Grenze. Das
       ist die Beobachtungsliste für Stellen im Research-Band (Fit 60–70 %), für
       die noch keine Bewerbung erzeugt wurde.
    3. **Noch nicht beworben** (``research``/``docs``): nur mit vorhandenem
       Anschreiben/Lebenslauf und innerhalb der Pendelzeit-Grenze. Das ist die
       Entscheidungsgrundlage, ob sich eine Bewerbung lohnt.

    Regel 3 bleibt bewusst streng: von 928 Einträgen liegen 658 im Status
    ``research``/``neu`` ohne Unterlagen. Ohne die Freigabe aus Regel 2 würde
    eine pauschale Lockerung die Tabelle mit 658 ungeprüften Funden füllen.

    ``limit`` kommt aus ``max_pendelzeit_min`` der Konfiguration; der Standard
    ist die Modulkonstante, damit Aufrufe ohne Konfiguration (Tests, Skripte)
    dasselbe Verhalten zeigen.
    """
    result = []
    for app in applications:
        status = normalize_status(app.get("status"))
        if status in _PROGRESSED_STATUSES:
            result.append(app)
            continue
        # Freigegebene Research-Funde: der Pendelweg bleibt harte Grenze, die
        # Unterlagen sind hier nicht nötig (es wird ja noch nicht beworben).
        if (status == "research" and app.get("research_sichtbar")
                and not _exceeds_dashboard_commute_limit(app, limit)):
            result.append(app)
            continue
        # ``research``/``docs``: nur mit vorhandenem Anschreiben/Lebenslauf und
        # innerhalb der Pendelzeit-Grenze. Reine Funde sind keine Bewerbungen
        # und dürfen weder Tabelle noch Zähler füllen.
        if not any(key in _APPLICATION_DOCUMENT_KEYS
                   for key, _ in _existing_documents(app)):
            continue
        if _exceeds_dashboard_commute_limit(app, limit):
            continue
        result.append(app)
    return result



def _app_id(app: dict) -> str:
    return app.get("key") or f"{app.get('firma', '')}|{app.get('titel', '')}"


def _parse_iso(value) -> datetime | None:
    """ISO-Zeitstempel tolerant einlesen (auch reine Datumsangaben)."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).strip())
    except ValueError:
        return None
    return dt


def zuletzt_gefunden(app: dict, letzter_fund: dict | None) -> bool:
    """Gehört die Stelle zum jüngsten Fund?

    ``created`` ist der Erfassungszeitpunkt (``_merge_state`` setzt ihn einmal je
    Lauf für alle neuen Stellen). Gespeichert ist der ``created``-Stempel des
    jüngsten Fundes; alles ab diesem Zeitpunkt ist „neu gefunden".

    Zeitstempel werden als ``datetime`` verglichen, nicht als Zeichenketten:
    ``2026-10-15T16:14:00+02:00`` und ``2026-10-15T16:14:00+01:00`` beschreiben
    verschiedene Zeitpunkte, sortieren als Text aber gleich.
    """
    if not letzter_fund:
        return False
    grenze = _parse_iso(letzter_fund.get("zeitpunkt"))
    created = _parse_iso(app.get("created"))
    if grenze is None or created is None:
        return False
    if (grenze.tzinfo is None) != (created.tzinfo is None):
        return False  # nicht vergleichbar: lieber kein Label als ein falsches
    return created >= grenze


def _fmt_date(app: dict) -> str:
    """Liefert das „Gefunden am"-Datum eines Eintrags (DD.MM.YYYY) oder ``""``.

    Priorität:
    1. ``datum``            – explizites Fund-Datum aus dem alten Dashboard.
    2. ``created``          – Erfassungszeitpunkt des Agenten (ISO-Zeitstempel).
    3. ``sentAt``           – Versanddatum (nur als Rückfallebene).

    Ist kein Wert vorhanden, wird **kein** Datum erfunden: früher fiel die
    Funktion auf „heute" zurück. Dadurch landeten Alt-Einträge ohne
    Zeitstempel im Wochenverlauf in der aktuellen Woche und täuschten neue
    Funde vor (z. B. 9 Einträge am 19.10.2026, obwohl nichts gefunden wurde).
    """
    datum = (app.get("datum") or "").strip()
    if datum:
        return datum
    created = (app.get("created") or "").strip()
    if created and len(created) >= 10:
        # ISO-Zeitstempel, z. B. "2026-10-08T11:25:53+02:00" → "08.10.2026".
        y, m, d = created[:10].split("-")
        return f"{d}.{m}.{y}"
    sent = (app.get("sentAt") or "").strip()
    if sent and len(sent) >= 10:
        y, m, d = sent[:10].split("-")
        return f"{d}.{m}.{y}"
    return ""


def _availability(app: dict) -> bool | None:
    """Verfügbarkeit der Anzeige als Tri-State.

    ``True``/``False`` = geprüft, ``None`` = unbekannt (nie geprüft).
    Ein unbekannter Wert darf im Dashboard NICHT als „abgelaufen" gelten —
    ``bool(None)`` wäre ``False`` und hätte genau dieses falsche Badge erzeugt.
    """
    value = app.get("verfuegbar")
    return None if value is None else bool(value)


def _dim_summary(dims: dict | None) -> dict | None:
    """Kompakte Anzeigeform der mehrdimensionalen Bewertung (Dashboard-Tooltip)."""
    if not isinstance(dims, dict) or dims.get("gesamt") is None:
        return None
    werte = dims.get("werte") or {}
    order = ("kompetenz", "aufgaben", "senioritaet", "technologie",
             "gehalt", "arbeitsmodell", "entwicklung")
    detail = " · ".join(f"{k} {werte[k]}" for k in order if k in werte)
    return {
        "gesamt": int(dims.get("gesamt") or 0),
        "ko": [str(k.get("grund") or "") for k in (dims.get("ko") or [])],
        "detail": detail,
    }


def _quality_summary(quality: dict | None) -> dict | None:
    """Kompakte Anzeigeform der Qualitätsprüfung (P0b)."""
    if not isinstance(quality, dict):
        return None
    befunde = quality.get("befunde") or []
    return {
        "ok": bool(quality.get("ok")),
        "n": len(befunde),
        "errors": sum(1 for f in befunde if f.get("schwere") == "fehler"),
        "umfang": quality.get("umfang") or "datei",
        "befunde": [f'{f.get("schwere", "?")}: {f.get("detail", "")}' for f in befunde[:6]],
    }


def _to_data(app: dict, letzter_fund: dict | None = None) -> dict:
    fit = fit_value(app)

    docs = []
    for key, stored in _existing_documents(app):
        # ``stored`` ist relativ zu 04_Agent; ``_root_rel`` macht daraus einen
        # Pfad relativ zum Server-Root (2026/). Der führende Schrägstrich ist
        # wichtig, damit der Browser den Link von /04_Agent/dashboard.html aus
        # korrekt gegen den Server-Root auflöst (sonst 404).
        rel = _root_rel(stored)
        docs.append({"label": _doc_label(key), "href": "/" + rel})
    # Interview-Briefings liegen erst nach dem Versand im Bewerbungsordner und
    # werden deshalb hier zusätzlich eingesammelt.
    existing_hrefs = {d["href"] for d in docs}
    docs.extend(d for d in _briefing_documents(app) if d["href"] not in existing_hrefs)

    folder = ""
    if docs:
        # Für /open?path=… (wird an ROOT angehängt) ohne führenden Schrägstrich.
        folder = os.path.dirname(docs[0]["href"]).lstrip("/").replace("\\", "/")

    # Absoluter Pfad für die Zwischenablage. ``folder`` ist relativ zum
    # Server-Root; erst damit lässt sich der Ordner in Explorer/Finder oder in
    # ein anderes Programm einfügen.
    folder_abs = os.path.normpath(str(ROOT / folder)) if folder else ""

    contact = app.get("contact") or app.get("ansprechpartner") or ""

    return {
        "id": _app_id(app),
        "company": app.get("firma", "") or "",
        "position": app.get("titel", "") or "",
        "branch": app.get("branche", "") or "",
        "location": app.get("ort", "") or "",
        "homeoffice": app.get("homeoffice", "") or "",
        "date": _fmt_date(app),
        "status": normalize_status(app.get("status")),
        "fit": fit,
        "dim": _dim_summary(app.get("dimensionen")),
        "quality": _quality_summary(app.get("qualitaet")),
        "salary": app.get("gehalt", "") or "",
        "salarySource": app.get("gehalt_quelle", "") or "",
        "commute": app.get("pendelzeit_min"),
        "commuteKm": app.get("pendeldistanz_km"),
        "commuteMode": app.get("pendel_modus", "") or "",
        "contact": contact,
        "link": app.get("url", "") or "",
        "folder": folder,
        "folderAbs": folder_abs,
        "docs": docs,
        "notes": app.get("notes", "") or "",
        "beschreibung": app.get("beschreibung", "") or "",
        "verfuegbar": _availability(app),
        "matched": app.get("matched_skills", []) or [],
        "interviewDate": app.get("interviewDate", "") or "",
        "statusChangedAt": app.get("statusChangedAt", "") or "",
        "sentAt": app.get("sentAt", "") or "",
        "neuImLauf": zuletzt_gefunden(app, letzter_fund),
        "deleted": bool(app.get("deleted")),
    }


def _last_run_label(letzter_fund: dict | None) -> str:
    """Zeitpunkt des jüngsten Fundes, z. B. „15.10.2026 16:14"."""
    zeitpunkt = _parse_iso((letzter_fund or {}).get("zeitpunkt"))
    if zeitpunkt is None:
        return ""
    return (f"{zeitpunkt.day:02d}.{zeitpunkt.month:02d}.{zeitpunkt.year} "
            f"{zeitpunkt:%H:%M}")


def build_dashboard(state: dict, output_path: Path,
                    commute_limit: int = MAX_COMMUTE_MINUTES,
                    letzter_fund: dict | None = None) -> Path:
    apps = state.get("applications", []) if isinstance(state, dict) else []
    # Der komplette Bestand wird eingebettet, damit der Wochenverlauf auch
    # frühere Bewerbungen ohne Dokumente zeigt: die Tabelle sowie die
    # Status-Verteilung und die KPIs beziehen sich nur auf relevante Stellen
    # (mit Dokumenten, Pendelweg innerhalb der Grenze), der Wochenverlauf auf die
    # Historie ohne „Research"-Funde. Deshalb bekommt jede Zeile ein
    # ``visible``-Flag statt den Bestand vorab zu filtern.
    visible_keys = {_app_id(a) for a in dashboard_applications(apps, commute_limit)}
    data = [_to_data(a, letzter_fund) for a in apps]
    for row in data:
        # Neu gefundene Stellen sind noch unbewertet und haben keine Unterlagen —
        # ohne diese Ausnahme wäre das „neu gefunden"-Label nie zu sehen. Sie
        # fallen automatisch wieder aus der Tabelle, sobald ein späterer Lauf
        # andere Stellen als die neuesten markiert.
        row["visible"] = row["id"] in visible_keys or row["neuImLauf"]
    data.sort(key=lambda r: r["fit"], reverse=True)

    data_json = json.dumps(data, ensure_ascii=False, indent=2).replace("</", "<\\/")
    html_doc = (_HTML_TEMPLATE
                .replace("__DATA__", data_json)
                .replace("__LAST_RUN__", json.dumps(_last_run_label(letzter_fund),
                                                    ensure_ascii=False))
                .replace("__LAST_FUND_ANZAHL__", str(int((letzter_fund or {}).get("anzahl") or 0)))
                .replace("__COMMUTE_LIMIT__", str(int(commute_limit)))
                .replace("__GENERATED__", now_iso()))

    output_path.write_text(html_doc, encoding="utf-8")
    return output_path


def _status_json() -> str:
    return json.dumps({k: {"label": v["label"], "cls": v["cls"], "color": v["color"]}
                       for k, v in STATUS.items()}, ensure_ascii=False)


def _order_json() -> str:
    return json.dumps(ORDER, ensure_ascii=False)


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate" />
<meta http-equiv="Pragma" content="no-cache" />
<title>Bewerbungs-Dashboard — Jacob Dietzmann</title>
<style>
  :root {
    --bg:#0f172a; --panel:#1e293b; --panel-2:#263449; --line:#334155;
    --text:#e2e8f0; --muted:#94a3b8; --accent:#38bdf8;
    --green:#22c55e; --amber:#f59e0b; --red:#ef4444; --violet:#a78bfa;
  }
  * { box-sizing:border-box; }
  body { margin:0; font-family:"Segoe UI",system-ui,-apple-system,Roboto,sans-serif;
         background:var(--bg); color:var(--text); padding:24px; }
  header { display:flex; flex-wrap:wrap; align-items:baseline; justify-content:space-between;
           gap:12px; margin-bottom:20px; }
  h1 { font-size:22px; margin:0; }
  .sub { color:var(--muted); font-size:13px; }
  .kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
          gap:14px; margin-bottom:24px; }
  .kpi { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:14px 16px; }
  .kpi .label { font-size:12px; color:var(--muted); }
  .kpi .value { font-size:26px; font-weight:700; margin-top:6px; }
  .kpi .value small { font-size:13px; color:var(--muted); font-weight:400; }
  .kpi .target { font-size:11px; margin-top:4px; }
  .good { color:var(--green); } .warn { color:var(--amber); } .bad { color:var(--red); }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:12px; overflow:hidden; }
  .dist-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(290px,1fr)); gap:22px; }
  .dist-title { font-size:12px; font-weight:600; color:var(--text); margin-bottom:2px; }
  .dist-sub { font-size:11px; color:var(--muted); margin-bottom:8px; }
  .dist-row { display:flex; align-items:center; gap:8px; font-size:11px; margin-bottom:4px; }
  .dist-label { width:132px; color:var(--muted); flex:none; overflow:hidden;
                text-overflow:ellipsis; white-space:nowrap; }
  .dist-track { flex:1; background:var(--panel-2); border-radius:5px; overflow:hidden; height:14px; }
  .dist-fill { height:100%; border-radius:5px; }
  .dist-num { width:52px; text-align:right; flex:none; color:var(--text); }
  .table-scroll { overflow-x:auto; }
  table { width:100%; min-width:1080px; border-collapse:collapse; font-size:13px; table-layout:fixed; }
  th, td { padding:8px 10px; text-align:left; border-bottom:1px solid var(--line); vertical-align:middle;
           overflow-wrap:break-word; word-break:break-word; }
  th { background:var(--panel-2); color:var(--muted); font-weight:600; position:sticky; top:0; }
  th[data-col] { cursor:pointer; user-select:none; }
  th[data-col]:hover { color:var(--text); }
  th .arw { color:#64748b; font-size:11px; margin-left:2px; }
  tbody tr:hover { background:rgba(56,189,248,.06); }
  td.center, th.center { text-align:center; }
  select, input[type=text], input[type=date] { background:var(--bg); color:var(--text);
    border:1px solid var(--line); border-radius:8px; padding:6px 8px; font-size:12px; width:100%; }
  input[type=text]::placeholder { color:#64748b; }
  input[type=date]::-webkit-calendar-picker-indicator { filter:invert(.7); }
  .badge { padding:3px 9px; border-radius:999px; font-size:11px; font-weight:600; white-space:nowrap; }
  .badge-neu { background:rgba(56,189,248,.18); color:#7dd3fc; border:1px solid rgba(56,189,248,.5); }
  tr.ist-neu > td:first-child { box-shadow:inset 3px 0 0 #38bdf8; }
  .s-research { background:#334155; color:#cbd5e1; }
  .s-docs     { background:#1d4ed833; color:#93c5fd; border:1px solid #1d4ed855; }
  .s-sent     { background:#7c3aed33; color:#c4b5fd; border:1px solid #7c3aed55; }
  .s-followup { background:#b4530933; color:#fdba74; border:1px solid #b4530955; }
  .s-interview{ background:#15803d33; color:#86efac; border:1px solid #15803d55; }
  .s-rejected { background:#7f1d1d33; color:#fca5a5; border:1px solid #7f1d1d66; }
  a.folder { color:var(--accent); text-decoration:none; font-size:12px; }
  a.folder:hover { text-decoration:underline; }
  /* „Pfad kopieren" sitzt neben „Ordner ↗" und soll wie ein Link wirken,
     aber als echter Button anklickbar sein. */
  button.copy-btn {
    background:none; border:none; padding:0; margin-left:6px;
    color:var(--muted); font:inherit; font-size:11px; cursor:pointer;
    text-decoration:underline;
  }
  button.copy-btn:hover { color:var(--accent); }
  button.copy-btn.done { color:#22c55e; text-decoration:none; }
  button.row-delete { background:transparent; border:1px solid var(--line); border-radius:8px;
    padding:4px 9px; font-size:13px; cursor:pointer; line-height:1; }
  button.row-delete:hover { border-color:var(--red); background:#7f1d1d22; }
  .toolbar { display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin:14px 0; }
  button { background:var(--panel-2); color:var(--text); border:1px solid var(--line);
    border-radius:8px; padding:8px 14px; font-size:12px; cursor:pointer; }
  button:hover { border-color:var(--accent); }
  .toolbar label.toggle { display:inline-flex; align-items:center; gap:8px; font-size:12px;
    background:var(--panel-2); border:1px solid var(--line); border-radius:8px;
    padding:8px 14px; cursor:pointer; user-select:none; }
  .toolbar label.toggle:hover { border-color:var(--accent); }
  .toolbar label.toggle input { accent-color:var(--accent); width:15px; height:15px; cursor:pointer; }
  .toolbar label.toggle .hint { color:var(--muted); }
  .legend { color:var(--muted); font-size:12px; margin-top:16px; line-height:1.6; }
  .legend code { background:var(--panel-2); padding:1px 6px; border-radius:5px; color:var(--text); }
  .hint { color:var(--muted); font-size:11px; margin-top:3px; }
  .desc-toggle { cursor:pointer; color:var(--accent); font-size:11px; background:none;
    border:none; padding:0; margin-top:4px; text-decoration:underline dotted; }
  .desc-toggle:hover { color:var(--text); }
  tr.desc-row td { padding:0 8px 12px; }
  .desc-body { padding:12px 14px; background:var(--panel-2);
    border-radius:8px; font-size:12.5px; line-height:1.6; color:var(--text); width:100%;
    white-space:normal; word-break:break-word; }
  #toast { position:fixed; left:50%; bottom:24px; transform:translateX(-50%) translateY(20px);
    background:var(--panel-2); color:var(--text); border:1px solid var(--accent);
    padding:12px 18px; border-radius:10px; font-size:13px; line-height:1.5; max-width:80vw;
    box-shadow:0 8px 30px #000a; opacity:0; pointer-events:none; transition:opacity .25s,transform .25s; z-index:999; }
  #toast.show { opacity:1; transform:translateX(-50%) translateY(0); }
  #toast code { background:var(--panel); padding:2px 6px; border-radius:5px; word-break:break-all; }
  .tabs { display:flex; gap:4px; margin-bottom:18px; border-bottom:1px solid var(--line); }
  .tab { background:transparent; border:none; border-bottom:2px solid transparent; border-radius:0;
         padding:11px 18px; font-size:13px; font-weight:600; color:var(--muted); cursor:pointer; }
  .tab:hover { color:var(--text); }
  .tab.active { color:var(--text); border-bottom-color:var(--accent); }
  .pane[hidden] { display:none; }
</style>
</head>
<body>
  <header>
    <div>
      <h1>Bewerbungs-Dashboard — Jacob Dietzmann</h1>
      <div class="sub">Live-Tracking · Änderungen werden über den lokalen Server dauerhaft gespeichert</div>
    </div>
    <div class="sub" id="stamp">Stand: __GENERATED__</div>
  </header>

  <nav class="tabs" role="tablist">
    <button class="tab active" id="tabBtn-table" data-tab="table" role="tab"
            aria-controls="tab-table" aria-selected="true">Tabelle</button>
    <button class="tab" id="tabBtn-stats" data-tab="stats" role="tab"
            aria-controls="tab-stats" aria-selected="false">Statistik &amp; Diagramme</button>
  </nav>

  <section class="pane" id="tab-table" role="tabpanel" aria-labelledby="tabBtn-table">
    <div class="toolbar" style="margin-top:0" id="statusToggles"></div>
    <div class="toolbar">
      <input type="text" id="searchBox" placeholder="Suche: Firma, Position, Branche …" style="max-width:260px" />
      <select id="fitFilter" style="max-width:200px">
        <option value="0">Alle Profil-Fits</option>
        <option value="50">Nur ≥ 50 % (mittel+)</option>
        <option value="65">Nur ≥ 65 % (gelb+)</option>
        <option value="80">Nur ≥ 80 % (grün)</option>
      </select>
      <label style="display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);white-space:nowrap">
        <input type="checkbox" id="neuFilter" /> Nur neu gefundene
      </label>
      <span id="neuInfo" class="sub" style="font-size:11px"></span>
    </div>

    <div class="card">
      <div class="table-scroll">
      <table id="table-main">
        <colgroup>
          <col style="width:12%">
          <col style="width:17%">
          <col style="width:9%">
          <col style="width:11%">
          <col style="width:5%">
          <col style="width:5%">
          <col style="width:6%">
          <col style="width:12%">
          <col style="width:5%">
          <col style="width:6%">
          <col style="width:8%">
          <col style="width:4%">
        </colgroup>
        <thead>
          <tr>
            <th data-col="0" onclick="sortTable(0)">Unternehmen <span class="arw">↕</span></th>
            <th data-col="1" onclick="sortTable(1)">Position <span class="arw">↕</span></th>
            <th data-col="2" onclick="sortTable(2)">Branche <span class="arw">↕</span></th>
            <th class="center" data-col="3" onclick="sortTable(3)">Arbeitsort <span class="arw">↕</span></th>
            <th class="center" data-col="4" onclick="sortTable(4)">Homeoffice <span class="arw">↕</span></th>
            <th class="center" data-col="5" onclick="sortTable(5)">Pendelweg <span class="arw">↕</span></th>
            <th class="center" data-col="6" onclick="sortTable(6)">Gefunden am <span class="arw">↕</span></th>
            <th class="center" data-col="7" onclick="sortTable(7)">Status <span class="arw">↕</span></th>
            <th class="center" data-col="8" onclick="sortTable(8)">Profil-Fit <span class="arw">↕</span></th>
            <th class="center" data-col="9" onclick="sortTable(9)">Gehalt (ca.) <span class="arw">↕</span></th>
            <th class="center" data-col="10" onclick="sortTable(10)">Links <span class="arw">↕</span></th>
            <th class="center">Aktion</th>
          </tr>
        </thead>
        <tbody id="rows"></tbody>
      </table>
      </div>
    </div>

    <div class="toolbar">
      <button id="reset">Auf Standard zurücksetzen</button>
      <button id="export">Als JSON exportieren</button>
    </div>

    <div class="legend">
      <strong>Status-Workflow:</strong>
      <code>Dokumente erstellt</code> → <code>Versendet</code> → <code>Follow-up</code> → <code>Interview</code> · Endstatus <code>Abgelehnt/Abgelaufen</code><br>
      <strong>Angezeigt werden nur Stellen mit Bewerbungsdokumenten</strong> (Pendelweg ≤ __COMMUTE_LIMIT__ min); zusätzlich die zuletzt gefundenen Stellen, auch ohne Unterlagen. Reine frühere Funde (<code>Research</code>) bleiben ausgeblendet und zählen nicht in den Kennzahlen mit.<br>
      <strong>„neu gefunden":</strong> Die Stelle gehört zum jüngsten Fund (blauer Balken links, Badge an der Position, Filter oben). Das bleibt stehen, bis ein Lauf neue Stellen mitbringt — ein Lauf ohne Funde löscht das Label nicht.<br>
      <strong>Pendelweg:</strong> Die Farbe zeigt die Restluft bis zur Grenze von __COMMUTE_LIMIT__ min — <span style="color:#22c55e">≤ 50 % grün</span>, <span style="color:#84cc16">≤ 75 % hellgrün</span>, <span style="color:#f59e0b">≤ 90 % gelb</span>, <span style="color:#f97316">≤ 100 % orange</span>, <span style="color:#ef4444">darüber rot</span>. Ein Tooltip nennt Minuten, Grenze und Restluft.<br>
      <strong>Profil-Fit (%):</strong> Matching-Ergebnis gegen das Skill-Profil. ≥ 80 % grün, 65–79 % gelb, &lt; 65 % rot. Neu importierte Stellen aus dem alten Dashboard behalten ihren ursprünglichen Wert; neue Web-Treffer basieren auf Titel/Firma/Ort (ohne Beschreibungstext) und liegen daher konservativ niedrig — für eine präzise Bewertung die Anzeige per Import mit Beschreibung einpflegen.<br>
      <strong>Prüfung:</strong> Qualitätsprüfung der erzeugten Unterlagen — <span style="color:#22c55e">✓ bestanden</span>, <span style="color:#fbbf24">⚠ nur Hinweise</span>, <span style="color:#fca5a5">✗ Fehler</span>. Der Tooltip nennt die Befunde (Behauptung ohne Profil-Beleg, falscher Zeitraum, fehlender Pflichtteil, PDF-Problem).<br>
      <strong>Status ändern:</strong> Direkt über das Dropdown in der Status-Spalte. Änderungen werden an den lokalen Server gesendet und in <code>data/state.json</code> gespeichert (Start über <code>dashboard-oeffnen.sh</code>).<br>
      <strong>Ordner öffnen:</strong> Öffnet den Bewerbungsordner (01_Bewerbungen bzw. 04_Agent/output) im Dateimanager, sofern das Dashboard über den Server läuft.<br>
      <strong>Aktion (🗑):</strong> Entfernt den Eintrag aus dem Dashboard (nach Bestätigung); rückgängig nur über „Auf Standard zurücksetzen".
    </div>
  </section>

  <section class="pane" id="tab-stats" role="tabpanel" aria-labelledby="tabBtn-stats" hidden>
    <section class="kpis" id="kpis"></section>

    <section class="card" style="padding:14px 16px;margin-bottom:16px">
      <div style="font-size:12px;color:var(--muted);margin-bottom:8px">Status-Verteilung</div>
      <div id="statusChart" style="display:flex;flex-direction:column;gap:6px"></div>
    </section>

    <section class="card" style="padding:14px 16px;margin-bottom:16px">
      <div style="font-size:12px;color:var(--muted);margin-bottom:8px">Bewerbungsaktivität im Wochenverlauf</div>
      <div id="timeChart" style="display:flex;align-items:flex-end;gap:12px;overflow-x:auto;padding:4px 2px 6px"></div>
      <div id="timeChartLegend" style="display:flex;flex-wrap:wrap;gap:12px;margin-top:8px;font-size:11px;color:var(--muted)"></div>
    </section>

    <section class="card" style="padding:14px 16px">
      <div style="font-size:12px;color:var(--text);font-weight:600;margin-bottom:2px">Häufigkeitsverteilungen</div>
      <div class="dist-sub" id="distBasis"></div>
      <div class="dist-grid">
        <div>
          <div class="dist-title">Homeoffice</div>
          <div class="dist-sub">Wie präsent ist die Stelle?</div>
          <div id="distHomeoffice"></div>
        </div>
        <div>
          <div class="dist-title">Fahrzeit (einfach, Auto)</div>
          <div class="dist-sub">Pendelweg zur Grenze von __COMMUTE_LIMIT__ min</div>
          <div id="distCommute"></div>
        </div>
        <div>
          <div class="dist-title">Profil-Fit</div>
          <div class="dist-sub">Matching gegen dein Skill-Profil</div>
          <div id="distFit"></div>
        </div>
        <div>
          <div class="dist-title">Unternehmen</div>
          <div class="dist-sub" id="distCompanySub">Top-Arbeitgeber im Bestand</div>
          <div id="distCompany"></div>
        </div>
      </div>
    </section>
  </section>

<script>
const STATUS = __STATUS__;
const ORDER = __ORDER__;
// Alle Status sind einblendbar. „Research" war früher ausgenommen, weil solche
// Einträge nie sichtbar waren — als „neu gefunden" erscheinen sie jetzt aber,
// also braucht es den Schalter. Aus den Kennzahlen bleiben sie weiterhin
// ausgenommen (siehe renderKpis).
const SHOWN_STATUSES = ORDER;
// Pendelzeit-Grenze aus der Konfiguration (max_pendelzeit_min) — so kann die
// Anzeige nicht von der Ausschlusslogik abweichen. Genau das war zuvor der Fall:
// die Grenze stand als 30 an vier Stellen im Code.
const COMMUTE_LIMIT = __COMMUTE_LIMIT__;
// Zeitpunkt des jüngsten Fundes (aus der meta-Tabelle der DB). Leer, wenn noch
// kein Fund protokolliert wurde.
const LAST_RUN = __LAST_RUN__;
// Anzahl der beim jüngsten Fund neu erfassten Stellen (vor Pendelweg-Filter).
const LAST_FUND_ANZAHL = __LAST_FUND_ANZAHL__;
const EDITABLE = ["status", "contact", "deleted", "deleted_reason", "notes", "interviewDate", "statusChangedAt", "sentAt"];
// Marker für eine Löschung durch den Nutzer. Der Pipeline-Lauf erkennt daran,
// dass er den Eintrag nicht wieder einblenden darf.
const USER_DELETE_REASON = __USER_DELETE_REASON__;
const KEY = "bewerbungsagent-dashboard-v1";
const HIDDEN_STATUSES_KEY = "bewerbungsagent-hidden-statuses";
const TAB_KEY = "bewerbungsagent-active-tab";

let sortCol = -1, sortAsc = true;

function readOverlay() {
  try {
    const o = JSON.parse(localStorage.getItem(KEY));
    if (o && typeof o === "object" && !Array.isArray(o)) return o;
  } catch (e) {}
  return {};
}

const DATA = __DATA__;

function load() {
  const base = JSON.parse(JSON.stringify(DATA));
  const overlay = readOverlay();
  base.forEach(r => {
    const o = overlay[r.id];
    if (o) EDITABLE.forEach(k => { if (o[k] !== undefined && o[k] !== null) r[k] = o[k]; });
  });
  return base;
}
let state = load();

let hiddenStatuses = new Set();
try {
  const arr = JSON.parse(localStorage.getItem(HIDDEN_STATUSES_KEY));
  if (Array.isArray(arr)) hiddenStatuses = new Set(arr);
} catch (e) {}

const SERVER = (location.protocol === "http:" || location.protocol === "https:")
  ? location.origin : "http://127.0.0.1:8766";

function overlayEntry(r) {
  return { status:r.status, contact:r.contact, deleted:!!r.deleted,
           deleted_reason:r.deleted_reason||"", notes:r.notes||"",
           interviewDate:r.interviewDate||"", statusChangedAt:r.statusChangedAt||"", sentAt:r.sentAt||"" };
}
function currentOverlay() {
  const o = {};
  state.forEach(r => { o[r.id] = overlayEntry(r); });
  return o;
}
function saveLocal() {
  try { localStorage.setItem(KEY, JSON.stringify(currentOverlay())); } catch (e) {}
}
let pendingOverlay = null;
let pushChain = Promise.resolve();
function pushServer(o) {
  pushChain = pushChain.then(() => fetch(SERVER + "/state", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify(o), keepalive:true
    }).then(r => {
      if (!r.ok) throw new Error("HTTP " + r.status);
      if (pendingOverlay === o) pendingOverlay = null;
    }).catch(() => {
      pendingOverlay = o;
      toast("⚠️ Speichern fehlgeschlagen – Dashboard-Server nicht erreichbar. Starte ihn über <code>dashboard-oeffnen.sh</code>; die Änderung bleibt lokal und wird automatisch nachgeholt.");
    })
  );
  return pushChain;
}
function save(id) {
  saveLocal();
  if (id) {
    const row = state.find(r => r.id === id);
    if (row) { pushServer({ [id]: overlayEntry(row) }); return; }
  }
  pushServer(currentOverlay());
}
saveLocal();

(function syncFromServer() {
  if (pendingOverlay) pushServer(pendingOverlay);
  fetch(SERVER + "/state", { cache:"no-store" })
    .then(r => r.ok ? r.json() : null)
    .then(serverOverlay => {
      if (!serverOverlay || typeof serverOverlay !== "object" || Array.isArray(serverOverlay)) return;
      const merged = pendingOverlay
        ? Object.assign({}, serverOverlay, currentOverlay())
        : Object.assign({}, currentOverlay(), serverOverlay);
      let changed = false;
      state.forEach(r => {
        const o = merged[r.id];
        if (!o) return;
        EDITABLE.forEach(k => {
          if (o[k] !== undefined && o[k] !== null && r[k] !== o[k]) { r[k] = o[k]; changed = true; }
        });
      });
      if (changed) { saveLocal(); refreshAllViews(); }
    })
    .catch(() => {});
})();

const cols = ["company","position","branch","location","homeoffice","commute","date","status","fit","salary","link","folder"];

function esc(s) {
  return String(s == null ? "" : s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

function parseDate(s) {
  const m = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec((s || "").trim());
  return m ? new Date(+m[3], +m[2]-1, +m[1]).getTime() : 0;
}
function parseSalary(s) {
  const m = /(\d+)/.exec((s || "").trim());
  return m ? +m[1] : 0;
}
function parseISO(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec((s || "").trim());
  return m ? new Date(+m[1], +m[2]-1, +m[3]).getTime() : 0;
}
function formatISOToDE(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec((iso || "").trim());
  return m ? m[3] + "." + m[2] + "." + m[1] : "";
}
// Interview-Datum: als TT.MM.JJJJ anzeigen (Fallback: Rohwert), damit ein
// bereits gespeicherter Freitext nicht unsichtbar wird.
function interviewDateDisplay(v) {
  const s = (v === undefined || v === null) ? "" : String(v);
  return formatISOToDE(s) || s;
}
// TT.MM.JJJJ -> ISO (YYYY-MM-DD). "" = leer, null = ungültig.
// Vierstelliges Jahr ist Pflicht — das native Datumsfeld hatte im
// deutschen Locale das Jahr zu "0022" verstümmelt.
function parseDEToISO(text) {
  const t = (text || "").trim();
  if (!t) return "";
  const m = /^(\d{1,2})[.\/-](\d{1,2})[.\/-](\d{4})$/.exec(t);
  if (!m) return null;
  const d = +m[1], mo = +m[2], y = +m[3];
  if (d < 1 || d > 31 || mo < 1 || mo > 12 || y < 1900 || y > 2200) return null;
  return y + "-" + String(mo).padStart(2, "0") + "-" + String(d).padStart(2, "0");
}
function todayISO() {
  const d = new Date();
  return d.getFullYear() + "-" + String(d.getMonth()+1).padStart(2,"0") + "-" + String(d.getDate()).padStart(2,"0");
}
function daysSince(ts) {
  return Math.floor((Date.now() - ts) / 86400000);
}
function pct(part, whole) {
  return whole ? Math.round((part / whole) * 100) : 0;
}
function cls(v, good, warn) {
  return v >= good ? "good" : (v >= warn ? "warn" : "bad");
}

function fitBadge(fit) {
  const f = +fit || 0;
  const color = f >= 80 ? "#22c55e" : (f >= 65 ? "#f59e0b" : "#ef4444");
  const bg = f >= 80 ? "#15803d33" : (f >= 65 ? "#b4530933" : "#7f1d1d33");
  return `<span class="badge" style="background:${bg};color:${color};border:1px solid ${color}55">${f}%</span>`;
}
function dimBadge(d) {
  // Mehrdimensionale Bewertung (berichtend): Gesamtwert + K.O.-Marker.
  // Der Tooltip nennt alle sieben Teilwerte — der Fit-Wert bleibt unverändert.
  if (!d) return "";
  const ko = (d.ko && d.ko.length)
    ? ` <span title="${esc(d.ko.join('; '))}" style="color:#fca5a5;cursor:help">⛔</span>`
    : "";
  return `<div style="margin-top:4px;font-size:10px;color:#94a3b8;cursor:help"
    title="Mehrdimensionale Bewertung (berichtend): ${esc(d.detail)}">Dim ${d.gesamt}%${ko}</div>`;
}
function qualityBadge(q) {
  // Qualitätsprüfung (P0b): ✓ bestanden, ⚠ nur Hinweise, ✗ Fehler.
  if (!q) return "";
  if (q.umfang !== "voll") {
    return `<div style="margin-top:4px;font-size:10px;color:#64748b" title="Nur die PDF-Dateien wurden geprüft. Die Textprüfung (Behauptungen, Zeiträume) läuft bei der nächsten Generierung.">Prüfung – Datei</div>`;
  }
  if (!q.n) return `<div style="margin-top:4px;font-size:10px;color:#22c55e" title="Qualitätsprüfung: alle Prüfungen bestanden">Prüfung ✓</div>`;
  const color = q.errors ? "#fca5a5" : "#fbbf24";
  const symbol = q.errors ? "✗" : "⚠";
  return `<div style="margin-top:4px;font-size:10px;color:${color};cursor:help"
    title="${esc((q.befunde || []).join(' · '))}">Prüfung ${symbol} ${q.n}</div>`;
}
function salaryBadge(s, source) {
  if (!s) return '<span style="color:#64748b">k. A.</span>';
  const hint = source === "Schätzung" ? ' <span style="font-size:10px;opacity:.7" title="geschätzt, keine Angabe in der Anzeige">(gesch.)</span>' : "";
  return `<span class="badge" style="background:#1e293b;color:#94a3b8;border:1px solid #334155">${s}${hint}</span>`;
}
function homeofficeBadge(h) {
  if (!h) return '<span style="color:#64748b">k. A.</span>';
  return `<span class="badge" style="background:#1e293b;color:#93c5fd;border:1px solid #334155">${h}</span>`;
}
function commuteBadge(r) {
  if (r.commuteMode === "Remote") {
    return '<span class="badge" style="background:#1e293b;color:#93c5fd;border:1px solid #334155">Remote</span>';
  }
  if (r.commute == null) return '<span style="color:#64748b">k. A.</span>';
  const c = +r.commute;
  const ratio = c / COMMUTE_LIMIT;
  // Farbe nach Restluft bis zur Grenze: je weniger Puffer, desto wärmer.
  // Fünf feste Stufen statt eines kontinuierlichen Verlaufs — die Farbe muss
  // beim Überfliegen der Tabelle eindeutig lesbar bleiben. Der oberste Split
  // liegt bei 90 %, weil sich sonst die 25-Minuten-Sammelgruppe (München,
  // 83 % der Grenze) nicht von den wirklich knappen 28-30 Minuten unterscheiden
  // ließe.
  let color, bg, hint;
  if (ratio <= 0.5)       { color = "#22c55e"; bg = "#15803d33"; hint = "viel Luft"; }
  else if (ratio <= 0.75) { color = "#84cc16"; bg = "#3f621233"; hint = "entspannt"; }
  else if (ratio <= 0.9)  { color = "#f59e0b"; bg = "#b4530933"; hint = "wird knapper"; }
  else if (ratio <= 1.0)  { color = "#f97316"; bg = "#c2410c33"; hint = "knapp an der Grenze"; }
  else                    { color = "#ef4444"; bg = "#7f1d1d33"; hint = "über der Grenze"; }
  const km = r.commuteKm != null ? ` · ${r.commuteKm} km` : "";
  const rest = COMMUTE_LIMIT - c;
  const luft = rest > 0 ? `noch ${rest} min Luft` : `${-rest} min über der Grenze`;
  const title = `${c} von ${COMMUTE_LIMIT} min (${Math.round(ratio * 100)} % der Grenze) — ${luft}`;
  return `<span class="badge" title="${title}" style="background:${bg};color:${color};border:1px solid ${color}55">${c} min${km}</span>`;
}
function linkBadge(r) {
  if (!r.link) return '<span style="color:#64748b">–</span>';
  // ``referrerpolicy="no-referrer"`` zusätzlich zu ``rel="noreferrer"``:
  // StepStone (und andere Portale mit WAF) brechen die Verbindung ab
  // (ERR_HTTP2_PROTOCOL_ERROR), wenn der Referer eine lokale Adresse ist — das
  // Dashboard läuft unter http://127.0.0.1:8766. ``rel="noreferrer"`` allein
  // genügt nicht in jedem Browser/Extension-Setup; das Attribut wirkt auch dann.
  if (r.verfuegbar === false) {
    return `<a class="folder" href="${esc(r.link)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer" title="Stellenanzeige ist nicht mehr verfügbar" style="opacity:.45;text-decoration:line-through">Anzeige ↗</a>`;
  }
  return `<a class="folder" href="${esc(r.link)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer" title="Stellenanzeige öffnen">Anzeige ↗</a>`;
}
function commuteVal(r) {
  if (r.commuteMode === "Remote") return 0;
  if (r.commute == null) return 9999;
  return +r.commute;
}
function statusAgeHint(r) {
  if (!r.statusChangedAt) return "";
  const ts = parseISO(r.statusChangedAt);
  if (!ts) return "";
  const d = daysSince(ts);
  const color = d >= 25 ? "#ef4444" : (d >= 14 ? "#f59e0b" : "#64748b");
  return `<div class="hint" style="color:${color}">seit ${d} Tagen</div>`;
}
function sentAtHint(r) {
  if (!r.sentAt) return "";
  const ts = parseISO(r.sentAt);
  if (!ts) return "";
  return `<div class="hint">Versendet: ${formatISOToDE(r.sentAt)} (vor ${daysSince(ts)} Tagen)</div>`;
}

// Zentrale Aktualisierung aller Ansichten. Tabellen- und Statistik-Ansicht
// dürfen nie auseinanderlaufen — jede Änderung (Status, Löschen, Datum) muss
// beide aktualisieren. Einzelne render*-Aufrufe an den Editierstellen hatten
// genau das vergessen.
function refreshAllViews() {
  renderRows();
  renderKpis();            // KPIs + Status-Verteilung + Wochenverlauf + Verteilungen
  updateStatusToggleCounts();
}

function renderKpis() {
  // Research-Einträge sind reine Funde ohne Dokumente und werden im Dashboard
  // nicht angezeigt; sie zählen daher auch in den Kennzahlen nicht mit.
  const rows = state.filter(r => !r.deleted && r.status !== "research");
  const total = rows.length;
  const rejectedCount = rows.filter(r => r.status === "rejected").length;
  const sentPlus = rows.filter(r => ["sent","followup","interview"].includes(r.status)).length;
  const interviews = rows.filter(r => r.status === "interview").length;

  // Versand-Quote: versendete Stellen gegen alle, die noch nicht abgelehnt sind.
  const versandBasis = total - rejectedCount;
  const versandQuote = pct(sentPlus, versandBasis);

  // Interview-Quote: nur *entschiedene* Bewerbungen zählen (Absage oder
  // Interview). Noch offene (sent/followup) sind kein Ergebnis und würden die
  // Quote künstlich drücken — 8 von 120 entschiedenen, nicht 8 von 159.
  const decided = rejectedCount + interviews;
  const interviewQuote = pct(interviews, decided);

  const ivRows = rows.filter(r => r.status === "interview");
  const fitAvg = ivRows.length ? (ivRows.reduce((a,r)=>a+(+r.fit||0),0)/ivRows.length) : 0;

  const cards = [
    { label:"Versand-Quote", value:versandQuote+"%", target:"Ziel ≥ 90%", c:cls(versandQuote,90,60) },
    { label:"Interview-Quote", value:interviewQuote+"%", target:`${interviews} von ${decided} entschieden`, c:cls(interviewQuote,15,8) },
    { label:"Ø Profil-Fit (Interviews)", value:(fitAvg?Math.round(fitAvg):"–")+" <small>%</small>", target:"Ziel ≥ 70%", c:fitAvg>=80?"good":(fitAvg>=65?"warn":(fitAvg?"bad":"")) },
    { label:"Aktiv im Prozess", value:sentPlus+" <small>/ "+total+"</small>", target:"Versendet o. weiter", c:"" },
  ];
  document.getElementById("kpis").innerHTML = cards.map(k => `
    <div class="kpi">
      <div class="label">${k.label}</div>
      <div class="value ${k.c}">${k.value}</div>
      <div class="target ${k.c}">${k.target}</div>
    </div>`).join("");
  renderStatusChart();
  renderTimeChart();
  renderDistributions();
}

// Ordnet die sehr uneinheitlichen Homeoffice-Angaben fünf Kategorien zu.
// Reihenfolge ist wichtig: „Vor Ort" vor „Homeoffice möglich", weil
// „k. A. (Vor Ort)" sonst als unbekannt gezählt würde.
function homeofficeCategory(v) {
  const s = (v == null ? "" : String(v)).toLowerCase().trim();
  if (!s || s === "unbekannt" || s === "k. a." || s === "keine angabe") return "Unbekannt";
  if (/voll.?remote|remote.?first|100\s*%\s*(remote|home|mobil)|^remote\b/.test(s)) return "Voll-Remote";
  if (/hybrid/.test(s)) return "Hybrid";
  if (/vor ort|präsenz|praesenz|vor-ort/.test(s)) return "Vor Ort";
  if (/home.?office|mobiles arbeiten|remote|nach vereinbarung|flex|mobil/.test(s)) return "Homeoffice möglich";
  return "Unbekannt";
}

const HOME_ORDER = ["Voll-Remote", "Hybrid", "Homeoffice möglich", "Vor Ort", "Unbekannt"];
const HOME_COLORS = {
  "Voll-Remote": "#22c55e", "Hybrid": "#84cc16", "Homeoffice möglich": "#38bdf8",
  "Vor Ort": "#f59e0b", "Unbekannt": "#64748b",
};

// Baut eine Balkenliste. ``items`` = [{label, n, color}], sortiert wie übergeben.
function renderDistBars(elId, items) {
  const el = document.getElementById(elId);
  if (!el) return;
  const max = Math.max(1, ...items.map(i => i.n));
  const total = items.reduce((a, i) => a + i.n, 0) || 1;
  el.innerHTML = items.map(i => {
    const w = Math.round((i.n / max) * 100);
    const share = Math.round((i.n / total) * 100);
    return `
      <div class="dist-row" title="${esc(i.label)}: ${i.n} (${share}%)">
        <div class="dist-label" title="${esc(i.label)}">${esc(i.label)}</div>
        <div class="dist-track"><div class="dist-fill" style="width:${w}%;background:${i.color}"></div></div>
        <div class="dist-num">${i.n} <span style="color:#64748b">· ${share}%</span></div>
      </div>`;
  }).join("") || '<div class="dist-sub">Keine Daten.</div>';
}

function renderDistributions() {
  // Gleiche Grundmenge wie die Status-Verteilung: sichtbare Zeilen, damit die
  // Zahlen untereinander konsistent sind.
  const rows = state.filter(r => !r.deleted && r.visible !== false);
  const basisEl = document.getElementById("distBasis");
  if (basisEl) basisEl.textContent = `Grundmenge: ${rows.length} Stellen (wie Status-Verteilung)`;

  // 1) Homeoffice
  const homeCounts = {};
  rows.forEach(r => {
    const c = homeofficeCategory(r.homeoffice);
    homeCounts[c] = (homeCounts[c] || 0) + 1;
  });
  renderDistBars("distHomeoffice", HOME_ORDER.map(k => ({
    label: k, n: homeCounts[k] || 0, color: HOME_COLORS[k],
  })));

  // 2) Fahrzeit — Bins um die konfigurierte Grenze herum
  const limit = COMMUTE_LIMIT;
  const bins = [
    { label: "≤ 15 min", n: 0, color: "#22c55e" },
    { label: "16–24 min", n: 0, color: "#84cc16" },
    { label: `25–${limit} min`, n: 0, color: "#f59e0b" },
    { label: `> ${limit} min`, n: 0, color: "#f97316" },
    { label: "unbekannt", n: 0, color: "#64748b" },
  ];
  rows.forEach(r => {
    const v = r.commute;
    if (v == null || v === "" || isNaN(+v)) { bins[4].n++; return; }
    const m = +v;
    if (m <= 15) bins[0].n++;
    else if (m <= 24) bins[1].n++;
    else if (m <= limit) bins[2].n++;
    else bins[3].n++;
  });
  renderDistBars("distCommute", bins);

  // 3) Profil-Fit
  const fitBins = [
    { label: "80–100 %", n: 0, color: "#22c55e" },
    { label: "65–79 %", n: 0, color: "#f59e0b" },
    { label: "50–64 %", n: 0, color: "#f97316" },
    { label: "< 50 %", n: 0, color: "#ef4444" },
    { label: "unbekannt", n: 0, color: "#64748b" },
  ];
  rows.forEach(r => {
    if (r.fit == null || r.fit === "" || isNaN(+r.fit)) { fitBins[4].n++; return; }
    const f = +r.fit;
    if (f >= 80) fitBins[0].n++;
    else if (f >= 65) fitBins[1].n++;
    else if (f >= 50) fitBins[2].n++;
    else fitBins[3].n++;
  });
  renderDistBars("distFit", fitBins);

  // 4) Unternehmen — Top 10, Rest zusammengefasst
  const companyCounts = {};
  rows.forEach(r => {
    const c = (r.company || "").trim() || "(ohne Firma)";
    companyCounts[c] = (companyCounts[c] || 0) + 1;
  });
  const sorted = Object.entries(companyCounts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const top = sorted.slice(0, 10).map(([label, n]) => ({ label, n, color: "#38bdf8" }));
  const restN = sorted.slice(10).reduce((a, [, n]) => a + n, 0);
  if (restN) top.push({ label: `weitere (${sorted.length - 10})`, n: restN, color: "#475569" });
  renderDistBars("distCompany", top);
  const sub = document.getElementById("distCompanySub");
  if (sub) sub.textContent = `${sorted.length} Unternehmen im Bestand, Top 10 gezeigt`;
}

function renderStatusChart() {
  const el = document.getElementById("statusChart");
  if (!el) return;
  // Nur die auch in der Tabelle sichtbaren Bewerbungen zählen, damit Diagramm
  // und Tabelle dieselben Zahlen zeigen. Seit „neu gefundene" Stellen auch ohne
  // Unterlagen sichtbar sind, können das Research-Zeilen sein.
  const rows = state.filter(r => !r.deleted && r.visible !== false);
  const total = rows.length || 1;
  el.innerHTML = SHOWN_STATUSES.map(s => {
    const n = rows.filter(r => r.status === s).length;
    const w = Math.round((n / total) * 100);
    return `
      <div style="display:flex;align-items:center;gap:10px;font-size:12px">
        <div style="width:120px;color:var(--muted)">${STATUS[s].label}</div>
        <div style="flex:1;background:var(--panel-2);border-radius:6px;overflow:hidden;height:16px">
          <div style="width:${w}%;background:${STATUS[s].color};height:100%"></div>
        </div>
        <div style="width:36px;text-align:right">${n}</div>
      </div>`;
  }).join("");
}

function mondayOf(ts) {
  const d = new Date(ts);
  const day = d.getDay() || 7;
  if (day !== 1) d.setDate(d.getDate() - (day - 1));
  d.setHours(0,0,0,0);
  return d.getTime();
}
function nextMonday(ts) {
  // Kalenderbasierte Wochenfortschaltung (kein fester 7-Tage-Millisekundenwert),
  // damit die Buckets auch über Zeitumstellungen (Sommer-/Winterzeit) hinweg
  // exakt auf „Montag 00:00" fallen und mit ``mondayOf`` übereinstimmen.
  const d = new Date(ts);
  d.setDate(d.getDate() + 7);
  d.setHours(0,0,0,0);
  return d.getTime();
}
function renderTimeChart() {
  const el = document.getElementById("timeChart");
  const legendEl = document.getElementById("timeChartLegend");
  if (!el) return;
  const rows = state.filter(r => !r.deleted && r.status !== "research" && parseDate(r.date));
  if (!rows.length) { el.innerHTML = ""; if (legendEl) legendEl.innerHTML = ""; return; }

  const mondays = rows.map(r => mondayOf(parseDate(r.date)));
  const minM = Math.min(...mondays), maxM = Math.max(...mondays);
  const buckets = [];
  for (let t = minM; t <= maxM; t = nextMonday(t)) {
    buckets.push({ monday:t, counts:Object.fromEntries(SHOWN_STATUSES.map(s => [s, 0])) });
  }
  rows.forEach(r => {
    const b = buckets.find(x => x.monday === mondayOf(parseDate(r.date)));
    if (b) b.counts[r.status]++;
  });
  const maxTotal = Math.max(1, ...buckets.map(b => SHOWN_STATUSES.reduce((a,s) => a + b.counts[s], 0)));
  const scale = 120 / maxTotal;

  el.innerHTML = buckets.map(b => {
    const total = SHOWN_STATUSES.reduce((a,s) => a + b.counts[s], 0);
    const segs = SHOWN_STATUSES.map(s => {
      const n = b.counts[s];
      if (!n) return "";
      return `<div title="${STATUS[s].label}: ${n}" style="height:${Math.round(n*scale)}px;background:${STATUS[s].color}"></div>`;
    }).join("");
    const d = new Date(b.monday);
    const label = `${String(d.getDate()).padStart(2,"0")}.${String(d.getMonth()+1).padStart(2,"0")}.`;
    return `
      <div style="display:flex;flex-direction:column;align-items:center;gap:4px;min-width:34px" title="Woche ab ${label}: ${total} Bewerbung${total===1?"":"en"}">
        <div style="font-size:10px;color:var(--muted)">${total || ""}</div>
        <div style="display:flex;flex-direction:column-reverse;width:24px;border-radius:4px;overflow:hidden;background:var(--panel-2);height:${Math.max(4,total*scale)}px">${segs}</div>
        <div style="font-size:10px;color:var(--muted)">${label}</div>
      </div>`;
  }).join("");

  if (legendEl) {
    legendEl.innerHTML = SHOWN_STATUSES.map(s => `
      <span style="display:inline-flex;align-items:center;gap:5px">
        <span style="width:9px;height:9px;border-radius:2px;background:${STATUS[s].color};display:inline-block"></span>${STATUS[s].label}
      </span>`).join("");
  }
}

function renderRows() {
  const tb = document.getElementById("rows");
  tb.innerHTML = "";
  const q = (document.getElementById("searchBox")?.value || "").trim().toLowerCase();
  const minFit = +(document.getElementById("fitFilter")?.value || 0);
  state.forEach((r, i) => {
    if (r.deleted) return;
    if (r.visible === false) return;
    if (hiddenStatuses.has(r.status)) return;
    if (minFit && (+r.fit || 0) < minFit) return;
    if (document.getElementById("neuFilter")?.checked && !r.neuImLauf) return;
    if (q) {
      const hay = `${r.company} ${r.position} ${r.branch} ${r.location}`.toLowerCase();
      if (!hay.includes(q)) return;
    }
    const tr = document.createElement("tr");
    if (r.neuImLauf) tr.className = "ist-neu";
    const statusOpts = ORDER.map(s =>
      `<option value="${s}" ${s === r.status ? "selected" : ""}>${STATUS[s].label}</option>`).join("");
    const docLinks = (r.docs || []).map(d =>
      `<a class="folder" href="${esc(d.href)}" target="_blank" rel="noopener noreferrer">${esc(d.label)}</a>`).join("<br>");
    const openBtn = r.folder
      ? `<br><a class="folder folder-open" href="#" data-folder="${encodeURIComponent(r.folder)}">Ordner ↗</a>`
        + (r.folderAbs
            ? `<button class="copy-btn" data-copy="${encodeURIComponent(r.folderAbs)}" title="Absoluten Ordnerpfad in die Zwischenablage kopieren">Pfad kopieren</button>`
            : "")
      : "";
    tr.innerHTML = `
      <td>${esc(r.company)}</td>
      <td>${esc(r.position)}${r.verfuegbar === false ? ' <span class="badge" style="background:#7f1d1d33;color:#fca5a5;border:1px solid #7f1d1d66">abgelaufen</span>' : ''}${r.neuImLauf ? ' <span class="badge badge-neu" title="Beim jüngsten Suchlauf gefunden">neu gefunden</span>' : ''}
        ${r.beschreibung ? `<button class="desc-toggle" data-i="${i}" aria-expanded="false">Beschreibung ▾</button>` : ""}
        ${(r.matched && r.matched.length) ? `<div class="hint">✓ ${esc(r.matched.slice(0,6).join(", "))}</div>` : ""}
      </td>
      <td>${r.branch || '<span style="color:#64748b">k. A.</span>'}</td>
      <td>${r.location || '<span style="color:#64748b">k. A.</span>'}</td>
      <td class="center">${homeofficeBadge(r.homeoffice)}</td>
      <td class="center">${commuteBadge(r)}</td>
      <td class="center">${r.date || '<span style="color:#64748b">k. A.</span>'}</td>
      <td class="center">
        <span class="badge ${STATUS[r.status].cls}">${STATUS[r.status].label}</span>
        <div style="margin-top:6px"><select autocomplete="off" data-i="${i}" data-k="status">${statusOpts}</select></div>
        ${statusAgeHint(r)}
        ${sentAtHint(r)}
        ${(r.status === "interview" || r.status === "followup") ? `<div style="margin-top:6px"><input type="text" autocomplete="off" inputmode="numeric" data-i="${i}" data-k="interviewDate" value="${esc(interviewDateDisplay(r.interviewDate))}" placeholder="TT.MM.JJJJ" maxlength="10" title="Interview-Termin (TT.MM.JJJJ)" style="width:118px"></div>` : ""}
      </td>
      <td class="center">${fitBadge(r.fit)}${dimBadge(r.dim)}</td>
      <td class="center">${salaryBadge(r.salary, r.salarySource)}</td>
      <td class="center">${linkBadge(r)}${docLinks ? "<br>" + docLinks : ""}${openBtn}${qualityBadge(r.quality)}</td>
      <td class="center"><button class="row-delete" data-i="${i}" title="Eintrag aus dem Dashboard entfernen">🗑</button></td>
    `;
    tb.appendChild(tr);

    // Vollbreite Beschreibungs-Zeile unterhalb der Stellen-Zeile (standardmässig
    // ausgeblendet, per „Beschreibung ▾"-Button umschaltbar).
    if (r.beschreibung) {
      const descRow = document.createElement("tr");
      descRow.className = "desc-row";
      descRow.dataset.i = String(i);
      descRow.style.display = "none";
      descRow.innerHTML = `<td colspan="12"><div class="desc-body">${esc(r.beschreibung).replace(/\n/g, "<br>")}</div></td>`;
      tb.appendChild(descRow);
    }
  });

  function applyValues() {
    tb.querySelectorAll("select, input").forEach(el => {
      const i = +el.dataset.i, k = el.dataset.k;
      if (!state[i]) return;
      const v = state[i][k];
      const s = (v === undefined || v === null) ? "" : String(v);
      el.value = (k === "interviewDate") ? interviewDateDisplay(s) : s;
    });
  }
  applyValues();
  requestAnimationFrame(applyValues);

  tb.querySelectorAll("select, input").forEach(el => {
    if (el.dataset.k === "interviewDate") {
      // Erst beim Verlassen auswerten: kein "input"-Listener, damit keine
      // halb getippten Jahre gespeichert werden.
      el.addEventListener("change", onEdit);
      el.addEventListener("blur", onEdit);
    } else {
      el.addEventListener("change", onEdit);
      if (el.tagName === "INPUT") el.addEventListener("input", onEdit);
    }
  });
  tb.querySelectorAll("a.folder-open").forEach(el => el.addEventListener("click", openFolder));
  tb.querySelectorAll("button.copy-btn").forEach(el => el.addEventListener("click", copyFolderPath));
  tb.querySelectorAll("button.row-delete").forEach(el => el.addEventListener("click", onDelete));
  tb.querySelectorAll("button.desc-toggle").forEach(el => el.addEventListener("click", onToggleDesc));
}

function onToggleDesc(e) {
  const btn = e.currentTarget;
  const i = btn.dataset.i;
  const rowsEl = document.getElementById("rows");
  const row = rowsEl.querySelector(`tr.desc-row[data-i="${i}"]`);
  if (!row) return;
  const hidden = row.style.display === "none";
  row.style.display = hidden ? "" : "none";
  btn.setAttribute("aria-expanded", String(hidden));
  btn.textContent = hidden ? "Beschreibung ▴" : "Beschreibung ▾";
}

function onEdit(e) {
  const el = e.currentTarget;
  const i = +el.dataset.i, k = el.dataset.k;
  const row = state[i];
  if (!row) return;
  let v = el.value;
  if (k === "deleted") v = el.checked;
  if (k === "interviewDate") {
    const iso = parseDEToISO(v);
    if (iso === null) {
      toast("⚠️ Bitte das Datum als TT.MM.JJJJ eingeben, z. B. 19.10.2026.");
      el.value = interviewDateDisplay(row.interviewDate);
      return;
    }
    if (iso === (row.interviewDate || "")) {
      el.value = interviewDateDisplay(iso);
      return;
    }
    v = iso;
  }
  if (k === "status" && v !== row.status) {
    row.status = v;
    if (v === "sent" && !row.sentAt) row.sentAt = todayISO();
    row.statusChangedAt = todayISO();
  } else {
    row[k] = v;
  }
  save(row.id);
  refreshAllViews();
}

function onDelete(e) {
  const i = +e.currentTarget.dataset.i;
  const row = state[i];
  if (!row) return;
  if (!confirm(`"${row.company} – ${row.position}" endgültig aus dem Dashboard entfernen?`)) return;
  row.deleted = true;
  row.deleted_reason = USER_DELETE_REASON;
  save(row.id);
  refreshAllViews();
}

function openFolder(e) {
  e.preventDefault();
  const folder = decodeURIComponent(e.currentTarget.dataset.folder);
  if (location.protocol === "http:" || location.protocol === "https:") {
    fetch("/open?path=" + encodeURIComponent(folder))
      .then(r => r.ok ? toast("Ordner geöffnet:<br><code>" + folder + "</code>")
                      : r.text().then(t => toast("Konnte Ordner nicht öffnen: " + t)))
      .catch(() => toast("Server nicht erreichbar. Dashboard über <code>dashboard-oeffnen.sh</code> öffnen."));
  } else {
    toast("Bitte über den Server öffnen (<code>dashboard-oeffnen.sh</code>), damit „Ordner öffnen“ funktioniert.");
  }
}

/* Kopiert den absoluten Ordnerpfad in die Zwischenablage.
   ``navigator.clipboard`` gibt es nur in einem „secure context" — bei
   http://127.0.0.1 ist das der Fall, bei Aufruf über file:// nicht. Deshalb
   gibt es einen Fallback über ein temporäres Textfeld. */
function copyFolderPath(e) {
  e.preventDefault();
  const btn = e.currentTarget;
  const value = decodeURIComponent(btn.dataset.copy || "");
  if (!value) return;

  const ok = () => {
    toast("Pfad kopiert:<br><code>" + esc(value) + "</code>");
    btn.classList.add("done");
    const old = btn.textContent;
    btn.textContent = "kopiert ✓";
    setTimeout(() => { btn.textContent = old; btn.classList.remove("done"); }, 1600);
  };
  const failed = () => toast("Kopieren nicht möglich. Pfad:<br><code>" + esc(value) + "</code>");
  const legacyCopy = () => {
    const ta = document.createElement("textarea");
    ta.value = value;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "-1000px";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    let copied = false;
    try { copied = document.execCommand("copy"); } catch (err) { copied = false; }
    document.body.removeChild(ta);
    copied ? ok() : failed();
  };

  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(value).then(ok).catch(legacyCopy);
  } else {
    legacyCopy();
  }
}

let toastTimer = null;
function toast(html) {  let t = document.getElementById("toast");
  if (!t) {
    t = document.createElement("div");
    t.id = "toast";
    document.body.appendChild(t);
  }
  t.innerHTML = html;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 6000);
}

function sortTable(col) {
  const colKey = cols[col];
  const numeric = ["fit"].includes(colKey);
  const defaultAsc = (colKey === "fit") ? false : true;
  if (sortCol === col) { sortAsc = !sortAsc; }
  else { sortCol = col; sortAsc = defaultAsc; }
  const dir = sortAsc ? 1 : -1;
  state.sort((a, b) => {
    let va, vb;
    if (colKey === "date") { va = parseDate(a.date); vb = parseDate(b.date); }
    else if (colKey === "status") { va = ORDER.indexOf(a.status); vb = ORDER.indexOf(b.status); }
    else if (colKey === "salary") { va = parseSalary(a.salary); vb = parseSalary(b.salary); }
    else if (colKey === "commute") { va = commuteVal(a); vb = commuteVal(b); }
    else if (numeric) { va = +a[colKey] || 0; vb = +b[colKey] || 0; }
    else {
      const cmp = (a[colKey] || "").toString().toLowerCase()
        .localeCompare((b[colKey] || "").toString().toLowerCase(), "de");
      if (cmp !== 0) return cmp * dir;
      return tieBreak(a, b, colKey);
    }
    if (va < vb) return -1 * dir;
    if (va > vb) return 1 * dir;
    return tieBreak(a, b, colKey);
  });
  updateArrows();
  renderRows();
}
function tieBreak(a, b, colKey) {
  if (colKey !== "fit" && (+b.fit || 0) !== (+a.fit || 0)) return (+b.fit || 0) - (+a.fit || 0);
  return (a.company || "").localeCompare(b.company || "", "de");
}
function updateArrows() {
  document.querySelectorAll("#table-main thead th[data-col]").forEach(th => {
    const a = th.querySelector(".arw");
    if (!a) return;
    a.textContent = (+th.dataset.col === sortCol) ? (sortAsc ? "▲" : "▼") : "↕";
  });
}

document.getElementById("reset").addEventListener("click", () => {
  if (confirm("Alle Änderungen verwerfen und auf Standard zurücksetzen?")) {
    state = JSON.parse(JSON.stringify(DATA));
    save();
    refreshAllViews();
  }
});
document.getElementById("export").addEventListener("click", () => {
  const blob = new Blob([JSON.stringify(state, null, 2)], { type:"application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "bewerbungsagent-dashboard.json";
  a.click();
});

const statusTogglesEl = document.getElementById("statusToggles");
statusTogglesEl.innerHTML = SHOWN_STATUSES.map(s => `
  <label class="toggle" for="hide-${s}">
    <input type="checkbox" id="hide-${s}" data-status="${s}" ${hiddenStatuses.has(s) ? "" : "checked"} />
    ${STATUS[s].label} einblenden <span class="hint" id="hideCount-${s}"></span>
  </label>`).join("");

function updateStatusToggleCounts() {
  // Gleiche Grundmenge wie Tabelle und Status-Verteilung: sonst zeigt der
  // Schalter „Research (11)", während die Tabelle 0 Zeilen hat.
  SHOWN_STATUSES.forEach(s => {
    const n = state.filter(r => !r.deleted && r.visible !== false && r.status === s).length;
    const el = document.getElementById("hideCount-" + s);
    if (el) el.textContent = n ? "(" + n + ")" : "";
  });
}
statusTogglesEl.querySelectorAll("input[type=checkbox]").forEach(box => {
  box.addEventListener("change", () => {
    const s = box.dataset.status;
    if (box.checked) hiddenStatuses.delete(s); else hiddenStatuses.add(s);
    try { localStorage.setItem(HIDDEN_STATUSES_KEY, JSON.stringify([...hiddenStatuses])); } catch (e) {}
    renderRows();
  });
});

document.getElementById("searchBox").addEventListener("input", renderRows);
document.getElementById("fitFilter").addEventListener("change", renderRows);
document.getElementById("neuFilter").addEventListener("change", renderRows);

function updateNeuInfo() {
  const el = document.getElementById("neuInfo");
  if (!el) return;
  const n = state.filter(r => !r.deleted && r.neuImLauf).length;
  const gesamt = LAST_FUND_ANZAHL || n;
  if (!n) {
    // Ein Fund unter der Fit-Schwelle ist unsichtbar — „keine Funde" wäre dann
    // schlicht falsch (der Lauf vom 19.10. fand eine Stelle mit 32 %).
    el.textContent = gesamt
      ? `${gesamt} neue Stelle(n), alle ausgeblendet (Fit < 50 % oder Pendelweg > ${COMMUTE_LIMIT} min)`
      : "noch keine Funde protokolliert";
    return;
  }
  el.textContent = n < gesamt
    ? `${n} von ${gesamt} neuen Stellen sichtbar (${LAST_RUN}) — der Rest liegt unter der Fit-Schwelle oder ausserhalb der Pendelgrenze`
    : `${n} Stelle(n) neu gefunden (${LAST_RUN})`;
}

// ---- Tabs ---------------------------------------------------------------
// Zwei Arbeitsflächen: Tabelle (tägliches Arbeiten) und Statistik (Auswertung).
// Der aktive Tab wird lokal gemerkt, damit ein Neuladen nicht zurückspringt.
function activateTab(name) {
  if (name !== "table" && name !== "stats") name = "table";
  document.querySelectorAll(".tab").forEach(btn => {
    const on = btn.dataset.tab === name;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-selected", on ? "true" : "false");
  });
  document.querySelectorAll(".pane").forEach(pane => {
    pane.hidden = pane.id !== "tab-" + name;
  });
  try { localStorage.setItem(TAB_KEY, name); } catch (e) {}
  // Diagramme neu zeichnen: versteckte Container haben keine Breite.
  if (name === "stats") {
    renderKpis();
  }
}

document.querySelectorAll(".tab").forEach(btn => {
  btn.addEventListener("click", () => activateTab(btn.dataset.tab));
});

let startTab = "table";
try { startTab = localStorage.getItem(TAB_KEY) || "table"; } catch (e) {}
activateTab(startTab);

refreshAllViews();
updateNeuInfo();

// Kommt der Tab aus dem Hintergrund zurück, können sich Daten geändert haben
// (z. B. Löschen in einem zweiten Fenster). Ein Neuzeichnen kostet nichts.
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") refreshAllViews();
});
</script>
</body>
</html>
"""

# STATUS/ORDER-Platzhalter im JS ersetzen (modulweit, einmalig).
_HTML_TEMPLATE = (_HTML_TEMPLATE
                  .replace("__STATUS__", _status_json())
                  .replace("__ORDER__", _order_json())
                  # Marker für Dashboard-Löschungen: eine Quelle im Backend,
                  # damit Frontend und Pipeline denselben Wert prüfen.
                  .replace("__USER_DELETE_REASON__", json.dumps(USER_DELETE_REASON, ensure_ascii=False)))
