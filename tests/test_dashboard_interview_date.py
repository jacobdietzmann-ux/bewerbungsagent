"""Regression: Interview-Datum als TT.MM.JJJJ statt nativem Datumsfeld.

Das native ``<input type="date">`` verstümmelte im deutschen Browser-Locale das
Jahr: aus 2026 wurde ``0022``. Dadurch wurde ein falsches Interview-Datum
gespeichert. Das Feld ist jetzt ein Textfeld mit vierstelliger Jahreseingabe
und eigener Validierung.
"""

from __future__ import annotations

from pathlib import Path

from bewerbungsagent.dashboard import build_dashboard


def _build(tmp_path: Path) -> str:
    apps = [{
        "key": "https://example.test/job/1",
        "titel": "Test Engineer",
        "firma": "Acme GmbH",
        "status": "interview",
        "interviewDate": "2026-11-15",
        "dokumente": {"lebenslauf_de": "output/x/Lebenslauf.pdf"},
    }]
    target = tmp_path / "dashboard.html"
    build_dashboard({"applications": apps}, target)
    return target.read_text(encoding="utf-8")


def test_kein_natives_datumsfeld_mehr(tmp_path):
    """``type="date"`` ist die Ursache der Jahres-Verstümmelung."""
    html = _build(tmp_path)
    assert 'type="date"' not in html


def test_interview_datum_als_textfeld_mit_vierstelligem_jahr(tmp_path):
    html = _build(tmp_path)
    assert 'data-k="interviewDate"' in html
    assert 'placeholder="TT.MM.JJJJ"' in html
    assert 'maxlength="10"' in html


def test_gespeichertes_iso_datum_wird_deutsch_angezeigt(tmp_path):
    """Der Wert kommt als ISO aus der DB, angezeigt wird TT.MM.JJJJ."""
    html = _build(tmp_path)
    assert "interviewDateDisplay" in html
    assert "parseDEToISO" in html
