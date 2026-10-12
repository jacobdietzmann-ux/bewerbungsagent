"""Importiert den Inhalt des alten Dashboards in den neuen Agenten.

Quellen:
- ``00_Dashboard/dashboard-state.json``  (autoritativ: 163 Bewerbungen mit Status,
  Notizen, Interview-Datum, Versand-Datum, Kontakt, gelöscht-Flag)
- ``00_Dashboard/Bewerbungs-Dashboard.md`` (Tracking-Tabelle: Branche, Arbeitsort,
  Pendelzeit, Homeoffice, Datum, Profil-Fit %, Gehalt, Ansprechpartner, Stellenanzeige-URL)

Beide werden über die Stelle (Firma + Titel) zusammengeführt.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .profile import normalize
from .statuses import normalize_status

# Alte Statuswerte -> kanonischer 6-Stufen-Funnel (siehe statuses.py).
STATUS_MAP = {
    "rejected": "rejected",
    "sent": "sent",
    "docs": "docs",
    "interview": "interview",
    "research": "research",
    "applied": "sent",
    "offer": "interview",
}

_LINK_RE = re.compile(r"\[[^\]]*\]\((https?://[^)]+)\)")


def _slug(text: str) -> str:
    """Normalisiert auf reine alphanumerische Zeichen (für robusten Titel-Vergleich)."""
    return re.sub(r"[^a-z0-9]", "", normalize(text))


def _norm_firma(name: str) -> str:
    """Normalisiert Firmennamen inkl. Abtrennung von Zusätzen wie „(VW-Konzern)“."""
    n = re.sub(r"\([^)]*\)", "", name or "")
    return _slug(n)


def _split_key(key: str) -> tuple[str, str]:
    firma, _, titel = key.partition(" - ")
    return firma.strip(), titel.strip()


def _fit_from_percent(pct: int) -> str:
    if pct >= 65:
        return "hoch"
    if pct >= 40:
        return "mittel"
    return "niedrig"


def _parse_md_table(path: Path) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    hdr_idx = next((i for i, l in enumerate(lines) if l.startswith("| Unternehmen")), None)
    if hdr_idx is None:
        return []

    rows: list[dict] = []
    for l in lines[hdr_idx + 2:]:
        line = l.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 11:
            continue

        fit_pct = 0
        m = re.search(r"(\d+)\s*%", cells[8])
        if m:
            fit_pct = int(m.group(1))

        url = ""
        m = _LINK_RE.search(cells[11])
        if m:
            url = m.group(1)

        contact = cells[10]
        if contact in ("_(offen)_", "–", "-", ""):
            contact = ""

        rows.append({
            "firma_md": cells[0],
            "titel_md": cells[1],
            "branche": cells[2],
            "ort": cells[3],
            "weg": cells[4],
            "homeoffice": cells[5],
            "datum": cells[6],
            "fit_pct": fit_pct,
            "gehalt": cells[9],
            "ansprechpartner": contact,
            "url": url,
        })
    return rows


def _find_docs(config, firma: str, titel: str) -> dict[str, str]:
    """Verknüpft vorhandene PDFs im Ordner ``01_Bewerbungen/<Firma> - <Titel>/``."""
    bew = config.agent_root.parent / "01_Bewerbungen"
    if not bew.exists():
        return {}

    target = _slug(f"{firma} - {titel}")
    fn = _norm_firma(firma)
    tn = _slug(titel)

    folder = None
    for d in bew.iterdir():
        if not d.is_dir():
            continue
        dn = _slug(d.name)
        if dn == target or (fn and fn in dn and tn in dn):
            folder = d
            break
    if folder is None:
        return {}

    labels = {
        "anschreiben_jacob_dietzmann": "Anschreiben",
        "lebenslauf_jacob_dietzmann": "Lebenslauf",
        "cover_letter_jacob_dietzmann_en": "Cover Letter (EN)",
        "cv_jacob_dietzmann_en": "CV (EN)",
    }
    docs: dict[str, str] = {}
    for f in sorted(folder.glob("*.pdf")):
        key = normalize(f.stem)
        if key in labels:
            docs[labels[key]] = os.path.relpath(str(f), str(config.agent_root))
    return docs


def import_old_dashboard(config) -> list[dict]:
    """Liest das alte Dashboard und liefert Anwendungen im neuen Schema."""
    state_path = config.agent_root.parent / "00_Dashboard" / "dashboard-state.json"
    md_path = config.agent_root.parent / "00_Dashboard" / "Bewerbungs-Dashboard.md"

    if not state_path.exists():
        return []

    old = json.loads(state_path.read_text(encoding="utf-8"))
    md_rows = _parse_md_table(md_path)

    # Index der MD-Zeilen: (firma_slug, titel_slug) -> row, plus titel_slug -> rows.
    by_pair: dict[tuple[str, str], dict] = {}
    by_titel: dict[str, list[dict]] = {}
    for r in md_rows:
        by_pair[(_norm_firma(r["firma_md"]), _slug(r["titel_md"]))] = r
        by_titel.setdefault(_slug(r["titel_md"]), []).append(r)

    # Für den Fuzzy-Fallback: alle MD-Zeilen und ihre Titel-Slugs.
    md_list = [(r, _slug(r["titel_md"]), _norm_firma(r["firma_md"])) for r in md_rows]

    apps: list[dict] = []
    for key, v in old.items():
        if v.get("deleted"):
            continue
        firma, titel = _split_key(key)
        fn = _norm_firma(firma)
        tn = _slug(titel)
        md = by_pair.get((fn, tn))
        if md is None:
            # Fallback 1: eindeutiger Titel.
            candidates = by_titel.get(tn, [])
            if len(candidates) == 1:
                md = candidates[0]
        if md is None:
            # Fallback 2: Fuzzy-Titel (difflib) mit Firma-Tiebreak.
            md = _fuzzy_match(md_list, fn, tn)

        apps.append({
            "firma": firma,
            "titel": titel,
            "ort": (md or {}).get("ort", ""),
            "branche": (md or {}).get("branche", ""),
            "gehalt": (md or {}).get("gehalt", ""),
            "ansprechpartner": (md or {}).get("ansprechpartner", ""),
            "url": (md or {}).get("url", ""),
            "quelle": "Alt-Dashboard",
            "status": normalize_status(STATUS_MAP.get(v.get("status", "research"), "research")),
            "key": normalize(f"{firma}|{titel}"),
            "notes": v.get("notes", ""),
            "contact": v.get("contact", ""),
            "interviewDate": v.get("interviewDate", ""),
            "sentAt": v.get("sentAt", ""),
            "statusChangedAt": v.get("statusChangedAt", ""),
            "datum": (md or {}).get("datum", ""),
            "homeoffice": (md or {}).get("homeoffice", ""),
            "fit_pct": (md or {}).get("fit_pct", 0),
            "dokumente": _find_docs(config, firma, titel),
        })
    return apps


def _fuzzy_match(md_list: list, firma_slug: str, titel_slug: str) -> dict | None:
    """Best-Effort-Fuzzy-Match über Titel-Ähnlichkeit (und Firma als Tiebreak)."""
    from difflib import SequenceMatcher

    best, best_ratio = None, 0.0
    for row, t_slug, f_slug in md_list:
        ratio = SequenceMatcher(None, titel_slug, t_slug).ratio()
        if firma_slug and f_slug and firma_slug == f_slug:
            ratio += 0.25  # Firma stimmt exakt -> stark bevorzugen
        if ratio > best_ratio:
            best, best_ratio = row, ratio
    if best_ratio >= 0.75:
        return best
    return None
