"""Tests für den Dokumentfilter des Dashboards."""

from __future__ import annotations

import json
import re
from pathlib import Path

from bewerbungsagent import dashboard


def _embedded_rows(html: str) -> dict[str, dict]:
    match = re.search(r"const DATA = (\[.*?\]);", html, re.DOTALL)
    assert match, "Dashboard-DATEN nicht gefunden"
    rows = json.loads(match.group(1))
    return {row["company"]: row for row in rows}


def test_dashboard_marks_only_relevant_applications_as_visible(
    tmp_path: Path, monkeypatch,
):
    agent_root = tmp_path / "04_Agent"
    agent_root.mkdir()
    applications_dir = tmp_path / "01_Bewerbungen"
    application_folder = applications_dir / "Beispiel GmbH - Testingenieur"
    application_folder.mkdir(parents=True)
    cover_letter = application_folder / "Anschreiben.pdf"
    cover_letter.write_bytes(b"pdf")
    (application_folder / "Stellenanzeige.txt").write_text("Anzeige", encoding="utf-8")
    monkeypatch.setattr(dashboard, "AGENT_ROOT", agent_root)

    state = {
        "applications": [
            {
                "firma": "Mit Dokument",
                "titel": "Testingenieur",
                "dokumente": {
                    "anschreiben_de": "../01_Bewerbungen/Beispiel GmbH - Testingenieur/Anschreiben.pdf",
                    "lebenslauf_de": "../01_Bewerbungen/Beispiel GmbH - Testingenieur/Fehlt.pdf",
                    "stellenanzeige": "../01_Bewerbungen/Beispiel GmbH - Testingenieur/Stellenanzeige.txt",
                },
            },
            {
                "firma": "Nur Anzeige",
                "titel": "Test",
                "dokumente": {
                    "stellenanzeige": "../01_Bewerbungen/Beispiel GmbH - Testingenieur/Stellenanzeige.txt",
                },
            },
            {
                "firma": "Zu weit",
                "titel": "Test",
                "pendelzeit_min": 91,
                "dokumente": {
                    "anschreiben_de": "../01_Bewerbungen/Beispiel GmbH - Testingenieur/Anschreiben.pdf",
                },
            },
            {
                "firma": "Pendelzeit unbekannt",
                "titel": "Test",
                "pendelzeit_min": None,
                "dokumente": {
                    "anschreiben_de": "../01_Bewerbungen/Beispiel GmbH - Testingenieur/Anschreiben.pdf",
                },
            },
            {"firma": "Ohne Dokument", "titel": "Test", "dokumente": {}},
        ],
    }
    output = tmp_path / "dashboard.html"

    dashboard.build_dashboard(state, output)

    rows = _embedded_rows(output.read_text(encoding="utf-8"))
    # Der komplette Bestand bleibt eingebettet (Historie für Charts/KPIs) …
    assert set(rows) == {
        "Mit Dokument", "Nur Anzeige", "Zu weit", "Pendelzeit unbekannt",
        "Ohne Dokument",
    }
    # … aber nur relevante Stellen sind in der Tabelle sichtbar.
    assert rows["Mit Dokument"]["visible"] is True
    assert rows["Nur Anzeige"]["visible"] is False
    assert rows["Zu weit"]["visible"] is False
    assert rows["Pendelzeit unbekannt"]["visible"] is True
    assert rows["Ohne Dokument"]["visible"] is False
    # Nicht vorhandene Dokumente werden nicht verlinkt.
    assert "Fehlt.pdf" not in output.read_text(encoding="utf-8")


def _documented_app(folder: Path, firma: str, status: str, pendelzeit: int | None = None) -> dict:
    app = {
        "firma": firma,
        "titel": "Testingenieur",
        "status": status,
        "dokumente": {"anschreiben_de": str(folder / "Anschreiben.pdf")},
    }
    if pendelzeit is not None:
        app["pendelzeit_min"] = pendelzeit
    return app


def test_dashboard_shows_only_relevant_applications_in_status_chart(
    tmp_path: Path, monkeypatch,
):
    """Die Status-Verteilung zählt nur sichtbare Stellen – Diagramm == Tabelle."""
    agent_root = tmp_path / "04_Agent"
    agent_root.mkdir()
    folder = tmp_path / "01_Bewerbungen" / "Firma - Stelle"
    folder.mkdir(parents=True)
    (folder / "Anschreiben.pdf").write_bytes(b"pdf")
    monkeypatch.setattr(dashboard, "AGENT_ROOT", agent_root)

    state = {
        "applications": [
            _documented_app(folder, "Sichtbar", "docs", 25),
            _documented_app(folder, "Zu weit", "docs", 97),
            _documented_app(folder, "Versendet", "sent", 20),
        ],
    }
    output = tmp_path / "dashboard.html"

    dashboard.build_dashboard(state, output)

    html = output.read_text(encoding="utf-8")
    # Das Status-Diagramm darf nur noch sichtbare Zeilen zählen, damit die im
    # Diagramm genannten Zahlen zur Tabelle passen.
    assert "state.filter(r => !r.deleted && r.visible !== false)" in html
    # Research-Funde bleiben überall außen vor (Diagramm, KPIs, Wochenverlauf).
    assert 'SHOWN_STATUSES = ORDER.filter(s => s !== "research")' in html
    assert 'r.status !== "research"' in html


def test_dashboard_does_not_offer_research_status_toggle(
    tmp_path: Path, monkeypatch,
):
    """„Research" wird im Dashboard weder angezeigt noch als Schalter angeboten."""
    agent_root = tmp_path / "04_Agent"
    agent_root.mkdir()
    monkeypatch.setattr(dashboard, "AGENT_ROOT", agent_root)

    state = {
        "applications": [
            {"firma": "Neuer Fund", "titel": "Testingenieur", "status": "neu", "dokumente": {}},
        ],
    }
    output = tmp_path / "dashboard.html"

    dashboard.build_dashboard(state, output)

    html = output.read_text(encoding="utf-8")
    assert "Research einblenden" not in html
    # Der Eintrag bleibt eingebettet (Datenverlust ausgeschlossen) …
    assert "Neuer Fund" in html
    # … ist aber nicht sichtbar.
    assert _embedded_rows(html)["Neuer Fund"]["visible"] is False
