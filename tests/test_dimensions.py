"""Tests für die mehrdimensionale Bewertung (``dimensions.py``, P0a).

Die Bewertung ist in dieser Ausbaustufe **berichtend**: Der Keyword-Fit
(``matching.score_job``) bleibt unverändert, hart ist nur die K.O.-Liste.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bewerbungsagent.dashboard import _dim_summary
from bewerbungsagent.dimensions import (
    DEFAULT_WEIGHTS,
    options,
    parse_salary_tsd,
    score_dimensions,
)
from bewerbungsagent.matching import score_job
from bewerbungsagent.pipeline import _dimensionen_blockieren, _merge_state


def _job(**kw):
    base = {"titel": "Testingenieur (m/w/d)", "firma": "Beispiel GmbH",
            "beschreibung": "", "ort": "Garching"}
    base.update(kw)
    return base


class TestGewichte:
    def test_default_summe_ist_eins(self):
        assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)

    def test_teilweise_gewichte_werden_normalisiert(self):
        cfg = {"matching": {"dimensions": {"gewichte": {"kompetenz": 3.0}}}}
        weights = options(cfg)["gewichte"]
        assert sum(weights.values()) == pytest.approx(1.0)
        assert weights["kompetenz"] > weights["entwicklung"]

    def test_unbekannte_dimension_wird_ignoriert(self):
        cfg = {"matching": {"dimensions": {"gewichte": {"quatsch": 1.0}}}}
        assert "quatsch" not in options(cfg)["gewichte"]


class TestScoreDimensions:
    def test_sieben_dimensionen_im_bereich(self, demo_profile):
        res = score_dimensions(demo_profile, _job(beschreibung="CAN HiL ADAS Python"))
        assert set(res) >= {"werte", "gewichte", "gesamt", "belege", "ko", "blockiert"}
        assert set(res["werte"]) == set(DEFAULT_WEIGHTS)
        assert all(0 <= v <= 100 for v in res["werte"].values())
        assert 0 <= res["gesamt"] <= 100

    def test_relevante_stelle_hoeher_als_irrelevante(self, demo_profile):
        relevant = _job(
            titel="Testingenieur HiL (m/w/d)",
            beschreibung=("Verantwortung für Testdurchführung, Testautomatisierung mit Python, "
                          "Inbetriebnahme von HiL-Prüfständen, Verifikation und Fehleranalyse. "
                          "Weiterbildung und Entwicklungsmöglichkeiten."),
        )
        irrelevant = _job(
            titel="Social Media Manager (m/w/d)",
            beschreibung="Betreuung von Instagram, Content-Erstellung, Community-Management.",
        )
        assert (score_dimensions(demo_profile, relevant)["gesamt"]
                > score_dimensions(demo_profile, irrelevant)["gesamt"])

    def test_jede_dimension_hat_belege(self, demo_profile):
        res = score_dimensions(demo_profile, _job(beschreibung="CAN HiL Python"))
        for dim, belege in res["belege"].items():
            assert belege, f"Dimension {dim} ohne Beleg"

    def test_senioritaet_koordinator_passt_zum_profil(self, demo_profile):
        # Das Demo-Profil führt „Testkoordinator“ → Stufe 3, die Stelle auch.
        res = score_dimensions(demo_profile, _job(titel="Testkoordinator (m/w/d)"))
        assert res["werte"]["senioritaet"] == 100

    def test_senioritaet_head_ist_schwaecher_als_koordinator(self, demo_profile):
        head = score_dimensions(demo_profile, _job(titel="Head of Test (m/f/d)"))
        koord = score_dimensions(demo_profile, _job(titel="Testkoordinator (m/w/d)"))
        assert head["werte"]["senioritaet"] < koord["werte"]["senioritaet"]

    def test_gehalt_aus_anzeige(self, demo_profile):
        res = score_dimensions(demo_profile, _job(gehalt="70–85 T€", gehalt_quelle="Anzeige"))
        assert res["werte"]["gehalt"] == 100

    def test_geschaetztes_gehalt_ist_neutral(self, demo_profile):
        res = score_dimensions(demo_profile, _job(gehalt="60–76 T€", gehalt_quelle="Schätzung"))
        assert res["werte"]["gehalt"] == 55

    def test_arbeitsmodell_nah_hoeher_als_weit(self, demo_profile):
        nah = score_dimensions(demo_profile, _job(pendelzeit_min=20))
        weit = score_dimensions(demo_profile, _job(pendelzeit_min=85))
        assert nah["werte"]["arbeitsmodell"] > weit["werte"]["arbeitsmodell"]

    def test_entwicklung_signale_heben_den_wert(self, demo_profile):
        mit = score_dimensions(demo_profile, _job(beschreibung="Weiterbildung, Karriere und Training"))
        ohne = score_dimensions(demo_profile, _job(beschreibung="Testen von Steuergeräten"))
        assert mit["werte"]["entwicklung"] > ohne["werte"]["entwicklung"]

    def test_ohne_konfiguration_keine_ko(self, demo_profile):
        res = score_dimensions(demo_profile, _job(titel="Head of Test"))
        assert res["blockiert"] is False
        assert res["ko"] == []

    def test_keyword_fit_bleibt_unveraendert(self, demo_profile):
        """Berichtend heißt: ``score_job`` erzeugt keine Dimensionen und ändert
        den Score nicht — die Dimensionen entstehen erst in ``run_enrich``."""
        res = score_job(demo_profile, _job(beschreibung="CAN HiL Python"))
        assert "dimensionen" not in res


class TestKO:
    def test_gehalt_unter_schwelle_blockiert_trotz_hohem_score(self, demo_profile):
        res = score_dimensions(demo_profile, _job(
            titel="Senior Testingenieur HiL",
            beschreibung="CAN ADAS Python HiL " * 5,
            gehalt="45–52 T€", gehalt_quelle="Anzeige",
            pendelzeit_min=15,
        ))
        assert res["blockiert"] is True
        assert res["ko"][0]["grund"] == "Gehalt unter Schwelle"
        # Der Rest-Score bleibt hoch — die K.O. ist nicht kompensierbar.
        assert res["gesamt"] > 50

    def test_geschaetztes_gehalt_blockiert_nicht(self, demo_profile):
        res = score_dimensions(demo_profile, _job(
            gehalt="45–52 T€", gehalt_quelle="Schätzung"))
        assert res["blockiert"] is False

    def test_xing_schaetzung_blockiert_nicht(self, demo_profile):
        """Realdaten: „48.500–67.000 € (Xing-Schätzung)“ trägt quelle=Anzeige,
        ist aber eine Schätzung — sie darf keine K.O. auslösen."""
        res = score_dimensions(demo_profile, _job(
            gehalt="48.500–67.000 € (Xing-Schätzung)", gehalt_quelle="Anzeige"))
        assert res["blockiert"] is False
        assert res["werte"]["gehalt"] == 55

    def test_spanne_mit_hohem_ende_blockiert_nicht(self, demo_profile):
        """Realdaten: „52–59 T€“ kann 59 T€ zahlen — kein harter Ausschluss."""
        res = score_dimensions(demo_profile, _job(
            gehalt="52–59 T€ (Anzeige)", gehalt_quelle="Anzeige"))
        assert res["blockiert"] is False

    def test_senioritaets_ko_nur_wenn_konfiguriert(self, demo_profile):
        cfg = {"matching": {"dimensions": {"ko_senioritaet": ["head of"]}}}
        assert score_dimensions(demo_profile, _job(titel="Head of Test"), cfg)["blockiert"] is True
        assert score_dimensions(demo_profile, _job(titel="Testingenieur"), cfg)["blockiert"] is False

    def test_gehaltsschwelle_konfigurierbar(self, demo_profile):
        cfg = {"matching": {"dimensions": {"ko_gehalt_min_tsd": 40}}}
        res = score_dimensions(demo_profile, _job(
            gehalt="45–52 T€", gehalt_quelle="Anzeige"), cfg)
        assert res["blockiert"] is False

    def test_pipeline_blockierfunktion_respektiert_schalter(self):
        an = SimpleNamespace(data={"matching": {"dimensions": {"ko_blockiert_generierung": True}}})
        aus = SimpleNamespace(data={"matching": {"dimensions": {"ko_blockiert_generierung": False}}})
        dims = {"blockiert": True, "ko": [{"grund": "Gehalt unter Schwelle"}]}
        assert _dimensionen_blockieren(an, dims) is True
        assert _dimensionen_blockieren(aus, dims) is False
        assert _dimensionen_blockieren(an, {"blockiert": False}) is False


class TestParseSalary:
    @pytest.mark.parametrize("text,expected", [
        ("62–78 T€", (62, 78)),
        ("88–93 T€ (Anzeige)", (88, 93)),
        ("60.000 – 75.000 €", (60, 75)),
        ("60.000 €", (60, 60)),
        ("70 T€", (70, 70)),
    ])
    def test_formate(self, text, expected):
        assert parse_salary_tsd(text) == expected

    @pytest.mark.parametrize("text", ["", "k. A.", "keine Angabe", "-"])
    def test_platzhalter(self, text):
        assert parse_salary_tsd(text) is None


class TestMergeState:
    def test_dimensionen_bleiben_im_bestand(self):
        existing = {"applications": [{"key": "k1", "status": "research"}]}
        match = [{"key": "k1", "titel": "Testingenieur", "score": 70,
                  "dimensionen": {"gesamt": 61, "blockiert": False}}]
        out = _merge_state(existing, match, limit=90)
        assert out["applications"][0]["dimensionen"]["gesamt"] == 61


class TestDashboardSummary:
    def test_ohne_dimensionen(self):
        assert _dim_summary(None) is None
        assert _dim_summary({}) is None

    def test_mit_dimensionen(self):
        summary = _dim_summary({
            "gesamt": 64,
            "werte": {"kompetenz": 80, "aufgaben": 50},
            "ko": [{"grund": "Gehalt unter Schwelle"}],
        })
        assert summary["gesamt"] == 64
        assert "kompetenz 80" in summary["detail"]
        assert summary["ko"] == ["Gehalt unter Schwelle"]
