from bewerbungsagent.firmenwerte import GEHALTSZUFRIEDENHEIT, schluessel, zufriedenheit


def test_exakter_treffer_mit_rechtsform():
    assert zufriedenheit("ROHDE & SCHWARZ GmbH & Co. KG") == {"pct": 85, "n": 20}


def test_laengerer_name_traegt_eintrag_am_wortanfang():
    assert zufriedenheit("ALTEN Consulting Services GmbH")["pct"] == 48
    assert zufriedenheit("Akkodis Germany Tech Experts GmbH")["pct"] == 30
    assert zufriedenheit("FERCHAU – Connecting People and Technologies")["pct"] == 54


def test_unbekannte_oder_leere_firma_liefert_none():
    assert zufriedenheit("Unbekannt GmbH") is None
    assert zufriedenheit("") is None
    assert zufriedenheit(None) is None


def test_kein_treffer_mitten_im_namen():
    assert zufriedenheit("Neo Alten Systems") is None


def test_alle_schluessel_sind_normalisiert():
    for key in GEHALTSZUFRIEDENHEIT:
        assert schluessel(key) == key
