#!/usr/bin/env python3
"""Erzeugt eine interaktive „Landkarte" des Bewerbungsagenten.

Das Ergebnis (``agent-map.html``) zeigt in einer einzigen, offline-fähigen
HTML-Datei:

1. **System-Map** — was der Agent in welcher Reihenfolge tut (Quellen →
   Verarbeitung → Ausgabe), als klickbares Ablaufdiagramm.
2. **Geografie-Map** — wo die Stellen liegen: echte Koordinaten aus dem
   Geocode-Cache, Wohnort Garching als Mittelpunkt, gefärbt nach Pendelzeit.
3. **Module & Fähigkeiten** — jedes Modul mit Verantwortung und Reinheit.
4. **Ablageplan** — welche Datei/Ordner an welcher Stelle entsteht.
5. **Externe Dienste** — welche Netzwerkdienste wann kontaktiert werden.

Alle Zahlen stammen aus dem echten Bestand (SQLite/``state.json``) und den
Caches. Nutzung:  ``python scripts/build_agent_map.py [--out PFAD]``
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from bewerbungsagent.config import Config  # noqa: E402

# Öffentliches Quellcode-Repository — erscheint als Fußzeile in der Agenten-Map,
# damit geteilte Ausdrucke/PDFs auf den nachprüfbaren Code verweisen.
REPO_URL = "https://github.com/jacobdietzmann-ux/bewerbungsagent"

# --------------------------------------------------------------------------
# Daten einsammeln
# --------------------------------------------------------------------------

_MODULES = [
    ("search/__init__.py", "Provider auswählen und ausführen, Treffer deduplizieren, "
     "Aggregator-/Lexikon-Seiten filtern, URLs bereinigen", "teils", "Suche"),
    ("search/stepstone.py", "StepStone: Suchbegriff und Ort getrennt, echte Anzeigen", "netz", "Suche"),
    ("search/duckduckgo.py", "Web-Suche als Lückenfüller (Übersichts-/Lexikonseiten werden verworfen)", "netz", "Suche"),
    ("search/bing.py", "Web-Suche als Lücke", "netz", "Suche"),
    ("search/ats.py", "Firmen-Karriereseiten (ATS-Boards), Arbeitnow, JobLeads, "
     "Jobbörsen-Sitemaps (u. a. jobs.eon.com)", "netz", "Suche"),
    ("search/arbeitnow.py", "Arbeitnow-API (viele Treffer, Firmenname teils ohne Leerzeichen)", "netz", "Suche"),
    ("search/manual.py", "Manuell gepflegte Anzeigen aus data/import_jobs.json", "io", "Suche"),
    ("search/browser.py", "Gemeinsamer Playwright-Helfer für Quellen ohne HTML-Antwort", "netz", "Suche"),
    ("search/xing.py", "XING über den Browser (JS-Anzeigen, Consent, Nachladen)", "netz", "Suche"),
    ("search/indeed.py", "Indeed über den Browser; Volltext per Klick auf den Titel", "netz", "Suche"),
    ("search/labo.py", "jobs.labo.de per HTTP (Suchergebnis + Anzeigentext)", "netz", "Suche"),
    ("search/jobspy.py", "JobSpy (LinkedIn/Indeed/Google) als Aggregator", "netz", "Suche"),
    ("saved_searches.py", "Benannte, wiederholbare Suchläufe", "rein", "Suche"),
    ("provider_health.py", "Fehlserien je Quelle zählen, Quelle nach N Fehlläufen abschalten", "io", "Suche"),
    ("triage.py", "Vorfilter vor dem Scoring (Studenten-/Technikerrollen, Ausschlüsse)", "rein", "Bewertung"),
    ("profile.py", "Profil laden; Keywords und Inhaltswörter extrahieren", "rein", "Bewertung"),
    ("matching.py", "Fit-Score 0–100 (Titel ×6, Text ×4, Wort ×2, Ort 0–10), Rollen-Gate", "rein", "Bewertung"),
    ("dimensions.py", "Sieben Dimensionen als zweites, berichtendes Urteil (ADR-031)", "rein", "Bewertung"),
    ("rag.py", "Belege zu einer Behauptung aus dem Profil holen (Quelle + Zeitraum)", "rein", "Ausgabe"),
    ("tailoring.py", "Stellenbezogener Lebenslauf-Zuschnitt aus JSON, prüft Belege", "rein", "Ausgabe"),
    ("industry.py", "Branche zuordnen (Arbeitgeber → Text → Titel)", "rein", "Anreicherung"),
    ("salary.py", "Gehalt schätzen aus Rolle, Seniorität, Branche, Ort", "rein", "Anreicherung"),
    ("homeoffice.py", "Homeoffice-Anteil aus der Anzeige lesen", "rein", "Anreicherung"),
    ("commute.py", "Pendelweg via Nominatim + OSRM, mit Cache; Grenze 30 min", "netz", "Anreicherung"),
    ("documents.py", "Anschreiben + Lebenslauf als PDF (eigene DOCX-Vorlage oder ReportLab)", "rein", "Ausgabe"),
    ("quality.py", "Erzeugte Unterlagen unabhängig prüfen (Belege, Pflichtteile, PDF)", "rein", "Ausgabe"),
    ("dashboard.py", "Interaktives HTML-Dashboard rendern", "rein", "Ausgabe"),
    ("db.py", "SQLite-Speicher: Provider-/Nutzer-Felder getrennt, History-Schutz", "io", "Speicher"),
    ("pipeline.py", "Orchestrierung der Stufen, State-Merge, Bereinigung", "teils", "Steuerung"),
    ("orchestrator.py", "Derselbe Ablauf als Graph (LangGraph, optional)", "teils", "Steuerung"),
    ("followup.py", "Fällige Nachfassen erkennen und Text danebenlegen", "io", "Pflege"),
    ("importer.py", "Bestand des alten Dashboards übernehmen", "io", "Steuerung"),
    ("cleanup.py", "Alte Bewerbungsordner in den Trash verschieben", "io", "Pflege"),
    ("statuses.py", "Status-Funnel + Normalisierung alter Werte", "rein", "Steuerung"),
    ("storage.py", "JSON lesen/schreiben, Zeitstempel", "io", "Speicher"),
    ("server.py", "Lokaler HTTP-Server: Dashboard, /state-API, Ordner öffnen", "netz", "Ausgabe"),
    ("semantic.py", "Embedding-Matching — Experiment, Hypothese widerlegt (ADR-015)", "exp", "Experiment"),
    ("rerank.py", "Cross-Encoder-Reranking — Experiment zur Alternative", "exp", "Experiment"),
]

_SERVICES = [
    ("StepStone", "Stellenanzeigen (HTML, <code>requests</code>)", "netz", "requests"),
    ("JobLeads", "Stellenanzeigen; max. 25 Karten je Anfrage, keine Paginierung", "netz", "requests"),
    ("XING", "Stellenanzeigen nur im gerenderten DOM", "netz", "playwright"),
    ("Indeed", "Trefferliste + Volltext; Cloudflare blockt einfache Clients (403)", "netz", "playwright"),
    ("jobs.labo.de", "Stellenanzeigen (reines HTML, Folge-Seite per Knopf-URL)", "netz", "requests"),
    ("Firmen-Karriereseiten", "ATS-Boards, Arbeitnow, Jobbörsen-Sitemap (z. B. jobs.eon.com)", "netz", "requests"),
    ("JobSpy → LinkedIn / Indeed / Google", "strukturierte Jobs (LinkedIn drosselt mit 429)", "netz", "python-jobspy"),
    ("Nominatim (OpenStreetMap)", "Adressen zu Koordinaten auflösen (Politeness ≥ 1 s)", "netz", "requests + Cache"),
    ("OSRM", "Fahrroute Auto → Distanz und Dauer", "netz", "requests + Cache"),
    ("Chromium / Playwright", "Anzeigen rendern und Volltext holen, wo HTML nicht reicht", "netz", "playwright"),
    ("LibreOffice (soffice)", "DOCX-Vorlage → PDF; fehlt es, greift die ReportLab-Vorlage", "lokal", "subprocess, optional"),
    ("Tectonic / Typst", "Externe CV-Vorlagen kompilieren (LaTeX / Typst)", "lokal", "CLI, offline"),
]

# Quellen für die Ablaufkarte (Reihenfolge = Reihenfolge im SVG).
_SRC_SVG = [
    ("StepStone", "#38bdf8"),
    ("JobLeads", "#38bdf8"),
    ("XING", "#38bdf8"),
    ("Indeed", "#38bdf8"),
    ("jobs.labo.de", "#38bdf8"),
    ("Firmen-Karriereseiten (ATS / Sitemap)", "#22c55e"),
    ("JobSpy (LinkedIn)", "#38bdf8"),
    ("Manueller Import", "#a78bfa"),
    ("Alt-Dashboard", "#a78bfa"),
]

# Dienste für die Ablaufkarte.
_SVC_SVG = [
    ("Nominatim + OSRM", "Pendelweg", "#38bdf8"),
    ("Chromium", "Volltext", "#38bdf8"),
    ("Profil-Datenbank", "Skills", "#a78bfa"),
    ("DOCX-Vorlage", "Lebenslauf", "#f59e0b"),
    ("Tailoring-JSON", "Zuschnitt", "#f59e0b"),
    ("LibreOffice", "DOCX → PDF", "#f59e0b"),
    ("ReportLab", "PDF-Fallback", "#f59e0b"),
]

# --------------------------------------------------------------------------
# SVG-Geografie-Map
# --------------------------------------------------------------------------

_STREET_HINTS = ("straße", "strasse", "str.", " weg", "weg ", "allee", "platz",
                 "gasse", "ring", "damm", "ufer", "chaussee", "steig")

# Keine Städte, sondern Länder/Regionen/Arbeitsmodelle.
_NON_CITY = {"germany", "deutschland", "bavaria", "bayern", "de", "remote",
             "homeoffice", "home office", "hybrid", "bundesweit", "various"}


def _city_label(ort: str) -> str:
    """Ortsangabe auf einen lesbaren Städtenamen reduzieren.

    Viele Anzeigen nennen eine Straße statt einer Stadt
    („Zeppelinstraße 18 82205 Gilching“). Für die Karte bleibt nur der
    Bestandteil übrig, der wie eine Stadt aussieht.
    """
    for part in reversed([p for p in re.split(r"[,/]", ort or "") if p.strip()]):
        tokens = [t for t in part.split() if t and not any(ch.isdigit() for ch in t)]
        tokens = [t for t in tokens if not any(h in t.lower() for h in _STREET_HINTS)]
        tokens = [t for t in tokens if t.lower() not in _NON_CITY]
        if tokens:
            return " ".join(tokens).strip()
    return ""


def _project(points, width, height, pad=48):
    """Equirektangulare Projektion (bei dieser Ausdehnung verzerrungsfrei genug)."""
    lons = [p[1] for p in points]
    lats = [p[0] for p in points]
    lon0, lon1 = min(lons), max(lons)
    lat0, lat1 = min(lats), max(lats)
    span_lon = max(lon1 - lon0, 1e-6)
    span_lat = max(lat1 - lat0, 1e-6)
    scale = min((width - 2 * pad) / span_lon, (height - 2 * pad) / span_lat)
    off_x = (width - span_lon * scale) / 2
    off_y = (height - span_lat * scale) / 2

    def f(lat, lon):
        x = off_x + (lon - lon0) * scale
        y = off_y + (lat1 - lat) * scale
        return x, y

    return f


def _commute_color(minutes, limit_minutes=30):
    """Farbe nach Restluft bis zur Pendelweg-Grenze.

    Fünf Stufen, damit sich die 25-Minuten-Sammelgruppe (München, 83 % der
    Grenze) von den wirklich knappen 28–30 Minuten unterscheidet. Die Skala ist
    relativ zur Grenze — eine feste 30/60-Skala wäre bei einer Grenze von 30 min
    durchgehend rot.
    """
    if minutes is None:
        return "#64748b"
    limit = limit_minutes or 30
    ratio = minutes / limit
    if ratio <= 0.5:
        return "#22c55e"
    if ratio <= 0.75:
        return "#84cc16"
    if ratio <= 0.9:
        return "#f59e0b"
    if ratio <= 1.0:
        return "#f97316"
    return "#ef4444"


def _build_geo_svg(apps, geocache, limit_minutes, width=1180, height=620,
                   home_address: str = ""):
    """Zeichnet die Karte; der Wohnort kommt aus der Konfiguration.

    Früher wurde der Eintrag über den Anfang der Adresse gesucht — dadurch
    stand ein Teil der Wohnadresse im Quelltext. Jetzt wird der konfigurierte
    Schlüssel verwendet.
    """
    from bewerbungsagent.profile import normalize
    home = None
    if home_address:
        wanted = normalize(home_address)
        home = geocache.get(home_address)
        if home is None:
            for k, v in geocache.items():
                if normalize(k) == wanted:
                    home = v
                    break

    # Orte aus den Stellen mit Pendelzeit/Koordinaten auflösen.
    from bewerbungsagent.commute import resolve_office

    city_counts: Counter = Counter()
    plotted = []
    city_by_point: list[str] = []
    for a in apps:
        if a.get("pendel_modus") != "Auto":
            continue
        office = resolve_office(a.get("ort") or "")
        if not office:
            continue
        # Derselbe Schlüssel wie im Geocoder (Umlaute → ASCII).
        key = normalize(office)
        entry = geocache.get(key)
        if not entry or entry.get("lat") is None:
            continue
        city = _city_label(a.get("ort") or "")
        plotted.append((entry["lat"], entry["lon"], a.get("pendelzeit_min"), city or office))
        # „Munich“ und „München“ sind dieselbe Stadt.
        _n = normalize(city or "")
        if _n == "munchen" or (city or "").lower().startswith("munich"):
            city = "München"
        city_by_point.append(city)
        if city:
            city_counts[city] += 1

    if not plotted or home is None:
        return ("<p class='muted'>Keine Geodaten vorhanden — zuerst "
                "<code>agent.py match</code> ausführen.</p>", {"total": 0, "top": []})

    pts = [(p[0], p[1]) for p in plotted] + [(home["lat"], home["lon"])]
    f = _project(pts, width, height)

    parts = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'style="width:100%;height:auto;display:block" role="img" '
        f'aria-label="Karte der Stellenorte im Umkreis von Garching">',
        '<defs>'
        '<linearGradient id="geoBg" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0%" stop-color="#111c31"/><stop offset="100%" stop-color="#0d1626"/>'
        '</linearGradient>'
        '<radialGradient id="homeGlow"><stop offset="0%" stop-color="#38bdf8" stop-opacity="0.45"/>'
        '<stop offset="100%" stop-color="#38bdf8" stop-opacity="0"/></radialGradient>'
        '</defs>',
        f'<rect width="{width}" height="{height}" fill="url(#geoBg)" rx="12"/>',
    ]

    # Gitter
    for i in range(1, 8):
        x = width * i / 8
        y = height * i / 8
        parts.append(f'<line x1="{x:.0f}" y1="0" x2="{x:.0f}" y2="{height}" stroke="#1e293b" stroke-width="1"/>')
        parts.append(f'<line x1="0" y1="{y:.0f}" x2="{width}" y2="{y:.0f}" stroke="#1e293b" stroke-width="1"/>')

    hx, hy = f(home["lat"], home["lon"])

    # Pendelzeit-Linien vom Wohnort zu jeder Stelle
    for lat, lon, minutes, _ort in plotted:
        if minutes is None:
            continue
        x, y = f(lat, lon)
        c = _commute_color(minutes, limit_minutes)
        op = 0.30 if minutes > limit_minutes else 0.14
        w = 1.6 if minutes > limit_minutes else 1.0
        parts.append(f'<line x1="{hx:.1f}" y1="{hy:.1f}" x2="{x:.1f}" y2="{y:.1f}" '
                     f'stroke="{c}" stroke-width="{w}" stroke-opacity="{op}"/>')

    # Punkte
    for lat, lon, minutes, ort in plotted:
        x, y = f(lat, lon)
        c = _commute_color(minutes, limit_minutes)
        r = 4.2 if (minutes or 0) <= limit_minutes else 3.2
        label = f"{ort} · {minutes} min" if minutes is not None else ort
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{c}" fill-opacity="0.85" '
            f'stroke="#0b1220" stroke-width="0.8"><title>{label}</title></circle>'
        )

    # Wohnort
    parts.append(f'<circle cx="{hx:.1f}" cy="{hy:.1f}" r="34" fill="url(#homeGlow)"/>')
    parts.append(f'<circle cx="{hx:.1f}" cy="{hy:.1f}" r="8" fill="#38bdf8" stroke="#0b1220" stroke-width="2"/>')
    parts.append(f'<circle cx="{hx:.1f}" cy="{hy:.1f}" r="14" fill="none" stroke="#38bdf8" '
                 f'stroke-width="1.4" stroke-opacity="0.7"/>')
    parts.append(f'<text x="{hx + 16:.1f}" y="{hy + 4:.1f}" fill="#7dd3fc" font-size="12" '
                 f'font-family="system-ui,sans-serif" font-weight="700">Wohnort Garching</text>')

    # Top-Orte beschriften
    for city, _n in city_counts.most_common(6):
        match = next((p for p in plotted if p[3] == city or _city_label(p[3]) == city), None)
        if not match:
            continue
        x, y = f(match[0], match[1])
        parts.append(f'<text x="{x + 7:.1f}" y="{y - 5:.1f}" fill="#94a3b8" font-size="10.5" '
                     f'font-family="system-ui,sans-serif">{city}</text>')

    parts.append("</svg>")
    meta = {
        "total": len(plotted),
        "top": city_counts.most_common(6),
        "lat": (min(p[0] for p in pts), max(p[0] for p in pts)),
        "lon": (min(p[1] for p in pts), max(p[1] for p in pts)),
    }
    return "".join(parts), meta


# --------------------------------------------------------------------------
# SVG-System-Map
# --------------------------------------------------------------------------

def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _stage_box(x, y, w, h, key, title, sub, color, icon):
    return (
        f'<g class="node" data-node="{key}" tabindex="0" role="button" '
        f'aria-label="{_esc(title)}">'
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="#16243b" '
        f'stroke="{color}" stroke-width="1.6"/>'
        f'<rect x="{x}" y="{y}" width="{w}" height="4" rx="2" fill="{color}"/>'
        f'<text x="{x + w/2:.0f}" y="{y+30:.0f}" text-anchor="middle" fill="#e2e8f0" '
        f'font-size="15" font-weight="700" font-family="system-ui,sans-serif">{icon} {_esc(title)}</text>'
        f'<text x="{x + w/2:.0f}" y="{y+52:.0f}" text-anchor="middle" fill="#94a3b8" '
        f'font-size="11" font-family="system-ui,sans-serif">{_esc(sub)}</text>'
        f'</g>'
    )


def _build_system_svg(width=1180, height=None):
    """Ablaufkarte: Quellen → vier Stufen → Ausgabe, mit Diensteschicht darunter.

    Die Höhe wird aus der Anzahl der Quellen berechnet: die Liste ist in den
    letzten Ausbaustufen von fünf auf neun Einträge gewachsen, und ein festes
    Raster hätte die unteren Kästen aus dem viewBox geschoben.
    """
    sx, sw = 0, 236                 # Quellen (breiter: „Firmen-Karriereseiten …")
    sy, sh, sg = 64, 44, 12
    src_count = len(_SRC_SVG)
    src_total = src_count * sh + (src_count - 1) * sg

    bx, bw, bg = 272, 156, 14       # Stufen (muss vor der Ausgabespalte ab 952 enden)
    by, bh = sy + src_total / 2 - 43, 86
    if by < sy:                     # wenige Quellen: Stufen nicht nach oben ziehen
        by = sy

    dw, dgx = 124, 12               # Dienste: 5 je Zeile in der Pipeline-Spalte
    svc_cols = 5
    svc_rows = max(1, -(-len(_SVC_SVG) // svc_cols))
    dy, dh, dgy = by + bh + 78, 44, 14

    ox, ow, oh, og = 952, 212, 62, 16   # Ausgabe
    svc_bottom = dy + svc_rows * dh + (svc_rows - 1) * dgy
    needed = max(sy + src_total + 24, svc_bottom + 28)
    height = max(440, needed) if height is None else max(height, needed)

    bus_l = sx + sw + 8
    stage_x = [bx + i * (bw + bg) for i in range(4)]
    stage_cy = by + bh / 2

    parts = [
        f'<svg viewBox="0 0 {width} {height:.0f}" xmlns="http://www.w3.org/2000/svg" '
        f'style="width:100%;height:auto;display:block" role="img" '
        f'aria-label="Ablaufkarte des Bewerbungsagenten">',
        '<defs>'
        '<marker id="arw" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto">'
        '<path d="M0,0 L0,6 L7,3 z" fill="#64748b"/></marker>'
        '<marker id="arwG" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto">'
        '<path d="M0,0 L0,6 L7,3 z" fill="#22c55e"/></marker>'
        '</defs>',
        f'<rect width="{width}" height="{height:.0f}" fill="#0d1626" rx="12"/>',
    ]

    for x, label in ((sx + sw / 2, "QUELLEN"),
                     ((bx + stage_x[-1] + bw) / 2, "VERARBEITUNG (Pipeline)"),
                     (ox + ow / 2, "AUSGABE")):
        parts.append(f'<text x="{x:.0f}" y="34" text-anchor="middle" fill="#64748b" font-size="11" '
                     f'font-weight="700" letter-spacing="1.2" '
                     f'font-family="system-ui,sans-serif">{label}</text>')

    # --- Quellen ---
    sources = _SRC_SVG
    src_cy = []
    for i, (name, color) in enumerate(sources):
        y = sy + i * (sh + sg)
        src_cy.append(y + sh / 2)
        parts.append(
            f'<g class="node" data-node="src-{i}" tabindex="0" role="button" aria-label="{_esc(name)}">'
            f'<rect x="{sx}" y="{y}" width="{sw}" height="{sh}" rx="9" fill="#16243b" '
            f'stroke="{color}" stroke-width="1.3"/>'
            f'<circle cx="{sx + 16}" cy="{y + sh / 2}" r="4" fill="{color}"/>'
            f'<text x="{sx + 30}" y="{y + sh / 2 + 4}" fill="#cbd5e1" font-size="11.5" '
            f'font-family="system-ui,sans-serif">{_esc(name)}</text>'
            f'</g>'
        )

    # Sammelschiene links: alle Quellen laufen in die erste Stufe.
    parts.append(f'<line x1="{bus_l}" y1="{src_cy[0]}" x2="{bus_l}" y2="{src_cy[-1]}" '
                 f'stroke="#475569" stroke-width="1.5"/>')
    for cy in src_cy:
        parts.append(f'<line x1="{sx + sw}" y1="{cy}" x2="{bus_l}" y2="{cy}" '
                     f'stroke="#475569" stroke-width="1.3"/>')
    parts.append(f'<line x1="{bus_l}" y1="{stage_cy}" x2="{bx - 10}" y2="{stage_cy}" '
                 f'stroke="#64748b" stroke-width="1.8" marker-end="url(#arw)"/>')

    # --- Pipeline (4 Stufen) ---
    stages = [
        ("search", "SEARCH", "Provider · Dedup", "#38bdf8", "🔍", "jobs.json"),
        ("match", "MATCH", "Fit-Score 0–100", "#22c55e", "🎯", "matches.json"),
        ("generate", "GENERATE", "PDFs erzeugen", "#f59e0b", "📄", "01_Bewerbungen/"),
        ("dashboard", "DASHBOARD", "HTML + Server", "#a78bfa", "📊", "dashboard.html"),
    ]
    for i, (key, title, sub, color, icon, out_file) in enumerate(stages):
        x = stage_x[i]
        parts.append(_stage_box(x, by, bw, bh, key, title, sub, color, icon))
        parts.append(f'<text x="{x + bw/2:.0f}" y="{by + bh + 22:.0f}" text-anchor="middle" '
                     f'fill="#fbbf24" font-size="10.5" font-family="ui-monospace,monospace">'
                     f'{_esc(out_file)}</text>')
        if i:
            parts.append(f'<line x1="{stage_x[i-1] + bw + 3}" y1="{stage_cy}" '
                         f'x2="{x - 7}" y2="{stage_cy}" stroke="#22c55e" stroke-width="2" '
                         f'marker-end="url(#arwG)"/>')

    # --- Dienste (Schicht unter der Pipeline) ---
    services = _SVC_SVG
    dx = bx + 2
    parts.append(f'<text x="{bx}" y="{dy - 14:.0f}" fill="#64748b" font-size="11" font-weight="700" '
                 f'letter-spacing="1.2" font-family="system-ui,sans-serif">'
                 f'DIENSTE &amp; WERKZEUGE</text>')
    # Verteilschiene: Dienste speisen die Pipeline.
    rail_y = by + bh + 34
    parts.append(f'<line x1="{bx}" y1="{rail_y:.0f}" x2="{stage_x[-1] + bw}" y2="{rail_y:.0f}" '
                 f'stroke="#334155" stroke-width="1.2" stroke-dasharray="4 3"/>')
    for i, (name, sub, color) in enumerate(services):
        row, col = divmod(i, svc_cols)
        x = dx + col * (dw + dgx)
        y = dy + row * (dh + dgy)
        parts.append(
            f'<g class="node" data-node="svc-{i}" tabindex="0" role="button" aria-label="{_esc(name)}">'
            f'<rect x="{x}" y="{y:.0f}" width="{dw}" height="{dh}" rx="9" fill="#131f33" '
            f'stroke="{color}" stroke-width="1.2" stroke-dasharray="4 3"/>'
            f'<text x="{x + dw/2:.0f}" y="{y + 18:.0f}" text-anchor="middle" fill="#cbd5e1" '
            f'font-size="10.5" font-weight="600" font-family="system-ui,sans-serif">{_esc(name)}</text>'
            f'<text x="{x + dw/2:.0f}" y="{y + 33:.0f}" text-anchor="middle" fill="#64748b" '
            f'font-size="9.5" font-family="system-ui,sans-serif">{_esc(sub)}</text>'
            f'</g>'
        )
        parts.append(f'<line x1="{x + dw/2:.0f}" y1="{y:.0f}" x2="{x + dw/2:.0f}" y2="{rail_y:.0f}" '
                     f'stroke="#334155" stroke-width="1" stroke-dasharray="3 3"/>')

    # --- Ausgabe (vertikal zentriert zur Pipeline) ---
    outs = [
        ("dashboard.html", "Interaktive Tabelle", "#a78bfa"),
        ("01_Bewerbungen/", "Ein Ordner pro Stelle", "#f59e0b"),
        ("data/jobs.db", "SQLite = Wahrheit", "#22c55e"),
        ("data/*.json", "Snapshots & Caches", "#64748b"),
    ]
    total_h = len(outs) * oh + (len(outs) - 1) * og
    oy = stage_cy - total_h / 2
    out_cy = [oy + i * (oh + og) + oh / 2 for i in range(len(outs))]
    for i, (name, sub, color) in enumerate(outs):
        y = oy + i * (oh + og)
        parts.append(
            f'<g class="node" data-node="out-{i}" tabindex="0" role="button" aria-label="{_esc(name)}">'
            f'<rect x="{ox}" y="{y:.0f}" width="{ow}" height="{oh}" rx="9" fill="#16243b" '
            f'stroke="{color}" stroke-width="1.3"/>'
            f'<text x="{ox + 14}" y="{y + 26:.0f}" fill="#e2e8f0" font-size="12" font-weight="600" '
            f'font-family="ui-monospace,monospace">{_esc(name)}</text>'
            f'<text x="{ox + 14}" y="{y + 45:.0f}" fill="#64748b" font-size="10.5" '
            f'font-family="system-ui,sans-serif">{_esc(sub)}</text>'
            f'</g>'
        )
    # Verteilschiene zur Ausgabe
    bus_o = ox - 8
    parts.append(f'<line x1="{stage_x[-1] + bw + 3}" y1="{stage_cy}" x2="{bus_o}" y2="{stage_cy}" '
                 f'stroke="#22c55e" stroke-width="2" marker-end="url(#arwG)"/>')
    parts.append(f'<line x1="{bus_o}" y1="{out_cy[0]:.0f}" x2="{bus_o}" y2="{out_cy[-1]:.0f}" '
                 f'stroke="#22c55e" stroke-width="1.6"/>')
    for cy in out_cy:
        parts.append(f'<line x1="{bus_o}" y1="{cy:.0f}" x2="{ox}" y2="{cy:.0f}" '
                     f'stroke="#22c55e" stroke-width="1.4"/>')

    parts.append("</svg>")
    return "".join(parts)


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

def _render(stats, system_svg, geo_svg, geo_meta):
    from datetime import datetime

    def rows_module(m):
        name, resp, kind, area = m
        badge = {"rein": ("deterministisch", "b-rein"), "netz": ("Netzwerk", "b-netz"),
                 "io": ("Datei/DB", "b-io"), "teils": ("gemischt", "b-teils"),
                 "exp": ("Experiment", "b-exp")}[kind]
        return (f'<tr><td><code>{_esc(name)}</code></td><td>{_esc(resp)}</td>'
                f'<td><span class="badge {badge[1]}">{badge[0]}</span></td>'
                f'<td class="muted">{_esc(area)}</td></tr>')

    def rows_service(s):
        name, resp, kind, tech = s
        cls = "b-netz" if kind == "netz" else "b-io"
        label = "Netzwerk" if kind == "netz" else "lokal"
        return (f'<tr><td><strong>{_esc(name)}</strong></td><td>{_esc(resp)}</td>'
                f'<td><span class="badge {cls}">{label}</span></td>'
                f'<td class="muted"><code>{_esc(tech)}</code></td></tr>')

    cmd_rows = "".join(
        f'<tr><td><code>python agent.py {c}</code></td><td>{_esc(d)}</td></tr>'
        for c, d in stats["commands"]
    )

    fs_rows = "".join(
        f'<tr><td><code>{_esc(p)}</code></td><td>{_esc(w)}</td>'
        f'<td class="muted">{_esc(when)}</td></tr>'
        for p, w, when in stats["filesystem"]
    )

    stage_cards = "".join(
        f'<div class="stage" data-stage="{k}">'
        f'<div class="stage-num" style="background:{c}22;color:{c};border-color:{c}55">{i}</div>'
        f'<h4>{_esc(t)}</h4><p>{_esc(d)}</p>'
        f'<div class="stage-out">→ <code>{_esc(o)}</code></div></div>'
        for i, (k, t, d, o, c) in enumerate(stats["stages"], 1)
    )

    geo_legend = "".join(
        f'<span class="lg"><i style="background:{c}"></i>{lbl}</span>'
        for c, lbl in [("#22c55e", f"≤ {stats['limit'] // 2} min (≤ 50 %)"),
                       ("#84cc16", f"≤ {round(stats['limit'] * 0.75)} min (≤ 75 %)"),
                       ("#f59e0b", f"≤ {round(stats['limit'] * 0.9)} min (≤ 90 %)"),
                       ("#f97316", f"≤ {stats['limit']} min (an der Grenze)"),
                       ("#ef4444", f"> {stats['limit']} min (ausgeblendet)"),
                       ("#64748b", "unbekannt")]
    )

    top_cities = "".join(
        f'<span class="pill">{_esc(c)} <b>{n}</b></span>' for c, n in geo_meta.get("top", [])
    )

    kpi_cards = "".join(
        f'<div class="kpi"><div class="k-label">{_esc(label)}</div>'
        f'<div class="k-value">{v}</div><div class="k-sub">{_esc(s)}</div></div>'
        for label, v, s in stats["kpis"]
    )

    # ``</`` maskieren, damit die Inline-<script>-Daten nie als Tag-Ende gelesen
    # werden (gleiches Muster wie im Dashboard).
    data_json = json.dumps(stats["nodes"], ensure_ascii=False).replace("</", "<\\/")

    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Cache-Control" content="no-store">
<title>Agenten-Map — was der Bewerbungsagent tut</title>
<style>
:root{{--bg:#0b1220;--panel:#131f33;--panel2:#1a2942;--line:#25364f;--text:#e2e8f0;
--muted:#8ba0bd;--accent:#38bdf8;--ok:#22c55e;--warn:#f59e0b;--vio:#a78bfa;}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);
font-family:"Segoe UI",system-ui,-apple-system,Roboto,sans-serif;padding:26px;}}
.wrap{{max-width:1240px;margin:0 auto}}
h1{{font-size:26px;margin:0 0 6px}}
h2{{font-size:19px;margin:38px 0 14px;padding-bottom:8px;border-bottom:1px solid var(--line)}}
h4{{margin:0 0 6px;font-size:14px}}
.sub{{color:var(--muted);font-size:13px;margin:0 0 4px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;
padding:16px;margin-bottom:16px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(158px,1fr));gap:12px;margin:22px 0}}
.kpi{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px}}
.k-label{{font-size:11.5px;color:var(--muted);letter-spacing:.03em}}
.k-value{{font-size:25px;font-weight:700;margin-top:6px;color:var(--accent)}}
.k-sub{{font-size:11px;color:var(--muted);margin-top:3px}}
.stages{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px}}
.stage{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;
display:flex;flex-direction:column;gap:4px}}
.stage p{{margin:0;font-size:12.5px;color:var(--muted);line-height:1.5}}
.stage-num{{width:26px;height:26px;border-radius:8px;border:1px solid;display:flex;
align-items:center;justify-content:center;font-weight:700;font-size:13px;margin-bottom:4px}}
.stage-out{{margin-top:auto;font-size:11.5px;color:#fbbf24}}
code{{background:#0a1120;padding:1.5px 6px;border-radius:5px;font-size:11.5px;
font-family:ui-monospace,SFMono-Regular,Menlo,monospace}}
table{{width:100%;border-collapse:collapse;background:var(--panel);border-radius:10px;
overflow:hidden;font-size:13px}}
th,td{{padding:9px 12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}}
th{{background:#16243b;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}}
tr:last-child td{{border-bottom:none}}
.muted{{color:var(--muted)}}
.badge{{display:inline-block;font-size:10.5px;font-weight:600;padding:2px 8px;border-radius:999px}}
.b-rein{{background:#22c55e22;color:#86efac}} .b-netz{{background:#38bdf822;color:#7dd3fc}}
.b-io{{background:#a78bfa22;color:#c4b5fd}} .b-teils{{background:#f59e0b22;color:#fcd34d}}
.b-exp{{background:#64748b22;color:#cbd5e1}}
.lg{{display:inline-flex;align-items:center;gap:6px;font-size:11.5px;color:var(--muted);
margin:0 14px 8px 0}}
.lg i{{width:10px;height:10px;border-radius:3px;display:inline-block}}
.pill{{display:inline-block;background:var(--panel2);border:1px solid var(--line);border-radius:999px;
padding:4px 11px;font-size:11.5px;margin:0 6px 6px 0;color:#cbd5e1}}
.pill b{{color:var(--accent)}}
#detail{{margin-top:14px;background:var(--panel2);border:1px solid var(--line);border-radius:10px;
padding:14px 16px;font-size:13px;min-height:66px;line-height:1.6}}
#detail h4{{color:var(--accent);margin-bottom:4px}}
.node{{cursor:pointer}}
.node rect{{transition:filter .15s,stroke-width .15s}}
.node:hover rect,.node.active rect{{filter:brightness(1.35);stroke-width:2.6}}
.node:focus{{outline:none}}
.node:focus-visible rect{{stroke:#fff;stroke-width:2.6}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
@media(max-width:900px){{.two{{grid-template-columns:1fr}}}}
.note{{background:#0f1c30;border-left:3px solid var(--accent);border-radius:8px;
padding:12px 15px;font-size:12.5px;color:#c3d3e8;line-height:1.6;margin:14px 0}}
.map-footer{{margin:22px 0 10px;padding-top:14px;border-top:1px solid #1e2f47;
font-size:12.5px;color:#94a3b8}}
.map-footer a{{color:#7dd3fc;word-break:break-all}}
.repo-banner{{display:flex;flex-wrap:wrap;align-items:center;gap:10px;
background:#0f2440;border:1px solid #1e4a75;border-radius:10px;
padding:12px 16px;margin:16px 0 6px}}
.repo-banner .rb-label{{font-size:12px;letter-spacing:.08em;text-transform:uppercase;
color:#7dd3fc;font-weight:700}}
.repo-banner a{{font-size:clamp(15px,2.1vw,21px);font-weight:700;color:#e2f1ff;
word-break:break-all;text-decoration:none;border-bottom:2px solid #2f6fa8}}
.repo-banner a:hover{{color:#fff;border-bottom-color:#7dd3fc}}
/* Druck/PDF: Farben behalten und Karten nicht mitten durchschneiden. */
@media print{{
  html,body{{background:#0b1220 !important}}
  .card,.kpi,table,.note{{break-inside:avoid;page-break-inside:avoid}}
  h1,h2,h3{{break-after:avoid;page-break-after:avoid}}
  *{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
}}
</style></head>
<body><div class="wrap">

<h1>🗺️ Agenten-Map</h1>
<p class="sub">Was der Bewerbungsagent tut, was er kann und wo er was verarbeitet —
Stand {datetime.now().strftime('%d.%m.%Y %H:%M')}</p>

<div class="repo-banner">
  <span class="rb-label">Quellcode öffentlich:</span>
  <a href="{REPO_URL}" target="_blank" rel="noopener">{REPO_URL}</a>
</div>

<section class="kpis">{kpi_cards}</section>

<h2>1 · System-Map — der Weg einer Stelle</h2>
<div class="card">
  {system_svg}
  <div id="detail">
    <h4>Knoten anklicken</h4>
    Klick auf einen Baustein (Quelle, Stufe, Dienst, Ausgabe) zeigt, was dort
    konkret passiert und welche Daten hinein- und hinausfließen.
  </div>
</div>

<h2>2 · Die vier Stufen im Detail</h2>
<div class="stages">{stage_cards}</div>

<h2>3 · Geografie-Map — wo die Stellen liegen</h2>
<div class="card">
  <p class="sub">Echte Koordinaten aus dem Geocode-Cache. Mittelpunkt ist der Wohnort
  Garching; Linien zeigen den Auto-Pendelweg. Stellen jenseits von
  {stats['limit']} min werden gar nicht erst angelegt.</p>
  {geo_svg}
  <div style="margin-top:12px">{geo_legend}</div>
  <div style="margin-top:8px">{top_cities}</div>
  <p class="sub" style="margin-top:10px">
    {geo_meta.get('total', 0)} Stellen mit Koordinaten ·
    Breite {geo_meta.get('lat', (0,0))[0]:.2f}–{geo_meta.get('lat', (0,0))[1]:.2f}° N ·
    Länge {geo_meta.get('lon', (0,0))[0]:.2f}–{geo_meta.get('lon', (0,0))[1]:.2f}° O
  </p>
</div>

<h2>4 · Was er kann — Befehle</h2>
<table><thead><tr><th>Befehl</th><th>Wirkung</th></tr></thead>
<tbody>{cmd_rows}</tbody></table>

<h2>5 · Wo er was ablegt</h2>
<table><thead><tr><th>Pfad</th><th>Inhalt</th><th>Wann</th></tr></thead>
<tbody>{fs_rows}</tbody></table>

<h2>6 · Womit er arbeitet — Dienste &amp; Werkzeuge</h2>
<table><thead><tr><th>Dienst</th><th>Aufgabe</th><th>Art</th><th>Technik</th></tr></thead>
<tbody>{''.join(rows_service(s) for s in _SERVICES)}</tbody></table>

<h2>7 · Module &amp; Verantwortlichkeiten</h2>
<table><thead><tr><th>Modul</th><th>Verantwortung</th><th>Art</th><th>Bereich</th></tr></thead>
<tbody>{''.join(rows_module(m) for m in _MODULES)}</tbody></table>

<div class="note">
<strong>Merksatz:</strong> Nur die Module mit dem Label
<span class="badge b-netz">Netzwerk</span> verlassen den Rechner oder hängen von
externen Diensten ab. Alles mit <span class="badge b-rein">deterministisch</span>
ist ohne Netzwerk reproduzierbar und getestet — deshalb ist die Bewertung
nachvollziehbar und nicht von einem Modell abhängig.
</div>

<div class="map-footer">
<strong>Quellcode:</strong>
<a href="{REPO_URL}" target="_blank" rel="noopener">{REPO_URL}</a>
<span class="muted">— vollständig einsehbar (Module, Tests, CI, Dokumentation)</span>
</div>

</div>
<script>
const NODES = {data_json};
const detail = document.getElementById("detail");
function show(key){{
  const n = NODES[key];
  document.querySelectorAll(".node").forEach(g =>
    g.classList.toggle("active", g.dataset.node === key));
  if(!n){{detail.innerHTML = "<h4>Knoten anklicken</h4>Klick auf einen Baustein zeigt Details.";return;}}
  detail.innerHTML = `<h4>${{n.title}}</h4>${{n.body}}`
    + (n.in ? `<div style="margin-top:8px"><span class="muted">Eingang:</span> <code>${{n.in}}</code></div>` : "")
    + (n.out ? `<div style="margin-top:4px"><span class="muted">Ausgang:</span> <code>${{n.out}}</code></div>` : "");
}}
document.querySelectorAll(".node").forEach(g => {{
  g.addEventListener("click", () => show(g.dataset.node));
  g.addEventListener("keydown", e => {{
    if(e.key === "Enter" || e.key === " "){{ e.preventDefault(); show(g.dataset.node); }}
  }});
}});
</script>
</body></html>"""


# --------------------------------------------------------------------------
# Zahlen sammeln
# --------------------------------------------------------------------------

def _boards(config: Config) -> list:
    """Konfigurierte ATS-Boards (leere/fehlende Liste → leer)."""
    boards = (config.data.get("search") or {}).get("ats_boards") or []
    return [b for b in boards if isinstance(b, dict)]


def _collect(config: Config) -> dict:
    store = None
    apps = []
    db_path = config.db_path()
    if db_path.exists():
        try:
            from bewerbungsagent.db import Store
            store = Store(db_path)
            apps = store.load_state().get("applications", [])
        except Exception:
            apps = []
    if not apps and config.state_path().exists():
        apps = json.loads(config.state_path().read_text(encoding="utf-8")).get("applications", [])

    geocache = {}
    gc_path = config.data_dir / "geocode_cache.json"
    if gc_path.exists():
        try:
            geocache = json.loads(gc_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            geocache = {}

    limit = config.data.get("max_pendelzeit_min", 30)
    status = Counter(a.get("status") for a in apps)
    docs = sum(1 for a in apps if a.get("dokumente"))
    desc = sum(1 for a in apps if (a.get("beschreibung") or "").strip())
    pend = [a.get("pendelzeit_min") for a in apps if a.get("pendelzeit_min") is not None]
    scores = [a.get("score") for a in apps if isinstance(a.get("score"), (int, float))]
    branches = {a.get("branche") for a in apps if a.get("branche")}
    sources = Counter(a.get("quelle") for a in apps if a.get("quelle"))

    bew_dir = config.bewerbungen_dir
    folders = 0
    pdfs = 0
    if bew_dir.exists():
        folders = sum(1 for d in bew_dir.iterdir() if d.is_dir())
        pdfs = len(list(bew_dir.rglob("*.pdf")))

    # Profil
    pdata = {}
    try:
        pdata = json.loads(config.profile_path.read_text(encoding="utf-8"))
    except Exception:
        pdata = {}
    skills = pdata.get("skills", {})
    n_skills = sum(len(v) if isinstance(v, list) else
                   sum(len(vv) if isinstance(vv, list) else 1 for vv in v.values())
                   if isinstance(v, dict) else 1
                   for v in skills.values())

    # „Sichtbar“ bedeutet dasselbe wie im Dashboard: Unterlagen vorhanden UND
    # Dateien noch auf der Platte. Eine eigene Zählung (nur `not deleted`) wich
    # davon ab (164 statt 46) — zwei Zahlen für denselben Begriff verwirren.
    try:
        from bewerbungsagent.dashboard import dashboard_applications
        visible = len(dashboard_applications(apps))
    except Exception:
        visible = sum(1 for a in apps if not a.get("deleted"))

    kpis = [
        ("Bewerbungen", f"{len(apps)}", "in der Datenbank"),
        ("Sichtbar im Dashboard", f"{visible}", f"{len(apps) - visible} ausgeblendet"),
        ("Dokumente erzeugt", f"{docs}", f"Ordner: {folders} · PDFs: {pdfs}"),
        ("Fit ≥ 50 %", f"{sum(1 for s in scores if s >= 50)}", f"von {len(scores)} bewertet"),
        ("Pendelweg Ø", f"{round(sum(pend)/len(pend))} min" if pend else "–", f"{len(pend)} berechnet"),
        ("Branchen", f"{len(branches)}", "erkannt"),
        ("Anzeigen mit Text", f"{desc}", "Volltext geladen"),
        ("Profil-Skills", f"{n_skills}", f"{len(pdata.get('work_experience', []))} Stationen"),
    ]

    fs = [
        ("02_Profil-und-Assets/Profil-Datenbank.json", "Skills, Erfahrung, Zertifikate", "Eingang"),
        ("02_Profil-und-Assets/Vorlage-Aktuell/*.docx", "Eigene Lebenslauf-Vorlage (DE/EN)", "Vorlage"),
        ("04_Agent/data/jobs.json", "Rohe Suchtreffer + Anreicherung", "nach search"),
        ("04_Agent/data/matches.json", "Gescorte Stellen (Fit, Begründung)", "nach match"),
        ("04_Agent/data/jobs.db", "SQLite — Quelle der Wahrheit", "laufend"),
        ("04_Agent/data/state.json", "Abgeleiteter Snapshot (Backup)", "laufend"),
        ("04_Agent/data/geocode_cache.json", "Adresse → Koordinaten", "nach match"),
        ("04_Agent/data/commute_cache.json", "Route → km / Minuten", "nach match"),
        ("04_Agent/data/jobs.db → provider_health", "Fehlserien je Quelle (Tabelle)", "nach search"),
        ("01_Bewerbungen/<Firma - Titel>/", "Anschreiben, Lebenslauf, Anzeige, Referenz", "nach generate"),
        ("01_Bewerbungen/<…>/Lebenslauf-Tailoring.json", "Zuschnitt für diese eine Stelle (optional)", "vor generate"),
        ("04_Agent/data/trash/", "Aufgeräumte Ordner (reversibel)", "nach cleanup"),
        ("04_Agent/dashboard.html", "Interaktives Bewerbungs-Dashboard", "nach dashboard"),
        ("04_Agent/output/agent-map.html", "Diese Landkarte", "manuell"),
    ]

    stages = [
        ("search", "SEARCH", "Neun Provider abfragen, Treffer deduplizieren, Aggregator- und "
         "Lexikon-Seiten herausfiltern. Anschließend Branche zuordnen und Pendelweg berechnen.",
         "jobs.json", "#38bdf8"),
        ("match", "MATCH", "Jede Stelle gegen das Profil scoren: Titel-Treffer ×6, Text-Treffer ×4, "
         "Inhaltswörter ×2, Standort 0–10 (Mehr-Standort-Angaben: 0). Merge in SQLite mit "
         "History-Schutz.", "matches.json", "#22c55e"),
        ("generate", "GENERATE", "Anschreiben pro Stelle formulieren; Lebenslauf aus der eigenen "
         "DOCX-Vorlage oder — wenn ein Tailoring-File vorliegt — aus dem zugeschnittenen "
         "ReportLab-Layout. PDFs in den Bewerbungsordner.", "01_Bewerbungen/", "#f59e0b"),
        ("dashboard", "DASHBOARD", "HTML-Board rendern: nur Stellen mit Dokumenten und Pendelweg "
         "≤ 30 min in der Tabelle, Status-Verteilung und Wochenverlauf darüber.",
         "dashboard.html", "#a78bfa"),
    ]

    commands = [
        ("search", "Web-Suche über alle aktiven Provider ausführen"),
        ("fetch", "Vollständige Anzeigentexte per Browser nachladen (bessere Bewertung)"),
        ("match", "Fit-Scoring gegen das Skill-Profil, Merge in die Datenbank"),
        ("enrich", "Pendelweg + Gehalt + Bereinigung + automatische Bewerbung"),
        ("generate --all", "Bewerbungsunterlagen für alle passenden Stellen"),
        ("generate --ids 1,2", "Unterlagen für bestimmte Stellen (umgeht Fit, Rollen-Gate, Dubletten)"),
        ("quality", "Erzeugte Unterlagen unabhängig prüfen (Belege, Pflichtteile, PDF)"),
        ("followup --days 14", "Fällige Nachfassen anzeigen; --write legt den Text daneben"),
        ("providers", "Zustand der Quellen anzeigen, --disable/--enable schalten einzelne ab"),
        ("searches", "Gespeicherte Suchläufe auflisten und wiederholen"),
        ("import-old", "Bestand des alten Dashboards übernehmen"),
        ("cleanup --dry-run", "Alte Bewerbungsordner anzeigen, nichts verschieben"),
        ("dashboard", "HTML-Dashboard neu erzeugen"),
        ("status", "Aktuelle Stellen in der Konsole anzeigen"),
        ("pipeline", "Kompletter Durchlauf: Suche → Match → Dokumente → Dashboard"),
        ("ablauf", "Derselbe Ablauf als Graph (LangGraph)"),
    ]

    nodes = {
        "src-0": {"title": "StepStone", "body": "Strukturierte Jobbörse. Wird per <code>requests</code> "
                  "abgefragt; Suchbegriff und Ort getrennt. Diese Treffer sind echte Anzeigen und "
                  "werden nicht durch die Aggregator-Filter geprüft.", "out": "jobs.json"},
        "src-1": {"title": "JobLeads", "body": "Liefert maximal 25 Karten je Anfrage und ignoriert "
                  "sämtliche Paginierungsparameter — die Begriffsliste entscheidet, was man sieht. "
                  "Bei zu vielen parallelen Abrufen drosselt Cloudflare mit HTTP 429; deshalb wenige "
                  "Threads und Wiederholungen mit Wartezeit.", "out": "jobs.json"},
        "src-2": {"title": "XING", "body": "Antwortet mit HTTP 200, enthält die Anzeigen aber erst im "
                  "gerenderten DOM. Deshalb über Chromium: Consent setzen, „mehr laden“ klicken, dann "
                  "Firma und Ort <em>relativ zum Titel</em> lesen — ein Badge wie „Dringend gesucht“ "
                  "steht davor und wurde früher als Ort missverstanden.", "out": "jobs.json"},
        "src-3": {"title": "Indeed", "body": "Cloudflare blockt einfache Clients (403), auch RSS und "
                  "JobSpy. Im Browser ist die Trefferliste lesbar; den Volltext gibt es erst nach "
                  "einem Klick auf den Titel (Master-Detail mit <code>&amp;vjk=…</code>).", "out": "jobs.json"},
        "src-4": {"title": "jobs.labo.de", "body": "Reines HTML, kein Browser nötig. Drei Eigenheiten: "
                  "die Firmenzeile trägt <code>data-*</code>-Attribute vor <code>class</code>, Titel "
                  "enthalten weiche Trennzeichen (<code>&amp;shy;</code>), und die Folgeseite gibt es "
                  "nur über die Knopf-URL mit Sitzungs-ID.", "out": "jobs.json"},
        "src-5": {"title": "Firmen-Karriereseiten", "body": (
            f"{len(_boards(config))} ATS-Boards (SuccessFactors, Greenhouse, Workday, Personio …), "
            "die Arbeitnow-API und Jobbörsen-Sitemaps. E.ON zum Beispiel ist nur über "
            "<code>jobs.eon.com/sitemap.xml</code> erreichbar (Ort im Slug); einzelne "
            "Sitemap-Einträge laufen in HTTP 404 und werden übersprungen."),
            "out": "jobs.json"},
        "src-6": {"title": "JobSpy (LinkedIn)", "body": "Aggregiert mehrere Portale auf einmal. "
                  "LinkedIn drosselt regelmäßig (429); die Quelle zählt deshalb nur dann als "
                  "Fehllauf, wenn sie Meldungen liefert <em>und</em> nichts findet.", "out": "jobs.json"},
        "src-7": {"title": "Manueller Import", "body": "Stellen aus <code>data/import_jobs.json</code> — "
                  "z. B. von Firmen-Karriereseiten, die keine offene Schnittstelle haben. Läuft bei jeder "
                  "Suche automatisch mit.", "out": "jobs.json"},
        "src-8": {"title": "Alt-Dashboard", "body": "Bestand aus dem früheren Dashboard "
                  "(<code>agent.py import-old</code>). Behält den ursprünglichen Fit-Wert.", "out": "state.json"},
        "search": {"title": "SEARCH", "body": "Führt alle Provider aus, entfernt Duplikate anhand der "
                   "bereinigten URL und ergänzt die Branche. Danach wird der Pendelweg berechnet — "
                   "das ist der Schritt, der Netzwerk braucht.", "in": "Provider-Treffer", "out": "data/jobs.json"},
        "match": {"title": "MATCH", "body": "Deterministisches Scoring gegen das Profil. Das Ergebnis ist "
                  "nachvollziehbar (Titel ×6, Text ×4, Inhaltswort ×2, Standort 0–10) und reproduzierbar — "
                  "kein Sprachmodell. Alle Summanden werden gespeichert, jeder Score bleibt nachrechenbar. "
                  "Danach Merge in SQLite: Nutzerfelder bleiben unangetastet.",
                  "in": "data/jobs.json", "out": "data/matches.json → data/jobs.db"},
        "generate": {"title": "GENERATE", "body": "Erzeugt pro Stelle Anschreiben und Lebenslauf. "
                    "Standard ist die eigene DOCX-Vorlage, in der nur der Profil-Absatz ersetzt wird. "
                    "Liegt im Ordner eine <code>Lebenslauf-Tailoring.json</code>, entsteht der "
                    "Lebenslauf stattdessen aus dem zugeschnittenen ReportLab-Layout (Headline, "
                    "Profil, Stations-Bullets, Fähigkeitsgruppen, Kernkompetenzen). Fachbegriffe, die "
                    "das Profil nicht belegt, werden gemeldet. Stellen mit zu weitem Pendelweg "
                    "werden übersprungen.", "in": "data/matches.json", "out": "01_Bewerbungen/<Firma - Titel>/"},
        "dashboard": {"title": "DASHBOARD", "body": "Rendert das interaktive Board als einzelne HTML-Datei. "
                     "Der lokale Server (<code>server.py</code>) speichert Statusänderungen über "
                     "<code>POST /state</code> zurück in die Datenbank.", "in": "data/jobs.db",
                     "out": "dashboard.html"},
        "svc-0": {"title": "Nominatim + OSRM", "body": "OpenStreetMap-Dienste: Adresse → Koordinaten und "
                  "Fahrroute → km/Minuten. Ergebnisse werden dauerhaft gecacht, damit wiederholte Läufe "
                  "keine neuen Anfragen auslösen (Politeness ≥ 1 s).", "in": "Ortsangabe", "out": "pendelzeit_min"},
        "svc-1": {"title": "Chromium / Playwright", "body": "Lädt den echten Anzeigentext. Nötig, weil "
                  "StepStone den einfachen Abruf blockiert; der gerenderte Text verbessert die Bewertung "
                  "erheblich (Fit-Score steigt deutlich).", "in": "Anzeigen-URL", "out": "beschreibung"},
        "svc-2": {"title": "Profil-Datenbank", "body": "Enthält Skills, Erfahrung, Ausbildung und "
                  "Zertifikate. Grundlage für das Scoring — und die einzige Quelle für Profilbegriffe.",
                  "in": "Profil-Datenbank.json", "out": "Keywords"},
        "svc-3": {"title": "DOCX-Vorlage", "body": "Die eigene, aktuelle Lebenslauf-Vorlage. Sie wird "
                  "1:1 übernommen; nur der Profil-Absatz wird pro Stelle ersetzt. Fällt bei fehlender "
                  "Datei automatisch auf die eingebauten ReportLab-Vorlagen zurück.", "in": "Vorlage-Aktuell/*.docx"},
        "svc-4": {"title": "Tailoring-JSON", "body": "Optionale <code>Lebenslauf-Tailoring.json</code> im "
                  "Bewerbungsordner: wählt Stationen-Bullets, Fähigkeitsgruppen und Kernkompetenzen für "
                  "diese eine Stelle aus und benennt sie um. Darf auswählen und weglassen, nicht "
                  "hinzufügen — unbelegte Fachbegriffe werden beim Erzeugen gemeldet.", "in": "Tailoring-JSON",
                  "out": "zugeschnittener Lebenslauf"},
        "svc-5": {"title": "LibreOffice", "body": "Konvertiert das angepasste DOCX zu PDF. Nötig, weil "
                  "die Bewerbung als PDF verschickt wird und das Layout exakt der Vorlage entsprechen soll.",
                  "in": "DOCX", "out": "Lebenslauf.pdf"},
        "svc-6": {"title": "ReportLab", "body": "Baut die PDFs direkt in Python — ohne externe Programme. "
                  "Greift immer dann, wenn keine DOCX-Vorlage konfiguriert ist, <code>soffice</code> fehlt "
                  "(auf diesem Rechner ist es nicht installiert) oder ein Tailoring vorliegt.",
                  "in": "Profil + Vorlage", "out": "Anschreiben / Lebenslauf.pdf"},
        "out-0": {"title": "dashboard.html", "body": "Das interaktive Bewerbungs-Board: Tabelle nur mit "
                  "Stellen, die Dokumente haben und innerhalb der Pendelgrenze liegen; darüber "
                  "Status-Verteilung und Wochenverlauf.", "in": "data/jobs.db"},
        "out-1": {"title": "01_Bewerbungen/", "body": "Ein Ordner pro Stelle mit Anschreiben, Lebenslauf "
                  "(DE + EN), der Stellenanzeige als Referenz und dem Referenzschreiben.", "in": "GENERATE"},
        "out-2": {"title": "data/jobs.db", "body": "SQLite als Quelle der Wahrheit. Provider-Felder "
                  "(dürfen beim nächsten Scrape aktualisiert werden) und Nutzerfelder (Status, Notizen, "
                  "Interview-Termin — werden nie überschrieben) liegen getrennt.", "in": "alle Stufen"},
        "out-3": {"title": "Snapshots & Caches", "body": "<code>state.json</code> als Backup-Snapshot sowie "
                  "die Caches für Geocoding und Routen — sie machen wiederholte Läufe schnell und "
                  "netzwerkschonend.", "in": "laufend"},
    }

    return {
        "kpis": kpis, "stages": stages, "commands": commands, "filesystem": fs,
        "nodes": nodes, "apps": apps, "geocache": geocache, "limit": limit,
        "sources": sources, "status": status,
    }


def export_pdf(html_path: Path, pdf_path: Path, landscape: bool = False) -> Path:
    """Druckt die Karte über Headless-Chromium als PDF.

    Für Bewerbungen ist ein PDF praktischer als die lokale HTML: es lässt sich
    anhängen und überall öffnen. Hintergrundfarben bleiben an, damit die
    farbcodierten Karten erhalten bleiben.

    ``landscape`` ist für die breiten Karten besser: bei A4 hochkant schrumpft
    die 1180 px breite Karte auf rund 60 % und die kleinsten Ortslabels landen
    bei ~5 pt; im Querformat sind es ~89 % und ~7 pt.

    Das Executable wird nur gesetzt, wenn ein System-Chromium existiert
    (``/usr/bin/chromium`` unter Linux). Auf Windows gibt es diesen Pfad nicht —
    ein fester Pfad ließ den Export dort mit „BrowserType.launch: Executable
    doesn't exist“ scheitern, statt Playwrights eigenes Chromium zu nehmen.
    """
    from playwright.sync_api import sync_playwright

    executable = Path("/usr/bin/chromium")
    launch_kwargs = {"headless": True,
                     "args": ["--no-sandbox", "--disable-blink-features=AutomationControlled"]}
    if executable.is_file():
        launch_kwargs["executable_path"] = str(executable)

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        page = browser.new_page(viewport={"width": 1240, "height": 1754})
        page.goto(html_path.resolve().as_uri(), wait_until="load")
        page.wait_for_timeout(1200)
        page.emulate_media(media="print")
        page.pdf(path=str(pdf_path), format="A4", landscape=landscape,
                 print_background=True,
                 margin={"top": "10mm", "bottom": "10mm",
                         "left": "10mm", "right": "10mm"})
        browser.close()
    return pdf_path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Agenten-Map erzeugen")
    ap.add_argument("--out", default=None, help="Zielpfad (Standard: output/agent-map.html)")
    ap.add_argument("--pdf", nargs="?", const=True, default=False,
                    help="Zusätzlich als PDF exportieren (optionaler Pfad)")
    ap.add_argument("--pdf-format", choices=("quer", "hoch"), default="quer",
                    help="Ausrichtung des PDF (Standard: quer — die Karten sind "
                         "1180 px breit und werden hochkant auf 632 px verkleinert)")
    args = ap.parse_args(argv)

    config = Config()
    stats = _collect(config)
    home_address = (config.data.get("commute") or {}).get("home_address") or ""
    geo_svg, geo_meta = _build_geo_svg(stats["apps"], stats["geocache"], stats["limit"],
                                       home_address=home_address)
    system_svg = _build_system_svg()

    html = _render(stats, system_svg, geo_svg, geo_meta)
    out = Path(args.out) if args.out else (config.output_dir / "agent-map.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Agenten-Map erzeugt: {out} ({out.stat().st_size:,} B)")

    if args.pdf:
        pdf_out = out.with_suffix(".pdf") if args.pdf is True else Path(args.pdf)
        export_pdf(out, pdf_out, landscape=args.pdf_format == "quer")
        print(f"PDF erzeugt: {pdf_out} ({pdf_out.stat().st_size:,} B)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
