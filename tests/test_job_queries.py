"""Tests für die lesenden Abfragen des MCP-Servers (ohne Produktiv-DB)."""

import json
import sqlite3
from datetime import date

import pytest

from bewerbungsagent import job_queries as q


@pytest.fixture
def apps():
    return [
        {"key": "a", "firma": "Renesas", "titel": "Testingenieur", "status": "rejected",
         "score": 80, "statusChangedAt": "2026-11-06", "beschreibung": "HIL und Python"},
        {"key": "b", "firma": "MTU", "titel": "Systemtest", "status": "sent", "score": 90,
         "statusChangedAt": "2026-10-01", "beschreibung": "x" * 3000},
        {"key": "c", "firma": "Alt", "titel": "Weg", "status": "neu", "score": None,
         "deleted": True, "statusChangedAt": "2026-11-07"},
    ]


def test_laedt_und_ueberlagert_nutzerfelder(tmp_path):
    db = tmp_path / "jobs.db"
    conn = sqlite3.connect(db)
    conn.execute("create table applications (key text, provider text, user text, updated_at text)")
    conn.execute("insert into applications values (?,?,?,?)",
                 ("k", json.dumps({"firma": "F", "status": "neu"}),
                  json.dumps({"status": "sent"}), "2026-11-08"))
    conn.commit()
    conn.close()
    assert q.lade_bewerbungen(db) == [
        {"firma": "F", "status": "sent", "key": "k", "updated_at": "2026-11-08"}]


def test_verbindung_kann_nicht_schreiben(tmp_path):
    db = tmp_path / "jobs.db"
    sqlite3.connect(db).close()
    conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("create table t (a)")
    conn.close()


def test_statistik_trennt_ausgeblendete(apps):
    s = q.statistik(apps)
    assert (s["gesamt"], s["sichtbar"], s["ausgeblendet"]) == (3, 2, 1)
    assert s["nach_status"] == {"rejected": 1, "sent": 1}


def test_suche_sortiert_und_filtert(apps):
    assert [t["key"] for t in q.suche(apps)["treffer"]] == ["b", "a"]
    assert [t["key"] for t in q.suche(apps, text="hil")["treffer"]] == ["a"]
    assert q.suche(apps, firma="mtu", min_score=95)["anzahl"] == 0
    assert q.suche(apps, mit_ausgeblendeten=True)["anzahl"] == 3


def test_suche_begrenzt_treffer_aber_nicht_anzahl(apps):
    ergebnis = q.suche(apps, limit=1)
    assert ergebnis["anzahl"] == 2
    assert len(ergebnis["treffer"]) == 1


def test_aenderungen_nach_zeitraum_und_status(apps):
    heute = date(2026, 11, 8)
    assert [t["key"] for t in q.aenderungen(apps, 7, heute=heute)["treffer"]] == ["a"]
    assert q.aenderungen(apps, 7, status="sent", heute=heute)["anzahl"] == 0


def test_details_kuerzt_beschreibung(apps):
    d = q.details(apps, "b")
    assert len(d["beschreibung"]) == q.MAX_BESCHREIBUNG
    assert d["beschreibung_gekuerzt"] is True
    assert q.details(apps, "fehlt") is None
