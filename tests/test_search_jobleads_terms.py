"""Der JobLeads-Provider darf ohne eigene Begriffsliste nicht leerlaufen.

Hintergrund: ``jobleads_searches`` ist eine **zweite** Begriffsliste neben
``query_terms``. Bei der Aktivierung des Providers standen dort nur zwei
Einträge, während 6 nachweislich passende Stellen derselben Trefferliste nie
gefunden wurden — der Provider suchte also an den vorhandenen Begriffen vorbei.
Eine leere Liste wird deshalb als vergessene Pflege behandelt und mit den
allgemeinen ``query_terms`` aufgefüllt (begrenzt über ``jobleads_max_terms``).
"""

from __future__ import annotations

import json

import pytest

from bewerbungsagent.config import Config
from bewerbungsagent.profile import Profile
from bewerbungsagent.search import ats, run_search

FIXTURES = __import__("pathlib").Path(__file__).resolve().parent / "fixtures"


def _config(tmp_path, search: dict) -> Config:
    basis = {
        "enabled": True,
        "providers": ["jobleads"],
        "query_terms": ["Testingenieur", "System Test Engineer", "ADAS Test",
                        "HiL Test Engineer", "Testautomatisierung",
                        "QA Engineer", "Requirements Engineer"],
        "location": "München",
        "triage": False,
    }
    basis.update(search)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "profil-demo.json").write_text(
        (FIXTURES / "profil-demo.json").read_text(encoding="utf-8"), encoding="utf-8")
    cfg = {
        "profile_json": str(tmp_path / "profil-demo.json"),
        "data_dir": str(tmp_path / "data"),
        "output_dir": str(tmp_path / "output"),
        "search": basis,
    }
    (tmp_path / "config.json").write_text(json.dumps(cfg, ensure_ascii=False),
                                         encoding="utf-8")
    return Config(tmp_path / "config.json")


def _profile(tmp_path) -> Profile:
    return Profile(json.loads((tmp_path / "profil-demo.json").read_text(encoding="utf-8")))


@pytest.fixture
def aufrufe(monkeypatch):
    """Ersetzt den Netzwerkaufruf und protokolliert die gebauten Such-URLs."""
    protokoll: list[str] = []

    def fake(list_url, **kwargs):
        protokoll.append(list_url)
        return []

    monkeypatch.setattr(ats, "jobleads", fake)
    return protokoll


def _begriffe(urls: list[str]) -> list[str]:
    from urllib.parse import unquote
    return [unquote(u.split("/q/")[1].split("?")[0]) for u in urls]


def test_leere_liste_nutzt_die_allgemeinen_suchbegriffe(tmp_path, aufrufe):
    """Ohne ``jobleads_searches`` wird nicht stillschweigend nichts gesucht."""
    cfg = _config(tmp_path, {"jobleads_searches": []})
    run_search(cfg, _profile(tmp_path))
    gesucht = _begriffe(aufrufe)
    assert gesucht == ["Testingenieur", "System Test Engineer", "ADAS Test",
                       "HiL Test Engineer", "Testautomatisierung", "QA Engineer"]


def test_rueckfall_ist_begrenzt(tmp_path, aufrufe):
    """Nicht alle 18 Begriffe auf einmal — jede Suche kostet 25 Detailseiten."""
    cfg = _config(tmp_path, {"jobleads_searches": [],
                             "jobleads_max_terms": 2})
    run_search(cfg, _profile(tmp_path))
    assert len(aufrufe) == 2


def test_eigene_liste_hat_vorrang(tmp_path, aufrufe):
    """Eine gepflegte Liste wird nicht durch ``query_terms`` ersetzt."""
    cfg = _config(tmp_path, {"jobleads_searches": ["HiL Test Engineer"]})
    run_search(cfg, _profile(tmp_path))
    assert _begriffe(aufrufe) == ["HiL Test Engineer"]


def test_fertige_list_url_bleibt_unveraendert(tmp_path, aufrufe):
    """Kuratierte Suchen (Dict mit ``list_url``) gehen direkt durch."""
    url = ("https://www.jobleads.com/de/jobs/l/M%C3%BCnchen/q/Test?location_radius=30")
    cfg = _config(tmp_path, {"jobleads_searches": [{"list_url": url, "max_jobs": 5}]})
    run_search(cfg, _profile(tmp_path))
    assert aufrufe == [url]


def test_rueckfall_greift_nicht_ohne_begriffe(tmp_path, aufrufe):
    """Beide Listen leer: dann gibt es nichts zu suchen (kein Fehler)."""
    cfg = _config(tmp_path, {"jobleads_searches": [], "query_terms": []})
    jobs, errors, _rejected = run_search(cfg, _profile(tmp_path))
    assert jobs == []
    assert not [e for e in errors if "jobleads" in e.lower()]
    assert aufrufe == []


def test_default_konfiguration_kennt_die_obergrenze():
    from bewerbungsagent.config import DEFAULT_CONFIG
    assert DEFAULT_CONFIG["search"]["jobleads_max_terms"] == 6
