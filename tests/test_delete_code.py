"""``deleted_code`` ersetzt das Parsen von ``deleted_reason`` (ADR-056).

``run_enrich`` las bisher Textanfänge: Eine umformulierte Begründung hätte die
Neubewertung still geändert, und „Fit <= 60 Prozent (Nutzerkriterium)" beginnt mit
demselben Wort wie die automatische Fit-Ausblendung. Der Text bleibt zur Anzeige,
die Logik hängt nur noch am Code.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from bewerbungsagent import db as D
from bewerbungsagent.config import Config
from bewerbungsagent.db import (
    DELETE_FIT,
    DELETE_KRITERIUM,
    DELETE_NUTZER,
    DELETE_PENDEL,
    DELETE_RESEARCH,
    DELETE_SONSTIG,
    DELETE_STUDENT,
    DELETE_TECHNIKER,
    USER_DELETE_REASON,
    Store,
    delete_code_aus_text,
)
from bewerbungsagent.pipeline import _flag_far_commute, run_enrich


@pytest.fixture
def config(tmp_path) -> Config:
    daten = {"data_dir": str(tmp_path / "data"), "output_dir": str(tmp_path / "output"),
             "profile_json": str(tmp_path / "profil.json"),
             "bewerbungen_dir": str(tmp_path / "bewerbungen"),
             "max_pendelzeit_min": 30}
    pfad = tmp_path / "config.json"
    pfad.write_text(json.dumps(daten), encoding="utf-8")
    return Config(pfad)


@pytest.fixture(autouse=True)
def _ohne_netz(monkeypatch):
    monkeypatch.setattr("bewerbungsagent.pipeline.enrich_commute",
                        lambda apps, data_dir, *a, **k: {"total": len(apps)})
    monkeypatch.setattr("bewerbungsagent.pipeline.enrich_salary",
                        lambda apps: {"kept": 0, "estimated": 0})


def _app(key="k", **felder) -> dict:
    return {"key": key, "firma": "Acme", "titel": "Testingenieur", "ort": "München",
            "status": "research", "score": 30, "dokumente": {}, **felder}


def _enrich(config, *apps) -> dict[str, dict]:
    store = Store(config.db_path())
    store.save_state({"applications": list(apps)})
    run_enrich(config, None)
    return {a["key"]: a for a in store.load_state()["applications"]}


class TestAuslegung:
    @pytest.mark.parametrize(("text_", "code"), [
        (USER_DELETE_REASON, DELETE_NUTZER),
        ("Nutzerkriterium: im Dashboard entfernt", DELETE_NUTZER),
        # Beginnen mit „Fit", sind aber Entscheidungen des Nutzers.
        ("Fit <= 60 Prozent (Nutzerkriterium)", DELETE_KRITERIUM),
        ("Fit unter 60 Prozent (Neubewertung 10.10.2026)", DELETE_KRITERIUM),
        ("", DELETE_KRITERIUM),
        (None, DELETE_KRITERIUM),
        ("FIT < 50 %", DELETE_FIT),
        ("Pendelweg > 30 min", DELETE_PENDEL),
        ("Pendelzeit ueber 30 Minuten", DELETE_PENDEL),
        ("research-kriterium: FIT 55 < 65 %", DELETE_RESEARCH),
        ("Studenten-/Praktikumsstelle (keine Vollzeit-Ingenieurrolle)", DELETE_STUDENT),
        ("Technikerrolle (keine Ingenieursstelle)", DELETE_TECHNIKER),
        ("Duplikat (Firma+Titel bereits vorhanden)", DELETE_SONSTIG),
    ])
    def test_texte(self, text_, code):
        assert delete_code_aus_text(text_) == code


class TestPipelineSetztDenCode:
    """Jede Ausblendung trägt Code und Text, und beide passen zusammen."""

    @pytest.mark.parametrize(("felder", "code"), [
        ({"score": 55}, DELETE_FIT),        # unter 65 %: ein Grund für alles
        ({"score": 30}, DELETE_FIT),
        ({"score": 80, "pendelzeit_min": 90}, DELETE_PENDEL),
        ({"titel": "Werkstudent Test"}, DELETE_STUDENT),
        ({"titel": "Test Technician"}, DELETE_TECHNIKER),
    ])
    def test_run_enrich(self, config, felder, code):
        app = _enrich(config, _app(**felder))["k"]
        assert app["deleted"] is True
        assert app["deleted_code"] == code
        assert delete_code_aus_text(app["deleted_reason"]) == code

    def test_pendelweg_beim_anlegen(self):
        app = _app(pendelzeit_min=90)
        assert _flag_far_commute(app, 30) is True
        assert app["deleted_code"] == DELETE_PENDEL
        assert delete_code_aus_text(app["deleted_reason"]) == DELETE_PENDEL


class TestRunEnrichLiestNurDenCode:
    """Der Text darf nichts mehr entscheiden."""

    def test_fit_code_wird_neu_bewertet_bei_beliebigem_text(self, config):
        app = _enrich(config, _app(score=80, deleted=True, deleted_code=DELETE_FIT,
                                   deleted_reason="beliebiger Text"))["k"]
        assert not app.get("deleted")
        assert "deleted_reason" not in app and "deleted_code" not in app

    def test_fit_text_ohne_fit_code_bleibt_ausgeblendet(self, config):
        app = _enrich(config, _app(score=80, deleted=True, deleted_code=DELETE_SONSTIG,
                                   deleted_reason="FIT < 50 %"))["k"]
        assert app["deleted"] is True

    def test_pendel_code_kommt_zurueck_wenn_die_grenze_passt(self, config):
        app = _enrich(config, _app(score=80, pendelzeit_min=20, deleted=True,
                                   deleted_code=DELETE_PENDEL, deleted_reason="alt"))["k"]
        assert not app.get("deleted")

    def test_nutzerloeschung_bleibt_auch_bei_hohem_fit(self, config):
        app = _enrich(config, _app(score=95, status="sent", deleted=True,
                                   deleted_code=DELETE_NUTZER, deleted_reason="irgendwas"))["k"]
        assert app["deleted"] is True

    @pytest.mark.parametrize("code", [DELETE_KRITERIUM, DELETE_SONSTIG])
    def test_entscheidungen_bleiben(self, config, code):
        app = _enrich(config, _app(score=90, deleted=True, deleted_code=code,
                                   deleted_reason="x"))["k"]
        assert app["deleted"] is True

    def test_nachgesetzter_techniker_zaehlt_nur_einmal(self, config):
        store = Store(config.db_path())
        store.save_state({"applications": [_app(titel="Test Technician")]})
        assert run_enrich(config, None)["deleted_technician"] == 1
        assert run_enrich(config, None)["deleted_technician"] == 0


class TestStore:
    def test_text_ohne_code_bekommt_beim_schreiben_einen(self, config):
        store = Store(config.db_path())
        store.save_state({"applications": [_app(deleted=True, deleted_reason="FIT < 50 %")]})
        assert store.load_state()["applications"][0]["deleted_code"] == DELETE_FIT

    def test_wieder_eingeblendet_verliert_den_code(self, config):
        store = Store(config.db_path())
        store.save_state({"applications": [_app(deleted=True, deleted_reason="FIT < 50 %")]})
        app = store.load_state()["applications"][0]
        app["deleted"] = False
        store.save_state({"applications": [app]})
        assert "deleted_code" not in store.load_state()["applications"][0]

    def test_code_liegt_in_der_nutzerspalte(self, config):
        store = Store(config.db_path())
        store.save_state({"applications": [_app(deleted=True, deleted_reason="FIT < 50 %")]})
        assert store.get_overlay()["k"]["deleted_code"] == DELETE_FIT

    def test_dashboard_loeschung_ersetzt_den_filter_code(self, config):
        """Der Knopf im Dashboard schickt nur den Text, kein Filter darf bleiben."""
        store = Store(config.db_path())
        store.save_state({"applications": [_app(deleted=True, deleted_reason="FIT < 50 %")]})
        store.apply_overlay({"k": {"deleted": True, "deleted_reason": USER_DELETE_REASON}})
        assert store.load_state()["applications"][0]["deleted_code"] == DELETE_NUTZER

    def test_anderes_nutzerfeld_laesst_den_code_stehen(self, config):
        store = Store(config.db_path())
        store.save_state({"applications": [_app(deleted=True, deleted_code=DELETE_KRITERIUM,
                                                deleted_reason="x")]})
        store.apply_overlay({"k": {"notes": "Notiz"}})
        assert store.load_state()["applications"][0]["deleted_code"] == DELETE_KRITERIUM

    def test_lauf_ueberschreibt_die_dashboard_loeschung_nicht(self, config):
        """Löschen, während ein Lauf den alten Stand im Speicher hält."""
        store = Store(config.db_path())
        store.save_state({"applications": [_app()]})
        lauf = store.load_state()
        store.apply_overlay({"k": {"deleted": True, "deleted_reason": USER_DELETE_REASON}})
        store.save_state(lauf)
        app = store.load_state()["applications"][0]
        assert app["deleted"] is True
        assert app["deleted_code"] == DELETE_NUTZER
        assert app["deleted_reason"] == USER_DELETE_REASON


class TestMigration:
    def _altbestand(self, config, *zeilen) -> Store:
        """Bestand wie vor ADR-056: nur ``deleted_reason``, kein Code, kein Meta-Eintrag."""
        store = Store(config.db_path())
        with store.engine.begin() as conn:
            conn.execute(text("DELETE FROM meta WHERE key = :k"), {"k": D._META_DELETE_CODE})
            for key, user in zeilen:
                conn.execute(
                    text("INSERT INTO applications (key, provider, user, updated_at) "
                         "VALUES (:key, :provider, :user, '2026-01-01')"),
                    {"key": key, "provider": json.dumps({"titel": "T"}),
                     "user": json.dumps(user)})
        return store

    def test_fuellt_den_code_nach(self, config):
        self._altbestand(
            config,
            ("nutzer", {"deleted": True, "deleted_reason": USER_DELETE_REASON}),
            ("kriterium", {"deleted": True, "deleted_reason": "Fit <= 60 Prozent (Nutzerkriterium)"}),
            ("fit", {"deleted": True, "deleted_reason": "FIT < 50 %"}),
            ("sichtbar", {"status": "docs"}),
        )
        store = Store(config.db_path())
        apps = {a["key"]: a for a in store.load_state()["applications"]}
        assert apps["nutzer"]["deleted_code"] == DELETE_NUTZER
        assert apps["kriterium"]["deleted_code"] == DELETE_KRITERIUM
        assert apps["fit"]["deleted_code"] == DELETE_FIT
        assert "deleted_code" not in apps["sichtbar"]
        assert apps["fit"]["deleted_reason"] == "FIT < 50 %"

    def test_protokolliert_die_anzahl_und_laeuft_einmal(self, config):
        self._altbestand(config, ("fit", {"deleted": True, "deleted_reason": "FIT < 50 %"}))
        store = Store(config.db_path())
        meta = store.get_meta(D._META_DELETE_CODE)
        assert meta["codes"] == {DELETE_FIT: 1}
        Store(config.db_path())
        assert store.get_meta(D._META_DELETE_CODE) == meta

    def test_ist_idempotent(self, config):
        store = self._altbestand(config, ("a", {"deleted": True,
                                                "deleted_code": DELETE_NUTZER,
                                                "deleted_reason": "FIT < 50 %"}))
        assert store.migrate_delete_codes() == {}
        assert store.load_state()["applications"][0]["deleted_code"] == DELETE_NUTZER

    def test_aendert_nicht_den_zeitstempel(self, config):
        self._altbestand(config, ("fit", {"deleted": True, "deleted_reason": "FIT < 50 %"}))
        store = Store(config.db_path())
        with store.engine.connect() as conn:
            stand = conn.execute(text("SELECT updated_at FROM applications")).scalar_one()
        assert stand == "2026-01-01"

    def test_neue_datenbank_ist_sofort_fertig(self, config):
        store = Store(config.db_path())
        assert store.get_meta(D._META_DELETE_CODE)["codes"] == {}

    def test_altbestand_verhaelt_sich_wie_zuvor(self, config):
        """Vom Altbestand bis zum Lauf: dieselben Entscheidungen wie mit Textpräfixen."""
        self._altbestand(
            config,
            ("wieder", {"deleted": True, "deleted_reason": "FIT < 50 %"}),
            ("bleibt", {"deleted": True, "deleted_reason": "Fit <= 60 Prozent (Nutzerkriterium)"}),
        )
        store = Store(config.db_path())
        with store.engine.begin() as conn:
            conn.execute(text("UPDATE applications SET provider = :p"), {"p": json.dumps(_app(score=80))})
        run_enrich(config, None)
        apps = {a["key"]: a for a in store.load_state()["applications"]}
        assert not apps["wieder"].get("deleted")
        assert apps["bleibt"]["deleted"] is True
