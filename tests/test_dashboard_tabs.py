"""Tests für den Zwei-Tab-Aufbau und die Häufigkeitsverteilungen.

Aufbau: Tab 1 enthält die Tabelle (tägliches Arbeiten), Tab 2 die Auswertung
(KPIs, Status-Verteilung, Wochenverlauf, Häufigkeitsverteilungen). Vorher stand
alles auf einer Seite und die Tabelle war weit nach unten gedrängt.
"""

from __future__ import annotations

from pathlib import Path

from bewerbungsagent.dashboard import build_dashboard

REQUIRED_IDS = [
    "kpis", "statusChart", "timeChart", "timeChartLegend",
    "distHomeoffice", "distCommute", "distFit", "distCompany",
    "searchBox", "fitFilter", "neuFilter", "rows",
]


def _build(tmp_path: Path) -> str:
    apps = [{
        "key": "https://example.test/job/1",
        "titel": "Test Engineer",
        "firma": "Acme GmbH",
        "status": "interview",
        "homeoffice": "Hybrid",
        "pendelzeit_min": 25,
        "fit_pct": 72,
        "dokumente": {"lebenslauf_de": "output/x/Lebenslauf.pdf"},
    }]
    target = tmp_path / "dashboard.html"
    build_dashboard({"applications": apps}, target)
    return target.read_text(encoding="utf-8")


def test_zwei_tabs_vorhanden(tmp_path):
    html = _build(tmp_path)
    assert 'id="tabBtn-table"' in html
    assert 'id="tabBtn-stats"' in html
    assert 'id="tab-table"' in html
    assert 'id="tab-stats"' in html


def test_statistik_tab_ist_zunaechst_versteckt(tmp_path):
    """Beim Laden soll die Tabelle sichtbar sein, nicht die Auswertung."""
    html = _build(tmp_path)
    stats_start = html.index('id="tab-stats"')
    assert "hidden" in html[stats_start:stats_start + 200]


def test_tabelle_und_statistik_getrennt(tmp_path):
    """Tabelle und Diagramme dürfen nicht im selben Pane stehen."""
    html = _build(tmp_path)
    table_open = html.index('id="tab-table"')
    stats_open = html.index('id="tab-stats"')
    # Die Tabelle liegt vor dem Statistik-Pane ...
    assert html.index('id="table-main"') < stats_open
    # ... und die Diagramme danach.
    for el in ("statusChart", "timeChart", "distHomeoffice"):
        assert html.index(f'id="{el}"') > stats_open
    assert table_open < stats_open


def test_alle_container_vorhanden(tmp_path):
    html = _build(tmp_path)
    for el in REQUIRED_IDS:
        assert f'id="{el}"' in html, el


def test_verteilungen_werden_gezeichnet(tmp_path):
    html = _build(tmp_path)
    assert "function renderDistributions" in html
    assert "renderDistributions();" in html
    assert "function homeofficeCategory" in html


def test_homeoffice_kategorien(tmp_path):
    html = _build(tmp_path)
    assert '"Voll-Remote"' in html
    assert '"Hybrid"' in html
    assert '"Vor Ort"' in html
    assert '"Unbekannt"' in html
