from bewerbungsagent.commute import ort_aus_text


def test_stadt_region_wie_bei_rohde_schwarz():
    text = ("Kontakt Sonja Kupfer Recruiting Manager Info Stadt/Region München (Deutschland) "
            "Einstiegslevel Berufserfahrene Beschäftigungsart Vollzeit")
    assert ort_aus_text(text) == "München"


def test_standort_mit_doppelpunkt():
    assert ort_aus_text("Wir bieten viel. Standort: Garching bei München, Vollzeit") == "Garching"


def test_praefix_ortsname():
    assert ort_aus_text("Einsatzort: Bad Tölz Vollzeit") == "Bad Tölz"


def test_schlagworte_sind_kein_ort():
    assert ort_aus_text("Standort: Remote Vollzeit") == ""
    assert ort_aus_text("Arbeitsort: Deutschland") == ""


def test_ort_im_fliesstext_ohne_beschriftung_zaehlt_nicht():
    assert ort_aus_text("Unser Hauptsitz ist in Berlin, wir suchen Tester.") == ""


def test_leer_und_none():
    assert ort_aus_text("") == ""
    assert ort_aus_text(None) == ""
