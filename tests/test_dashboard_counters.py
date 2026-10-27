"""Die Zahlen der Dashboard-Zusammenfassung müssen zusammenpassen.

Ausgabe von ``agent.py dashboard``:

    (207 relevante Stellen; 64 ohne Bewerbungsdokumente und 0 mit mehr als
     30 Minuten Pendelzeit ausgeblendet)

Vorher stand dort ``-39``: „ohne Bewerbungsdokumente" verglich **alle**
Einträge (auch die gelöschten) mit den dokumentierten, und „zu weit" rechnete
``documented - applications``. Beides ist falsch, weil ``applications`` auch
Stellen ohne Dokumente enthält (Research-Funde, Neuzugänge des letzten Laufs) —
die Differenz wurde dadurch negativ.

``dashboard.dashboard_applications`` prüft, ob die Dokumente **auf der Platte**
liegen (relativ zu ``AGENT_ROOT``). Die Tests legen daher echte PDF-Dateien an
und biegen ``AGENT_ROOT`` auf das temporäre Verzeichnis um — sonst wäre der
Bestand leer und die Zählung würde nichts beweisen.
"""

from __future__ import annotations

import json
from pathlib import Path

from bewerbungsagent import dashboard
from bewerbungsagent.config import Config
from bewerbungsagent.pipeline import run_dashboard

DOC_REL = "01_Bewerbungen/{firma}/Anschreiben.pdf"


def _app(firma: str, *, pendel=20, dokumente=True, deleted=False,
         status="docs") -> dict:
    return {
        "firma": firma, "titel": "Testingenieur", "status": status,
        "pendelzeit_min": pendel,
        "dokumente": ({"anschreiben_de": DOC_REL.format(firma=firma)}
                      if dokumente else {}),
        "deleted": deleted,
    }


class Umgebung:
    """Temporärer Agent-Ordner mit Bestand, Dokumenten und Dashboard-Ziel."""

    def __init__(self, tmp_path: Path, apps: list[dict], limit: int = 30):
        self.root = tmp_path
        self.agent = tmp_path / "04_Agent"
        self.agent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "00_Dashboard").mkdir(parents=True, exist_ok=True)

        for app in apps:
            for rel in (app.get("dokumente") or {}).values():
                datei = tmp_path / rel
                datei.parent.mkdir(parents=True, exist_ok=True)
                datei.write_bytes(b"%PDF-1.4 Testdokument")

        cfg = {
            "profile_json": str(tmp_path / "profil.json"),
            "data_dir": str(self.agent / "data"),
            "output_dir": str(self.agent / "output"),
            "dashboard_file": str(tmp_path / "00_Dashboard" / "dashboard.html"),
            "bewerbungen_dir": str(tmp_path / "01_Bewerbungen"),
            "db_path": str(self.agent / "data" / "jobs.db"),
            "max_pendelzeit_min": limit,
            "search": {"enabled": False, "providers": [], "location": "München",
                       "query_terms": []},
            "documents": {"languages": ["de"], "accent_color": "#0B3D5C"},
        }
        pfad = self.agent / "config.json"
        pfad.write_text(json.dumps(cfg), encoding="utf-8")
        self.config = Config(str(pfad))
        self.config.data_dir.mkdir(parents=True, exist_ok=True)

        from bewerbungsagent.db import Store

        Store(self.config.db_path()).save_state({"applications": apps})

    def baue(self, monkeypatch) -> dict:
        monkeypatch.setattr(dashboard, "AGENT_ROOT", self.root)
        monkeypatch.setattr(dashboard, "ROOT", self.root)
        return run_dashboard(self.config)


class TestZusammenfassung:
    def test_zahlen_ergeben_den_aktiven_bestand(self, tmp_path, monkeypatch):
        apps = [
            _app("Sichtbar"),
            _app("OhneDok", dokumente=False),
            _app("Fern", pendel=90),
            _app("Beworben", status="sent", pendel=90, dokumente=False),
            _app("Geloescht", deleted=True),
        ]
        res = Umgebung(tmp_path, apps).baue(monkeypatch)
        # ``sent`` ist immer sichtbar (dokumentiert den Vorgang), auch ohne
        # Dokumente und jenseits der Pendelgrenze.
        assert res["applications"] == 2
        assert res["hidden_without_documents"] == 1
        assert res["hidden_too_far"] == 1
        # Die vier aktiven Einträge (ohne den gelöschten) sind vollständig erklärt.
        assert (res["applications"] + res["hidden_without_documents"]
                + res["hidden_too_far"]) == 4

    def test_keine_negativen_zahlen(self, tmp_path, monkeypatch):
        """Regression: ``documented - applications`` wurde negativ."""
        apps = [
            _app("MitDok1"), _app("MitDok2"),
            _app("OhneDok1", dokumente=False), _app("OhneDok2", dokumente=False),
            _app("OhneDok3", dokumente=False),
        ]
        res = Umgebung(tmp_path, apps).baue(monkeypatch)
        for key in ("applications", "hidden_without_documents", "hidden_too_far"):
            assert res[key] >= 0, (key, res)
        assert res["applications"] + res["hidden_without_documents"] == 5

    def test_zu_weite_stelle_wird_als_solche_gezaehlt(self, tmp_path, monkeypatch):
        apps = [_app("Nah", pendel=15), _app("Fern", pendel=90)]
        res = Umgebung(tmp_path, apps).baue(monkeypatch)
        assert res["applications"] == 1
        assert res["hidden_too_far"] == 1
        assert res["hidden_without_documents"] == 0

    def test_beworbene_stelle_bleibt_trotz_pendelweg_sichtbar(self, tmp_path, monkeypatch):
        """Ein Vorgang, der stattgefunden hat, wird nicht nachträglich versteckt."""
        res = Umgebung(tmp_path, [_app("Beworben", status="sent", pendel=90)]).baue(monkeypatch)
        assert res["applications"] == 1
        assert res["hidden_too_far"] == 0

    def test_stelle_ohne_pendelzeit_bleibt_sichtbar(self, tmp_path, monkeypatch):
        app = _app("OhnePendel")
        app["pendelzeit_min"] = None
        res = Umgebung(tmp_path, [app]).baue(monkeypatch)
        assert res["applications"] == 1
        assert res["hidden_too_far"] == 0

    def test_fehlende_datei_gilt_als_ohne_dokument(self, tmp_path, monkeypatch):
        """Ein Pfad in ``dokumente`` ohne Datei ist kein Beleg."""
        umgebung = Umgebung(tmp_path, [_app("DateiFehlt")])
        (tmp_path / DOC_REL.format(firma="DateiFehlt")).unlink()
        res = umgebung.baue(monkeypatch)
        assert res["applications"] == 0
        assert res["hidden_without_documents"] == 1
