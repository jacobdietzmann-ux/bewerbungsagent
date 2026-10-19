"""Tests für die KPI-Karten des Dashboards.

Entfernt wurden zwei Kennzahlen ohne eigenen Informationsgehalt:

- „Antwortrate": Antworten sind im Datenmodell kein eigenes Feld, nur ein
  Statuswechsel — die Kennzahl war eine Ableitung aus ``followup``/``interview``.
- „Funnel" (Interviews ÷ Gesamt): mathematisch das Produkt aus Interview-Rate
  und Versand-Anteil, also ohne unabhängige Aussage. Der Nenner enthielt zudem
  alle abgelehnten Einträge.
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


def test_funnel_entfernt(tmp_path):
    """Der Funnel war das Produkt der beiden anderen Quoten — kein Mehrwert."""
    html = _build(tmp_path)
    assert "Interviews von Gesamt" not in html
    assert "Funnel" not in html


def test_kernkennzahlen_bleiben(tmp_path):
    html = _build(tmp_path)
    for label in ("Versand-Quote", "Interview-Rate", "Aktiv im Prozess",
                  "Ø Profil-Fit (Interviews)"):
        assert label in html
