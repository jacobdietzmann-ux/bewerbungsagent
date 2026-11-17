"""Tests für den Jobwatch-Digest: Pendelgrenze wie im Dashboard.

Hintergrund: Der Telegram-Digest filterte nur nach Fit und listete deshalb
Stellen mit 97 oder 293 Minuten Pendelweg, die das Dashboard längst ausblendet.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_QUELLE = Path(__file__).resolve().parent.parent / "scripts" / "jobwatch.py"
_spec = importlib.util.spec_from_file_location("jobwatch_modul", _QUELLE)
jobwatch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(jobwatch)  # type: ignore[union-attr]

JOBS = [
    {"firma": "Nah GmbH", "titel": "Testingenieur", "score": 90, "pendelzeit_min": 25,
     "url": "https://example.org/nah"},
    {"firma": "Weit AG", "titel": "Testingenieur", "score": 100, "pendelzeit_min": 97,
     "url": "https://example.org/weit"},
]


def test_zu_weite_stelle_wird_ausgeblendet():
    text = jobwatch.build_digest(JOBS, JOBS, True, 60, 5, max_commute=30)
    assert "example.org/nah" in text
    assert "example.org/weit" not in text


def test_kulanz_stelle_ist_research_und_wird_gezaehlt():
    jobs = [{"firma": "Knapp AG", "titel": "Testingenieur", "score": 84, "pendelzeit_min": 34,
             "pendel_knapp": True, "url": "https://example.org/knapp"}]
    text = jobwatch.build_digest(jobs, jobs, False, 65, 5, max_commute=30)
    assert "🚗34′ 84 % Knapp AG – Testingenieur" in text


def test_etikett_folgt_dem_echten_stand():
    """Bis 13.11.2026 stand „[Unterlagen]“ an jeder Stelle über 70 %."""
    mit = {"titel": "Testingenieur", "score": 80, "status": "docs", "dokumente": {"de": "x"}}
    ohne_rolle = {"titel": "Staff Computer Vision Engineer", "score": 94, "status": "neu"}
    rolle = {"titel": "Testingenieur", "score": 80, "status": "neu"}
    mittel = {"titel": "Testingenieur", "score": 68, "status": "neu"}
    assert jobwatch.etikett(mit) == "Unterlagen erstellt"
    assert jobwatch.etikett(ohne_rolle) == "Research, kein Rollentitel"
    assert jobwatch.etikett(rolle) == "Unterlagen folgen"
    assert jobwatch.etikett(mittel) == "Research"


def test_bereite_unterlagen_werden_gezaehlt():
    jobs = [{"firma": "A", "titel": "Testingenieur", "score": 80, "status": "docs",
             "dokumente": {"de": "x"}, "pendelzeit_min": 20}]
    text = jobwatch.build_digest(jobs, [], False, 65, 5, max_commute=30)
    assert "📄 1 Unterlagen bereit" in text


def test_digest_ist_kurz():
    """17.11.2026: höchstens Kopf + 2 Zeilen je Stelle + Fußzeile."""
    jobs = [{"firma": f"Firma {i}", "titel": "Testingenieur " + "x" * 80, "score": 90 - i,
             "pendelzeit_min": 20, "url": f"https://example.org/{i}"} for i in range(9)]
    text = jobwatch.build_digest(jobs, jobs, False, 65, 5, max_commute=30)
    zeilen = text.splitlines()
    assert zeilen[0].startswith("💼 Bewerbung") and "9 neu" in zeilen[0]
    assert len(zeilen) == 1 + 2 * 5 + 1
    assert zeilen[-1] == "+4 weitere"
    assert all(len(z) <= 100 for z in zeilen)


def test_passende_rollen_stehen_vorn():
    jobs = [{"firma": "Se3", "titel": "Staff Computer Vision Engineer", "score": 94,
             "pendelzeit_min": 20},
            {"firma": "Test AG", "titel": "Testingenieur HiL", "score": 72, "pendelzeit_min": 20}]
    zeilen = jobwatch.build_digest(jobs, jobs, False, 65, 5, max_commute=30).splitlines()
    assert "Test AG" in zeilen[1] and "Se3" in zeilen[2]


def test_ohne_grenze_bleiben_alle_treffer():
    text = jobwatch.build_digest(JOBS, JOBS, True, 60, 5)
    assert "example.org/nah" in text and "example.org/weit" in text


def test_stelle_ohne_pendelzeit_bleibt_sichtbar():
    jobs = [{"firma": "Unbekannt", "titel": "Test", "score": 80, "url": "https://example.org/x"}]
    text = jobwatch.build_digest(jobs, jobs, True, 60, 5, max_commute=30)
    assert "example.org/x" in text
