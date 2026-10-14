"""Tests für die Auswahl des tatsächlichen Orts aus Suchangaben."""

from bewerbungsagent.commute import resolve_office


def test_resolve_office_uses_city_not_state_or_country():
    assert resolve_office("Regensburg, Bavaria, Germany") == "Regensburg"


def test_resolve_office_does_not_geocode_a_country_as_the_workplace():
    assert resolve_office("Bavaria, Germany") == ""


def test_resolve_office_removes_nearby_city_qualifier():
    assert resolve_office("Gräfelfing bei München") == "Gräfelfing"
    assert resolve_office("Erding (bei München)") == "Erding"
