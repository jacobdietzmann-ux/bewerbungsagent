"""Tests für ``dashboard.min_fit_visible`` (Sichtbarkeitsschwelle im Dashboard).

Hintergrund: ``agent.py dashboard`` und der HTTP-Server bauen dasselbe
Dashboard. Ohne gemeinsame Schwelle überschrieb der Server den Stand der CLI —
und nach dem Einbau der Schwelle rief der Server ``build_dashboard(min_fit=…)``
auf, während die Funktion den Parameter nicht kannte (TypeError).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from bewerbungsagent import dashboard


@pytest.fixture
def folder(tmp_path, monkeypatch):
    agent_root = tmp_path / "04_Agent"
    agent_root.mkdir()
    monkeypatch.setattr(dashboard, "AGENT_ROOT", agent_root)
    return tmp_path


def _app(folder: Path, firma: str, fit: int, status: str = "sent") -> dict:
    datei = folder / f"{firma}.pdf"
    datei.write_bytes(b"%PDF-1.4 test")
    return {"key": firma, "firma": firma, "titel": "Testingenieur", "status": status,
            "score": fit, "fit_geschaetzt": fit,
            "dokumente": {"anschreiben_de": str(datei)}}


def _visible(html: str) -> list[str]:
    data = json.loads(re.search(r"const DATA = (\[.*?\]);", html, re.S).group(1)
                      .replace("<\\/", "</"))
    return [row["company"] for row in data if row.get("visible")]


def test_ohne_schwelle_bleiben_alle_sichtbar(folder):
    ziel = folder / "d.html"
    apps = [_app(folder, "Hoch", 80), _app(folder, "Niedrig", 40)]
    dashboard.build_dashboard({"applications": apps}, ziel)
    assert set(_visible(ziel.read_text(encoding="utf-8"))) == {"Hoch", "Niedrig"}


def test_schwelle_blendet_nur_aus(folder):
    ziel = folder / "d.html"
    apps = [_app(folder, "Hoch", 80), _app(folder, "Niedrig", 40)]
    dashboard.build_dashboard({"applications": apps}, ziel, min_fit=65)
    sichtbar = _visible(ziel.read_text(encoding="utf-8"))
    assert sichtbar == ["Hoch"]
    # Ausblenden heißt nicht löschen: der Eintrag bleibt in den Daten.
    daten = json.loads(re.search(r"const DATA = (\[.*?\]);", ziel.read_text(encoding="utf-8"), re.S)
                       .group(1).replace("<\\/", "</"))
    assert {row["company"] for row in daten} == {"Hoch", "Niedrig"}
