"""Tests für Wochenbudget, Firmenlimit, Pendelkulanz und Neufund-Filter."""

from __future__ import annotations

from datetime import datetime, timedelta

from bewerbungsagent.auswahl import (
    apply_limits,
    auto_docs_last_days,
    neufund_relevant,
    offene_pro_firma,
    shortlist,
    within_commute_grace,
)

JETZT = datetime(2026, 11, 1, 12, 0).astimezone()


def _key(name):
    return (name or "").lower().replace(" gmbh", "").strip()


def _job(firma, fit, titel="Testingenieur HiL (m/w/d)", **extra):
    return {"firma": firma, "titel": titel, "score": fit, **extra}


class TestPendelkulanz:
    def test_quantum_systems_31_min_bleibt(self):
        # Realfall: 82 % Fit, Gilching, 31 min bei Grenze 30 → wurde gelöscht.
        job = _job("Quantum-Systems GmbH", 82, "System Test Engineer (m/f/d)",
                   pendelzeit_min=31)
        assert within_commute_grace(job, limit=30, grace=10, min_fit=65)

    def test_genau_an_der_kulanzgrenze(self):
        assert within_commute_grace(_job("X", 80, pendelzeit_min=40), 30, 10, 65)
        assert not within_commute_grace(_job("X", 80, pendelzeit_min=41), 30, 10, 65)

    def test_innerhalb_der_grenze_ist_keine_kulanz(self):
        assert not within_commute_grace(_job("X", 90, pendelzeit_min=25), 30, 10, 65)

    def test_schwacher_fit_bekommt_keine_kulanz(self):
        assert not within_commute_grace(_job("X", 60, pendelzeit_min=32), 30, 10, 65)

    def test_unbekannte_pendelzeit(self):
        assert not within_commute_grace(_job("X", 90, pendelzeit_min=None), 30, 10, 65)
        assert not within_commute_grace(_job("X", 90, pendelzeit_min="?"), 30, 10, 65)

    def test_kulanz_null_schaltet_ab(self):
        assert not within_commute_grace(_job("X", 90, pendelzeit_min=31), 30, 0, 65)


class TestNeufund:
    def test_testrolle_mit_fit_ist_relevant(self):
        assert neufund_relevant(_job("X", 72, "Senior Test Engineer"))

    def test_rauschen_aus_dem_bestand(self):
        for titel in ("Director Sustainability Data & AI Products (f/m/div)",
                      "Digital IP Design Engineer (f/m/d)",
                      "Konstrukteur Elektrisch (w/m/d)",
                      "Deployment Strategist - German Speaking"):
            assert not neufund_relevant(_job("X", 70, titel)), titel

    def test_testrolle_unter_50_ist_nicht_relevant(self):
        assert not neufund_relevant(_job("X", 40, "Testingenieur (m/w/d)"))


class TestLimits:
    def test_wochenbudget_nimmt_die_besten(self):
        kandidaten = [_job(f"F{i}", fit) for i, fit in enumerate([72, 95, 80, 88])]
        ok, budget, firma = apply_limits(kandidaten, [], company_key=_key,
                                         max_per_week=2, max_per_company=None, now=JETZT)
        assert [j["score"] for j in ok] == [95, 88]
        assert [j["score"] for j in budget] == [80, 72]
        assert firma == []

    def test_bereits_erzeugte_unterlagen_zaehlen_gegen_budget(self):
        bestand = [{"unterlagen_erzeugt_am": (JETZT - timedelta(days=d)).isoformat()}
                   for d in (1, 3, 9)]
        assert auto_docs_last_days(bestand, JETZT) == 2
        ok, budget, _ = apply_limits([_job("A", 90), _job("B", 80)], bestand,
                                     company_key=_key, max_per_week=3,
                                     max_per_company=None, now=JETZT)
        assert len(ok) == 1 and len(budget) == 1

    def test_firmenlimit_mit_bestand(self):
        # ALTEN hatte 10 Bewerbungen gleichzeitig.
        bestand = [_job("ALTEN", 80, status="sent"),
                   _job("ALTEN", 75, status="docs", dokumente={"a": "x.pdf"}),
                   _job("ALTEN", 75, status="rejected")]
        assert offene_pro_firma(bestand, _key)["alten"] == 2
        ok, _, firma = apply_limits([_job("ALTEN", 99), _job("STARK", 90)], bestand,
                                    company_key=_key, max_per_week=None,
                                    max_per_company=2, now=JETZT)
        assert [j["firma"] for j in ok] == ["STARK"]
        assert [j["firma"] for j in firma] == ["ALTEN"]

    def test_firmenlimit_innerhalb_eines_laufs(self):
        kandidaten = [_job("Quantum-Systems GmbH", f) for f in (90, 85, 80)]
        ok, _, firma = apply_limits(kandidaten, [], company_key=_key,
                                    max_per_week=None, max_per_company=2, now=JETZT)
        assert len(ok) == 2 and len(firma) == 1

    def test_geloeschte_und_docs_ohne_dateien_zaehlen_nicht(self):
        bestand = [_job("A", 80, status="sent", deleted=True),
                   _job("A", 80, status="docs")]
        assert offene_pro_firma(bestand, _key)["a"] == 0

    def test_limits_abschaltbar(self):
        kandidaten = [_job("A", 80) for _ in range(5)]
        ok, _, _ = apply_limits(kandidaten, [], company_key=_key,
                                max_per_week=0, max_per_company=0, now=JETZT)
        assert len(ok) == 5


def test_shortlist():
    apps = [
        _job("A", 70, status="docs", dokumente={"x": "a.pdf"}),
        _job("B", 90, status="docs", dokumente={"x": "b.pdf"}, contact="Frau Muster"),
        _job("C", 95, status="sent", dokumente={"x": "c.pdf"}),
        _job("D", 99, status="docs"),
        _job("E", 85, status="docs", dokumente={"x": "e.pdf"}, deleted=True),
    ]
    liste = shortlist(apps, top=5)
    assert [s["firma"] for s in liste] == ["B", "A"]
    assert liste[0]["kontakt_fehlt"] is False
    assert liste[1]["kontakt_fehlt"] is True
