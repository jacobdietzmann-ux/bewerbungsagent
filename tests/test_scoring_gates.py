"""Tests für die drei Scoring-Korrekturen aus der x1F-Analyse.

Hintergrund: eine Stelle „Lead Integration Engineer (m/w/d) im Team Technology
Consulting" erreichte 84 %, obwohl sie Integrationsarchitektur und Beratung
beschreibt (Kafka, REST/SOAP, Middleware, API-Governance) und keine
Test-/Verifikationsrolle ist. Zerlegung des Scores:

    0 (Titel) + 52 (13 body_hits) + 22 (11 word_hits) + 10 (Ortsbonus) = 84

Drei Ursachen, drei Korrekturen:

* **A – Rollen-Gate**: ``\\bintegration\\w*`` allein genügte als Rollensignal.
  Jetzt sind Architektur-/Beratungstitel ausgeschlossen, solange kein
  Test-/Verifikationskern im Titel steht. ``integration`` bleibt drin, weil
  „Payload Integration Engineer" eine gewünschte Rolle ist.
* **C – Ortsbonus**: „bundesweit, Düsseldorf, … München" wurde wegen des
  Teilstrings „münchen" und des Markers „bundesweit" als ``Remote`` gewertet und
  gab pauschal +10, obwohl der Einsatzort offen ist. Mehr-Standort-Angaben
  geben jetzt 0.
* **D – Nachvollziehbarkeit**: ``word_hits`` floss in den Score, wurde aber nie
  gespeichert — der Score war nicht nachrechenbar.
"""

from __future__ import annotations

from bewerbungsagent.commute import is_multi_location
from bewerbungsagent.matching import has_role_signal, location_bonus_for, score_job
from bewerbungsagent.pipeline import _merge_state

# Der Ortsstring der x1F-Anzeige, der den Bonus auslöste.
X1F_ORT = ("bundesweit, Düsseldorf, Frankfurt am Main, Hamburg, Essen, Köln, "
           "Stuttgart, Berlin, Leipzig, München")


class TestRollenGate:
    """A — Architektur/Beratung ist keine Testrolle."""

    def test_beratungs_integrationsrolle_faellt_durch(self):
        assert not has_role_signal("Lead Integration Engineer (m/w/d) im Team Technology "
                                   "Consulting")

    def test_architekt_rolle_faellt_durch(self):
        assert not has_role_signal("Systems Architect ECU Autonomous Driving")

    def test_payload_integration_bleibt_erlaubt(self):
        assert has_role_signal("Senior Payload Integration Engineer - UGV Platforms (m/w/d)")

    def test_hw_sw_integration_bleibt_erlaubt(self):
        assert has_role_signal("HW/SW Integration Engineer (m/f/d)")

    def test_ai_integration_bleibt_erlaubt(self):
        assert has_role_signal("R&D Engineer - AI Integration (m/f/d)")

    def test_test_architekt_bleibt_erlaubt(self):
        """Architektur schließt nur aus, wenn kein Testkern im Titel steht."""
        assert has_role_signal("Test-Architekt (m/w/d)")
        assert has_role_signal("Architekt für Testautomatisierung")

    def test_klassische_testrolle_unveraendert(self):
        assert has_role_signal("Systemtestingenieur (m/w/d)")
        assert has_role_signal("Verification Engineer")

    def test_thesis_im_bereich_integration_bleibt_erlaubt(self):
        """Kein Architektur-/Beratungswort — Verhalten unverändert."""
        assert has_role_signal("Abschlussarbeit im Bereich System Integration (m/w/d)")


class TestMehrStandort:
    """C — Mehr-Standort-Angaben belegen keine Nähe."""

    def test_bundesweite_aufzaehlung_ist_mehrort(self):
        assert is_multi_location(X1F_ORT)

    def test_einzelner_ort_ist_kein_mehrort(self):
        assert not is_multi_location("München")
        assert not is_multi_location("Poing bei München")
        assert not is_multi_location("")

    def test_mehrere_standorte_marker(self):
        assert is_multi_location("Mehrere Standorte in Deutschland")
        assert is_multi_location("Wechselnde Einsatzorte")

    def test_land_und_bundesland_sind_kein_zweiter_standort(self):
        assert not is_multi_location("München, Bayern, Deutschland")
        assert not is_multi_location("Garching b. Muenchen, Bayern, Germany")
        assert not is_multi_location("Ottobrunn, Bavaria, Germany")

    def test_zwei_staedte_sind_mehrort(self):
        assert is_multi_location("München, Berlin")
        assert is_multi_location("Munich, Germany, San Diego, California")

    def test_strassenadresse_ist_ein_standort(self):
        assert not is_multi_location("Landaubogen 1, 81373 München (Sendling)")
        assert not is_multi_location("Willy-Messerschmitt-Straße 1, 82024 Taufkirchen")

    def test_nur_nahe_standorte_behalten_den_bonus(self):
        from bewerbungsagent.commute import all_locations_near_munich
        assert all_locations_near_munich("München, Starnberg")
        assert not all_locations_near_munich(X1F_ORT)

    def test_mehrort_bekommt_keinen_bonus(self):
        job = {"titel": "Lead Integration Engineer", "ort": X1F_ORT,
               "pendel_modus": "Remote"}
        assert location_bonus_for(job, "München") == 0

    def test_echtes_remote_bekommt_weiterhin_bonus(self):
        job = {"titel": "Testingenieur", "ort": "Remote", "pendel_modus": "Remote"}
        assert location_bonus_for(job, "München") == 10

    def test_x1f_score_ohne_ortsbonus(self, demo_profile):
        job = {"titel": "Lead Integration Engineer (m/w/d) im Team Technology Consulting",
               "beschreibung": "Test von Integrationen mit Kafka und REST",
               "ort": X1F_ORT, "firma": "x1F GmbH", "pendel_modus": "Remote"}
        res = score_job(demo_profile, job, location="München")
        assert res["location_bonus"] == 0


class TestWordHitsGespeichert:
    """D — ``word_hits`` wird zurückgegeben und beim Merge übernommen."""

    def test_score_job_liefert_word_hits(self, demo_profile):
        job = {"titel": "Testingenieur (m/w/d)", "ort": "München",
               "beschreibung": "Automatisierung von Prüfständen mit CAN und HIL",
               "firma": "Beispiel GmbH"}
        res = score_job(demo_profile, job, location="München")
        assert isinstance(res["word_hits"], list)
        assert res["word_hits"] == sorted(set(res["word_hits"]))

    def test_score_ist_aus_den_teilen_nachrechenbar(self, demo_profile):
        job = {"titel": "Testingenieur (m/w/d)", "ort": "München",
               "beschreibung": "Automatisierung von Prüfständen mit CAN und HIL",
               "firma": "Beispiel GmbH"}
        res = score_job(demo_profile, job, location="München")
        raw = (6 * len(res["title_hits"]) + 4 * len(res["body_hits"])
               + 2 * len(res["word_hits"]) + res["location_bonus"])
        assert res["score"] == min(100, raw)

    def test_merge_state_uebernimmt_word_hits(self):
        existing = {"applications": [{"key": "k1", "status": "research"}]}
        matches = [{"key": "k1", "score": 70, "word_hits": ["can", "hil"],
                    "title_hits": [], "body_hits": []}]
        out = _merge_state(existing, matches)
        assert out["applications"][0]["word_hits"] == ["can", "hil"]
