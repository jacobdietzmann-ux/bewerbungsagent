"""Tests für die Erkennung abgelaufener Stellenanzeigen.

Hintergrund: Im Dashboard trugen 142 von 313 Einträgen das Badge „abgelaufen",
obwohl die Stellen aktiv waren. Ursache war eine Kette aus drei Fehlern:

1. ``_merge_state`` überschrieb ``verfuegbar`` mit ``None``, weil das
   Matching-Ergebnis das Feld gar nicht enthält.
2. ``dashboard._to_data`` machte daraus ``bool(None)`` → ``False``.
3. ``_is_expired`` nutzte das nackte Wort ``"abgelaufen"``, das auf Jobbörsen
   auch in Sidebars und Footern fremder Anzeigen steht.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from bewerbungsagent.dashboard import _availability, _to_data
from bewerbungsagent.pipeline import _merge_state
from fetch_descriptions import _is_expired

# --------------------------------------------------------------------------
# 1) Erkennung abgelaufener Anzeigen
# --------------------------------------------------------------------------

class TestIsExpired:
    @pytest.mark.parametrize("text", [
        "Diese Stellenanzeige ist leider nicht mehr verfügbar.",
        "Die Anzeige ist abgelaufen.",
        "Stellenanzeige nicht mehr verfügbar",
        "This job is no longer available.",
        "The position has been filled.",
        "Diese Stelle wurde besetzt.",
        "Die Bewerbungsfrist ist abgelaufen.",
        "Leider ist die Stelle nicht mehr vorhanden.",
        "This position is closed.",
    ])
    def test_detects_real_expiry_messages(self, text: str):
        assert _is_expired(text) is not None

    @pytest.mark.parametrize("text", [
        # Fußzeilen/Sidebar einer Jobbörse: listet fremde, teils alte Anzeigen.
        "Jobs in München\nAbgelaufene Jobs\nAlle Jobs anzeigen",
        "Weitere Stellenangebote\nSenior Test Engineer\nSystemingenieur\nJobs finden",
        # Aktive Anzeige, die "verfügbar" im Normaltext verwendet.
        "Diese Stellenanzeige ist für alle Geschlechter verfügbar. Wir suchen ab sofort.",
        "Benefits: Jobticket, flexible Arbeitszeiten, Weiterbildung",
        # Aktive Anzeige mit dem Wort im Aufgabentext.
        "Sie prüfen, ob Werte abgelaufen sind und dokumentieren Abweichungen.",
        # "vakant" heißt im Deutschen "offen" — darf NICHT als abgelaufen gelten.
        "Die Stelle ist ab sofort vakant und wird zum nächstmöglichen Zeitpunkt besetzt.",
    ])
    def test_ignores_false_positives(self, text: str):
        assert _is_expired(text) is None

    def test_returns_matched_marker_for_diagnostics(self):
        marker = _is_expired("Hinweis: Die Stellenanzeige ist abgelaufen.")
        assert marker is not None
        assert "abgelaufen" in marker.lower()

    def test_empty_text_is_not_expired(self):
        assert _is_expired("") is None


# --------------------------------------------------------------------------
# 2) Tri-State: unbekannt ist nicht abgelaufen
# --------------------------------------------------------------------------

class TestAvailability:
    def test_unknown_is_none_not_false(self):
        assert _availability({}) is None
        assert _availability({"verfuegbar": None}) is None

    def test_checked_values_survive(self):
        assert _availability({"verfuegbar": True}) is True
        assert _availability({"verfuegbar": False}) is False

    def test_unchecked_job_gets_no_expired_badge_in_dashboard(self):
        """Kernregression: None wurde zu bool(None)=False → Badge „abgelaufen"."""
        row = _to_data({"firma": "ACME", "titel": "Test Engineer"})
        assert row["verfuegbar"] is not False

    def test_checked_false_job_still_reports_false(self):
        row = _to_data({"firma": "ACME", "titel": "Test Engineer",
                        "verfuegbar": False})
        assert row["verfuegbar"] is False


# --------------------------------------------------------------------------
# 3) _merge_state darf vorhandene Werte nicht mit None überschreiben
# --------------------------------------------------------------------------

class TestMergeStatePreservesFields:
    def test_missing_verfuegbar_keeps_previous_value(self):
        """``score_job()`` liefert kein ``verfuegbar`` → alter Wert muss bleiben."""
        existing = {"applications": [{
            "key": "acme::test-engineer", "firma": "ACME",
            "titel": "Test Engineer", "verfuegbar": True, "status": "docs",
        }]}
        matches = [{
            "key": "acme::test-engineer", "firma": "ACME",
            "titel": "Test Engineer", "score": 70,
        }]
        merged = _merge_state(existing, matches)
        app = merged["applications"][0]
        assert app["verfuegbar"] is True
        assert app["score"] == 70

    def test_explicit_false_is_still_applied(self):
        existing = {"applications": [{
            "key": "acme::test-engineer", "verfuegbar": True, "status": "docs",
        }]}
        matches = [{"key": "acme::test-engineer", "score": 60, "verfuegbar": False}]
        merged = _merge_state(existing, matches)
        assert merged["applications"][0]["verfuegbar"] is False

    def test_missing_beschreibung_keeps_previous_text(self):
        """jobs.json wird bei jedem Search-Lauf ersetzt — Text darf nicht verfallen."""
        existing = {"applications": [{
            "key": "acme::test-engineer", "beschreibung": "Aufgaben: Testautomatisierung",
            "status": "docs",
        }]}
        matches = [{"key": "acme::test-engineer", "score": 55}]
        merged = _merge_state(existing, matches)
        assert merged["applications"][0]["beschreibung"] == "Aufgaben: Testautomatisierung"

    def test_new_job_without_flag_stays_unknown(self):
        matches = [{"key": "neu::x", "firma": "Neu", "titel": "X", "score": 50}]
        merged = _merge_state({"applications": []}, matches)
        assert merged["applications"][0].get("verfuegbar") is None


# --------------------------------------------------------------------------
# 4) Recheck-Skript zielt nur auf echte False-Flags
# --------------------------------------------------------------------------

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "recheck_expired.py"


@pytest.fixture(scope="module")
def recheck_mod():
    spec = importlib.util.spec_from_file_location("recheck_expired", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["recheck_expired"] = module
    spec.loader.exec_module(module)
    return module


class TestRecheckTargets:
    def test_only_explicitly_expired_jobs_are_checked(self, recheck_mod):
        apps = [
            {"id": 1, "verfuegbar": False, "url": "https://a"},
            {"id": 2, "verfuegbar": None, "url": "https://b"},
            {"id": 3, "verfuegbar": True, "url": "https://c"},
            {"id": 4, "verfuegbar": False, "url": ""},
            {"id": 5, "verfuegbar": False, "url": "https://d"},
        ]
        assert [a["id"] for a in recheck_mod._targets(apps, None)] == [1, 5]

    def test_limit_cuts_the_list(self, recheck_mod):
        apps = [{"id": i, "verfuegbar": False, "url": f"https://{i}"} for i in range(5)]
        assert [a["id"] for a in recheck_mod._targets(apps, 2)] == [0, 1]
