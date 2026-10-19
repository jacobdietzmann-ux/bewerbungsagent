"""Tests für das „neu gefunden"-Label im Dashboard.

Der Nutzer soll auf einen Blick sehen, welche Stellen zuletzt gefunden wurden.
Gespeichert wird der ``created``-Stempel des jüngsten Fundes (nicht das Zeitfenster
des letzten Laufs) — sonst würde ein Lauf ohne neue Funde das Label bei allen
Stellen verschwinden lassen, obwohl die Funde die neuesten bleiben.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bewerbungsagent.dashboard import build_dashboard, zuletzt_gefunden

FUND = {"zeitpunkt": "2026-10-15T16:14:00+02:00", "anzahl": 8}


class TestZuletztGefunden:
    def test_gleicher_zeitpunkt(self):
        assert zuletzt_gefunden({"created": FUND["zeitpunkt"]}, FUND) is True

    def test_spaeterer_fund(self):
        """Der Stempel des jüngsten Fundes wandert mit; alles danach ist neu."""
        assert zuletzt_gefunden({"created": "2026-10-16T12:03:00+02:00"}, FUND) is True

    def test_frueherer_fund_ist_nicht_mehr_neu(self):
        assert zuletzt_gefunden({"created": "2026-10-14T10:00:00+02:00"}, FUND) is False

    def test_eine_sekunde_davor_ist_nicht_neu(self):
        assert zuletzt_gefunden({"created": "2026-10-15T16:13:59+02:00"}, FUND) is False

    def test_zeitzonen_werden_verrechnet(self):
        """Gleiche Ortszeit in anderer Zone beschreibt einen anderen Zeitpunkt.

        Ein Textvergleich hielte ``16:14+00:00`` für gleich ``16:14+02:00``,
        obwohl es zwei Stunden später ist.
        """
        assert zuletzt_gefunden({"created": "2026-10-15T16:14:00+00:00"}, FUND) is True
        assert zuletzt_gefunden({"created": "2026-10-15T14:14:00+00:00"}, FUND) is True
        assert zuletzt_gefunden({"created": "2026-10-15T12:14:00+00:00"}, FUND) is False

    @pytest.mark.parametrize("app, fund", [
        ({"created": FUND["zeitpunkt"]}, None),
        ({"created": FUND["zeitpunkt"]}, {}),
        ({"created": None}, FUND),
        ({}, FUND),
        ({"created": "kaputt"}, FUND),
        ({"created": FUND["zeitpunkt"]}, {"anzahl": 3}),
    ])
    def test_fehlende_angaben_ergeben_kein_label(self, app, fund):
        """Lieber kein Label als ein falsches."""
        assert zuletzt_gefunden(app, fund) is False

    def test_naive_und_bewusste_zone_werden_nicht_gemischt(self):
        assert zuletzt_gefunden({"created": "2026-10-15T16:14:00"}, FUND) is False


class TestDashboardAusgabe:
    @pytest.fixture
    def app(self):
        return {
            "key": "a", "firma": "STARK Defence", "titel": "Flight Test Engineer",
            "created": FUND["zeitpunkt"], "status": "docs", "score": 80,
            "dokumente": {"anschreiben_de": "x/Anschreiben.pdf"},
        }

    def _baue(self, tmp_path: Path, apps, fund):
        ziel = tmp_path / "dashboard.html"
        build_dashboard({"applications": apps}, ziel, letzter_fund=fund)
        return ziel.read_text(encoding="utf-8")

    def _daten(self, html: str) -> list[dict]:
        roh = html.split("const DATA = ", 1)[1].split(";\n", 1)[0]
        return json.loads(roh.replace("<\\/", "</"))

    def test_flag_im_eingebetteten_json(self, tmp_path, app):
        assert self._daten(self._baue(tmp_path, [app], FUND))[0]["neuImLauf"] is True

    def test_ohne_fund_kein_flag(self, tmp_path, app):
        assert self._daten(self._baue(tmp_path, [app], None))[0]["neuImLauf"] is False

    def test_zeitpunkt_steht_lesbar_drin(self, tmp_path, app):
        assert 'const LAST_RUN = "15.10.2026 16:14";' in self._baue(tmp_path, [app], FUND)

    def test_ohne_fund_leerer_text(self, tmp_path, app):
        assert 'const LAST_RUN = "";' in self._baue(tmp_path, [app], None)


class TestNeueFundeSindSichtbar:
    """Das Label nützt nichts, wenn die Zeile ausgeblendet ist.

    Neu gefundene Stellen haben noch keine Unterlagen und wären nach der
    Standardregel („nur dokumentierte Stellen") nie zu sehen.
    """

    def _daten(self, tmp_path: Path, apps, fund) -> list[dict]:
        ziel = tmp_path / "dashboard.html"
        build_dashboard({"applications": apps}, ziel, letzter_fund=fund)
        roh = ziel.read_text(encoding="utf-8").split("const DATA = ", 1)[1].split(";\n", 1)[0]
        return {r["id"]: r for r in json.loads(roh.replace("<\\/", "</"))}

    def test_neuer_fund_ohne_unterlagen_ist_sichtbar(self, tmp_path):
        rows = self._daten(tmp_path, [{
            "key": "neu", "firma": "Saab", "titel": "Systems Engineer",
            "created": FUND["zeitpunkt"], "status": "neu",
        }], FUND)
        assert rows["neu"]["visible"] is True

    def test_alter_fund_ohne_unterlagen_ist_ebenfalls_sichtbar(self, tmp_path):
        """``research`` ist durch den Pipeline-Filter kuratiert und immer sichtbar.

        Früher hing die Sichtbarkeit an Unterlagen bzw. am „neu gefunden"-Label.
        Das führte dazu, dass der Status-Schalter Research-Einträge zählte, die
        in der Tabelle fehlten. Die Kuratierung passiert jetzt in
        ``research_filter`` (Pipeline), nicht in der Anzeige.
        """
        rows = self._daten(tmp_path, [{
            "key": "alt", "firma": "Alt GmbH", "titel": "Testingenieur",
            "created": "2026-10-01T09:00:00+02:00", "status": "neu",
        }], FUND)
        assert rows["alt"]["visible"] is True
        # Das „neu gefunden"-Label bleibt trotzdem korrekt unterscheidend.
        assert rows["alt"]["neuImLauf"] is False

    def test_dokumentierte_stelle_bleibt_sichtbar(self, tmp_path, monkeypatch):
        import bewerbungsagent.dashboard as dash
        monkeypatch.setattr(dash, "AGENT_ROOT", tmp_path)
        ordner = tmp_path / "01_Bewerbungen" / "STARK Defence - Flight Test Engineer"
        ordner.mkdir(parents=True)
        (ordner / "Anschreiben.pdf").write_bytes(b"pdf")
        rows = self._daten(tmp_path, [{
            "key": "dok", "firma": "STARK Defence", "titel": "Flight Test Engineer",
            "created": "2026-10-01T09:00:00+02:00", "status": "docs",
            "dokumente": {"anschreiben_de": str(ordner / "Anschreiben.pdf")},
        }], FUND)
        assert rows["dok"]["visible"] is True


class TestSchalterUndAnzeigetext:
    """Der Research-Schalter fehlte, seit solche Zeilen sichtbar werden können."""

    def _html(self, tmp_path: Path, fund) -> str:
        ziel = tmp_path / "dashboard.html"
        build_dashboard({"applications": []}, ziel, letzter_fund=fund)
        return ziel.read_text(encoding="utf-8")

    def test_research_ist_einblendbar(self, tmp_path):
        assert "const SHOWN_STATUSES = ORDER;" in self._html(tmp_path, FUND)

    def test_anzahl_wird_mitgegeben(self, tmp_path):
        assert "const LAST_FUND_ANZAHL = 8;" in self._html(tmp_path, FUND)

    def test_ohne_fund_null(self, tmp_path):
        assert "const LAST_FUND_ANZAHL = 0;" in self._html(tmp_path, None)
