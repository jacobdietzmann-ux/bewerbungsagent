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
                "status": "docs",
                "dokumente": {
                    "stellenanzeige": "../01_Bewerbungen/Beispiel GmbH - Testingenieur/Stellenanzeige.txt",
                },
            },
            {
                "firma": "Zu weit",
                "titel": "Test",
                "status": "docs",
                "pendelzeit_min": 91,
                "dokumente": {
                    "anschreiben_de": "../01_Bewerbungen/Beispiel GmbH - Testingenieur/Anschreiben.pdf",
                },
            },
            {
                "firma": "Pendelzeit unbekannt",
                "titel": "Test",
                "status": "docs",
                "pendelzeit_min": None,
                "dokumente": {
                    "anschreiben_de": "../01_Bewerbungen/Beispiel GmbH - Testingenieur/Anschreiben.pdf",
                },
            },
            {"firma": "Ohne Dokument", "titel": "Test", "status": "docs", "dokumente": {}},
            {"firma": "Research ohne Unterlagen", "titel": "Test", "status": "research",
             "dokumente": {}},
        ],
    }
    output = tmp_path / "dashboard.html"

    dashboard.build_dashboard(state, output)

    rows = _embedded_rows(output.read_text(encoding="utf-8"))
    # Der komplette Bestand bleibt eingebettet (Historie für Charts/KPIs) …
    assert set(rows) == {
        "Mit Dokument", "Nur Anzeige", "Zu weit", "Pendelzeit unbekannt",
        "Ohne Dokument", "Research ohne Unterlagen",
    }
    # … aber nur relevante Stellen sind in der Tabelle sichtbar.
    # ``docs`` ohne Dateien bleibt unsichtbar: der Status behauptet eine
    # Bewerbung, die es nicht gibt.
    assert rows["Mit Dokument"]["visible"] is True
    assert rows["Nur Anzeige"]["visible"] is False
    assert rows["Zu weit"]["visible"] is False
    assert rows["Pendelzeit unbekannt"]["visible"] is True
    assert rows["Ohne Dokument"]["visible"] is False
    # ``research`` ohne Unterlagen ist ein reiner Fund und bleibt unsichtbar —
    # damit zählt der Status-Schalter dieselbe Menge wie die Tabelle.
    assert rows["Research ohne Unterlagen"]["visible"] is False
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
    # Research-Funde bleiben aus Kennzahlen und Wochenverlauf aussen vor. In der
    # Status-Verteilung dürfen sie erscheinen: sie folgt der Tabelle, und als
    # „neu gefunden" ist eine Research-Zeile dort sichtbar.
    assert html.count('r.status !== "research"') == 2
    assert "SHOWN_STATUSES = ORDER;" in html


def test_dashboard_offers_research_status_toggle(
    tmp_path: Path, monkeypatch,
):
    """Research braucht einen Schalter, seit solche Zeilen sichtbar sein können."""
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
    # Die Schalter werden im Browser aus ``SHOWN_STATUSES`` erzeugt; im HTML steht
    # deshalb nur die Liste. Sie muss „research" enthalten, sonst gäbe es keinen
    # Schalter zum Ausblenden der als „neu gefunden" sichtbaren Research-Zeilen.
    assert 'const SHOWN_STATUSES = ORDER;' in html
    assert '"research"' in html.split("const ORDER = ", 1)[1].split(";", 1)[0]
    # Der Eintrag bleibt eingebettet (Datenverlust ausgeschlossen) und ohne
    # Unterlagen unsichtbar.
    assert "Neuer Fund" in html
    assert _embedded_rows(html)["Neuer Fund"]["visible"] is False


class TestBriefingLinks:
    """Interview-Briefings werden im Bewerbungsordner gefunden und verlinkt.

    Sie entstehen erst nach dem Versand und stehen deshalb nicht im
    ``dokumente``-Feld der DB — ohne Ordner-Scan blieben sie unsichtbar.
    """

    def _setup(self, tmp_path, monkeypatch, *files):
        agent_root = tmp_path / "04_Agent"
        agent_root.mkdir()
        folder = tmp_path / "01_Bewerbungen" / "Firma - Stelle"
        folder.mkdir(parents=True)
        (folder / "Anschreiben.pdf").write_bytes(b"pdf")
        for name in files:
            (folder / name).write_bytes(b"pdf" if name.endswith(".pdf") else b"# md")
        monkeypatch.setattr(dashboard, "AGENT_ROOT", agent_root)
        return folder

    def _app(self, folder) -> dict:
        return {
            "firma": "Firma", "titel": "Testingenieur", "status": "interview",
            "interviewDate": "2026-11-03", "pendelzeit_min": 20,
            "dokumente": {"anschreiben_de": str(folder / "Anschreiben.pdf")},
        }

    def _docs(self, tmp_path, folder) -> list[dict]:
        output = tmp_path / "dashboard.html"
        dashboard.build_dashboard({"applications": [self._app(folder)]}, output)
        return _embedded_rows(output.read_text(encoding="utf-8"))["Firma"]["docs"]

    def test_briefing_pdf_wird_verlinkt(self, tmp_path, monkeypatch):
        folder = self._setup(tmp_path, monkeypatch,
                             "Briefing_Firma_2026-10-20.pdf")
        labels = {d["label"]: d["href"] for d in self._docs(tmp_path, folder)}
        assert "Briefing (PDF)" in labels
        assert labels["Briefing (PDF)"].endswith("Briefing_Firma_2026-10-20.pdf")

    def test_englische_variante_bekommt_eigenes_label(self, tmp_path, monkeypatch):
        folder = self._setup(tmp_path, monkeypatch,
                             "Briefing_Firma_2026-10-20.pdf",
                             "Briefing_Firma_2026-10-20_EN.pdf")
        labels = [d["label"] for d in self._docs(tmp_path, folder)]
        assert "Briefing (PDF)" in labels
        assert "Briefing (PDF, EN)" in labels

    def test_markdown_nur_ohne_passendes_pdf(self, tmp_path, monkeypatch):
        folder = self._setup(tmp_path, monkeypatch,
                             "Briefing_A.pdf", "Briefing_A.md", "Briefing_B.md")
        hrefs = [d["href"] for d in self._docs(tmp_path, folder)]
        assert any(h.endswith("Briefing_A.pdf") for h in hrefs)
        assert not any(h.endswith("Briefing_A.md") for h in hrefs)
        assert any(h.endswith("Briefing_B.md") for h in hrefs)

    def test_ohne_briefing_keine_leeren_links(self, tmp_path, monkeypatch):
        folder = self._setup(tmp_path, monkeypatch)
        docs = self._docs(tmp_path, folder)
        assert [d["label"] for d in docs] == ["Anschreiben"]

    def test_briefing_allein_macht_stelle_nicht_sichtbar(self, tmp_path, monkeypatch):
        """Ein Briefing ist kein Bewerbungsunterlagen-Ersatz."""
        agent_root = tmp_path / "04_Agent"
        agent_root.mkdir()
        folder = tmp_path / "01_Bewerbungen" / "Firma - Stelle"
        folder.mkdir(parents=True)
        (folder / "Briefing_Firma.pdf").write_bytes(b"pdf")
        monkeypatch.setattr(dashboard, "AGENT_ROOT", agent_root)

        output = tmp_path / "dashboard.html"
        dashboard.build_dashboard({"applications": [{
            "firma": "Firma", "titel": "Testingenieur", "status": "docs",
            "dokumente": {"anschreiben_de": str(folder / "Fehlt.pdf")},
        }]}, output)
        rows = _embedded_rows(output.read_text(encoding="utf-8"))
        assert rows["Firma"]["visible"] is False
