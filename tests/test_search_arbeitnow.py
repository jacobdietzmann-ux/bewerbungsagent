"""Tests für den Arbeitnow-Provider (kostenlose API, kein Schlüssel)."""

from __future__ import annotations

import pytest

from bewerbungsagent.search import arbeitnow


class _Resp:
    def __init__(self, payload, status: int = 200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _job(**over) -> dict:
    job = {
        "title": "Testingenieur (m/w/d)",
        "company_name": "Acme GmbH",
        "location": "München",
        "url": "https://www.arbeitnow.com/jobs/companies/acme/1",
        "description": "<p>Kurzfassung</p>",
    }
    job.update(over)
    return job


class TestArbeitnow:
    def test_filtert_nach_ort_und_entfernt_html(self, monkeypatch):
        payload = {"data": [_job(),
                            _job(location="Hamburg", url="https://x/2")]}
        monkeypatch.setattr(arbeitnow.requests, "get",
                            lambda *a, **k: _Resp(payload))

        jobs = arbeitnow.search(max_pages=1)

        assert len(jobs) == 1
        assert jobs[0]["ort"] == "München"
        assert "<p>" not in jobs[0]["snippet"]
        assert jobs[0]["quelle"] == "Arbeitnow"
        # Kein Volltext: Arbeitnow liefert nur eine Kurzfassung. Der
        # Browser-Fetch muss diese Stellen nachladen.
        assert jobs[0]["beschreibung"] == ""

    def test_filter_abschaltbar(self, monkeypatch):
        payload = {"data": [_job(location="Hamburg")]}
        monkeypatch.setattr(arbeitnow.requests, "get",
                            lambda *a, **k: _Resp(payload))

        jobs = arbeitnow.search(max_pages=1, only_near_munich=False)

        assert len(jobs) == 1

    def test_duplikate_ueber_seiten_entfallen(self, monkeypatch):
        payload = {"data": [_job()]}
        monkeypatch.setattr(arbeitnow.requests, "get",
                            lambda *a, **k: _Resp(payload))

        jobs = arbeitnow.search(max_pages=3)

        assert len(jobs) == 1

    def test_leere_seite_beendet_die_schleife(self, monkeypatch):
        calls: list[int] = []

        def _get(_url, params=None, **_k):
            calls.append((params or {}).get("page"))
            return _Resp({"data": []})

        monkeypatch.setattr(arbeitnow.requests, "get", _get)

        assert arbeitnow.search(max_pages=5) == []
        assert calls == [1]

    def test_http_fehler_liefert_leere_liste(self, monkeypatch):
        monkeypatch.setattr(arbeitnow.requests, "get",
                            lambda *a, **k: _Resp({}, status=503))
        assert arbeitnow.search(max_pages=2) == []
