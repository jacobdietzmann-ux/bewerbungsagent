"""Gespeicherte Suchen: benannte, einzeln ausführbare Suchdefinitionen.

Eine gespeicherte Suche ist eine benannte Teilmenge der Suchparameter
(``query_terms``, ``location``, ``providers``). Sie liegt als JSON-Array in
``data/saved_searches.json``:

    [
      {"name": "Test & Verification", "query_terms": ["Testingenieur", "ADAS Test"],
       "location": "München", "providers": ["stepstone", "jobspy"]}
    ]

Ohne Datei wird eine „Standard"-Suche aus ``config.json`` abgeleitet. Der
manuelle Import (``data/import_jobs.json``) läuft unabhängig von der gewählten
Suche immer mit.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import Config


def _path(config: Config) -> Path:
    return config.data_dir / "saved_searches.json"


def default_search(config: Config) -> dict:
    """Leitet die „Standard"-Suche aus ``config.json`` ab."""
    s = config.data["search"]
    return {
        "name": "Standard",
        "query_terms": list(s.get("query_terms", [])),
        "location": s.get("location", "München"),
        "providers": list(s.get("providers", [])),
    }


def load_saved_searches(config: Config) -> list[dict]:
    """Lädt die gespeicherten Suchen; ohne Datei: nur die Standard-Suche."""
    path = _path(config)
    if not path.exists():
        return [default_search(config)]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return [default_search(config)]
    if isinstance(data, dict):
        data = data.get("searches", [])
    if not isinstance(data, list):
        return [default_search(config)]
    searches = [s for s in data if isinstance(s, dict) and s.get("name")]
    return searches or [default_search(config)]


def save_saved_searches(config: Config, searches: list[dict]) -> None:
    """Schreibt die gespeicherten Suchen (atomar, bisync-sicher)."""
    path = _path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(searches, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    tmp.replace(path)


def find_saved_search(config: Config, name: str) -> dict | None:
    """Sucht eine gespeicherte Suche anhand des Namens (exakt)."""
    for s in load_saved_searches(config):
        if s.get("name") == name:
            return s
    return None


def to_definition(search: dict) -> dict:
    """Projiziert eine gespeicherte Suche auf die ``definition``-Form von
    ``search.run_search`` (nur die überschreibbaren Felder)."""
    return {
        "query_terms": search.get("query_terms"),
        "location": search.get("location"),
        "providers": search.get("providers"),
    }
