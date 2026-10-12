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
