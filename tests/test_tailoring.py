"""Tests für das stellenbezogene Tailoring (``tailoring.py`` + Anbindung).

Grundsatz: Das Tailoring darf auswählen und umformulieren, aber nichts
erfinden. Die Tests sichern beide Seiten ab — die Wirkung (Headline, Profil,
Bullets, Fähigkeitsgruppen kommen im PDF an) und die Grenze (unbelegte
Fachbegriffe und bestätigte Lücken werden gemeldet).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bewerbungsagent import tailoring as tal
from bewerbungsagent.documents import (
    _curate_skill_groups,
    _cv_profile_summary,
    _key_competencies,
    _styles,
    generate_lebenslauf,
)
from bewerbungsagent.quality import pdf_page_count


def _demo_tailoring() -> dict:
    return {
        "stelle": "Integration Engineer",
        "firma": "Beispiel GmbH",
        "headline": {"de": "Integrationsingenieur · Schnittstellen · Test",
                     "en": "Integration Engineer · Interfaces · Test"},
        "profil": {"de": "Profiltext auf die Stelle zugeschnitten.",
                   "en": "Profile text tailored to the role."},
        "kernkompetenzen": {
            "de": [{"wert": "10+", "text": "Jahre Integration",
                    "zusatz": "E/E-Systeme"}],
        },
        "berufserfahrung": [
            {"index": 0,
             "rolle": {"de": "Integrationskoordinator", "en": "Integration Coordinator"},
             "bullets": {"de": ["Schnittstellen definiert und abgestimmt."],
                         "en": ["Defined and agreed interfaces."]}},
        ],
        "skills": {
            "gruppen": [
                {"label": {"de": "Systemintegration", "en": "Systems integration"},
                 "items": ["Fahrzeugarchitektur E/E (CAN, CAN-FD, LIN, FlexRay, "
                           "Automotive Ethernet)", "CAN-Trace-Analyse"]},
                {"label": {"de": "Test & Automatisierung", "en": "Test & automation"},
                 "items": ["CANoe", "XiL-/HiL-Prüfstände"]},
            ],
            "weitere": ["JIRA"],
        },
    }


class TestDatei:
    def test_ohne_datei_kein_tailoring(self, tmp_path: Path):
        assert tal.for_application(tmp_path) is None

    def test_datei_wird_gelesen(self, tmp_path: Path):
        (tmp_path / tal.FILENAME).write_text(
            json.dumps(_demo_tailoring(), ensure_ascii=False), encoding="utf-8")
        assert tal.for_application(tmp_path)["firma"] == "Beispiel GmbH"

    def test_kaputtes_json_meldet_fehler(self, tmp_path: Path):
        (tmp_path / tal.FILENAME).write_text("{kein json", encoding="utf-8")
        with pytest.raises(tal.TailoringError, match="kein gültiges JSON"):
            tal.for_application(tmp_path)

    def test_liste_statt_objekt_meldet_fehler(self, tmp_path: Path):
        (tmp_path / tal.FILENAME).write_text("[]", encoding="utf-8")
        with pytest.raises(tal.TailoringError, match="JSON-Objekt"):
            tal.for_application(tmp_path)


class TestSprachwahl:
    def test_deutsch_und_englisch_getrennt(self):
        data = _demo_tailoring()
        assert tal.text(data, "headline", "de").startswith("Integrationsingenieur")
        assert tal.text(data, "headline", "en").startswith("Integration Engineer")

    def test_fehlt_englisch_greift_deutsch(self):
        data = {"headline": {"de": "Nur Deutsch"}}
        assert tal.text(data, "headline", "en") == "Nur Deutsch"

    def test_fehlender_schluessel_bleibt_none(self):
        assert tal.text({}, "headline", "de") is None
        assert tal.text(None, "headline", "de") is None


class TestUeberschreibungen:
    def test_rollen_nach_index(self):
        rollen = tal.role_overrides(_demo_tailoring())
        assert set(rollen) == {0}
        assert tal.text(rollen[0], "rolle", "en") == "Integration Coordinator"

    def test_ungueltiger_index_wird_ignoriert(self):
        data = {"berufserfahrung": [{"index": "abc"}, {"rolle": {}}, {"index": 2}]}
        assert set(tal.role_overrides(data)) == {2}

    def test_skill_gruppen_in_dateireihenfolge(self):
        groups = tal.skill_groups(_demo_tailoring(), "de")
        assert [label for label, _ in groups] == ["Systemintegration", "Test & Automatisierung"]

    def test_leere_gruppen_ergeben_none(self):
        assert tal.skill_groups({"skills": {"gruppen": []}}, "de") is None
        assert tal.skill_groups(None, "de") is None

    def test_kernkompetenzen_als_karten(self):
        cards = tal.competencies(_demo_tailoring(), "de")
        assert cards == [("10+", "Jahre Integration", "E/E-Systeme")]


class TestProfilAbgleich:
    def test_belegte_begriffe_werden_nicht_gemeldet(self, demo_profile):
        assert tal.unbacked_terms(_demo_tailoring(), demo_profile) == []

    def test_unbelegter_begriff_wird_gemeldet(self, demo_profile):
        data = {"skills": {"gruppen": [
            {"label": {"de": "Middleware"}, "items": ["Apache Kafka", "CANoe"]},
        ]}}
        offen = tal.unbacked_terms(data, demo_profile)
        assert offen == ["Apache Kafka"]

    def test_bestaetigte_luecke_wird_als_solche_gemeldet(self, demo_profile):
        demo_profile.data["gap_terms"] = ["Kubernetes"]
        try:
            data = {"skills": {"gruppen": [
                {"label": {"de": "Betrieb"}, "items": ["Kubernetes-Erfahrung"]},
            ]}}
            assert tal.unbacked_terms(data, demo_profile) == [
                "Kubernetes-Erfahrung (bestätigte Lücke)"]
        finally:
            demo_profile.data.pop("gap_terms", None)

    def test_weitere_zeile_wird_mitgeprueft(self, demo_profile):
        data = {"skills": {"weitere": ["Guidewire"]}}
        assert tal.unbacked_terms(data, demo_profile) == ["Guidewire"]


class TestLebenslauf:
    def _job(self) -> dict:
        return {"titel": "Integration Engineer (m/w/d)", "firma": "Beispiel GmbH",
                "ort": "München", "matched_skills": ["CANoe"]}

    def test_profilabsatz_kommt_aus_tailoring(self, demo_profile):
        summary = _cv_profile_summary(demo_profile, self._job(), {}, "de",
                                      _demo_tailoring())
        assert summary == "Profiltext auf die Stelle zugeschnitten."

    def test_ohne_tailoring_bleibt_der_standardtext(self, demo_profile):
        summary = _cv_profile_summary(demo_profile, self._job(), {}, "de")
        assert "Diplom-Ingenieur" in summary

    def test_faehigkeitsgruppen_folgen_dem_tailoring(self, demo_profile):
        groups, overflow = _curate_skill_groups(demo_profile, {}, "de", _demo_tailoring())
        assert [label for label, _ in groups] == ["Systemintegration", "Test & Automatisierung"]
        assert overflow == ["JIRA"]

    def test_tailoring_eintraege_werden_uebersetzt(self, demo_profile):
        """Im englischen Lebenslauf dürfen keine deutschen Skill-Namen stehen.

        Regression: Der Tailoring-Pfad in ``_curate_skill_groups`` gab die
        Einträge ungeprüft weiter — im EN-CV stand dadurch
        „Python (erweiterte Grundkenntnisse)', während das Profil sonst über
        ``_SKILL_TRANSLATIONS_EN`` übersetzt wird.
        """
        data = _demo_tailoring()
        data["skills"]["gruppen"] = [{
            "label": {"de": "Skripting", "en": "Scripting"},
            "items": ["Python (erweiterte Grundkenntnisse)", "CANoe"],
        }]
        groups, _overflow = _curate_skill_groups(demo_profile, {}, "en", data)
        anzeigen = [display for _label, items in groups for display, _hit in items]
        assert "Python (advanced basics)" in anzeigen
        assert "Python (erweiterte Grundkenntnisse)" not in anzeigen

    def test_kernkompetenzen_aus_tailoring(self, demo_profile):
        story: list = []
        table = _key_competencies(story, _styles(), "de", _demo_tailoring())
        text = table._cellvalues[0][0].text
        assert "Jahre Integration" in text

    def test_pdf_entsteht_mit_tailoring(self, demo_profile, tmp_path: Path):
        out = tmp_path / "Lebenslauf.pdf"
        generate_lebenslauf(demo_profile, self._job(), {}, out,
                            {"documents": {"accent_color": "#0B3D5C"}}, "de",
                            template="classic", tailoring=_demo_tailoring())
        data = out.read_bytes()
        assert data.startswith(b"%PDF")
        assert pdf_page_count(data) >= 1
