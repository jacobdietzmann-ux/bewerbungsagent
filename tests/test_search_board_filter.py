"""Tests für die Board-Auswahl einer gespeicherten Suche.

Hintergrund: Die Suche „China-EV München" fragt die Marken ab. Ohne Filter zog
der ``ats``-Provider alle Karriereseiten (Airbus, Infineon, HENSOLDT …) mit —
627 Funde, davon 2 zur eigentlichen Frage. Eine Suche soll auf ihre Firmen
zeigen können.
"""

from __future__ import annotations

from bewerbungsagent.saved_searches import to_definition
from bewerbungsagent.search import _filter_boards

BOARDS = [
    {"firma": "XPeng", "ats": "greenhouse", "board": "xpengmotors"},
    {"firma": "Airbus", "ats": "workday", "tenant": "ag", "site": "Airbus"},
    {"firma": "NIO", "ats": "workday", "tenant": "nio", "site": "NIO_Careers"},
]


def test_ohne_auswahl_bleiben_alle_boards():
    assert _filter_boards(BOARDS, None) == BOARDS


def test_auswahl_beschraenkt_auf_marke():
    treffer = _filter_boards(BOARDS, ["XPeng"])
    assert [b["firma"] for b in treffer] == ["XPeng"]


def test_auswahl_ignoriert_gross_kleinschreibung():
    assert [b["firma"] for b in _filter_boards(BOARDS, ["xpeng"])] == ["XPeng"]


def test_leere_auswahl_liefert_keine_boards():
    assert _filter_boards(BOARDS, []) == []


def test_gespeicherte_suche_gibt_board_auswahl_weiter():
    definition = to_definition({
        "name": "China-EV München",
        "query_terms": ["BYD", "NIO"],
        "location": "München",
        "providers": ["stepstone", "ats"],
        "ats_firmen": ["XPeng"],
    })
    assert definition["ats_firmen"] == ["XPeng"]
