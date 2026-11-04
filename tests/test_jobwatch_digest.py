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
    assert "über der Pendelgrenze von 30 min" in text


def test_ohne_grenze_bleiben_alle_treffer():
    text = jobwatch.build_digest(JOBS, JOBS, True, 60, 5)
    assert "example.org/nah" in text and "example.org/weit" in text


def test_stelle_ohne_pendelzeit_bleibt_sichtbar():
    jobs = [{"firma": "Unbekannt", "titel": "Test", "score": 80, "url": "https://example.org/x"}]
    text = jobwatch.build_digest(jobs, jobs, True, 60, 5, max_commute=30)
    assert "example.org/x" in text
