"""Tests für die Auswahl des tatsächlichen Orts aus Suchangaben."""

from bewerbungsagent.commute import resolve_office


def test_resolve_office_uses_city_not_state_or_country():
    assert resolve_office("Regensburg, Bavaria, Germany") == "Regensburg"


def test_resolve_office_does_not_geocode_a_country_as_the_workplace():
    assert resolve_office("Bavaria, Germany") == ""


def test_resolve_office_removes_nearby_city_qualifier():
    assert resolve_office("Gräfelfing bei München") == "Gräfelfing"
    assert resolve_office("Erding (bei München)") == "Erding"


def test_resolve_office_removes_near_qualifier_without_preposition():
    """„nahe München" war nicht abgedeckt — nur „bei".

    „Kaufering nahe München" blieb unverändert, war bei Nominatim nicht
    auflösbar und die Stelle hatte danach gar keinen Pendelweg. Damit umging sie
    die harte 30-Minuten-Grenze und bekam Unterlagen (Hilti, 76 %).
    """
    assert resolve_office("Kaufering nahe München") == "Kaufering"
    assert resolve_office("Weßling Nähe München") == "Weßling"
    assert resolve_office("Poing bei München") == "Poing"
    assert resolve_office("Gilching (bei München)") == "Gilching"
    assert resolve_office("Markt Schwaben Raum München") == "Markt Schwaben"


def test_resolve_office_keeps_a_bare_city_name():
    """Ohne Zusatz darf nichts abgeschnitten werden."""
    assert resolve_office("München") == "München"
    assert resolve_office("Kaufering") == "Kaufering"
