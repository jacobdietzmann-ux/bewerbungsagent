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
    apps = [_app(folder, "Hoch", 80, "docs"), _app(folder, "Niedrig", 40, "docs")]
    dashboard.build_dashboard({"applications": apps}, ziel, min_fit=65)
    sichtbar = _visible(ziel.read_text(encoding="utf-8"))
    assert sichtbar == ["Hoch"]
    # Ausblenden heißt nicht löschen: der Eintrag bleibt in den Daten.
    daten = json.loads(re.search(r"const DATA = (\[.*?\]);", ziel.read_text(encoding="utf-8"), re.S)
                       .group(1).replace("<\\/", "</"))
    assert {row["company"] for row in daten} == {"Hoch", "Niedrig"}


def test_versendete_bewerbung_bleibt_trotz_schwelle_sichtbar(folder):
    """Sonst zeigte die Tabelle 67 Absagen, die Kennzahlen rechneten mit 151."""
    ziel = folder / "d.html"
    apps = [_app(folder, status, 40, status) for status in ("sent", "interview", "rejected")]
    dashboard.build_dashboard({"applications": apps}, ziel, min_fit=65)
    assert set(_visible(ziel.read_text(encoding="utf-8"))) == {"sent", "interview", "rejected"}


def test_schreibweisen_einer_firma_werden_zusammengefasst():
    gruppen = dashboard._firmen_gruppen([
        "Quantum-Systems GmbH", "Quantum-Systems GmbH", "Quantum- Systems GmbH", "Quantum-Systems",
        "ALTEN", "ALTEN", "ALTEN Consulting Services",
        "FERCHAU", "FERCHAU – Connecting People and Technologies",
        "E.ON Drive Germany GmbH", "E.ON Energie Deutschland GmbH",
    ])
    assert len({gruppen[n] for n in gruppen if n.startswith("Quantum")}) == 1
    assert gruppen["ALTEN Consulting Services"] == "ALTEN"
    assert gruppen["FERCHAU – Connecting People and Technologies"] == gruppen["FERCHAU"]
    assert gruppen["E.ON Drive Germany GmbH"] != gruppen["E.ON Energie Deutschland GmbH"]
