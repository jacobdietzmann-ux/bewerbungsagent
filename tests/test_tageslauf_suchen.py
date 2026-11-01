"""Tests für den Tageslauf mit mehreren Suchen.

Hintergrund: Der Tageslauf führte genau eine Suche aus. Markensuchen wie
„China-EV München" liefen separat und überschrieben dabei ``jobs.json``.
Jetzt kann sich eine gespeicherte Suche mit ``"daily": true`` einklinken; die
Treffer werden zusammengeführt und einmal geschrieben.
"""

from __future__ import annotations

import bewerbungsagent.saved_searches as saved
from bewerbungsagent.pipeline import _tageslauf_definitionen


def test_standard_und_daily_suchen(monkeypatch):
    monkeypatch.setattr(saved, "load_saved_searches", lambda config: [
        {"name": "Standard", "query_terms": ["Testingenieur"], "daily": True},
        {"name": "China-EV München", "daily": True, "query_terms": ["BYD", "NIO"],
         "location": "München", "providers": ["stepstone", "ats"],
         "ats_firmen": ["XPeng"]},
        {"name": "Nur manuell", "query_terms": ["CAD"]},
    ])
    defs = _tageslauf_definitionen(object())
    assert [name for name, _ in defs] == ["Standard", "China-EV München"]
    assert defs[0][1] is None                      # Standard kommt aus config.json
    assert defs[1][1]["ats_firmen"] == ["XPeng"]
    assert defs[1][1]["location"] == "München"


def test_ohne_daily_bleibt_nur_die_standard_suche(monkeypatch):
    monkeypatch.setattr(saved, "load_saved_searches", lambda config: [
        {"name": "Standard", "query_terms": ["a"]},
        {"name": "Manuell", "query_terms": ["b"]},
    ])
    assert [name for name, _ in _tageslauf_definitionen(object())] == ["Standard"]
