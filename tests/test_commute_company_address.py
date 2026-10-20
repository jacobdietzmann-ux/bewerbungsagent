"""Firmenadresse statt Stadtmittelpunkt, wenn die Anzeige nur „München" nennt.

Der Pendelweg zum Stadtmittelpunkt kann um die halbe Stadt danebenliegen. Liegt
nur eine Stadt als Arbeitsort vor, wird deshalb die echte Firmenadresse gesucht;
findet sich keine, bleibt es beim Stadt-Geocoding.
"""

from __future__ import annotations

from bewerbungsagent import commute
from bewerbungsagent.commute import _company_address, is_city_only


class TestIsCityOnly:
    def test_stadt_ohne_nummer(self):
        assert is_city_only("München") is True

    def test_strasse_mit_hausnummer(self):
        assert is_city_only("Karl-Hammerschmidt-Straße 34, Aschheim") is False

    def test_plz_zaehlt_als_adresse(self):
        assert is_city_only("80992 München") is False

    def test_leer(self):
        assert is_city_only("") is False


class _FakeGeocoder:
    def __init__(self, treffer: dict[str, dict | None]):
        self.treffer = treffer
        self.queries: list[str] = []

    def search_one(self, query, *, addressdetails=False, extra_params=None):
        self.queries.append(query)
        return self.treffer.get(query)


def _item(**over) -> dict:
    item = {
        "lat": "48.15",
        "lon": "11.68",
        "type": "company",
        "display_name": "Beispiel GmbH, Musterstraße 1, München",
        "address": {"road": "Musterstraße", "house_number": "1",
                    "postcode": "80331", "city": "München"},
    }
    item.update(over)
    return item


class TestCompanyAddress:
    def test_uebernimmt_strasse_und_plz(self):
        geo = _FakeGeocoder({"Beispiel GmbH, München": _item()})
        res = _company_address(geo, "Beispiel GmbH", "München", {})
        assert res["strasse"] == "Musterstraße 1"
        assert res["plz"] == "80331"
        assert res["lat"] == 48.15

    def test_stadtmittelpunkt_ist_kein_gewinn(self):
        geo = _FakeGeocoder({
            "Beispiel GmbH, München": _item(type="city", address={"city": "München"}),
            "Beispiel GmbH": _item(type="administrative", address={"city": "München"}),
        })
        assert _company_address(geo, "Beispiel GmbH", "München", {}) is None

    def test_unsinnig_kurzer_strassenname_wird_verworfen(self):
        """„T&S" traf in OSM ein Gebäude namens „S" — kein Arbeitsort."""
        geo = _FakeGeocoder({
            "Beispiel GmbH, München": _item(address={"road": "S", "postcode": "80809",
                                                     "city": "München"}),
        })
        assert _company_address(geo, "Beispiel GmbH", "München", {}) is None

    def test_andere_stadt_wird_verworfen(self):
        geo = _FakeGeocoder({
            "Beispiel GmbH, München": _item(address={"road": "Hauptstraße",
                                                     "postcode": "10115",
                                                     "city": "Berlin"}),
        })
        assert _company_address(geo, "Beispiel GmbH", "München", {}) is None

    def test_muenchener_umland_wird_akzeptiert(self):
        geo = _FakeGeocoder({
            "Beispiel GmbH, München": _item(address={"road": "Karl-Hammerschmidt-Straße",
                                                     "house_number": "34",
                                                     "postcode": "85609",
                                                     "city": "Aschheim"}),
        })
        res = _company_address(geo, "Beispiel GmbH", "München", {})
        assert res and res["ort"] == "Aschheim"

    def test_rechtsform_wird_als_variante_probiert(self):
        geo = _FakeGeocoder({"Beispiel, München": _item()})
        res = _company_address(geo, "Beispiel GmbH", "München", {})
        assert res is not None
        assert "Beispiel, München" in geo.queries

    def test_fehlschlag_wird_gecacht(self):
        geo = _FakeGeocoder({})
        cache: dict = {}
        assert _company_address(geo, "Beispiel GmbH", "München", cache) is None
        assert cache  # auch ``None`` wird gespeichert
        vorher = len(geo.queries)
        assert _company_address(geo, "Beispiel GmbH", "München", cache) is None
        assert len(geo.queries) == vorher  # kein zweiter API-Aufruf

    def test_ohne_firma_kein_aufruf(self):
        geo = _FakeGeocoder({})
        assert _company_address(geo, "", "München", {}) is None
        assert geo.queries == []


class TestEnrichUsesCompanyAddress:
    def test_stadt_wird_durch_firmenadresse_ersetzt(self, tmp_path, monkeypatch):
        klass = type("G", (), {
            "__init__": lambda self, *_a, **_k: None,
            "geocode": lambda self, _q: {"lat": 48.14, "lon": 11.57,
                                         "display_name": "München"},
            "search_one": lambda self, _q, **_k: _item(),
            "save": lambda self: None,
        })
        monkeypatch.setattr(commute, "_Geocoder", klass)
        monkeypatch.setattr(commute, "_route_driving",
                            lambda *_a: (12.3, 24))
        job = {"firma": "Beispiel GmbH", "ort": "München"}

        stats = commute.enrich_commute([job], tmp_path,
                                       "Musterstraße 1, 12345 Musterstadt")

        assert stats["address_resolved"] == 1
        assert job["office_adresse"] == "Musterstraße 1 80331 München"
        assert job["pendel_modus"] == "Auto"

    def test_strasse_in_anzeige_bleibt_unveraendert(self, tmp_path, monkeypatch):
        klass = type("G", (), {
            "__init__": lambda self, *_a, **_k: None,
            "geocode": lambda self, _q: {"lat": 48.14, "lon": 11.57,
                                         "display_name": "x"},
            "search_one": lambda self, *_a, **_k: (_ for _ in ()).throw(
                AssertionError("darf nicht aufgerufen werden")),
            "save": lambda self: None,
        })
        monkeypatch.setattr(commute, "_Geocoder", klass)
        monkeypatch.setattr(commute, "_route_driving", lambda *_a: (3.0, 12))
        job = {"firma": "Beispiel GmbH", "ort": "Musterstraße 1, 80331 München"}

        stats = commute.enrich_commute([job], tmp_path,
                                       "Musterstraße 1, 12345 Musterstadt")

        assert stats["address_resolved"] == 0
        assert job["pendelzeit_min"] == 12
