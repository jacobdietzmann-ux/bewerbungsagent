"""Tests für die Identitätsbildung (Firmen-Aliase, Rechtsformen).

Hintergrund: „NXP" und „NXP Semiconductors" sind dieselbe Anzeige; ohne
Alias entstanden zwei Einträge (einer davon blieb bei 100 %, während der
andere über das Rollen-Gate auf 60 % fiel).
"""

from __future__ import annotations

from bewerbungsagent.pipeline import _company_key, _identity


class TestCompanyKey:
    def test_rechtsform_zaehlt_nicht(self):
        assert _company_key("BWI GmbH") == _company_key("BWI")
        assert _company_key("Quantum-Systems GmbH") == _company_key("Quantum-Systems")

    def test_alias_fuehrt_zusammen(self):
        aliases = {"nxp semiconductors": "nxp"}
        assert _company_key("NXP Semiconductors", aliases) == "nxp"
        assert _company_key("NXP", aliases) == "nxp"

    def test_ohne_alias_bleiben_sie_verschieden(self):
        assert _company_key("NXP Semiconductors") != _company_key("NXP")


class TestIdentity:
    def test_gleiche_stelle_gleiche_identitaet(self):
        aliases = {"nxp semiconductors": "nxp"}
        a = _identity({"firma": "NXP Semiconductors", "titel": "Test Engineer (m/w/d)", "ort": "Munich"}, aliases)
        b = _identity({"firma": "NXP", "titel": "Test Engineer (m/w/d)", "ort": "München"}, aliases)
        assert a == b

    def test_gender_tags_zaehlen_nicht(self):
        a = _identity({"firma": "MicroNova AG", "titel": "Produktmanager (m/w/x) Testautomatisierung", "ort": "Vierkirchen"})
        b = _identity({"firma": "MicroNova AG", "titel": "Produktmanager Testautomatisierung m/w/d", "ort": "Vierkirchen"})
        assert a == b

    def test_synonym_fuehrt_product_owner_zusammen(self):
        synonyms = {"product owner": "produktmanager"}
        a = _identity({"firma": "MicroNova AG", "titel": "Product Owner Testautomatisierung m/w/d", "ort": "München"}, synonyms=synonyms)
        b = _identity({"firma": "MicroNova AG", "titel": "Produktmanager (m/w/x) Testautomatisierung", "ort": "Vierkirchen"}, synonyms=synonyms)
        assert a[:2] == b[:2]

    def test_andere_stelle_andere_identitaet(self):
        a = _identity({"firma": "NXP", "titel": "Test Engineer", "ort": "München"})
        b = _identity({"firma": "NXP", "titel": "System Engineer", "ort": "München"})
        assert a != b
