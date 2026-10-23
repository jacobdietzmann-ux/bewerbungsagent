"""Research-Funde erscheinen nur mit ausdrücklicher Freigabe im Dashboard.

Ausgangslage: ``dashboard_applications`` blendet alles ohne Anschreiben/
Lebenslauf aus — das ist die Entscheidungsgrundlage „lohnt sich eine Bewerbung?“
und darf nicht pauschal gelockert werden (im Live-Bestand liegen 658 Einträge
im Status ``research``/``neu`` ohne Unterlagen).

Stellen im Research-Band (Fit 60–70 %) sind aber bewusst beobachtete Kandidaten.
Für sie gibt es die Freigabe ``research_sichtbar``. Sie wirkt nur:

- bei Status ``research`` (nicht bei ``docs``),
- innerhalb der Pendelzeit-Grenze (harte Grenze bleibt),
- unabhängig von vorhandenen Unterlagen.
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


def _app(firma: str, status: str = "research", *, docs: bool = False,
         pendelzeit: int | None = 25, sichtbar: bool | None = None) -> dict:
    app = {"key": firma, "firma": firma, "titel": "Testingenieur", "status": status}
    app["dokumente"] = {}
    if pendelzeit is not None:
        app["pendelzeit_min"] = pendelzeit
    if sichtbar is not None:
        app["research_sichtbar"] = sichtbar
    return app


def test_research_ohne_freigabe_bleibt_verborgen(folder):
    """Der Standardfall: Research ohne Unterlagen füllt die Tabelle nicht."""
    assert dashboard.dashboard_applications([_app("Acme")]) == []


def test_freigegebener_research_fund_ist_sichtbar(folder):
    app = _app("Acme", sichtbar=True)
    assert dashboard.dashboard_applications([app]) == [app]


@pytest.mark.parametrize("fit", [64, 68, 70])
def test_freigabe_gilt_im_research_band(folder, fit):
    app = _app(f"Acme-{fit}", sichtbar=True)
    app["score"] = fit
    app["fit_geschaetzt"] = "mittel"
    vorher = dashboard.dashboard_applications([app])
    assert vorher == [app]
    assert dashboard._to_data(app)["fit"] == fit


def test_freigabe_hebt_die_pendelgrenze_nicht_auf(folder):
    """Ein zu weiter Weg bleibt auch mit Freigabe ein Ausschlusskriterium."""
    assert dashboard.dashboard_applications([_app("Acme", pendelzeit=97, sichtbar=True)]) == []


def test_freigabe_wirkt_nur_bei_status_research(folder):
    """``docs`` ohne Unterlagen bleibt unsichtbar — dort gilt Regel 3."""
    assert dashboard.dashboard_applications(
        [_app("Acme", status="docs", sichtbar=True)]) == []


def test_freigabe_false_bleibt_verborgen(folder):
    assert dashboard.dashboard_applications([_app("Acme", sichtbar=False)]) == []


def test_freigabe_ist_kein_freifahrtschein_fuer_neu(folder):
    """Alt-Status ``neu`` ist ``research`` — ohne Flag bleibt er unsichtbar."""
    assert dashboard.dashboard_applications([_app("Acme", status="neu")]) == []


def test_beworbene_stelle_bleibt_ohne_freigabe_sichtbar(folder):
    assert dashboard.dashboard_applications([_app("Acme", status="sent", pendelzeit=99)]) != []


def test_freigabe_ueberlebt_die_datenbank(tmp_path):
    """``research_sichtbar`` ist ein Nutzerfeld und wird nicht zum Provider-Anteil."""
    from bewerbungsagent.db import Store

    store = Store(tmp_path / "jobs.db")
    app = _app("Acme", sichtbar=True)
    app["beschreibung"] = "x" * 300
    store.save_state({"applications": [app], "updated": "2026-10-23T10:00:00+02:00"})
    geladen = store.load_state()["applications"][0]
    assert geladen.get("research_sichtbar") is True
    assert dashboard.dashboard_applications([geladen]) == [geladen]
