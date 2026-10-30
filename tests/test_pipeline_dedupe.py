"""Tests für die Dublettenprüfung im Zustands-Merge.

Hintergrund: Glassdoor listet dieselbe MicroNova-Stelle als „München", „Dachau"
und „Freising" — bei gleichem Titel entstanden sechs Einträge. Für bereits
beworbene Rollen gilt: gleiche Firma + gleicher Titel = dieselbe Stelle,
unabhängig vom Ort.
"""

from __future__ import annotations

from bewerbungsagent.pipeline import _merge_state


def _app(**kwargs) -> dict:
    basis = {"key": "a", "firma": "MicroNova AG", "titel": "Produktmanager Testautomatisierung",
             "ort": "Vierkirchen", "status": "sent", "pendel_modus": "Remote"}
    basis.update(kwargs)
    return basis


def test_gleiche_beworbene_stelle_anderer_ort_wird_uebersprungen():
    match = {"key": "b", "firma": "MicroNova AG", "titel": "Produktmanager Testautomatisierung",
             "ort": "Dachau", "score": 90, "pendel_modus": "Remote"}
    state = _merge_state({"applications": [_app()]}, [match])
    assert [a["key"] for a in state["applications"]] == ["a"]


def test_andere_firma_bleibt_eigener_eintrag():
    match = {"key": "c", "firma": "Andere GmbH", "titel": "Produktmanager Testautomatisierung",
             "ort": "Dachau", "score": 90, "pendel_modus": "Remote"}
    state = _merge_state({"applications": [_app()]}, [match])
    assert {a["key"] for a in state["applications"]} == {"a", "c"}


def test_gleiche_stelle_ohne_bewerbung_bleibt_ortsspezifisch():
    """Ohne sent/followup/interview bleibt der Ort Teil der Identität."""
    match = {"key": "d", "firma": "MicroNova AG", "titel": "Produktmanager Testautomatisierung",
             "ort": "Dachau", "score": 90, "pendel_modus": "Remote"}
    state = _merge_state({"applications": [_app(status="neu")]}, [match])
    assert {a["key"] for a in state["applications"]} == {"a", "d"}
