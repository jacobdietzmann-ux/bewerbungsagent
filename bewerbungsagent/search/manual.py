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
from pathlib import Path


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
