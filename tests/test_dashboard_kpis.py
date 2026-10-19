"""Tests für die KPI-Karten des Dashboards.

„Antwortrate" wurde entfernt: die Kennzahl war doppeldeutig (Antworten sind im
Datenmodell nicht als eigenes Feld erfasst, nur als Statuswechsel), und der
Funnel-Wert heißt jetzt selbsterklärend „Interviews von Gesamt".
"""

from __future__ import annotations

from pathlib import Path

from bewerbungsagent.dashboard import build_dashboard


def _build(tmp_path: Path) -> str:
    apps = [{
        "key": "https://example.test/job/1",
        "titel": "Test Engineer",
        "firma": "Acme GmbH",
        "status": "interview",
        "dokumente": {"lebenslauf_de": "output/x/Lebenslauf.pdf"},
    }]
    target = tmp_path / "dashboard.html"
    build_dashboard({"applications": apps}, target)
    return target.read_text(encoding="utf-8")


def test_antwortrate_entfernt(tmp_path):
    assert "Antwortrate" not in _build(tmp_path)


def test_funnel_label_selbsterklaerend(tmp_path):
    html = _build(tmp_path)
    assert "Interviews von Gesamt" in html
    assert "Funnel (IV/Gesamt)" not in html


def test_kernkennzahlen_bleiben(tmp_path):
    html = _build(tmp_path)
    for label in ("Versand-Quote", "Interview-Rate", "Aktiv im Prozess"):
        assert label in html
