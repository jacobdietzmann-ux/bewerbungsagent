"""Glassdoor-Provider: aus dem Live-Ordner ins Repo geholt und angebunden (ADR-057)."""

from __future__ import annotations

import json

from bewerbungsagent import search
from bewerbungsagent.config import Config
from bewerbungsagent.search import glassdoor


def test_karte_wird_zerlegt():
    karte = {"id": "42", "titel": "Testingenieur HiL (m/w/d)", "url": "https://www.glassdoor.de/job-listing/x",
             "firma": "Acme",
             "zeilen": ["Acme", "4,1", "Testingenieur HiL (m/w/d)", "München",
                        "60.000 € – 75.000 € (Schätzung)",
                        "Sie testen Steuergeräte am HiL-Prüfstand und automatisieren Testfälle "
                        "mit Python für ADAS-Funktionen.",
                        "Kenntnisse und Fähigkeiten: HiL, Python", "Anzeige", "3 T."]}
    job = glassdoor._parse(karte, "München")
    assert job["firma"] == "Acme"
    assert job["ort"] == "München"
    assert job["quelle"] == "Glassdoor"
    assert job["gehalt"].startswith("60.000")
    assert "HiL-Prüfstand" in job["beschreibung"]
    assert "Kenntnisse und Fähigkeiten: HiL, Python" in job["beschreibung"]


def test_karte_ohne_titel_entfaellt():
    assert glassdoor._parse({"titel": "", "zeilen": []}, "München") is None


def test_url_nur_mit_erlaubten_parametern():
    url = glassdoor.search_url("Testingenieur", "München", radius=20, min_salary=60000,
                               sort="date_desc")
    assert url.startswith("https://www.glassdoor.de/")
    assert "page" not in url and "offset" not in url


def test_provider_bekommt_umkreis_und_gehalt(tmp_path, monkeypatch, demo_profile):
    pfad = tmp_path / "config.json"
    pfad.write_text(json.dumps({
        "data_dir": str(tmp_path / "data"),
        "search": {"enabled": True, "providers": ["glassdoor"], "query_terms": ["Testingenieur"],
                   "location": "München", "glassdoor_radius": 12,
                   "glassdoor_min_salary": 69000, "glassdoor_max_results": 5},
    }), encoding="utf-8")
    gerufen = {}

    def suche(terms, **kw):
        gerufen.update(kw, terms=terms)
        return [{"titel": "Testingenieur", "firma": "Acme", "ort": "München",
                 "url": "https://www.glassdoor.de/job-listing/1", "quelle": "Glassdoor",
                 "beschreibung": "HiL Test"}]

    monkeypatch.setattr(glassdoor, "available", lambda: True)
    monkeypatch.setattr(glassdoor, "search", suche)
    jobs, fehler, _ = search.run_search(Config(pfad), demo_profile)
    assert fehler == []
    assert gerufen["radius"] == 12 and gerufen["min_salary"] == 69000
    assert "max_salary" not in gerufen
    assert gerufen["max_results"] == 5
    # Glassdoor-URLs sind echte Anzeigen, kein Aggregator-Rauschen.
    assert [j["firma"] for j in jobs] == ["Acme"]
