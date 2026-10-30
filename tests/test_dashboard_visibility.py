"""Regression: abgeschlossene Bewerbungen dürfen nicht versteckt werden.

Der Dokument-/Pendelweg-Filter ist eine Entscheidungshilfe für *potenzielle*
Bewerbungen. Auf ``sent``/``rejected`` angewandt blendete er 56 echte Vorgänge
aus Tabelle und Status-Verteilung aus — die Absagen-Quote rechnete dadurch nur
auf einer Teilmenge (63 statt 112 Absagen).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bewerbungsagent import dashboard


@pytest.fixture
def folder(tmp_path, monkeypatch):
    agent_root = tmp_path / "04_Agent"
    agent_root.mkdir()
    monkeypatch.setattr(dashboard, "AGENT_ROOT", agent_root)
    return tmp_path


def _app(folder: Path, firma: str, status: str, *, docs: bool = True,
         pendelzeit: int | None = None) -> dict:
    app = {"key": firma, "firma": firma, "titel": "Testingenieur", "status": status}
    if docs:
        path = folder / f"{firma}.pdf"
        path.write_bytes(b"%PDF-1.4 test")
        app["dokumente"] = {"anschreiben_de": str(path)}
    else:
        app["dokumente"] = {}
    if pendelzeit is not None:
        app["pendelzeit_min"] = pendelzeit
    return app


@pytest.mark.parametrize("status", ["sent", "followup", "interview", "rejected"])
def test_beworbene_stelle_ist_immer_sichtbar(folder, status):
    """Egal ob Unterlagen fehlen oder der Weg zu weit ist."""
    app = _app(folder, "Acme", status, docs=False, pendelzeit=99)
    assert dashboard.dashboard_applications([app]) == [app]


@pytest.mark.parametrize("status", ["sent", "rejected"])
def test_beworbene_stelle_mit_zu_weitem_weg_bleibt_sichtbar(folder, status):
    app = _app(folder, "Acme", status, pendelzeit=41)
    assert dashboard.dashboard_applications([app]) == [app]


def test_legacy_status_wird_erkannt(folder):
    """``absage``/``beworben`` sind Alt-Werte und zählen als beworben."""
    a = _app(folder, "A", "absage", docs=False)
    b = _app(folder, "B", "beworben", docs=False)
    visible = dashboard.dashboard_applications([a, b])
    assert a in visible and b in visible


def test_potenzielle_bewerbung_braucht_unterlagen(folder):
    app = _app(folder, "Acme", "docs", docs=False)
    assert dashboard.dashboard_applications([app]) == []


def test_potenzielle_bewerbung_braucht_naehe(folder):
    app = _app(folder, "Acme", "docs", pendelzeit=97)
    assert dashboard.dashboard_applications([app]) == []


def test_potenzielle_bewerbung_mit_unterlagen_und_naehe(folder):
    app = _app(folder, "Acme", "docs", pendelzeit=25)
    assert dashboard.dashboard_applications([app]) == [app]


def test_geloeschte_stelle_bleibt_trotz_unterlagen_verborgen(folder):
    """Dubletten mit Status ``docs`` und Dateien dürfen keine Karten erzeugen."""
    app = _app(folder, "MicroNova", "docs", pendelzeit=25)
    app["deleted"] = True
    assert dashboard.dashboard_applications([app]) == []
