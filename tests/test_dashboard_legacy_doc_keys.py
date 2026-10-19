"""Regression: Alt-Dashboard-Dokumente unter Anzeige-Labels.

Der Import des alten Dashboards speicherte Dokumente unter ihren *Labels*
(``"Anschreiben"``, ``"Lebenslauf"``) statt unter technischen Keys
(``anschreiben_de``). ``_APPLICATION_DOCUMENT_KEYS`` erkannte sie nicht, die
Einträge galten als „ohne Bewerbungsunterlagen" und fielen aus Tabelle und
Status-Verteilung — betroffen waren 53 Einträge, darunter 6 von 7 Interviews.
"""

from __future__ import annotations

import pytest

from bewerbungsagent.dashboard import (_APPLICATION_DOCUMENT_KEYS, _canonical_doc_key,
                                       _existing_documents, documented_applications)


@pytest.mark.parametrize("label, canonical", [
    ("Anschreiben", "anschreiben_de"),
    ("Lebenslauf", "lebenslauf_de"),
    ("Cover Letter (EN)", "cover_letter_en"),
    ("CV (EN)", "cv_en"),
    ("Stellenanzeige", "stellenanzeige"),
    ("Referenzschreiben (BMW)", "referenzschreiben"),
])
def test_labels_werden_abgebildet(label, canonical):
    assert _canonical_doc_key(label) == canonical


def test_technische_keys_bleiben_unveraendert():
    for key in ("anschreiben_de", "lebenslauf_en", "briefing", "briefing_en"):
        assert _canonical_doc_key(key) == key


def test_unbekannter_key_bleibt_erhalten():
    assert _canonical_doc_key("irgendwas") == "irgendwas"


def test_alle_labels_liefern_anwendungsdokumente():
    """Jedes Legacy-Label, das ein Anschreiben/Lebenslauf meint, muss zählen."""
    for label in ("Anschreiben", "Lebenslauf", "Cover Letter (EN)", "CV (EN)"):
        assert _canonical_doc_key(label) in _APPLICATION_DOCUMENT_KEYS


def test_legacy_eintrag_gilt_als_dokumentiert(tmp_path, monkeypatch):
    """Kernbug: ein Interview mit Label-Keys war für das Dashboard unsichtbar."""
    doc = tmp_path / "Anschreiben.pdf"
    doc.write_bytes(b"%PDF-1.4 test")

    app = {
        "key": "https://example.test/job/1",
        "firma": "Acme GmbH",
        "titel": "Test Engineer",
        "status": "interview",
        "dokumente": {"Anschreiben": str(doc), "Lebenslauf": str(doc)},
    }

    monkeypatch.setattr("bewerbungsagent.dashboard.AGENT_ROOT", tmp_path)
    keys = [k for k, _ in _existing_documents(app)]
    assert "anschreiben_de" in keys
    assert documented_applications([app]) == [app]


def test_kanonischer_key_gewinnt_gegen_label_duplikat(tmp_path, monkeypatch):
    """Liegt dasselbe Dokument doppelt vor, erscheint es nur einmal."""
    doc = tmp_path / "x.pdf"
    doc.write_bytes(b"%PDF-1.4 test")

    app = {
        "key": "k",
        "dokumente": {"anschreiben_de": str(doc), "Anschreiben": str(doc)},
    }
    monkeypatch.setattr("bewerbungsagent.dashboard.AGENT_ROOT", tmp_path)
    keys = [k for k, _ in _existing_documents(app)]
    assert keys.count("anschreiben_de") == 1
