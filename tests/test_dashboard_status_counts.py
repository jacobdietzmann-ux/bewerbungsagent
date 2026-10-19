"""Regression: Status-Schalter, Tabelle und Diagramm müssen dieselbe Menge zeigen.

Fehlerbild: Der Schalter zeigte „Research (11)", die Tabelle war leer. Ursache
waren zwei verschiedene Grundmengen:

- ``updateStatusToggleCounts()`` zählte alle nicht gelöschten Einträge,
- Tabelle und Status-Verteilung filterten zusätzlich ``visible``.

Research-Einträge ohne Unterlagen waren dadurch gezählt, aber nirgends zu sehen.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from bewerbungsagent import dashboard


def _build(tmp_path: Path, apps: list[dict]) -> str:
    target = tmp_path / "dashboard.html"
    dashboard.build_dashboard({"applications": apps}, target)
    return target.read_text(encoding="utf-8")


def _rows(html: str) -> list[dict]:
    m = re.search(r"^const DATA = (\[.*?\]);$", html, re.M | re.S)
    assert m
    return json.loads(m.group(1))


def test_forschung_ohne_unterlagen_ist_sichtbar(tmp_path, monkeypatch):
    """Der Pipeline-Filter hat sie behalten — dann muss man sie auch sehen."""
    agent_root = tmp_path / "04_Agent"
    agent_root.mkdir()
    monkeypatch.setattr(dashboard, "AGENT_ROOT", agent_root)

    app = {
        "key": "k1", "firma": "Acme", "titel": "Testingenieur",
        "status": "research", "fit_pct": 68, "pendelzeit_min": 25,
        "dokumente": {},
    }
    rows = _rows(_build(tmp_path, [app]))
    assert rows[0]["visible"] is True


def test_docs_ohne_unterlagen_bleibt_unsichtbar(tmp_path, monkeypatch):
    """``docs`` heißt „hier liegt eine Bewerbung" — ohne Dateien ist das falsch."""
    agent_root = tmp_path / "04_Agent"
    agent_root.mkdir()
    monkeypatch.setattr(dashboard, "AGENT_ROOT", agent_root)

    app = {"key": "k2", "firma": "Acme", "titel": "T", "status": "docs",
           "pendelzeit_min": 25, "dokumente": {}}
    rows = _rows(_build(tmp_path, [app]))
    assert rows[0]["visible"] is False


def test_schalter_zaehlt_wie_die_tabelle(tmp_path):
    """Der Zähler im Schalter darf nicht mehr zählen, was die Tabelle verbirgt."""
    html = _build(tmp_path, [])
    start = html.index("function updateStatusToggleCounts()")
    body = html[start:start + 400]
    assert "r.visible !== false" in body
