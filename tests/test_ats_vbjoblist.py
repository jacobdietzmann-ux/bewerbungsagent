"""Tests für die ATS-Quelle ``vbjoblist`` (ALTEN/OSB-JobScout, JSON-Endpunkt).

Der Endpunkt liefert 10 Stellen pro Blatt als JSON; geprüft wird hier das, was
im Live-Betrieb schiefgehen kann: HTML-escaped Volltext, Gehaltsformat,
Blättern über ``offset``/``cnt``, Dubletten über mehrere Orte und der
Umkreis-Vorfilter.
"""

from __future__ import annotations

import json

import pytest

from bewerbungsagent.search import ats

API = "https://beispiel.test/jobs?eID=txVbJoblistAjaxDispatcher&targetAction=jobs-list"


def _raw(**kw):
    base = {
        "id": "1",
        "titel": "Testingenieur (all gender)",
        "arbeitsort": "München",
        "stellenlink": "https://jobs.beispiel.test/job/view/1",
        # HTML-escaped, wie es der Endpunkt liefert (Volltext > 200 Zeichen,
        # sonst verwirft ``_job`` ihn als unbrauchbar kurzen Text).
        "volltext": "&lt;p&gt;" + "Teste &amp;amp; dokumentiere. " * 12 + "&lt;/p&gt;",
        "salaryMin": "35000",
        "salaryMax": "45000",
    }
    base.update(kw)
    return base


class _Resp:
    def __init__(self, payload: dict):
        self._payload = payload
        self.text = json.dumps(payload)

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def _fake_get(monkeypatch, payloads, calls):
    """Antwortet der Reihe nach mit ``payloads`` und protokolliert die Parameter."""

    def fake(url, params=None, headers=None, timeout=None):
        calls.append(dict(params or {}))
        index = min(len(calls) - 1, len(payloads) - 1)
        return _Resp(payloads[index])

    monkeypatch.setattr(ats.requests, "get", fake)


class TestVbjoblist:
    def test_parst_felder_und_bereinigt_texte(self, monkeypatch):
        calls: list[dict] = []
        _fake_get(monkeypatch, [{"xmldata": [_raw()], "cnt": 1}], calls)

        jobs = ats.vbjoblist(API, "ALTEN Consulting Services",
                             work_locations=["München"])

        assert len(jobs) == 1
        job = jobs[0]
        assert job["titel"] == "Testingenieur (all gender)"
        assert job["ort"] == "München"
        assert job["url"] == "https://jobs.beispiel.test/job/view/1"
        # ``quelle`` bleibt „ATS“: nur so greifen die Direktquellen-Ausnahmen
        # in ``search.add`` (Übersichtsseiten-/Host-Filter).
        assert job["quelle"] == "ATS"
        assert job["gehalt"] == "35.000–45.000 €"
        assert job["gehalt_quelle"] == "Anzeige"
        # HTML-escaped Volltext: Tags dürfen nicht als Text in der Beschreibung landen.
        assert "<p>" not in job["beschreibung"]
        assert "&lt;" not in job["beschreibung"]
        assert "Teste & dokumentiere." in job["beschreibung"]
        assert calls[0]["workLocation"] == "München"

    def test_filtert_ort_und_dedupliziert(self, monkeypatch):
        calls: list[dict] = []
        page = {"xmldata": [
            _raw(),
            _raw(id="2", arbeitsort="Berlin",
                 stellenlink="https://jobs.beispiel.test/job/view/2"),
            # gleiche Anzeige, zweiter Ort → darf nicht doppelt im Ergebnis sein
            _raw(id="1", arbeitsort="München"),
        ], "cnt": 3}
        _fake_get(monkeypatch, [page], calls)

        jobs = ats.vbjoblist(API, "ALTEN", work_locations=["München"])

        assert [j["url"] for j in jobs] == ["https://jobs.beispiel.test/job/view/1"]

    def test_blaettert_ueber_offset_bis_cnt(self, monkeypatch):
        calls: list[dict] = []
        seite1 = {"xmldata": [_raw(id=str(i), stellenlink=f"https://jobs.beispiel.test/job/view/{i}")
                              for i in range(10)], "cnt": 13}
        seite2 = {"xmldata": [_raw(id=str(i), stellenlink=f"https://jobs.beispiel.test/job/view/{i}")
                              for i in range(10, 13)], "cnt": 13}
        _fake_get(monkeypatch, [seite1, seite2], calls)

        jobs = ats.vbjoblist(API, "ALTEN", work_locations=["München"], max_pages=5)

        assert len(jobs) == 13
        assert [c["offset"] for c in calls] == [0, 10]

    def test_respektiert_max_jobs(self, monkeypatch):
        calls: list[dict] = []
        seite = {"xmldata": [_raw(id=str(i), stellenlink=f"https://jobs.beispiel.test/job/view/{i}")
                             for i in range(10)], "cnt": 100}
        _fake_get(monkeypatch, [seite], calls)

        jobs = ats.vbjoblist(API, "ALTEN", work_locations=["München"], max_jobs=4)

        assert len(jobs) == 4
        assert len(calls) == 1

    def test_ohne_api_url_fehler(self):
        with pytest.raises(ValueError):
            ats.vbjoblist("", "ALTEN")

    def test_gehalt_einzelwert_und_fehlend(self, monkeypatch):
        calls: list[dict] = []
        payload = {"xmldata": [
            _raw(salaryMin="55000", salaryMax="55000"),
            _raw(id="2", stellenlink="https://jobs.beispiel.test/job/view/2",
                 salaryMin="", salaryMax=""),
        ], "cnt": 2}
        _fake_get(monkeypatch, [payload], calls)

        jobs = ats.vbjoblist(API, "ALTEN", work_locations=["München"])

        assert jobs[0]["gehalt"] == "55.000 €"
        assert "gehalt" not in jobs[1]
