"""Arbeitnow: kostenlose Job-Board-API ohne Schlüssel.

Liefert 300 Stellen pro Seite, aber **ohne** serverseitige Filter — die
Parameter ``search``/``location`` werden ignoriert (live geprüft). Der Ort muss
deshalb lokal gefiltert werden. Der Ertrag für München ist begrenzt (rund 10 von
300 pro Seite), deshalb ist der Provider ein ergänzendes Netz und kein Ersatz
für StepStone oder die ATS-Abfrage.

Die Anzeigen kommen **ohne** Beschreibungstext (nur ``description``-Kurzfassung
als HTML); für das Scoring lädt ``fetch_descriptions.py`` sie nach.
"""

from __future__ import annotations

import requests

from ..commute import is_near_munich
from .base import clean_html

ENDPOINT = "https://www.arbeitnow.com/api/job-board-api"
_TIMEOUT = 25


def search(max_pages: int = 3, *, user_agent: str | None = None,
           only_near_munich: bool = True) -> list[dict]:
    """Holt die ersten ``max_pages`` Seiten und filtert lokal nach Ort."""
    headers = {"User-Agent": user_agent or "Bewerbungsagent/1.0 "
               "(+https://github.com/jacobdietzmann-ux/bewerbungsagent)"}
    jobs: list[dict] = []
    seen: set[str] = set()
    for page in range(1, max(1, max_pages) + 1):
        try:
            resp = requests.get(ENDPOINT, params={"page": page},
                                headers=headers, timeout=_TIMEOUT)
            resp.raise_for_status()
            rows = (resp.json() or {}).get("data") or []
        except (requests.RequestException, ValueError):
            break
        if not rows:
            break
        for raw in rows:
            url = (raw.get("url") or "").strip()
            ort = (raw.get("location") or "").strip()
            if not url or url in seen:
                continue
            if only_near_munich and not is_near_munich(ort):
                continue
            seen.add(url)
            jobs.append({
                "titel": (raw.get("title") or "").strip(),
                "firma": (raw.get("company_name") or "").strip(),
                "ort": ort,
                "url": url,
                "quelle": "Arbeitnow",
                "snippet": clean_html(raw.get("description") or "")[:400],
                # Kein Volltext: Arbeitnow liefert nur eine Kurzfassung.
                "beschreibung": "",
            })
    return jobs
