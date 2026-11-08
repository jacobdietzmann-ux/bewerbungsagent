"""Regressionstests aus dem Review vom 07.11.2026 (ADR-053).

Jeder Test hält einen Fehler fest, der im Echtbetrieb aufgetreten oder im Code
nachgewiesen ist: abgebrochene Mehrbegriff-Suchen, überschriebene Unterlagen
bereits versendeter Bewerbungen und als Fehler gezählte Statistikzeilen.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest
import requests

from bewerbungsagent import pipeline
from bewerbungsagent.commute import _Geocoder
from bewerbungsagent.config import Config
from bewerbungsagent.db import Store
from bewerbungsagent.profile import Profile, normalize
from bewerbungsagent.search import arbeitnow, ats, indeed, stepstone_browser, xing
from bewerbungsagent.storage import save_json

_QUELLE = Path(__file__).resolve().parent.parent / "scripts" / "jobwatch.py"
_spec = importlib.util.spec_from_file_location("jobwatch_review", _QUELLE)
jobwatch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(jobwatch)  # type: ignore[union-attr]


class _Seite:
    """Browserseite ohne Browser: merkt sich die aufgerufenen URLs."""

    def __init__(self):
        self.besucht: list[str] = []

    def goto(self, url, **_k):
        self.besucht.append(url)

    def wait_for_timeout(self, _ms):
        return None


@contextlib.contextmanager
def _browser(seite):
    yield seite


def _karten(seite, praefix: str, anzahl: int) -> list[dict]:
    begriff = len(seite.besucht)
    return [{"titel": f"Stelle {begriff}-{i}", "firma": "Acme", "ort": "München",
             "href": f"{praefix}{begriff}-{i}", "jk": f"{begriff}-{i}"}
            for i in range(anzahl)]


class TestBegriffslimit:
    """``max_results`` begrenzte alle Begriffe zusammen, nicht je Begriff."""

    def _vorbereiten(self, monkeypatch, modul, anzahl: int, praefix: str) -> _Seite:
        seite = _Seite()
        monkeypatch.setattr(modul, "browser_page", lambda **_k: _browser(seite))
        monkeypatch.setattr(modul, "dismiss_consent", lambda *_a: True)
        monkeypatch.setattr(modul, "_karten", lambda s: _karten(s, praefix, anzahl))
        return seite

    def test_stepstone_sucht_alle_begriffe(self, monkeypatch):
        seite = self._vorbereiten(monkeypatch, stepstone_browser, 25,
                                  "/stellenangebote--x-")
        monkeypatch.setattr(stepstone_browser, "_mehr_anzeigen", lambda _p: False)
        jobs = stepstone_browser.search(["A", "B", "C"], max_results=10)
        assert len(seite.besucht) == 3
        assert len(jobs) == 75

    def test_xing_sucht_alle_begriffe_mit_ort(self, monkeypatch):
        seite = self._vorbereiten(monkeypatch, xing, 3, "/jobs/x-")
        monkeypatch.setattr(xing, "_mehr_klicken", lambda _p: False)
        jobs = xing.search(["A", "B"], location="Augsburg", max_results=2,
                           with_description=False)
        assert len(seite.besucht) == 2
        assert all("Augsburg" in url for url in seite.besucht)
        assert len(jobs) == 6

    def test_indeed_sucht_alle_begriffe_mit_ort(self, monkeypatch):
        seite = self._vorbereiten(monkeypatch, indeed, 3, "")
        jobs = indeed.search(["A", "B"], location="Augsburg", max_results=2,
                             with_description=False)
        assert len(seite.besucht) == 2
        assert all("Augsburg" in url for url in seite.besucht)
        assert len(jobs) == 4

    def test_xing_laedt_bekannten_text_nicht_erneut(self, monkeypatch):
        self._vorbereiten(monkeypatch, xing, 2, "/jobs/x-")
        monkeypatch.setattr(xing, "_mehr_klicken", lambda _p: False)
        geladen: list[str] = []
        monkeypatch.setattr(xing, "_beschreibung",
                            lambda _p, url: geladen.append(url) or "Text " * 50)
        bekannt = {f"{xing.BASE}/jobs/x-1-0"}
        xing.search(["A"], known_urls=bekannt)
        assert geladen == [f"{xing.BASE}/jobs/x-1-1"]


class _Antwort:
    def __init__(self, payload, status: int = 200):
        self._payload = payload
        self.status_code = status
        self.text = payload if isinstance(payload, str) else ""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class TestArbeitnow:
    def test_volltext_wird_uebernommen_und_begrenzt(self, monkeypatch):
        lang = "<p>" + "Testingenieur " * 5000 + "</p>"
        kurz = "<p>Kurz</p>"
        zeilen = [{"title": "T", "company_name": "A", "location": "München",
                   "url": f"https://example.test/{i}", "description": d}
                  for i, d in enumerate((lang, kurz))]
        monkeypatch.setattr(arbeitnow.requests, "get",
                            lambda *_a, **_k: _Antwort({"data": zeilen}))
        jobs = arbeitnow.search(max_pages=1)
        assert len(jobs[0]["beschreibung"]) == arbeitnow._MAX_DESCRIPTION
        assert "<p>" not in jobs[0]["beschreibung"]
        assert len(jobs[0]["snippet"]) == 400
        assert jobs[1]["beschreibung"] == ""


_WORKDAY_FACETTEN = [{"facetParameter": "locationMainGroup", "values": [
    {"facetParameter": "locationCountry", "descriptor": "Country", "values": [
        {"descriptor": "France", "id": "fr", "count": 900},
        {"descriptor": "Germany", "id": "de", "count": 473},
    ]},
]}]


class TestWorkday:
    def _antwort(self, gesehen: list[dict]):
        def post(_url, json=None, **_k):
            gesehen.append(json)
            if json["appliedFacets"]:
                return _Antwort({"total": 2, "jobPostings": [
                    {"title": "Nah", "locationsText": "München Area", "externalPath": "/job/1"},
                    {"title": "Fern", "locationsText": "Hamburg Area", "externalPath": "/job/2"},
                ]})
            return _Antwort({"total": 2000, "facets": _WORKDAY_FACETTEN, "jobPostings": []})
        return post

    def test_filtert_serverseitig_auf_das_land(self, monkeypatch):
        gesehen: list[dict] = []
        monkeypatch.setattr(ats.requests, "post", self._antwort(gesehen))
        jobs = ats.workday("ag", "Airbus", "Airbus", country="Germany")
        assert gesehen[-1]["appliedFacets"] == {"locationCountry": ["de"]}
        assert [j["titel"] for j in jobs] == ["Nah", "Fern"]

    def test_text_nur_im_umkreis_und_nicht_fuer_bekannte(self, monkeypatch):
        monkeypatch.setattr(ats.requests, "post", self._antwort([]))
        abrufe: list[str] = []

        def get(url, **_k):
            abrufe.append(url)
            return _Antwort({"jobPostingInfo": {"jobDescription": "<p>" + "Text " * 60 + "</p>"}})

        monkeypatch.setattr(ats.requests, "get", get)
        jobs = ats.workday("ag", "Airbus", "Airbus", country="Germany",
                           with_description=True)
        assert abrufe == ["https://ag.wd3.myworkdayjobs.com/wday/cxs/ag/Airbus/job/1"]
        assert jobs[0]["beschreibung"].startswith("Text")
        assert jobs[1]["beschreibung"] == ""

        abrufe.clear()
        ats.workday("ag", "Airbus", "Airbus", country="Germany", with_description=True,
                    known_urls={jobs[0]["url"]})
        assert abrufe == []


class TestAtsMeldungen:
    def test_defekte_diehl_detailseite_kostet_nur_den_text(self, monkeypatch):
        def get(*_a, **_k):
            return _Antwort("", status=503)

        monkeypatch.setattr(ats.requests, "get", get)
        assert ats._diehl_detail("https://new.diehl.com/x", None) == ""

    def test_quelle_gilt_nicht_als_fehlgeschlagen(self, monkeypatch, tmp_path, tmp_config):
        from bewerbungsagent import search as suche

        tmp_config["search"].update(enabled=True, providers=["ats"], ats_boards=[{"firma": "A"}])
        pfad = tmp_path / "config.json"
        pfad.write_text(json.dumps(tmp_config), encoding="utf-8")

        def search(*_a, status, **_k):
            status["A"] = {"gefunden": 5, "im_umkreis": 0, "fehler": []}
            return [], []

        monkeypatch.setattr(suche.ats, "search", search)
        stats: dict = {}
        _jobs, fehler, _n = suche.run_search(Config(pfad), None, stats=stats)
        assert fehler == []
        assert stats["ats"]["fehler"] == []
        assert stats["ats"]["hinweise"] == ["ats (A): 5 gefunden, 0 im Umkreis"]


@pytest.fixture
def config(tmp_path: Path, tmp_config: dict) -> Config:
    pfad = tmp_path / "config.json"
    pfad.write_text(json.dumps(tmp_config), encoding="utf-8")
    return Config(pfad)


def _treffer(key: str, **extra) -> dict:
    return {"key": key, "id": 1, "firma": "Acme", "titel": "Testingenieur",
            "ort": "München", "url": f"https://example.test/{key}", "score": 90,
            "pendelzeit_min": 20, **extra}


class TestMengenlauf:
    """``run_generate`` überschrieb den Ordner bereits versendeter Bewerbungen."""

    @pytest.fixture
    def erzeugt(self, monkeypatch):
        aufrufe: list[str] = []

        def fake(_config, _profile, job, template=None, auto=False):
            aufrufe.append(job["key"])
            return [{"id": job.get("id"), "firma": job["firma"], "titel": job["titel"],
                     "dokumente": {}, "qualitaet": None}]

        monkeypatch.setattr(pipeline, "_generate_one", fake)
        return aufrufe

    def _lauf(self, config, bestand, treffer):
        Store(config.db_path()).save_state({"applications": bestand})
        save_json(config.matches_path(), treffer)
        return pipeline.run_generate(config, None)

    def test_dublette_einer_anderen_boerse_bleibt_unberuehrt(self, config, erzeugt):
        bestand = [_treffer("alt", status="sent", dokumente={"anschreiben_de": "x.pdf"})]
        ergebnis = self._lauf(config, bestand, [_treffer("neue-url", status="neu")])
        assert erzeugt == []
        assert ergebnis["skipped_bestand"] == 1

    @pytest.mark.parametrize("zustand", [
        {"status": "research", "deleted": True},
        {"status": "rejected"},
        {"status": "sent"},
    ])
    def test_geloeschte_und_abgeschlossene_stellen(self, config, erzeugt, zustand):
        self._lauf(config, [_treffer("a", **zustand)], [_treffer("a", status="neu")])
        assert erzeugt == []

    def test_offene_stelle_wird_erzeugt(self, config, erzeugt):
        self._lauf(config, [_treffer("a", status="research")], [_treffer("a", status="neu")])
        assert erzeugt == ["a"]

    def test_fehler_stoppt_den_lauf_nicht(self, config, monkeypatch):
        aufrufe: list[str] = []

        def fake(_config, _profile, job, template=None, auto=False):
            aufrufe.append(job["key"])
            if job["key"] == "a":
                raise PermissionError("PDF gesperrt")
            return []

        monkeypatch.setattr(pipeline, "_generate_one", fake)
        bestand = [_treffer("a", firma="Eins", status="research"),
                   _treffer("b", firma="Zwei", status="research")]
        ergebnis = self._lauf(config, bestand, bestand)
        assert sorted(aufrufe) == ["a", "b"]
        assert ergebnis["failed"] == [{"firma": "Eins", "titel": "Testingenieur",
                                       "fehler": "PermissionError: PDF gesperrt"}]


class TestEnrich:
    def test_abgeschlossene_stelle_bekommt_keine_unterlagen(self, config, monkeypatch):
        monkeypatch.setattr(pipeline, "enrich_commute", lambda apps, *_a: {"total": len(apps)})
        monkeypatch.setattr(pipeline, "enrich_salary", lambda apps: {})
        aufrufe: list[str] = []
        monkeypatch.setattr(pipeline, "_generate_one",
                            lambda _c, _p, job, **_k: aufrufe.append(job["key"]) or [])
        Store(config.db_path()).save_state(
            {"applications": [_treffer("a", status="rejected", dokumente={})]})
        pipeline.run_enrich(config, None)
        assert aufrufe == []

    def test_ausgeblendete_stelle_braucht_keinen_pendelweg(self, config, monkeypatch):
        gesehen: list[list[str]] = []

        def commute(apps, *_a):
            gesehen.append([a["key"] for a in apps])
            return {"total": len(apps)}

        monkeypatch.setattr(pipeline, "enrich_commute", commute)
        monkeypatch.setattr(pipeline, "enrich_salary", lambda apps: {})
        Store(config.db_path()).save_state({"applications": [
            _treffer("offen", status="sent"),
            _treffer("weg", status="neu", deleted=True, deleted_reason="FIT < 50 %",
                     pendel_modus="Auto", score=10),
        ]})
        pipeline.run_enrich(config, None)
        assert gesehen == [["offen"]]

    def test_fehlversuch_zaehlt_nicht_gegen_das_budget(self, config, monkeypatch):
        monkeypatch.setattr(pipeline, "enrich_commute", lambda apps, *_a: {"total": len(apps)})
        monkeypatch.setattr(pipeline, "enrich_salary", lambda apps: {})

        def kaputt(*_a, **_k):
            raise OSError("voll")

        monkeypatch.setattr(pipeline, "_generate_one", kaputt)
        store = Store(config.db_path())
        store.save_state({"applications": [_treffer("a", status="research", dokumente={})]})
        ergebnis = pipeline.run_enrich(config, None)
        assert ergebnis["failed"][0]["fehler"] == "OSError: voll"
        assert "unterlagen_erzeugt_am" not in store.load_state()["applications"][0]


class TestAblauf:
    def test_tagessuche_nutzt_alle_definitionen(self, config, monkeypatch):
        (config.data_dir / "saved_searches.json").write_text(json.dumps([
            {"name": "China-EV", "daily": True, "query_terms": ["NIO"],
             "location": "München", "providers": ["arbeitnow"]},
        ]), encoding="utf-8")
        aufrufe: list = []

        def suche(_c, _p, definition, health=None, stats=None, **_k):
            aufrufe.append((definition or {}).get("query_terms"))
            return [], [], 0

        monkeypatch.setattr(pipeline, "_search", suche)
        monkeypatch.setattr(pipeline, "enrich_commute", lambda *_a: {})
        ergebnis = pipeline.run_search(config, None)
        assert aufrufe == [None, ["NIO"]]
        assert ergebnis["searches"] == ["Standard", "China-EV"]

    def test_eigene_begriffe_gelten_auch_fuer_browser_provider(self, monkeypatch, tmp_path,
                                                               tmp_config):
        from bewerbungsagent import search as suche

        tmp_config["search"].update(enabled=True, providers=["xing"], triage=False,
                                    xing_terms=["Testingenieur"], jobspy_max_terms=2)
        pfad = tmp_path / "config.json"
        pfad.write_text(json.dumps(tmp_config), encoding="utf-8")
        gesehen: list = []
        monkeypatch.setattr(suche.xing, "available", lambda: True)
        monkeypatch.setattr(suche.xing, "search",
                            lambda terms, **_k: gesehen.append(terms) or [])
        suche.run_search(Config(pfad), None, definition={"query_terms": ["NIO"]})
        suche.run_search(Config(pfad), None)
        assert gesehen == [["NIO"], ["Testingenieur"]]

    def test_textluecke_gilt_nicht_als_gesehen(self, config, monkeypatch):
        monkeypatch.setattr(pipeline, "_search", lambda *_a, **_k: ([], [], 0))
        monkeypatch.setattr(pipeline, "enrich_commute", lambda *_a: {})
        monkeypatch.setattr(pipeline, "_textluecken", lambda *_a: [
            {"key": "alt", "titel": "T", "url": "https://example.test/alt",
             "zuletzt_gesehen": "2026-10-01T00:00:00+01:00"}])
        pipeline.run_searches(config, None)
        jobs = json.loads(config.jobs_path().read_text(encoding="utf-8"))
        assert jobs[0]["zuletzt_gesehen"] == "2026-10-01T00:00:00+01:00"

    def test_pipeline_ruft_enrich_auf(self, config, monkeypatch):
        reihenfolge: list[str] = []
        monkeypatch.setattr(pipeline, "run_searches",
                            lambda *_a: reihenfolge.append("suche") or {})
        monkeypatch.setattr(pipeline, "run_fetch",
                            lambda *_a: reihenfolge.append("fetch") or {})
        monkeypatch.setattr(pipeline, "run_match",
                            lambda *_a: reihenfolge.append("match") or {"matched": 0})
        monkeypatch.setattr(pipeline, "run_enrich", lambda *_a: reihenfolge.append("enrich") or {
            "generated": [{"id": 1}], "failed": []})
        monkeypatch.setattr(pipeline, "run_generate", lambda *_a: reihenfolge.append("generate") or {
            "generated": [{"id": 2}], "failed": []})
        monkeypatch.setattr(pipeline, "run_quality",
                            lambda *_a: reihenfolge.append("quality") or {})
        monkeypatch.setattr(pipeline, "run_dashboard",
                            lambda *_a: reihenfolge.append("dashboard") or {})
        ergebnis = pipeline.run_full(config, None)
        assert reihenfolge == ["suche", "fetch", "match", "enrich", "generate", "quality",
                               "dashboard"]
        assert [g["id"] for g in ergebnis["generated"]] == [1, 2]


class TestStore:
    def test_lauf_behaelt_parallele_nutzerfelder(self, config):
        store = Store(config.db_path())
        store.save_state({"applications": [_treffer("a", status="docs")]})
        lauf = store.load_state()
        store.apply_overlay({"a": {"absage_grund": "Profil", "research_sichtbar": True}})
        store.save_state(lauf)
        app = store.load_state()["applications"][0]
        assert app["absage_grund"] == "Profil"
        assert app["research_sichtbar"] is True

    def test_update_app_aendert_nur_den_eintrag(self, config):
        store = Store(config.db_path())
        store.save_state({"applications": [_treffer("a", status="research"),
                                           _treffer("b", status="research")]})
        assert store.update_app("a", lambda app: app.update(status="docs", dokumente={"x": "y"}))
        assert not store.update_app("fehlt", lambda app: None)
        apps = {a["key"]: a for a in store.load_state()["applications"]}
        assert apps["a"]["status"] == "docs"
        assert apps["a"]["dokumente"] == {"x": "y"}
        assert apps["b"]["status"] == "research"

    def test_unveraenderte_zeile_behaelt_updated_at(self, config):
        from bewerbungsagent.db import Application

        store = Store(config.db_path())
        store.save_state({"applications": [_treffer("a", status="research")]})
        with store._Session() as session:
            session.query(Application).update({"updated_at": "alt"})
            session.commit()
        store.save_state(store.load_state())
        with store._Session() as session:
            assert session.query(Application).one().updated_at == "alt"


class TestGeocoder:
    def test_ort_ohne_nahen_namensvetter_wird_gemerkt(self, tmp_path, monkeypatch):
        import bewerbungsagent.commute as commute

        aufrufe: list[str] = []

        class Treffer:
            status_code = 200

            def json(self):
                return [{"lat": "49.6", "lon": "11.0", "display_name": "Erlangen"}]

        def get(_url, params=None, **_k):
            aufrufe.append(params["q"])
            return Treffer()

        monkeypatch.setattr(commute.requests, "get", get)
        home = {"lat": 48.2, "lon": 11.6}
        pfad = tmp_path / "cache.json"
        geocoder = _Geocoder(pfad)
        geocoder._throttle = lambda: None
        assert geocoder.geocode_near("Erlangen", home) is None
        geocoder.save()

        wieder = _Geocoder(pfad)
        wieder._throttle = lambda: None
        assert wieder.geocode_near("Erlangen", home) is None
        assert aufrufe == ["Erlangen"]


class TestNormalisierung:
    @pytest.mark.parametrize("roh,erwartet", [
        ("München", "munchen"),
        ("Straße", "strasse"),
        ("c‐uas", "c-uas"),
        ("ﬁt ½", "fit 1⁄2"),
        ("Crème", "creme"),
    ])
    def test_ergebnis(self, roh, erwartet):
        assert normalize(roh) == erwartet

    def test_kurze_und_mehrwort_schluessel(self):
        profil = Profile({"skills": {"werkzeuge": ["CAN", "Test Engineer"]}})
        assert "can" not in profil.keywords_in("candidate")
        assert "can" in profil.keywords_in("Erfahrung mit CAN und LIN")
        assert "test engineer" in profil.keywords_in("Test Automation Engineer")


class TestJobwatch:
    def _lauf(self, monkeypatch, tmp_path, fehlschlag: str, fehler):
        monkeypatch.setattr(jobwatch, "RUN_OUTPUT", tmp_path / "lauf.log")
        schritte: list[str] = []

        class Ergebnis:
            def __init__(self, code):
                self.returncode = code

        def run(befehl, **_k):
            schritt = befehl[2]
            schritte.append(schritt)
            if schritt == fehlschlag:
                if isinstance(fehler, BaseException):
                    raise fehler
                return Ergebnis(fehler)
            return Ergebnis(0)

        monkeypatch.setattr(jobwatch.subprocess, "run", run)
        return jobwatch.run_pipeline(), schritte

    def test_fehlendes_nachladen_stoppt_das_matching_nicht(self, monkeypatch, tmp_path):
        ok, schritte = self._lauf(monkeypatch, tmp_path, "fetch", 1)
        assert ok is False
        assert schritte == ["search", "fetch", "match", "enrich", "generate", "quality",
                            "dashboard"]

    def test_zeitlimit_beendet_den_lauf_geordnet(self, monkeypatch, tmp_path):
        ok, schritte = self._lauf(monkeypatch, tmp_path, "search",
                                  subprocess.TimeoutExpired("agent.py", 1))
        assert ok is False
        assert schritte == ["search"]
