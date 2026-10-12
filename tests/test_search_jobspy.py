"""Tests für den JobSpy-Provider (``search/jobspy.py``).

Der echte ``python-jobspy``-Aufruf wird über eine Fake-DataFrame im ``sys.modules``
gemockt, damit die Tests ohne pandas/pydantic und ohne Netzwerk laufen.
"""

from __future__ import annotations

import sys
import types

from bewerbungsagent.search import jobspy
from bewerbungsagent.search.jobspy import _direct_url, _is_ats, _snippet


class _FakeDF:
    """Minimaler Ersatz für die pandas-DataFrame aus ``scrape_jobs``."""

    empty = False

    def __init__(self, records):
        self._records = records

    def to_dict(self, orient="records"):
        assert orient == "records"
        return self._records


def _patch_scrape(records):
    fake = types.ModuleType("jobspy")
    fake.scrape_jobs = lambda **kw: _FakeDF(records)
    sys.modules["jobspy"] = fake


def _record(**overrides):
    rec = {
        "site": "linkedin",
        "title": "Senior Software Test Engineer (m/f/d)",
        "company": "AstraZeneca",
        "company_name": "AstraZeneca GmbH",
        "job_url": "https://www.linkedin.com/jobs/view/123",
        "job_url_direct": "https://astrazeneca.wd3.myworkdayjobs.com/foo",
        "location": "München, Bayern, Deutschland",
        "description": "Wir suchen einen Testingenieur mit CAN und Python.",
    }
    rec.update(overrides)
    return rec


class TestHelpers:
    def test_direct_url_prefers_job_url_direct(self):
        assert _direct_url(_record()) == "https://astrazeneca.wd3.myworkdayjobs.com/foo"

    def test_direct_url_falls_back_to_job_url(self):
        assert _direct_url({"job_url": "https://x.example/job"}) == "https://x.example/job"

    def test_direct_url_empty(self):
        assert _direct_url({}) == ""

    def test_is_ats_detects_greenhouse_and_lever(self):
        assert _is_ats("https://boards.greenhouse.io/foo/jobs/1")
        assert _is_ats("https://jobs.lever.co/acme/123")
        assert not _is_ats("https://www.stepstone.de/jobs/1")

    def test_snippet_short_unchanged(self):
        assert _snippet("kurzer Text") == "kurzer Text"

    def test_snippet_truncates_with_ellipsis(self):
        out = _snippet(" ".join("Wort" for _ in range(200)))
        assert out.endswith("…")
        assert len(out) <= jobspy._SNIPPET_MAX + 2


class TestSearch:
    def test_maps_records_to_internal_format(self):
        _patch_scrape([_record()])
        result = jobspy.search("Test Engineer", location="München")
        assert len(result) == 1
        job = result[0]
        assert job["titel"] == "Senior Software Test Engineer (m/f/d)"
        assert job["firma"] == "AstraZeneca"
        assert job["ort"].startswith("München")
        assert job["url"] == "https://astrazeneca.wd3.myworkdayjobs.com/foo"
        assert job["quelle"] == "LinkedIn"
        assert job["beschreibung"] == "Wir suchen einen Testingenieur mit CAN und Python."
        assert job["snippet"] == job["beschreibung"]

    def test_skips_records_without_title_or_url(self):
        _patch_scrape([
            _record(title=""),
            _record(job_url="", job_url_direct=""),
            _record(),
        ])
        result = jobspy.search("Test Engineer", location="München")
        assert len(result) == 1

    def test_site_labels(self):
        _patch_scrape([
            _record(site="google", job_url_direct="https://boards.greenhouse.io/x"),
            _record(site="indeed", job_url_direct="https://de.indeed.com/viewjob?jk=1"),
        ])
        result = jobspy.search("Test Engineer", location="München")
        assert [j["quelle"] for j in result] == ["Google Jobs", "Indeed"]

    def test_empty_dataframe_returns_empty_list(self):
        fake = types.ModuleType("jobspy")
        fake.scrape_jobs = lambda **kw: _FakeDF([])
        sys.modules["jobspy"] = fake
        assert jobspy.search("Test Engineer") == []

    def test_company_fallback_to_company_name(self):
        rec = _record()
        del rec["company"]
        _patch_scrape([rec])
        result = jobspy.search("Test Engineer")
        assert result[0]["firma"] == "AstraZeneca GmbH"
