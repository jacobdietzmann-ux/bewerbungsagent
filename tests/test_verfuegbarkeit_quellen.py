"""Tests für ADR-054: vermisste Stellen, Quellenmeldungen und Workday-Host.

Hintergrund: Am 07.11.2026 fehlten 22 von 60 offenen Einträgen im Suchlauf, ohne
dass der Bestand davon wusste. Ausfälle einzelner Boards standen nur dann im
Digest, wenn der Bestand schrumpfte, und NXP meldete bloß ``JSONDecodeError``.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import requests

import agent
from bewerbungsagent import pipeline
from bewerbungsagent.auswahl import shortlist, tage_vermisst, vermutlich_abgelaufen
from bewerbungsagent.config import Config
from bewerbungsagent.dashboard import _to_data, build_dashboard
from bewerbungsagent.db import Store
from bewerbungsagent.pipeline import _merge_state, abgelaufen_kwargs, dashboard_kwargs
from bewerbungsagent.provider_health import (
    ABGESCHALTET,
    AUSFALL,
    aenderungen_seit,
    empty_entry,
    letzter_abruf,
    record,
    stoerungen,
)
from bewerbungsagent.search import ats

_QUELLE = Path(__file__).resolve().parent.parent / "scripts" / "jobwatch.py"
_spec = importlib.util.spec_from_file_location("jobwatch_quellen", _QUELLE)
jobwatch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(jobwatch)  # type: ignore[union-attr]

TAG_0 = "2026-11-01T07:00:00+01:00"
TAG_6 = "2026-11-07T07:30:00+01:00"
TAG_7 = "2026-11-08T07:30:00+01:00"


def _stelle(key: str = "https://example.test/1", **extra) -> dict:
    return {"key": key, "firma": "Muster GmbH", "titel": "Testingenieur", "ort": "München",
            "url": key, "quelle": "XING", "status": "research", **extra}


def _erfolg(zeitpunkt: str) -> dict:
    return {**empty_entry(), "letzter_erfolg": zeitpunkt}


def _quellen(zeitpunkt: str = TAG_7, **boards) -> dict:
    return {"provider": {"xing": _erfolg(zeitpunkt), "ats": _erfolg(zeitpunkt)},
            "boards": boards}


def _config(tmp_path: Path, tmp_config: dict, **search) -> Config:
    tmp_config["search"].update(search)
    pfad = tmp_path / "config.json"
    pfad.write_text(json.dumps(tmp_config), encoding="utf-8")
    return Config(pfad)


class TestMergeState:
    def test_neue_stelle_traegt_den_zeitpunkt_der_suche(self):
        state = _merge_state({"applications": []},
                             [{**_stelle(), "score": 80, "zuletzt_gesehen": TAG_0}])
        assert state["applications"][0]["zuletzt_gesehen"] == TAG_0

    def test_ohne_stempel_der_suche_gilt_jetzt(self):
        state = _merge_state({"applications": []}, [{**_stelle(), "score": 80}])
        assert state["applications"][0]["zuletzt_gesehen"]

    def test_gefundene_stelle_rueckt_vor(self):
        bestand = {"applications": [_stelle(zuletzt_gesehen=TAG_0)]}
        state = _merge_state(bestand, [{**_stelle(), "score": 80, "zuletzt_gesehen": TAG_7}])
        assert state["applications"][0]["zuletzt_gesehen"] == TAG_7

    def test_fehlende_stelle_bleibt_mit_altem_zeitpunkt(self):
        bestand = {"applications": [_stelle(zuletzt_gesehen=TAG_0)]}
        state = _merge_state(bestand, [])
        assert len(state["applications"]) == 1
        app = state["applications"][0]
        assert app["zuletzt_gesehen"] == TAG_0
        assert not app.get("deleted")

    def test_match_ohne_neue_suche_frischt_nichts_auf(self):
        """``agent.py match`` läuft auf demselben ``jobs.json`` wie der Suchlauf."""
        bestand = {"applications": [_stelle(zuletzt_gesehen=TAG_0)]}
        state = _merge_state(bestand, [{**_stelle(), "score": 80, "zuletzt_gesehen": TAG_0}])
        assert state["applications"][0]["zuletzt_gesehen"] == TAG_0

    def test_versendete_stelle_bleibt_eingefroren(self):
        """ADR-039: Status und Bewertung bleiben, nur der Zeitpunkt rückt vor."""
        bestand = {"applications": [_stelle(status="sent", score=88, zuletzt_gesehen=TAG_0)]}
        state = _merge_state(bestand, [{**_stelle(), "score": 40, "zuletzt_gesehen": TAG_7}])
        app = state["applications"][0]
        assert (app["status"], app["score"]) == ("sent", 88)
        assert app["zuletzt_gesehen"] == TAG_7

    def test_dublette_einer_anderen_boerse_zaehlt_als_gesehen(self):
        """Sonst gälte der Eintrag als vermisst, obwohl die Stelle gefunden wurde."""
        bestand = {"applications": [_stelle("https://a.test/1", zuletzt_gesehen=TAG_0)]}
        treffer = {**_stelle("https://b.test/2"), "score": 80, "zuletzt_gesehen": TAG_7}
        state = _merge_state(bestand, [treffer])
        assert len(state["applications"]) == 1
        assert state["applications"][0]["key"] == "https://a.test/1"
        assert state["applications"][0]["zuletzt_gesehen"] == TAG_7

    def test_beworbene_rolle_an_anderem_ort_zaehlt_als_gesehen(self):
        bestand = {"applications": [_stelle(status="sent", zuletzt_gesehen=TAG_0)]}
        treffer = {**_stelle("https://b.test/2", ort="Dachau"), "score": 80,
                   "zuletzt_gesehen": TAG_7}
        state = _merge_state(bestand, [treffer])
        assert len(state["applications"]) == 1
        assert state["applications"][0]["zuletzt_gesehen"] == TAG_7

    def test_offener_altbestand_beginnt_mit_diesem_lauf(self):
        """Ohne Feld ist unbekannt, seit wann die Stelle fehlt: kein Alarm am ersten Tag."""
        bestand = {"applications": [_stelle(created="2026-09-01T10:00:00+02:00")]}
        app = _merge_state(bestand, [])["applications"][0]
        assert app["zuletzt_gesehen"] > "2026-09-02"
        assert not vermutlich_abgelaufen(app, _quellen(app["zuletzt_gesehen"]))

    @pytest.mark.parametrize("extra", [{"status": "sent"}, {"status": "rejected"},
                                       {"deleted": True}])
    def test_abgeschlossener_altbestand_bleibt_ohne_feld(self, extra):
        bestand = {"applications": [_stelle(**extra)]}
        assert "zuletzt_gesehen" not in _merge_state(bestand, [])["applications"][0]


class TestVermutlichAbgelaufen:
    def test_ab_der_frist_gilt_die_stelle_als_vermutlich_abgelaufen(self):
        app = _stelle(zuletzt_gesehen=TAG_0)
        assert tage_vermisst(app, _quellen(TAG_7)) == 7
        assert vermutlich_abgelaufen(app, _quellen(TAG_7), 7)

    def test_vor_der_frist_nicht(self):
        assert not vermutlich_abgelaufen(_stelle(zuletzt_gesehen=TAG_0), _quellen(TAG_6), 7)

    def test_frist_ist_einstellbar(self):
        app = _stelle(zuletzt_gesehen=TAG_0)
        assert vermutlich_abgelaufen(app, _quellen(TAG_6), 6)
        assert not vermutlich_abgelaufen(app, _quellen(TAG_7), 8)

    def test_null_schaltet_die_pruefung_ab(self):
        assert not vermutlich_abgelaufen(_stelle(zuletzt_gesehen=TAG_0), _quellen(TAG_7), 0)

    def test_erneuter_fund_hebt_die_vermutung_auf(self):
        assert not vermutlich_abgelaufen(_stelle(zuletzt_gesehen=TAG_7), _quellen(TAG_7), 7)

    @pytest.mark.parametrize("extra", [
        {"status": "sent"}, {"status": "followup"}, {"status": "interview"},
        {"status": "rejected"}, {"status": "beworben"}, {"deleted": True},
        {"verfuegbar": False},
    ])
    def test_nur_offene_stellen(self, extra):
        assert not vermutlich_abgelaufen(_stelle(zuletzt_gesehen=TAG_0, **extra), _quellen(), 7)

    def test_unbekannter_zeitpunkt_ist_keine_aussage(self):
        assert tage_vermisst(_stelle(), _quellen()) is None
        assert not vermutlich_abgelaufen(_stelle(), _quellen(), 7)
        assert not vermutlich_abgelaufen(_stelle(zuletzt_gesehen=TAG_0), None, 7)

    def test_ausgefallenes_board_macht_keine_stelle_verdaechtig(self):
        """NXP antwortet nicht: Über dessen Anzeigen sagt das Fehlen nichts."""
        app = _stelle(quelle="ATS", firma="NXP", zuletzt_gesehen=TAG_0)
        quellen = _quellen(TAG_7, NXP=_erfolg(TAG_0), Airbus=_erfolg(TAG_7))
        assert not vermutlich_abgelaufen(app, quellen, 7)
        anderes = _stelle(quelle="ATS", firma="Airbus", zuletzt_gesehen=TAG_0)
        assert vermutlich_abgelaufen(anderes, quellen, 7)

    def test_abgeschaltete_quelle_macht_keine_stelle_verdaechtig(self):
        quellen = {"provider": {"xing": {**_erfolg(TAG_0), "deaktiviert": True},
                                "ats": _erfolg(TAG_7)}, "boards": {}}
        assert not vermutlich_abgelaufen(_stelle(zuletzt_gesehen=TAG_0), quellen, 7)

    def test_pause_des_tageslaufs_macht_keine_stelle_verdaechtig(self):
        """Der Maßstab ist der letzte Lauf der Quelle, nicht das heutige Datum."""
        assert not vermutlich_abgelaufen(_stelle(zuletzt_gesehen=TAG_0), _quellen(TAG_0), 7)

    def test_stepstone_nutzt_den_erfolgreichen_der_beiden_provider(self):
        health = {"stepstone": _erfolg(TAG_0), "stepstone_browser": _erfolg(TAG_7)}
        assert letzter_abruf({"quelle": "StepStone"}, health) == TAG_7

    def test_import_ohne_eigene_historie_nutzt_den_letzten_lauf(self):
        assert letzter_abruf({"quelle": "Import"}, {"xing": _erfolg(TAG_7)}) == TAG_7

    def test_board_ohne_historie_faellt_auf_den_provider_zurueck(self):
        health = {"ats": _erfolg(TAG_7)}
        assert letzter_abruf({"quelle": "ATS", "firma": "Neu"}, health, {}) == TAG_7


class TestAnzeige:
    def test_einstellung_aus_der_config(self, tmp_path, tmp_config):
        config = _config(tmp_path, tmp_config, abgelaufen_nach_tagen=14)
        assert abgelaufen_kwargs(config)["abgelaufen_tage"] == 14

    def test_null_in_der_config_bleibt_null(self, tmp_path, tmp_config):
        config = _config(tmp_path, tmp_config, abgelaufen_nach_tagen=0)
        assert abgelaufen_kwargs(config)["abgelaufen_tage"] == 0

    def test_standard_ist_eine_woche(self, tmp_path, tmp_config):
        assert abgelaufen_kwargs(_config(tmp_path, tmp_config))["abgelaufen_tage"] == 7

    def test_dashboard_zeile(self):
        zeile = _to_data(_stelle(zuletzt_gesehen=TAG_0), quellen=_quellen(), abgelaufen_tage=7)
        assert zeile["vermutlichAbgelaufen"] is True
        assert zeile["zuletztGesehen"] == "01.11.2026"
        assert _to_data(_stelle())["vermutlichAbgelaufen"] is False

    def test_dashboard_zeigt_die_markierung(self, tmp_path):
        apps = [_stelle(zuletzt_gesehen=TAG_0, score=80)]
        pfad = build_dashboard({"applications": apps}, tmp_path / "d.html",
                               quellen=_quellen(), abgelaufen_tage=7)
        html = pfad.read_text(encoding="utf-8")
        assert '"vermutlichAbgelaufen": true' in html or '"vermutlichAbgelaufen":true' in html
        assert '<span class="badge badge-vermisst"' in html

    def test_dashboard_liest_die_historie_aus_der_datenbank(self, tmp_path, tmp_config):
        config = _config(tmp_path, tmp_config, abgelaufen_nach_tagen=3)
        store = Store(config.db_path())
        store.set_meta("provider_health", {"xing": _erfolg(TAG_7)})
        store.set_meta("board_health", {"NXP": _erfolg(TAG_0)})
        kwargs = dashboard_kwargs(config)
        assert kwargs["quellen"]["provider"]["xing"]["letzter_erfolg"] == TAG_7
        assert kwargs["quellen"]["boards"]["NXP"]["letzter_erfolg"] == TAG_0
        assert kwargs["abgelaufen_tage"] == 3

    def test_shortlist_behaelt_die_stelle_und_markiert_sie(self):
        apps = [_stelle(status="docs", dokumente={"x": "a.pdf"}, score=90,
                        zuletzt_gesehen=TAG_0)]
        liste = shortlist(apps, quellen=_quellen(), abgelaufen_tage=7)
        assert [s["vermutlich_abgelaufen"] for s in liste] == [True]
        assert shortlist(apps)[0]["vermutlich_abgelaufen"] is False

    def test_shortlist_im_cli(self, tmp_path, tmp_config, capsys):
        config = _config(tmp_path, tmp_config)
        store = Store(config.db_path())
        store.save_state({"applications": [
            _stelle(status="docs", dokumente={"x": "a.pdf"}, score=90, zuletzt_gesehen=TAG_0)]})
        store.set_meta("provider_health", {"xing": _erfolg(TAG_7)})
        assert agent.main(["--config", str(tmp_path / "config.json"), "shortlist"]) == 0
        assert "vermutlich abgelaufen" in capsys.readouterr().out


def _html(url: str, status: int = 200) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r.url = url
    r.encoding = "utf-8"
    r._content = (b"<!DOCTYPE html><html><head><title>Workday is currently unavailable."
                  b"</title></head><body>x</body></html>")
    return r


def _json_antwort(payload: dict, status: int = 200, url: str = "") -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r.url = url
    r.encoding = "utf-8"
    r._content = json.dumps(payload).encode("utf-8")
    return r


WARTUNG = "https://community.workday.com/maintenance-page"


class TestWorkdayHost:
    @pytest.mark.parametrize("host,erwartet", [
        (None, "nxp.wd3.myworkdayjobs.com"),
        ("", "nxp.wd3.myworkdayjobs.com"),
        ("wd5", "nxp.wd5.myworkdayjobs.com"),
        (" wd12 ", "nxp.wd12.myworkdayjobs.com"),
        ("nxp.wd1.myworkdayjobs.com", "nxp.wd1.myworkdayjobs.com"),
        ("https://nxp.wd1.myworkdayjobs.com/careers", "nxp.wd1.myworkdayjobs.com"),
    ])
    def test_hostname(self, host, erwartet):
        assert ats._workday_host("nxp", host) == erwartet

    def test_host_bestimmt_abruf_und_stellen_url(self, monkeypatch):
        aufrufe: list[str] = []

        def post(url, **_k):
            aufrufe.append(url)
            return _json_antwort({"total": 1, "jobPostings": [
                {"title": "Testingenieur", "locationsText": "Munich",
                 "externalPath": "/job/Munich/Test_1"}]})

        monkeypatch.setattr(ats.requests, "post", post)
        jobs = ats.workday("nxp", "careers", "NXP", host="wd5")
        assert aufrufe == ["https://nxp.wd5.myworkdayjobs.com/wday/cxs/nxp/careers/jobs"]
        assert jobs[0]["url"] == ("https://nxp.wd5.myworkdayjobs.com/en-US/careers"
                                  "/job/Munich/Test_1")

    def test_detailtext_kommt_vom_selben_host(self, monkeypatch):
        monkeypatch.setattr(ats.requests, "post", lambda *_a, **_k: _json_antwort({
            "total": 1, "jobPostings": [{"title": "Testingenieur", "locationsText": "München",
                                         "externalPath": "/job/M/T_1"}]}))
        abrufe: list[str] = []

        def get(url, **_k):
            abrufe.append(url)
            return _json_antwort({"jobPostingInfo": {"jobDescription": "x" * 300}})

        monkeypatch.setattr(ats.requests, "get", get)
        ats.workday("nxp", "careers", "NXP", host="wd5", with_description=True)
        assert abrufe == ["https://nxp.wd5.myworkdayjobs.com/wday/cxs/nxp/careers/job/M/T_1"]

    def test_board_eintrag_reicht_den_host_durch(self, monkeypatch):
        erhalten: dict = {}

        def workday(*_a, **k):
            erhalten.update(k)
            return []

        monkeypatch.setattr(ats, "workday", workday)
        ats.search([{"firma": "NXP", "ats": "workday", "tenant": "nxp", "site": "careers",
                     "host": "wd5"}])
        assert erhalten["host"] == "wd5"


class TestHtmlStattJson:
    def _board(self) -> dict:
        return {"firma": "NXP", "ats": "workday", "tenant": "nxp", "site": "careers"}

    def test_wartungsseite_wird_verstaendlich_gemeldet(self, monkeypatch):
        monkeypatch.setattr(ats.requests, "post", lambda *_a, **_k: _html(WARTUNG))
        jobs, fehler = ats.search([self._board()])
        assert jobs == []
        assert len(fehler) == 1
        assert "JSONDecodeError" not in fehler[0]
        assert "HTML-Seite statt JSON" in fehler[0]
        assert "Workday is currently unavailable." in fehler[0]
        assert "community.workday.com" in fehler[0]

    def test_defektes_board_stoppt_die_anderen_nicht(self, monkeypatch):
        monkeypatch.setattr(ats.requests, "post", lambda *_a, **_k: _html(WARTUNG))
        monkeypatch.setattr(ats.requests, "get", lambda *_a, **_k: _json_antwort({"jobs": [
            {"title": "Testingenieur", "location": {"name": "München"},
             "absolute_url": "https://x.test/1", "content": "a" * 300}]}))
        jobs, fehler = ats.search([self._board(),
                                   {"firma": "Gut", "ats": "greenhouse", "board": "gut"}])
        assert [j["firma"] for j in jobs] == ["Gut"]
        assert len(fehler) == 1

    def test_gilt_auch_fuer_andere_json_boards(self, monkeypatch):
        monkeypatch.setattr(ats.requests, "get", lambda *_a, **_k: _html("https://x.test/"))
        _jobs, fehler = ats.search([{"firma": "G", "ats": "greenhouse", "board": "g"}])
        assert "HTML-Seite statt JSON" in fehler[0]

    def test_anderer_text_als_html(self, monkeypatch):
        antwort = _html("https://x.test/")
        antwort._content = b"Service Unavailable"
        monkeypatch.setattr(ats.requests, "get", lambda *_a, **_k: antwort)
        _jobs, fehler = ats.search([{"firma": "G", "ats": "lever", "board": "g"}])
        assert "Antwort ist kein JSON" in fehler[0]

    def test_falscher_host_nennt_das_feld(self, monkeypatch):
        """Live geprüft: Airbus antwortet auf wd1 und wd5 mit HTTP 422 als JSON."""
        monkeypatch.setattr(ats.requests, "post", lambda *_a, **_k: _json_antwort(
            {"errorCode": "HTTP_422"}, status=422))
        _jobs, fehler = ats.search([self._board()])
        assert "HTTP 422" in fehler[0]
        assert "host" in fehler[0]

    def test_http_fehler_nennt_den_status(self, monkeypatch):
        monkeypatch.setattr(ats.requests, "get", lambda *_a, **_k: _json_antwort({}, status=503))
        _jobs, fehler = ats.search([{"firma": "G", "ats": "greenhouse", "board": "g"}])
        assert fehler == ["ats (G): HTTP 503"]


class TestBoardStatus:
    def test_statistik_steht_nicht_in_den_fehlern(self, monkeypatch):
        monkeypatch.setattr(ats.requests, "get", lambda *_a, **_k: _json_antwort({"jobs": [
            {"title": "Testingenieur", "location": {"name": "München"},
             "absolute_url": "https://x.test/1", "content": "a" * 300},
            {"title": "Testingenieur 2", "location": {"name": "Hamburg"},
             "absolute_url": "https://x.test/2", "content": "a" * 300}]}))
        status: dict = {}
        _jobs, fehler = ats.search([{"firma": "G", "ats": "greenhouse", "board": "g"}],
                                   status=status)
        assert fehler == []
        assert status == {"G": {"gefunden": 2, "im_umkreis": 1, "fehler": []}}

    def test_fehler_steht_mit_grund_im_status(self, monkeypatch):
        monkeypatch.setattr(ats.requests, "post", lambda *_a, **_k: _html(WARTUNG))
        status: dict = {}
        ats.search([{"firma": "NXP", "ats": "workday", "tenant": "nxp", "site": "careers"}],
                   status=status)
        assert status["NXP"]["gefunden"] == 0
        assert "HTML-Seite" in status["NXP"]["fehler"][0]
        assert not status["NXP"]["fehler"][0].startswith("ats (")

    def test_unvollstaendiger_eintrag_zaehlt_als_fehler_des_boards(self):
        status: dict = {}
        _jobs, fehler = ats.search([{"firma": "NXP", "ats": "workday"}], status=status)
        assert fehler == ["ats (workday:?/?): tenant/site fehlt"]
        assert status["NXP"]["fehler"] == fehler

    def test_zwei_boards_derselben_firma_summieren_sich(self, monkeypatch):
        def get(url, **_k):
            if "kaputt" in url:
                return _json_antwort({}, status=500)
            return _json_antwort({"jobs": [
                {"title": "Testingenieur", "location": {"name": "München"},
                 "absolute_url": "https://x.test/1", "content": "a" * 300}]})

        monkeypatch.setattr(ats.requests, "get", get)
        status: dict = {}
        ats.search([{"firma": "G", "ats": "greenhouse", "board": "kaputt"},
                    {"firma": "G", "ats": "greenhouse", "board": "gut"}], status=status)
        assert status["G"]["gefunden"] == 1
        assert status["G"]["fehler"] == ["HTTP 500"]

    def test_boards_werden_nie_abgeschaltet(self):
        historie: dict = {}
        fehler = {"NXP": {"gefunden": 0, "fehler": ["HTML-Seite statt JSON"]}}
        for tag in range(10):
            historie = record(historie, fehler, now=f"2026-11-{tag + 1:02d}T07:00:00",
                              max_failures=None)
        assert historie["NXP"]["serie_fehler"] == 10
        assert historie["NXP"]["deaktiviert"] is False


class TestSuchlaufBisDatenbank:
    def _config(self, tmp_path, tmp_config) -> Config:
        return _config(tmp_path, tmp_config, enabled=True, providers=["ats"], triage=False,
                       ats_only_near_munich=False, ats_boards=[
                           {"firma": "NXP", "ats": "workday", "tenant": "nxp", "site": "c"},
                           {"firma": "Gut", "ats": "greenhouse", "board": "gut"}])

    def _netz(self, monkeypatch) -> None:
        monkeypatch.setattr(pipeline, "enrich_commute", lambda *_a, **_k: {})
        monkeypatch.setattr(ats.requests, "post", lambda *_a, **_k: _html(WARTUNG))
        monkeypatch.setattr(ats.requests, "get", lambda *_a, **_k: _json_antwort({"jobs": [
            {"title": "Testingenieur", "location": {"name": "München"},
             "absolute_url": "https://x.test/1", "content": "Testautomatisierung " * 30}]}))

    def test_stempel_und_historie_landen_in_der_datenbank(self, monkeypatch, tmp_path,
                                                          tmp_config, demo_profile):
        config = self._config(tmp_path, tmp_config)
        self._netz(monkeypatch)
        ergebnis = pipeline.run_search(config, demo_profile, definition={})
        assert ergebnis["errors"][0].startswith("ats (NXP): HTML-Seite statt JSON")
        assert not any("gefunden" in e for e in ergebnis["errors"])
        assert ergebnis["provider_stats"]["ats"]["hinweise"] == [
            "ats (Gut): 1 gefunden, 1 im Umkreis"]
        pipeline.run_match(config, demo_profile)

        store = Store(config.db_path())
        apps = store.load_state()["applications"]
        assert apps and all(a.get("zuletzt_gesehen") for a in apps)
        historie = store.get_meta("board_health")
        assert historie["NXP"]["serie_fehler"] == 1
        assert "HTML-Seite" in historie["NXP"]["letzter_fehler_text"]
        assert historie["Gut"]["letzter_erfolg"]
        assert list(stoerungen(store.get_meta("provider_health"), historie)) == ["ATS-Board NXP"]

    def test_tageslauf_fuehrt_die_historie_ebenso(self, monkeypatch, tmp_path, tmp_config,
                                                  demo_profile):
        config = self._config(tmp_path, tmp_config)
        self._netz(monkeypatch)
        pipeline.run_searches(config, demo_profile)
        assert Store(config.db_path()).get_meta("board_health")["NXP"]["serie_fehler"] == 1
        jobs = json.loads(config.jobs_path().read_text(encoding="utf-8"))
        assert jobs and all(j.get("zuletzt_gesehen") for j in jobs)


class TestStoerungen:
    def test_ausfall_und_abschaltung(self):
        health = {
            "xing": {**empty_entry(), "serie_fehler": 1, "letzter_fehler_text": "Timeout"},
            "indeed": {**empty_entry(), "serie_fehler": 3, "deaktiviert": True},
            "labo": empty_entry(),
        }
        boards = {"NXP": {**empty_entry(), "serie_fehler": 2, "letzter_fehler_text": "HTML"},
                  "Airbus": empty_entry()}
        assert stoerungen(health, boards) == {
            "xing": {"zustand": AUSFALL, "grund": "Timeout"},
            "indeed": {"zustand": ABGESCHALTET, "grund": None},
            "ATS-Board NXP": {"zustand": AUSFALL, "grund": "HTML"},
        }

    def test_teilausfall_ist_keine_stoerung(self):
        """2 von 28 Begriffen scheitern, die Quelle liefert aber weiter."""
        health = record({}, {"stepstone": {"gefunden": 5, "fehler": ["ReadTimeout"]}},
                        now=TAG_0)
        assert stoerungen(health) == {}


def _aus(zustand: str = AUSFALL, grund: str | None = "kaputt") -> dict:
    return {"zustand": zustand, "grund": grund}


class TestAenderungen:
    def test_neuer_ausfall(self):
        stand, neu = aenderungen_seit({}, {"NXP": _aus()})
        assert stand == {"NXP": AUSFALL}
        assert neu == {"neu": [("NXP", "kaputt")], "abgeschaltet": [], "wieder_da": []}

    def test_bekannter_ausfall_ist_keine_aenderung(self):
        stand, neu = aenderungen_seit({"NXP": AUSFALL}, {"NXP": _aus()})
        assert stand == {"NXP": AUSFALL}
        assert neu == {"neu": [], "abgeschaltet": [], "wieder_da": []}

    def test_anderer_fehlertext_ist_keine_aenderung(self):
        _stand, neu = aenderungen_seit({"NXP": AUSFALL}, {"NXP": _aus(grund="HTTP 503")})
        assert neu["neu"] == []

    def test_abschaltung_nach_ausfall_ist_eine_aenderung(self):
        stand, neu = aenderungen_seit({"xing": AUSFALL}, {"xing": _aus(ABGESCHALTET)})
        assert stand == {"xing": ABGESCHALTET}
        assert neu["abgeschaltet"] == [("xing", "kaputt")]

    def test_wieder_da(self):
        stand, neu = aenderungen_seit({"NXP": AUSFALL, "xing": ABGESCHALTET}, {})
        assert stand == {}
        assert neu["wieder_da"] == ["NXP", "xing"]

    def test_probe_einer_abgeschalteten_quelle_bleibt_still(self):
        """``release_due`` gibt die Quelle frei, ein Teillauf prüft sie aber nicht."""
        stand, neu = aenderungen_seit({"xing": ABGESCHALTET}, {"xing": _aus()})
        assert stand == {"xing": ABGESCHALTET}
        assert neu == {"neu": [], "abgeschaltet": [], "wieder_da": []}
        stand, neu = aenderungen_seit(stand, {"xing": _aus(ABGESCHALTET)})
        assert neu["abgeschaltet"] == []


class TestDigestZeilen:
    def test_aufbau(self):
        zeilen = jobwatch.quellen_zeilen({"neu": [("ATS-Board NXP", "HTML-Seite")],
                                          "abgeschaltet": [("xing", None)],
                                          "wieder_da": ["Diehl", "labo"]})
        assert zeilen == ["⚠️ Neu ausgefallen: ATS-Board NXP (HTML-Seite)",
                          "⛔ Abgeschaltet: xing", "✅ Wieder da: Diehl, labo"]

    def test_keine_aenderung_keine_zeile(self):
        assert jobwatch.quellen_zeilen({"neu": [], "abgeschaltet": [], "wieder_da": []}) == []

    def test_viele_ausfaelle_bleiben_kurz(self):
        ausfaelle = [(f"Board {i}", "x" * 500) for i in range(20)]
        zeilen = jobwatch.quellen_zeilen({"neu": ausfaelle})
        assert len(zeilen) == jobwatch.MAX_QUELLEN + 1
        assert zeilen[-1] == "… und 12 weitere."
        assert all(len(z) < 220 for z in zeilen)

    def test_quellen_stehen_getrennt_von_den_kennzahlen(self):
        text = jobwatch.build_digest([], [], False, 60, 5,
                                     quellen=["⚠️ Neu ausgefallen: ATS-Board NXP"])
        block = text.split("\n\n")
        assert block[0].startswith("Bewerbungs-Watch")
        assert block[1] == "Quellen:\n⚠️ Neu ausgefallen: ATS-Board NXP"


JOB = {"firma": "Muster GmbH", "titel": "Testingenieur", "url": "https://example.test/1",
       "score": 80}


class _Watch:
    """Führt ``jobwatch.main`` wiederholt gegen eine eigene Datenbank aus."""

    def __init__(self, tmp_path: Path, tmp_config: dict, monkeypatch):
        (tmp_path / "config.json").write_text(json.dumps(tmp_config), encoding="utf-8")
        self.store = Store(Config(tmp_path / "config.json").db_path())
        self.gesendet: list[str] = []
        self.zustellung = True
        self.snapshot = tmp_path / "snapshot.json"
        monkeypatch.setattr(jobwatch, "AGENT_DIR", tmp_path)
        monkeypatch.setattr(jobwatch, "SNAPSHOT", self.snapshot)
        monkeypatch.setattr(jobwatch, "RUN_LOG", tmp_path / "runs.json")
        monkeypatch.setattr(jobwatch, "load_jobs", lambda: [JOB])
        monkeypatch.setattr(jobwatch, "send_telegram", self._senden)

    def _senden(self, text: str) -> bool:
        self.gesendet.append(text)
        return self.zustellung

    def lauf(self, *argumente: str) -> list[str]:
        """Ein Lauf ohne Suche; liefert die Nachrichten dieses Laufs."""
        vorher = len(self.gesendet)
        assert jobwatch.main(["--no-search", *argumente]) == 0
        return self.gesendet[vorher:]

    def board_ausfall(self, name: str = "NXP") -> None:
        self.store.set_meta("board_health", {name: {
            **empty_entry(), "serie_fehler": 1, "letzter_fehler_text": "HTML-Seite statt JSON"}})

    def board_wieder_da(self, name: str = "NXP") -> None:
        self.store.set_meta("board_health", {name: empty_entry()})


@pytest.fixture
def watch(tmp_path, tmp_config, monkeypatch) -> _Watch:
    return _Watch(tmp_path, tmp_config, monkeypatch)


class TestDigestEinmalJeAenderung:
    def test_ausfall_wird_genau_einmal_gemeldet(self, watch):
        watch.lauf()                                    # Baseline
        watch.board_ausfall()
        erster = watch.lauf()
        assert len(erster) == 1
        assert "Neu ausgefallen: ATS-Board NXP (HTML-Seite statt JSON)" in erster[0]
        assert watch.lauf() == []
        assert watch.lauf() == []

    def test_meldung_ohne_neue_stellen_und_ohne_schrumpfenden_bestand(self, watch):
        """Vorher erschienen Ausfälle nur, wenn der Bestand kleiner wurde."""
        watch.lauf()
        watch.board_ausfall()
        nachricht = watch.lauf()[0]
        assert "Bestand gefallen" not in nachricht
        assert "NEU in diesem Lauf: 0" in nachricht

    def test_erholung_wird_einmal_gemeldet(self, watch):
        watch.lauf()
        watch.board_ausfall()
        watch.lauf()
        watch.board_wieder_da()
        nachricht = watch.lauf()
        assert len(nachricht) == 1
        assert "Wieder da: ATS-Board NXP" in nachricht[0]
        assert watch.lauf() == []

    def test_erneuter_ausfall_ist_eine_neue_aenderung(self, watch):
        watch.lauf()
        watch.board_ausfall()
        watch.lauf()
        watch.board_wieder_da()
        watch.lauf()
        watch.board_ausfall()
        assert "Neu ausgefallen" in watch.lauf()[0]

    def test_abschaltung_des_providers_wird_gemeldet(self, watch):
        watch.lauf()
        watch.store.set_meta("provider_health", {"xing": {
            **empty_entry(), "serie_fehler": 3, "deaktiviert": True,
            "letzter_fehler_text": "Playwright fehlt"}})
        assert "Abgeschaltet: xing (Playwright fehlt)" in watch.lauf()[0]
        assert watch.lauf() == []

    def test_fehlgeschlagener_versand_wird_nachgeholt(self, watch):
        watch.lauf()
        watch.board_ausfall()
        watch.zustellung = False
        assert len(watch.lauf()) == 1
        watch.zustellung = True
        assert "Neu ausgefallen" in watch.lauf()[0]
        assert watch.lauf() == []

    def test_probelauf_verbraucht_die_meldung_nicht(self, watch, capsys):
        watch.lauf()
        watch.board_ausfall()
        assert watch.lauf("--dry-run") == []
        assert "Neu ausgefallen" in capsys.readouterr().out
        assert "Neu ausgefallen" in watch.lauf()[0]

    def test_unlesbare_historie_meldet_keine_erholung(self, watch, monkeypatch):
        watch.lauf()
        watch.board_ausfall()
        watch.lauf()

        def kaputt(*_a, **_k):
            raise OSError("Datenbank gesperrt")

        monkeypatch.setattr(Store, "get_meta", kaputt)
        assert watch.lauf() == []
        gespeichert = json.loads(watch.snapshot.read_text(encoding="utf-8"))
        assert gespeichert["gemeldete_quellen"] == {"ATS-Board NXP": AUSFALL}

    def test_erster_lauf_meldet_bestehende_ausfaelle(self, watch):
        watch.board_ausfall()
        nachricht = watch.lauf()
        assert len(nachricht) == 1
        assert "Baseline" in nachricht[0]
        assert "Neu ausgefallen: ATS-Board NXP" in nachricht[0]
