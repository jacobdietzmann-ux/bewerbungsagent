"""Tests für die deterministische Branchenzuordnung."""

from bewerbungsagent.industry import classify_industry


def test_explicit_industry_is_preserved():
    assert classify_industry({
        "branche": "Automotive (E-Mobilität)",
        "branche_quelle": "Quelle",
    }) == "Automotive (E-Mobilität)"


def test_industry_is_inferred_from_company_and_title():
    assert classify_industry({
        "firma": "Diehl Defence",
        "titel": "Testingenieur für Betriebssysteme",
    }) == "Defense / Wehrtechnik"
    assert classify_industry({
        "firma": "Bertrandt Group",
        "titel": "Versuchsingenieur für Hardwaretests",
    }) == "Engineering-Dienstleister"
    assert classify_industry({
        "firma": "ALTEN",
        "titel": "Test Engineer Hochvolt-Batteriesysteme – Automotive",
    }) == "Engineering-Dienstleister / Automotive"


def test_job_description_does_not_override_employer_industry():
    assert classify_industry({
        "firma": "Reinhausen",
        "titel": "Senior Testingenieur für HIL & PHIL Leistungselektronik",
        "beschreibung": "Zusammenarbeit mit Unternehmen aus Robotik und Bahn.",
    }) == "Energie / Leistungselektronik"


def test_previous_heuristic_branch_is_recalculated():
    assert classify_industry({
        "firma": "Reinhausen",
        "titel": "Testingenieur Leistungselektronik",
        "branche": "Robotik / Automation",
        "branche_quelle": "Heuristik",
    }) == "Energie / Leistungselektronik"


def test_unrecognized_industry_is_not_left_blank():
    assert classify_industry({"firma": "Beispiel GmbH", "titel": "Projektmanager"}) == "Nicht ermittelt"
