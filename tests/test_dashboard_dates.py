"""Tests für die Datumslogik des Dashboards (``dashboard._fmt_date``).

Regression 1: Die Wochenstatistik war falsch, weil ``_fmt_date`` das Feld
``created`` (Erfassungszeitpunkt) ignorierte und alles auf „heute" fiel.

Regression 2: Der Rückfall auf „heute" blieb für Einträge ohne jeden
Zeitstempel bestehen und erzeugte Phantom-Wochen im Verlauf.
"""

from __future__ import annotations

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

    def test_unbekanntes_datum_bleibt_leer(self):
        """Kein Datum erfinden: „heute" erzeugte Phantom-Wochen im Verlauf.

        9 Alt-Einträge ohne ``datum``/``created``/``sentAt`` landeten so am
        19.10.2026 im Wochenverlauf, obwohl an dem Tag nichts gefunden wurde.
        """
        assert _fmt_date({}) == ""

    def test_malformed_created_ignored(self):
        """Zu kurze/defekte Werte dürfen nicht crashen und kein Datum erfinden."""
        assert _fmt_date({"created": "kaputt"}) == ""
        assert _fmt_date({"created": ""}) == ""
