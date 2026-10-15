"""Vertragstests für die Such-Orchestrierung (``search/__init__.py``).

Sichert den Kern-Kontrakt der Provider-Integration: der Lexikon-/Aggregator-Filter
darf nur auf rohe Web-Such-Treffer angewendet werden, nicht auf strukturierte
Quellen (StepStone/Import/JobSpy) — sonst würden die echten LinkedIn-/Indeed-URLs
aus JobSpy sofort wieder herausgefiltert (ADR-017).
"""

from __future__ import annotations

from bewerbungsagent.search import (
    _DIRECT_SOURCES,
    _is_non_job_host,
    build_queries,
    build_stepstone_queries,
)


class TestDirectSourceGate:
    def test_linkedin_and_indeed_are_still_blocklisted_for_web_search(self):
        # Die Blacklist bleibt intakt: Rohe Web-Such-Treffer auf LinkedIn/Indeed
        # sind weiterhin unerwünscht (nur Listing-/Redirect-Seiten).
        assert _is_non_job_host("https://www.linkedin.com/jobs/view/123")
        assert _is_non_job_host("https://de.indeed.com/viewjob?jk=abc")

    def test_jobspy_sources_bypass_the_host_filter(self):
        # Die JobSpy-Quellen stehen in _DIRECT_SOURCES → ihr Host wird nicht
        # gefiltert, obwohl LinkedIn/Indeed auf der Blacklist stehen.
        assert {"LinkedIn", "Indeed", "Google Jobs"} <= _DIRECT_SOURCES

    def test_stepstone_and_import_are_direct_sources(self):
        assert {"StepStone", "Import"} <= _DIRECT_SOURCES

    def test_web_search_sources_are_not_direct(self):
        # DuckDuckGo/Bing bleiben "rohe" Quellen und durchlaufen den Filter.
        assert "DuckDuckGo" not in _DIRECT_SOURCES
        assert "Bing" not in _DIRECT_SOURCES


class TestQueryBuilding:
    def test_build_queries_uses_provided_search_dict(self):
        s = {"location": "München", "query_terms": ["Testingenieur", "ADAS Test"]}
        assert build_queries(s) == ["Testingenieur Jobs München", "ADAS Test Jobs München"]

    def test_build_stepstone_queries_has_no_suffix(self):
        s = {"query_terms": ["Testingenieur", "ADAS Test"]}
        assert build_stepstone_queries(s) == ["Testingenieur", "ADAS Test"]

    def test_build_queries_empty_terms(self):
        assert build_queries({"location": "München", "query_terms": []}) == []


class TestTriageFilterInSearch:
    """Die Triage greift in ``run_search`` — domänenfremde Treffer fliegen raus.

    Geprüft über den manuellen Import-Provider (kein Netzwerk nötig), der die
    ``data/import_jobs.json`` liest.
    """

    def _config(self, tmp_path, jobs):
        import json
        from pathlib import Path
        fixtures = Path(__file__).resolve().parent / "fixtures"
        (tmp_path / "data").mkdir(parents=True, exist_ok=True)
        (tmp_path / "profil-demo.json").write_text(
            (fixtures / "profil-demo.json").read_text(encoding="utf-8"), encoding="utf-8")
        cfg = {
            "profile_json": str(tmp_path / "profil-demo.json"),
            # Absoluter Pfad: ``Config.resolve()`` lässt absolute Pfade unverändert,
            # so schreibt der Test in sein tmp-Verzeichnis statt ins Repo.
            "data_dir": str(tmp_path / "data"),
            "output_dir": str(tmp_path / "output"),
            "search": {"enabled": False, "providers": ["manual"], "query_terms": [],
                       "location": "München"},
        }
        (tmp_path / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        (tmp_path / "data" / "import_jobs.json").write_text(
            json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
        from bewerbungsagent.config import Config
        return Config(tmp_path / "config.json")

    def _run(self, tmp_path, jobs):
        import json

        from bewerbungsagent.profile import Profile
        from bewerbungsagent.search import run_search
        cfg = self._config(tmp_path, jobs)
        prof = Profile(json.loads((tmp_path / "profil-demo.json").read_text(encoding="utf-8")))
        return run_search(cfg, prof)

    def test_laerm_wird_gefiltert(self, tmp_path):
        result = self._run(tmp_path, [
            {"titel": "Senior Test Engineer (m/w/d)", "firma": "Acme", "url": "https://a.test/1"},
            {"titel": "Taxifahrer (m/w/d)", "firma": "Taxi GmbH", "url": "https://a.test/2"},
            {"titel": "Manager Digitales Marketing", "firma": "Lotterie",
             "url": "https://a.test/3"},
        ])
        jobs, _errors, rejected = result
        titel = [j["titel"] for j in jobs]
        assert "Senior Test Engineer (m/w/d)" in titel
        assert "Taxifahrer (m/w/d)" not in titel
        assert "Manager Digitales Marketing" not in titel
        assert rejected == 2

    def test_unsure_bleibt_im_bestand(self, tmp_path):
        jobs, _errors, rejected = self._run(tmp_path, [
            {"titel": "Teamleitung", "firma": "VITES", "url": "https://a.test/1"},
        ])
        assert len(jobs) == 1
        assert rejected == 0

    def test_abgelehnte_werden_protokolliert(self, tmp_path):
        import json
        self._run(tmp_path, [
            {"titel": "Koch (m/w/d)", "firma": "Restaurant", "url": "https://a.test/1"},
        ])
        proto = tmp_path / "data" / "triage_rejected.json"
        assert proto.exists()
        data = json.loads(proto.read_text(encoding="utf-8"))
        assert data[0]["titel"] == "Koch (m/w/d)"
        assert data[0]["grund"]

    def test_ids_sind_nach_dem_filter_lueckenlos(self, tmp_path):
        jobs, _errors, _rejected = self._run(tmp_path, [
            {"titel": "Taxifahrer", "firma": "A", "url": "https://a.test/1"},
            {"titel": "Test Engineer", "firma": "B", "url": "https://a.test/2"},
            {"titel": "Buchhalter", "firma": "C", "url": "https://a.test/3"},
            {"titel": "System Test Engineer", "firma": "D", "url": "https://a.test/4"},
        ])
        assert [j["id"] for j in jobs] == [1, 2]

    def test_triage_abschaltbar(self, tmp_path):
        import json
        cfg = self._config(tmp_path, [{"titel": "Taxifahrer", "firma": "A",
                                       "url": "https://a.test/1"}])
        raw = json.loads(cfg.path.read_text(encoding="utf-8"))
        raw["search"]["triage"] = False
        cfg.path.write_text(json.dumps(raw), encoding="utf-8")
        from bewerbungsagent.config import Config
        from bewerbungsagent.profile import Profile
        from bewerbungsagent.search import run_search
        cfg2 = Config(cfg.path)
        prof = Profile(json.loads((tmp_path / "profil-demo.json").read_text(encoding="utf-8")))
        jobs, _errors, rejected = run_search(cfg2, prof)
        assert len(jobs) == 1
        assert rejected == 0
