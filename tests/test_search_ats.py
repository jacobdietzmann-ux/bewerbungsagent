"""Tests für die ATS-Abfrage (Greenhouse/Lever/Ashby).

Hintergrund: Jobbörsen liefern nur Indexiertes, und die allgemeinen Suchmaschinen
sind für Stellensuche unbrauchbar geworden (DuckDuckGo 0 Treffer, Bing nur
``bing.com/ck/a``-Redirects, Mojeek Captcha). Die Karriereseiten selbst haben
öffentliche JSON-Endpunkte — mit vollständigem Anzeigentext.
"""

from __future__ import annotations

import pytest

from bewerbungsagent.search import ats


class _Resp:
    def __init__(self, payload, status: int = 200):
        self._payload = payload
        self.status_code = status
        self.text = payload if isinstance(payload, str) else ""

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _kein_netzwerk(monkeypatch):
    """Standard: jeder HTTP-Aufruf schlägt fehl, Tests setzen ihn selbst."""
    def _fail(*_a, **_k):
        raise AssertionError("unerwarteter Netzwerkaufruf")
    monkeypatch.setattr(ats.requests, "get", _fail)


class TestDetectBoard:
    @pytest.mark.parametrize("url,erwartet", [
        ("https://job-boards.eu.greenhouse.io/skdse/jobs/4988153101",
         ("greenhouse", "skdse")),
        ("https://boards.greenhouse.io/acme/jobs/1", ("greenhouse", "acme")),
        ("https://jobs.lever.co/acme/123", ("lever", "acme")),
        ("https://jobs.ashbyhq.com/helsing/945e7605", ("ashby", "helsing")),
    ])
    def test_erkennt_system_und_board(self, url, erwartet):
        assert ats.detect_board(url) == erwartet

    @pytest.mark.parametrize("url", [
        "https://www.stepstone.de/stellenangebote--Testingenieur-Muenchen--1",
        "https://career.quantum-systems.com/o/system-test-engineer-mfd",
        "https://jobs.bmwgroup.com/job/AI-Solution-Architect/197410-en_U",
        "",
    ])
    def test_unbekannte_hosts_liefern_nichts(self, url):
        assert ats.detect_board(url) is None

    def test_greenhouse_nicht_als_substring_fremder_domain(self):
        """``greenhouse.io.evil.test`` darf nicht als Greenhouse gelten."""
        assert ats.detect_board("https://greenhouse.io.evil.test/acme/jobs/1") is None

    def test_boards_from_jobs_dedupliziert(self):
        jobs = [
            {"firma": "STARK Defence", "url": "https://job-boards.eu.greenhouse.io/skdse/jobs/1"},
            {"firma": "STARK Defence", "url": "https://job-boards.eu.greenhouse.io/skdse/jobs/2"},
            {"firma": "ARX", "url": "https://job-boards.eu.greenhouse.io/arxroboticsgmbh/jobs/3"},
            {"firma": "StepStone-Fund", "url": "https://www.stepstone.de/x"},
        ]
        boards = ats.boards_from_jobs(jobs)
        assert boards == [
            {"firma": "ARX", "ats": "greenhouse", "board": "arxroboticsgmbh"},
            {"firma": "STARK Defence", "ats": "greenhouse", "board": "skdse"},
        ]


class TestGreenhouse:
    def test_volltext_und_ort(self, monkeypatch):
        payload = {"jobs": [{
            "title": "Systems Integration & QA Engineer",
            "location": {"name": "Munich"},
            "absolute_url": "https://job-boards.eu.greenhouse.io/skdse/jobs/1",
            "content": "<p>" + "Teste Simulationsumgebungen. " * 20 + "</p>",
        }]}
        monkeypatch.setattr(ats.requests, "get", lambda *a, **k: _Resp(payload))

        jobs = ats.greenhouse("skdse", "STARK Defence")

        assert len(jobs) == 1
        job = jobs[0]
        assert job["titel"] == "Systems Integration & QA Engineer"
        assert job["ort"] == "Munich"
        assert job["quelle"] == "ATS"
        assert "<p>" not in job["beschreibung"]
        assert len(job["beschreibung"]) > 200


class TestLever:
    def test_mapped_auf_gemeinsames_format(self, monkeypatch):
        payload = [{
            "text": "Testingenieur (m/w/d)",
            "hostedUrl": "https://jobs.lever.co/acme/1",
            "categories": {"location": "München"},
            "descriptionPlain": "Aufgaben: " + "HiL-Tests aufbauen. " * 20,
        }]
        monkeypatch.setattr(ats.requests, "get", lambda *a, **k: _Resp(payload))

        jobs = ats.lever("acme", "Acme GmbH")

        assert jobs[0]["titel"] == "Testingenieur (m/w/d)"
        assert jobs[0]["ort"] == "München"
        assert jobs[0]["beschreibung"].startswith("Aufgaben:")


class TestAshby:
    def test_nicht_gelistete_stellen_entfallen(self, monkeypatch):
        payload = {"jobs": [
            {"title": "Sichtbar", "location": "Munich", "jobUrl": "https://x/1",
             "descriptionPlain": "x" * 300},
            {"title": "Versteckt", "location": "Munich", "jobUrl": "https://x/2",
             "isListed": False, "descriptionPlain": "y" * 300},
        ]}
        monkeypatch.setattr(ats.requests, "get", lambda *a, **k: _Resp(payload))

        jobs = ats.ashby("acme", "Acme")

        assert [j["titel"] for j in jobs] == ["Sichtbar"]


class TestWorkday:
    def _postings(self, n: int, title="Ingenieur", location="München Area") -> list[dict]:
        return [{"title": f"{title} {i}", "locationsText": location,
                 "externalPath": f"/job/X/{title}-{i}", "postedOn": "2026-10-21"}
                for i in range(n)]

    def _responder(self, postings: list[dict]):
        def _post(url, json=None, **_k):
            offset = (json or {}).get("offset", 0)
            page = postings[offset:offset + 20]
            return _Resp({"jobPostings": page, "total": len(postings)})
        return _post

    def test_paginiert_alle_stellen(self, monkeypatch):
        monkeypatch.setattr(ats.requests, "post", self._responder(self._postings(45)))
        assert len(ats.workday("ag", "Airbus", "Airbus")) == 45

    def test_url_und_ort_korrekt(self, monkeypatch):
        monkeypatch.setattr(ats.requests, "post", self._responder(self._postings(1)))
        jobs = ats.workday("ag", "Airbus", "Airbus")
        assert jobs[0]["url"] == "https://ag.wd3.myworkdayjobs.com/en-US/Airbus/job/X/Ingenieur-0"
        assert jobs[0]["ort"] == "München Area"
        assert jobs[0]["quelle"] == "ATS"

    def test_max_jobs_begrenzt(self, monkeypatch):
        monkeypatch.setattr(ats.requests, "post", self._responder(self._postings(100)))
        assert len(ats.workday("ag", "Airbus", "Airbus", max_jobs=30)) == 30

    def test_ohne_external_path_entfaellt(self, monkeypatch):
        postings = [{"title": "Ohne Pfad", "locationsText": "München Area",
                     "externalPath": ""}]
        monkeypatch.setattr(ats.requests, "post", self._responder(postings))
        assert ats.workday("ag", "Airbus", "Airbus") == []

    def test_search_mit_workday_eintrag(self, monkeypatch):
        postings = [
            {"title": "Systemingenieur", "locationsText": "München Area",
             "externalPath": "/job/1"},
            {"title": "Systemingenieur Fern", "locationsText": "Toulouse Area",
             "externalPath": "/job/2"},
        ]
        monkeypatch.setattr(ats.requests, "post", self._responder(postings))
        jobs, errors = ats.search([{"firma": "Airbus", "ats": "workday",
                                    "tenant": "ag", "site": "Airbus"}])
        assert [j["titel"] for j in jobs] == ["Systemingenieur"]

    def test_workday_ohne_tenant_site_meldet_fehler(self):
        jobs, errors = ats.search([{"firma": "Airbus", "ats": "workday"}])
        assert jobs == []
        assert any("tenant/site fehlt" in e for e in errors)


class TestEightfold:
    def _position(self, i: int) -> dict:
        return {"id": 1000 + i, "name": f"Engineer {i}",
                "locations": ["Munich, Germany"],
                "positionUrl": f"/careers/job/{1000 + i}"}

    def _responder(self, positions: list[dict]):
        def _get(url, params=None, **_k):
            start = (params or {}).get("start", 0)
            page = positions[start:start + 10]
            return _Resp({"status": 200, "data": {
                "positions": page, "count": len(positions)}})
        return _get

    def test_paginiert_und_mappt(self, monkeypatch):
        monkeypatch.setattr(ats.requests, "get",
                            self._responder([self._position(i) for i in range(25)]))
        jobs = ats.eightfold("careers.qualcomm.com", "qualcomm.com", "Qualcomm")
        assert len(jobs) == 25
        assert jobs[0]["url"] == "https://careers.qualcomm.com/careers/job/1000"
        assert jobs[0]["titel"] == "Engineer 0"
        assert jobs[0]["ort"] == "Munich, Germany"
        assert jobs[0]["beschreibung"] == ""  # kein Volltext im Index

    def test_ohne_titel_oder_url_entfaellt(self, monkeypatch):
        pos = [{"name": "", "locations": ["Munich"], "positionUrl": "/x"},
               {"name": "Ok", "locations": ["Munich"], "positionUrl": ""},
               {"name": "Gut", "locations": ["Munich"], "positionUrl": "/y"}]
        monkeypatch.setattr(ats.requests, "get", self._responder(pos))
        assert [j["titel"] for j in
                ats.eightfold("h", "d", "Firma")] == ["Gut"]

    def test_search_mit_eightfold_eintrag(self, monkeypatch):
        monkeypatch.setattr(ats.requests, "get",
                            self._responder([self._position(0)]))
        jobs, errors = ats.search([{"firma": "Qualcomm", "ats": "eightfold",
                                    "host": "careers.qualcomm.com",
                                    "domain": "qualcomm.com"}])
        assert [j["titel"] for j in jobs] == ["Engineer 0"]

    def test_eightfold_ohne_host_domain_meldet_fehler(self):
        jobs, errors = ats.search([{"firma": "X", "ats": "eightfold"}])
        assert jobs == []
        assert any("host/domain fehlt" in e for e in errors)


class TestSuccessFactorsJ2W:
    def _tile(self, path: str, title: str, location: str) -> str:
        return (
            f'<li class="job-tile job-id-1" data-url="{path}">'
            f'<div class="tiletitle"><a class="jobTitle-link" href="{path}">{title}</a></div>'
            f'<div id="job-1-desktop-section-multilocation-value">{location}</div>'
            f'</li>'
        )

    def _responder(self, tiles: list[str]):
        def _get(url, params=None, **_k):
            startrow = (params or {}).get("startrow", 0)
            page = tiles[startrow // 25:(startrow // 25) + 25]
            return _Resp("".join(page))
        return _get

    def test_parst_tiles(self, monkeypatch):
        tiles = [self._tile("/job/X/1/", "Systemingenieur (m/w/d)",
                            "Taufkirchen, DE, 82024")]
        monkeypatch.setattr(ats.requests, "get", self._responder(tiles))
        jobs = ats.successfactors_j2w("jobs.hensoldt.net", "HENSOLDT")
        assert len(jobs) == 1
        assert jobs[0]["titel"] == "Systemingenieur (m/w/d)"
        assert jobs[0]["url"] == "https://jobs.hensoldt.net/job/X/1/"
        assert "Taufkirchen" in jobs[0]["ort"]
        assert jobs[0]["beschreibung"] == ""

    def test_leere_seite_beendet_schleife(self, monkeypatch):
        monkeypatch.setattr(ats.requests, "get",
                            lambda *a, **k: _Resp("keine Tiles"))
        assert ats.successfactors_j2w("h", "Firma") == []

    def test_search_mit_successfactors_eintrag(self, monkeypatch):
        tiles = [self._tile("/job/1/", "Entwicklungsingenieur",
                            "Taufkirchen, DE, 82024")]
        monkeypatch.setattr(ats.requests, "get", self._responder(tiles))
        jobs, errors = ats.search([{"firma": "HENSOLDT", "ats": "successfactors",
                                    "host": "jobs.hensoldt.net"}])
        assert [j["titel"] for j in jobs] == ["Entwicklungsingenieur"]


class TestSearch:
    def _board(self, **over):
        return {"firma": "Acme", "ats": "greenhouse", "board": "acme", **over}

    def test_filtert_entfernte_orte(self, monkeypatch):
        payload = {"jobs": [
            {"title": "Nah", "location": {"name": "München"},
             "absolute_url": "https://x/1", "content": "a" * 300},
            {"title": "Fern", "location": {"name": "Thessaloniki, Greece"},
             "absolute_url": "https://x/2", "content": "b" * 300},
        ]}
        monkeypatch.setattr(ats.requests, "get", lambda *a, **k: _Resp(payload))

        jobs, _ = ats.search([self._board()])

        assert [j["titel"] for j in jobs] == ["Nah"]

    def test_filter_abschaltbar(self, monkeypatch):
        payload = {"jobs": [{"title": "Fern", "location": {"name": "Greece"},
                             "absolute_url": "https://x/2", "content": "b" * 300}]}
        monkeypatch.setattr(ats.requests, "get", lambda *a, **k: _Resp(payload))

        jobs, _ = ats.search([self._board()], only_near_munich=False)

        assert len(jobs) == 1

    def test_defektes_board_stoppt_die_anderen_nicht(self, monkeypatch):
        def _get(url, *_a, **_k):
            if "kaputt" in url:
                return _Resp({}, status=500)
            return _Resp({"jobs": [{"title": "Ok", "location": {"name": "Munich"},
                                    "absolute_url": "https://x/1", "content": "a" * 300}]})
        monkeypatch.setattr(ats.requests, "get", _get)

        jobs, errors = ats.search([
            self._board(firma="Kaputt", board="kaputt"),
            self._board(firma="Gut", board="gut"),
        ])

        assert [j["titel"] for j in jobs] == ["Ok"]
        assert any("Kaputt" in e for e in errors)

    def test_unbekanntes_system_meldet_fehler(self):
        jobs, errors = ats.search([{"firma": "X", "ats": "unbekannt", "board": "y"}])
        assert jobs == []
        assert any("unbekanntes System" in e for e in errors)

    def test_remote_wird_behalten(self, monkeypatch):
        payload = {"jobs": [{"title": "Remote", "location": {"name": "Remote"},
                             "absolute_url": "https://x/1", "content": "a" * 300}]}
        monkeypatch.setattr(ats.requests, "get", lambda *a, **k: _Resp(payload))

        jobs, _ = ats.search([self._board()])

        assert [j["titel"] for j in jobs] == ["Remote"]
