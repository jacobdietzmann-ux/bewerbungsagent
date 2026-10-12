"""Tests für die Datumslogik des Dashboards (``dashboard._fmt_date``).

Regression: Die Wochenstatistik war falsch, weil ``_fmt_date`` das Feld
``created`` (Erfassungszeitpunkt) ignorierte und alles auf „heute" fiel.
"""

from __future__ import annotations

from datetime import date

from bewerbungsagent.dashboard import _fmt_date


class TestFmtDate:
    def test_datum_wins(self):
        app = {"datum": "15.03.2024", "created": "2026-10-08T11:25:53+02:00"}
        assert _fmt_date(app) == "15.03.2024"

    def test_created_used_when_datum_missing(self):
        """Kernbug: ohne 'datum' muss 'created' das Funddatum liefern."""
        app = {"created": "2026-10-08T11:25:53+02:00"}
        assert _fmt_date(app) == "08.10.2026"

    def test_sentat_fallback(self):
        app = {"sentAt": "2026-10-09"}
        assert _fmt_date(app) == "09.10.2026"

    def test_created_beats_sentat(self):
        app = {"created": "2026-10-08T10:00:00+02:00", "sentAt": "2026-10-20"}
        assert _fmt_date(app) == "08.10.2026"

    def test_fallback_to_today(self):
        today = date.today()
        expected = f"{today.day:02d}.{today.month:02d}.{today.year}"
        assert _fmt_date({}) == expected

    def test_malformed_created_ignored(self):
        """Zu kurze/defekte Werte dürfen nicht crashen."""
        today = date.today()
        expected = f"{today.day:02d}.{today.month:02d}.{today.year}"
        assert _fmt_date({"created": "kaputt"}) == expected
        assert _fmt_date({"created": ""}) == expected
