"""Tests für die KPI-Karten des Dashboards.

Entfernt wurden zwei Kennzahlen ohne eigenen Informationsgehalt:

- „Antwortrate": Antworten sind im Datenmodell kein eigenes Feld, nur ein
  Statuswechsel — die Kennzahl war eine Ableitung aus ``followup``/``interview``.
- „Funnel" (Interviews ÷ Gesamt): mathematisch das Produkt aus Interview-Quote
  und Versand-Anteil, also ohne unabhängige Aussage. Der Nenner enthielt zudem
  alle abgelehnten Einträge.
- „Absagen-Quote": negativ formuliert und als Steuerungsgröße wenig nützlich.
  Ersetzt durch die Interview-Quote auf Basis der *entschiedenen* Bewerbungen.
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
        "dokumente": {"lebenslauf_de": "output/x/Lebenslauf.pdf"},
    }]
    target = tmp_path / "dashboard.html"
    build_dashboard({"applications": apps}, target)
    return target.read_text(encoding="utf-8")


def test_antwortrate_entfernt(tmp_path):
    assert "Antwortrate" not in _build(tmp_path)


def test_funnel_entfernt(tmp_path):
    """Der Funnel war das Produkt der beiden anderen Quoten — kein Mehrwert."""
    html = _build(tmp_path)
    assert "Interviews von Gesamt" not in html
    assert "Funnel" not in html


def test_kernkennzahlen_bleiben(tmp_path):
    html = _build(tmp_path)
    for label in ("Versand-Quote", "Interview-Quote", "Aktiv im Prozess",
                  "Ø Profil-Fit (Interviews)"):
        assert label in html


def test_interview_quote_nur_entschiedene(tmp_path):
    """Interview-Quote = Interviews ÷ (Absagen + Interviews).

    Noch offene Bewerbungen (sent/followup) sind kein Ergebnis; sie in den
    Nenner zu nehmen würde die Quote künstlich drücken (8/159 statt 8/120).
    Die frühere Absagen-Quote und die zweite Interview-Rate entfallen.
    """
    html = _build(tmp_path)
    assert "Absagen-Quote" not in html
    assert "Interview-Rate" not in html
    assert "const decided = rejectedCount + interviews;" in html
    assert "const interviewQuote = pct(interviews, decided);" in html


def test_interview_quote_ist_hoch_gut(tmp_path):
    """Bei der Interview-Quote ist ein hoher Wert gut."""
    html = _build(tmp_path)
    assert "function cls(" in html
    assert "cls(interviewQuote,15,8)" in html


def test_interview_quote_zeigt_ihre_basis(tmp_path):
    """Die Karte muss sagen, worauf sie sich bezieht — sonst ist sie nicht lesbar."""
    html = _build(tmp_path)
    assert "von ${decided} entschieden" in html
