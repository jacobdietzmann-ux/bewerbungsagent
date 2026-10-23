"""Regression: dieselbe Anzeige unter anderer URL darf keine zweite Bewerbung erzeugen.

Der Fall ist real aufgetreten: Advantest „R&D Engineer - AI Integration" lag über
JobLeads im Bestand (Status ``sent``) und wurde von jobs.labo.de erneut gefunden.
Weil ``_merge_state`` nur nach ``key`` (URL) vergleicht, entstand ein zweiter
Eintrag mit eigenen Unterlagen — im Dashboard zwei Zeilen für eine Stelle, und
im schlimmsten Fall zwei Bewerbungen.

Der Schlüssel ist deshalb Firma + Titel + Ort, wobei „Munich"/„Muenchen" als
„München" zählt (die Börsen übersetzen den Ort).
"""

from __future__ import annotations

import pytest

from bewerbungsagent.pipeline import _identity, _merge_state


def _app(key: str, firma="Advantest Europe GmbH",
         titel="R&D Engineer - AI Integration (m/f/d)", ort="München", **extra) -> dict:
    return {"key": key, "firma": firma, "titel": titel, "ort": ort, **extra}


def test_identitaet_ignoriert_die_url():
    a = _app("https://www.jobleads.com/de/job/x")
    b = _app("https://jobs.labo.de/job/y")
    assert _identity(a) == _identity(b)


@pytest.mark.parametrize("ort", ["München", "Munich", "MUENCHEN", "munchen"])
def test_identitaet_normalisiert_den_ortsnamen(ort):
    assert _identity(_app("k", ort=ort)) == _identity(_app("k2", ort="München"))


def test_verschiedene_orte_bleiben_verschieden():
    """Zwei Standorte derselben Firma sind zwei Stellen."""
    assert (_identity(_app("k", ort="München"))
            != _identity(_app("k2", ort="Ottobrunn")))


def test_kein_zweiter_eintrag_fuer_dieselbe_stelle():
    bestand = {"applications": [_app("https://www.jobleads.com/de/job/x",
                                    status="sent", sentAt="2026-10-23")]}
    match = {**_app("https://jobs.labo.de/job/y", ort="Munich"), "score": 72}
    state = _merge_state(bestand, [match])
    assert len(state["applications"]) == 1
    assert state["applications"][0]["status"] == "sent"
    assert state["neu"] == []


def test_andere_stelle_kommt_weiterhin_durch():
    bestand = {"applications": [_app("k1", status="sent")]}
    match = {**_app("k2", titel="Systemtest- und Integrationsingenieur (aG)"),
             "score": 98}
    state = _merge_state(bestand, [match])
    assert len(state["applications"]) == 2
    assert state["neu"]


def test_gleiche_url_wird_aktualisiert_nicht_dupliziert():
    bestand = {"applications": [_app("k1", status="research")]}
    match = {**_app("k1"), "score": 91}
    state = _merge_state(bestand, [match])
    assert len(state["applications"]) == 1
    assert state["applications"][0]["score"] == 91


def test_dublette_im_selben_lauf_wird_ebenfalls_verhindert():
    """Zwei Quellen liefern dieselbe Stelle im selben Lauf."""
    match_a = {**_app("https://a.test/1"), "score": 72}
    match_b = {**_app("https://b.test/2", ort="Munich"), "score": 72}
    state = _merge_state({"applications": []}, [match_a, match_b])
    assert len(state["applications"]) == 1
