"""Tests für die Relevanz-Triage (``triage.py``).

Der Klassifikator entscheidet, ob eine gefundene Stelle überhaupt in den
Bestand darf. Zwei Fehlerarten sind unterschiedlich teuer:

* **False Positive** (Lärm bleibt drin) kostet nur einen Eintrag, den der Fit
  später aussortiert.
* **False Negative** (echte Ingenieursrolle wird verworfen) kostet eine echte
  Bewerbungschance — und fällt nicht auf, weil die Stelle einfach fehlt.

Deshalb ist die Liste der echten Rollen unten absichtlich groß und die Regel
„im Zweifel behalten" (``unsure`` statt ``reject``) bewusst gewählt.
"""

from __future__ import annotations

import pytest

from bewerbungsagent.triage import REJECT, RELEVANT, UNSURE, classify, split, verdict_for


class TestLaermWirdAbgelehnt:
    """Eindeutig andere Domänen — dürfen nie im Bestand landen."""

    @pytest.mark.parametrize("titel", [
        # Vertrieb / Verkauf
        "Head of International Sales (m/w/d)",
        "Gebietsverkaufsleiter/in im Außendienst (m/w/d)",
        "Sales Service Coordinator (m/w/d)",
        "Account Manager (m/w/d) Defence",
        # Marketing / E-Commerce
        "Manager Digitales Marketing und E-Commerce (m/w/d)",
        "Manager Amazon* - E-Commerce",
        "Social Media Manager (m/w/d)",
        # Finanzen / Rechnungswesen
        "Buchhalter (m/w/d)",
        "Controlling Specialist - Preisprüfer (m/w/d)",
        "Finance Manager (m/w/d)",
        # Personal / Recht / Verwaltung
        "Sachbearbeiter Personalwesen",
        "Jurist (m/w/d) Vertragsrecht",
        "Team Lead Operativer Einkauf",
        # Gastronomie
        "Commis de Cuisine (m/w/d)",
        "Koch (m/w/d)",
        "Servicekraft (m/w/d)",
        # Fahren / Transport
        "Taxifahrer (m/w/d) - Bad Wiessee",
        "VIP Chauffeur (m/w/d) mit Busführerschein",
        "Berufskraftfahrer (m/w/d)",
        "Lagerlogistik Mitarbeiter (m/w/d)",
        # Pflege / Soziales
        "Altenpfleger (m/w/d)",
        "Erzieher (m/w/d)",
        # Handwerk / Fertigung
        "Karosserie- und Fahrzeugbaumechaniker (m/w/d)",
        "Industriemechaniker (m/w/d)",
        # Immobilien / Bank
        "Immobilienkaufmann (m/w/d)",
        "Filialleiter (m/w/d) Bank",
        # Compliance / Exportkontrolle
        "Export Control Specialist (m/w/d)",
        # Pharmazie / GMP
        "GMP Consultant (m/w/d)",
        # IT-Betrieb
        "IT Service & Application Consultant (m/w/d)",
        # Prüfungswesen (Examen, nicht Softwaretest)
        "Prüfungskoordinator:in telc",
        # Fahrerrolle (Fahrzeug ist autonom, der Job bleibt Fahren)
        "Testfahrer für autonome Fahrzeuge",
    ])
    def test_domaenenfremd(self, titel):
        assert classify(titel).label == REJECT

    @pytest.mark.parametrize("titel", [
        "Werkstudent (m/w/d) Testautomatisierung",
        "Working Student - Software Engineering (m/f/d)",
        "Praktikant Kommunikationsdesign (m/w/d)",
        "Auszubildender Werkzeugmechaniker (m/w/d)",
        "Intern, Customer Test Coordination",
    ])
    def test_studentenrollen(self, titel):
        assert classify(titel).label == REJECT

    def test_grund_ist_nachvollziehbar(self):
        v = classify("Taxifahrer (m/w/d)")
        assert v.is_reject
        assert v.reason, "der Grund darf nicht leer sein"


class TestEchteRollenBleiben:
    """Der teure Fehler: eine Ingenieursrolle fälschlich verwerfen."""

    @pytest.mark.parametrize("titel", [
        "Senior Test Engineer (m/f/d)",
        "System Test Engineer (m/f/d)",
        "Software Test Engineer (m/w/d)",
        "Test Automation Engineer (all genders)",
        "HiL Test Engineer",
        "Flight Test & Field Systems Engineer C-UAS (m/f/d)",
        "Testmanager (m/w/d)",
        "Testkoordinator (m/w/d)",
        "Validierungsingenieur Gesamtfahrzeug",
        "Erprobungsingenieur Gesamtfahrzeug Inbetriebnahme",
        "Absicherungsingenieur (m/w/d)",
        "Qualitätsingenieur (m/w/d)",
        "Prüfstandsingenieur (m/w/d)",
        "Messtechniker (m/w/d)",
        "Qualification / Verification Engineer (m/w/x) Aerospace",
        "HW/SW Integration Engineer (m/f/d)",
        "Embedded Software Engineer (m/f/d)",
        "Requirements Engineer (m/w/d)",
        "Systemingenieur Verteidigungsindustrie",
        "Systems Safety Engineer (m/f/d)",
        "SOTIF Expert",
        "SDV Expert in für SDV ADAS/AD Homologation (all genders)",
        "Data Engineer (m/w/d)",
        "AI Solution Architect - Agentic AI & Foundation Models",
    ])
    def test_technische_rollen_sind_nicht_reject(self, titel):
        assert classify(titel).label != REJECT

    def test_studentenmuster_kein_fehltreffer(self):
        """„internal“/„Systems“ dürfen keine Studentenrolle vortäuschen."""
        for titel in ("Internal Systems Engineer", "Systems Safety Engineer",
                      "Senior Ground Test Engineer (All Genders)"):
            assert classify(titel).label != REJECT


class TestUnsureIstDerSichereAusgang:
    """Bei unklarer Lage wird behalten, nicht verworfen."""

    def test_fuehrung_ohne_techniksignal(self):
        assert classify("Teamleitung").label == UNSURE

    def test_leerer_titel(self):
        assert classify(None).label == UNSURE
        assert classify("").label == UNSURE

    def test_beschreibung_kann_technik_belegen(self):
        """Ein unklarer Titel wird relevant, wenn der Text Technik nennt."""
        v = classify("Fachkraft Qualitätssicherung", beschreibung="HiL-Prüfstand und ECU-Tests")
        assert v.label == RELEVANT

    def test_beschreibung_ohne_technik_bleibt_unsure(self):
        v = classify("Fachkraft Qualitätssicherung", beschreibung="Wareneingang prüfen")
        assert v.label == UNSURE


class TestTechnischAberAndereDomaene:
    """Mischfälle bleiben im Bestand — der Fit entscheidet."""

    def test_sales_engineer(self):
        v = classify("Sales Engineer (m/w/d)")
        assert v.label == UNSURE
        assert "Sales" in v.reason

    def test_head_of_sales_ist_trotzdem_laerm(self):
        """Regression: ein Führungswort darf eine fremde Domäne nicht retten."""
        assert classify("Head of International Sales (m/w/d)").label == REJECT

    def test_finance_software_manager(self):
        assert classify("Head of Finance Systems, Data & Analytics").label == UNSURE


class TestSplit:
    def test_split_trennt_nur_reject(self):
        jobs = [
            {"titel": "Senior Test Engineer", "firma": "X"},
            {"titel": "Taxifahrer", "firma": "Y"},
            {"titel": "Teamleitung", "firma": "Z"},
        ]
        kept, rejected = split(jobs)
        assert len(kept) == 2
        assert len(rejected) == 1
        assert rejected[0]["titel"] == "Taxifahrer"

    def test_split_behaelt_unsure(self):
        kept, _ = split([{"titel": "Teamleitung", "firma": "Z"}])
        assert len(kept) == 1

    def test_verdict_for_job(self):
        v = verdict_for({"titel": "Taxifahrer", "firma": "Taxi GmbH"})
        assert v.is_reject


class TestFahrerassistenzIstTechnik:
    """Abgrenzung: „Fahrerassistenz" ist Technik, „Testfahrer" ein Fahrerjob.

    Beide enthalten „fahrer". Nur die Wortgrenze trennt sie — ohne sie würde
    eine ADAS-Rolle fälschlich verworfen (das teure False Negative).
    """

    @pytest.mark.parametrize("titel", [
        "Fahrerassistenz-Systementwickler (m/w/d)",
        "ADAS Fahrerassistenz Test Engineer",
        "Entwicklungsingenieur Fahrerassistenzsysteme",
        "Testingenieur Fahrerassistenz",
    ])
    def test_fahrerassistenz_bleibt_relevant(self, titel):
        assert classify(titel).label != REJECT

    @pytest.mark.parametrize("titel", [
        "Testfahrer (m/w/d)",
        "Testfahrer für autonome Fahrzeuge",
        "Berufskraftfahrer (m/w/d)",
    ])
    def test_fahrerjobs_werden_abgelehnt(self, titel):
        assert classify(titel).label == REJECT


class TestNutzerentscheidung:
    """Restfälle, die ein Regelwerk nicht prinzipiell entscheiden kann.

    „Sales Manager *Embedded*" nennt Technik, meint aber Vertrieb. Statt dafür
    Wörter anzuhäufen (Overfitting), entscheidet der Nutzer — dauerhaft und in
    der Konfiguration nachvollziehbar.
    """

    TITEL = "(Senior) Consultant Sicherheitsevaluierung (m/w/d)"

    def test_ohne_eintrag_bleibt_es_unsure(self):
        """Die Regel allein kann diesen Fall nicht entscheiden."""
        assert classify(self.TITEL).label == UNSURE

    def test_reject_eintrag_verwirft(self):
        v = classify(self.TITEL, reject_patterns=["Consultant Sicherheitsevaluierung"])
        assert v.is_reject
        assert "Nutzerentscheidung" in v.reason

    def test_keep_eintrag_schlaegt_reject(self):
        """Eine zu breite Reject-Regel darf nie eine Stelle verlieren."""
        v = classify(self.TITEL,
                     reject_patterns=["Consultant"],
                     keep_patterns=["Sicherheitsevaluierung"])
        assert v.label == RELEVANT
        assert "Nutzerentscheidung" in v.reason

    def test_keep_gewinnt_auch_gegen_regel_reject(self):
        """Selbst eine Studenten-/Domänenregel wird vom Nutzer überstimmt."""
        v = classify("Werkstudent Testautomatisierung", keep_patterns=["Werkstudent"])
        assert v.label == RELEVANT

    def test_gross_klein_egal(self):
        v = classify(self.TITEL, reject_patterns=["consultant sicherheitsevaluierung"])
        assert v.is_reject

    def test_leere_liste_wirkt_nicht(self):
        assert classify(self.TITEL, reject_patterns=[]) == classify(self.TITEL)
        assert classify(self.TITEL, reject_patterns=["", "  "]).label == UNSURE

    def test_projektleitung_versicherungs_software(self):
        titel = "Projektleitung Versicherungs-Software (all Genders)"
        assert classify(titel).label == UNSURE
        assert classify(titel, reject_patterns=["Projektleitung Versicherungs-Software"]).is_reject


class TestOverridesAusConfig:
    def test_liest_search_triage_reject(self):
        from bewerbungsagent.triage import verdict_for

        class _Cfg:
            def __init__(self):
                self.data = {"search": {"triage_reject": ["Sicherheitsevaluierung"]}}

        v = verdict_for({"titel": "(Senior) Consultant Sicherheitsevaluierung (m/w/d)"},
                        _Cfg())
        assert v.is_reject

    def test_ohne_config_keine_overrides(self):
        from bewerbungsagent.triage import verdict_for
        assert verdict_for({"titel": "Senior Test Engineer"}).label == RELEVANT
        assert verdict_for({"titel": "Teamleitung"}).label == UNSURE

    def test_fehlende_oder_kaputte_werte_sind_egal(self):
        from bewerbungsagent.triage import verdict_for
        for data in ({}, {"search": {}}, {"search": {"triage_reject": "kein-liste"}},
                     {"search": {"triage_reject": None}}):
            class _Cfg:
                def __init__(self, d):
                    self.data = d
            assert verdict_for({"titel": "Test Engineer"}, _Cfg(data)).label == RELEVANT
