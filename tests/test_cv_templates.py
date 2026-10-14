"""Tests für die drei Lebenslauf-Vorlagen (classic, modern, functional)."""

from __future__ import annotations

import pytest

from bewerbungsagent import documents as D


@pytest.fixture
def job():
    return {"titel": "Testingenieur (m/w/d)", "firma": "Acme GmbH", "ort": "München"}


@pytest.fixture
def match():
    return {"matched_skills": ["hil", "python", "can"]}


def test_registry_has_expected_templates():
    assert set(D.CV_TEMPLATES) == {
        "classic", "awesome", "deedy", "mcdowell", "sidebar", "elegant", "clean",
    }
    for template in D.CV_TEMPLATES.values():
        assert template["label"]
        assert template["description"]


def test_default_template_is_classic():
    assert D.DEFAULT_CV_TEMPLATE == "classic"


def test_cv_story_returns_flowables_for_each_template(demo_profile, job, match):
    config = {"documents": {"accent_color": "#0B3D5C"}}
    for template in D.CV_TEMPLATES:
        story, accent = D._cv_story(demo_profile, job, match, config, "de", template=template)
        assert story
        assert accent is not None


def test_unknown_template_raises(demo_profile, job, match):
    with pytest.raises(ValueError):
        D._cv_story(demo_profile, job, match, {"documents": {}}, "de", template="nope")


def test_generate_lebenslauf_all_templates(tmp_path, demo_profile, job, match, tmp_config):
    """Smoke-Test: jede Vorlage erzeugt ein nicht-leeres PDF."""
    for template in D.CV_TEMPLATES:
        out = tmp_path / f"cv-{template}.pdf"
        D.generate_lebenslauf(demo_profile, job, match, out, tmp_config, lang="de", template=template)
        assert out.exists()
        assert out.stat().st_size > 0


def test_generate_lebenslauf_defaults_to_config_template(tmp_path, demo_profile, job, match, tmp_config):
    tmp_config["documents"]["lebenslauf_template"] = "elegant"
    out = tmp_path / "cv-default.pdf"
    D.generate_lebenslauf(demo_profile, job, match, out, tmp_config, lang="de")
    assert out.exists() and out.stat().st_size > 0


class TestSkillCuration:
    def test_group_is_capped(self, demo_profile):
        """Gruppen mit mehr als 6 Einträgen werden gekürzt, Rest wandert in die Weitere-Zeile."""
        groups, overflow = D._curate_skill_groups(demo_profile, match=None, lang="de")
        assert all(len(items) <= D._MAX_SKILLS_PER_GROUP for _, items in groups)
        # Die Demo-Gruppe "test_datenauswertung_automatisierung" hat 7 Einträge → 1 Overflow.
        assert len(overflow) >= 1

    def test_matched_skills_are_ranked_first(self, demo_profile):
        match = {"matched_skills": ["python"]}
        groups, _ = D._curate_skill_groups(demo_profile, match=match, lang="de")
        # In der Programmierung-Gruppe muss der gematchte Skill vorne stehen.
        for label, items in groups:
            if "Programmierung" in label:
                assert items[0][1] is True
                return
        pytest.fail("Programmierung-Gruppe nicht gefunden")

    def test_profile_skills_are_not_mutated(self, demo_profile):
        """Kuratierung darf die Profil-Daten (Matching-Grundlage) nicht verändern."""
        before = {k: (list(v) if isinstance(v, (list, tuple)) else v) for k, v in demo_profile.skills.items()}
        D._curate_skill_groups(demo_profile, match={"matched_skills": ["python"]}, lang="de")
        assert demo_profile.skills == before



# ---------------------------------------------------------------------------
# Eigene DOCX-Vorlage (lebenslauf_vorlage)
# ---------------------------------------------------------------------------

def test_vorlage_falls_back_without_config(tmp_path, demo_profile, job, match, tmp_config):
    """Ohne konfigurierte Vorlage wird auf die ReportLab-Generierung zurückgefallen."""
    tmp_config["documents"].pop("lebenslauf_vorlage", None)
    out = tmp_path / "cv.pdf"
    r = D.generate_lebenslauf_vorlage(demo_profile, job, match, out, tmp_config, lang="de")
    assert r == str(out)
    assert out.exists() and out.stat().st_size > 0


def test_vorlage_falls_back_when_file_missing(tmp_path, demo_profile, job, match, tmp_config):
    """Fehlende DOCX-Datei => Fallback auf ReportLab (kein Fehler)."""
    tmp_config["documents"]["lebenslauf_vorlage"] = {"de": str(tmp_path / "gibt-es-nicht.docx")}
    out = tmp_path / "cv.pdf"
    r = D.generate_lebenslauf_vorlage(demo_profile, job, match, out, tmp_config, lang="de")
    assert r == str(out)
    assert out.exists() and out.stat().st_size > 0


def test_replace_profile_paragraph_replaces_only_summary():
    """Nur der Absatz nach der „■ PROFIL“-Zeile wird ersetzt; Format bleibt erhalten."""
    from docx import Document

    doc = Document()
    doc.add_paragraph("")
    doc.add_paragraph("■ PROFIL")
    p = doc.add_paragraph("Alter Profiltext")
    # Formatierung, die erhalten bleiben muss.
    p.runs[0].font.size = None  # Standardgröße des Vorlagen-Absatzes
    doc.add_paragraph("■ BERUFSERFAHRUNG")
    doc.add_paragraph("Erfahrungseintrag bleibt unverändert")

    D._replace_profile_paragraph(doc, "Neuer Profiltext", lang="de")

    texts = [para.text for para in doc.paragraphs]
    assert "Neuer Profiltext" in texts
    assert "Alter Profiltext" not in texts
    assert "Erfahrungseintrag bleibt unverändert" in texts
    assert "■ PROFIL" in texts


def test_replace_profile_paragraph_no_heading_is_noop():
    """Ohne Profil-Überschrift passiert nichts (kein IndexError)."""
    from docx import Document

    doc = Document()
    doc.add_paragraph("Ein Absatz ohne Überschrift")
    D._replace_profile_paragraph(doc, "Ignoriert", lang="de")
    assert doc.paragraphs[0].text == "Ein Absatz ohne Überschrift"
