"""Manueller Import-Provider: liest ``data/import_jobs.json``.

Erwartetes Format (Array):

    [
      {
        "firma": "Beispiel GmbH",
        "titel": "Testingenieur HiL (m/w/d)",
        "ort": "München",
        "url": "https://...",
        "beschreibung": "Optionaler Anzeigentext ..."
      }
    ]
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

# Leads aus Job-Mails (JobLeads, Xing, Instaffo …): nur Firma + Titel, ohne Anzeigentext.
# Sie landen im selben Import, werden aber erst nach den Web-Providern aufgenommen
# (siehe ``run_search``) — eine vollständige Anzeige darf nicht vom Platzhalter verdrängt werden.
MAIL_LEAD = "Mail-Lead"
MAIL_LEAD_TAGE = 30


def _identity(firma: str | None, titel: str | None) -> tuple[str, str]:
    def norm(text: str | None) -> str:
        return " ".join(re.sub(r"[^a-z0-9äöüß]+", " ", (text or "").lower()).split())
    return norm(firma), norm(titel)


def merge_mail_leads(path: Path, leads: list[dict], heute: date | None = None,
                     max_age_days: int = MAIL_LEAD_TAGE) -> int:
    """Hängt neue Mail-Leads an den Import an; gibt die Zahl der neu aufgenommenen zurück.

    Von Hand gepflegte Einträge bleiben unangetastet. Nur alte Mail-Leads
    (älter als ``max_age_days``) werden entfernt. Ohne Firma oder Titel wird
    ein Lead nicht aufgenommen — ohne beides lässt er sich weder zuordnen
    noch bewerten.
    """
    heute = heute or date.today()
    grenze = (heute - timedelta(days=max_age_days)).isoformat()
    bestehend = load_import(path)
    behalten = [j for j in bestehend
                if j.get("quelle") != MAIL_LEAD or str(j.get("gefunden") or "9999") >= grenze]
    bekannt = {_identity(j.get("firma"), j.get("titel")) for j in behalten}
    neu = 0
    for lead in leads:
        firma, titel = (lead.get("firma") or "").strip(), (lead.get("titel") or "").strip()
        ident = _identity(firma, titel)
        if not firma or not titel or ident in bekannt:
            continue
        bekannt.add(ident)
        behalten.append({"firma": firma, "titel": titel, "ort": lead.get("ort") or "",
                         "url": "", "beschreibung": "", "quelle": MAIL_LEAD,
                         "herkunft": lead.get("quelle") or "", "gefunden": heute.isoformat()})
        neu += 1
    if neu or len(behalten) != len(bestehend):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(behalten, ensure_ascii=False, indent=2), encoding="utf-8")
    return neu


def load_import(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("jobs", [])
    if not isinstance(data, list):
        return []
    return data


def search(path: Path) -> list[dict]:
    jobs = []
    for j in load_import(path):
        description = (j.get("beschreibung") or j.get("description")
                       or j.get("snippet") or "")
        jobs.append({
            "titel": j.get("titel") or j.get("title") or "",
            "url": j.get("url") or "",
            # Volltext sowohl als ``beschreibung`` (Dashboard-Anzeige, Matching)
            # als auch als ``snippet`` (Kurzfassung) durchreichen.
            "beschreibung": description,
            "snippet": description[:400],
            "firma": j.get("firma") or j.get("company") or "",
            "ort": j.get("ort") or j.get("location") or "",
            "quelle": j.get("quelle") or "Import",
        })
    return jobs
