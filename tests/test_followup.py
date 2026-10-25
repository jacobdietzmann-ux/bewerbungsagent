"""Tests für das Nachfassen (``followup.py``)."""

from __future__ import annotations

from datetime import date

from bewerbungsagent.dashboard import _to_data, build_dashboard
from bewerbungsagent.followup import (
    DEFAULT_AFTER_DAYS,
    days_waiting,
    due_applications,
    followup_text,
    is_due,
    write_followup,
)

HEUTE = date(2026, 10, 25)


def _app(**kw):
    base = {"firma": "Beispiel GmbH", "titel": "Testingenieur",
            "status": "sent", "sentAt": "2026-10-01"}
    base.update(kw)
    return base


class TestDaysWaiting:
    def test_tage_seit_versand(self):
        assert days_waiting(_app(), HEUTE) == 24

    def test_ohne_datum(self):
        assert days_waiting(_app(sentAt=""), HEUTE) is None
        assert days_waiting(_app(sentAt="kein datum"), HEUTE) is None

    def test_followup_nutzt_statusChangedAt(self):
        app = _app(status="followup", sentAt="2026-09-01",
                   statusChangedAt="2026-10-10")
        assert days_waiting(app, HEUTE) == 15


class TestIsDue:
    def test_schwelle_ist_faellig(self):
        assert is_due(_app(sentAt="2026-10-11"), today=HEUTE) is True
        assert is_due(_app(sentAt="2026-10-12"), today=HEUTE) is False

    def test_interview_ist_keine_faelligkeit(self):
        assert is_due(_app(interviewDate="2026-11-03"), today=HEUTE) is False

    def test_geloescht_ist_nicht_faellig(self):
        assert is_due(_app(deleted=True), today=HEUTE) is False

    def test_nicht_versendet_ist_nicht_faellig(self):
        assert is_due(_app(status="research", sentAt="2026-01-01"), today=HEUTE) is False
        assert is_due(_app(status="docs", sentAt=""), today=HEUTE) is False

    def test_zweite_nachfrage_nach_followup(self):
        app = _app(status="followup", sentAt="2026-09-01",
                   statusChangedAt="2026-10-05")
        assert is_due(app, today=HEUTE) is True

    def test_sortierung_nach_wartezeit(self):
        apps = [_app(firma="A", sentAt="2026-10-01"),
                _app(firma="B", sentAt="2026-09-01"),
                _app(firma="C", sentAt="2026-10-20")]
        assert [a["firma"] for a in due_applications(apps, today=HEUTE)] == ["B", "A"]


class TestFollowupText:
    def test_deutsch(self, demo_profile):
        text = followup_text(_app(), demo_profile, "de")
        assert "Nachfrage zu meiner Bewerbung als Testingenieur" in text
        assert "01.10.2026" in text
        assert "Max Mustermann" in text
        assert "Mit freundlichen Grüßen" in text

    def test_englisch(self, demo_profile):
        text = followup_text(_app(), demo_profile, "en")
        assert "Follow-up on my application" in text
        assert "01.10.2026" in text
        assert "Sincerely" in text


class TestWriteFollowup:
    def test_schreibt_neben_die_unterlagen(self, tmp_path, demo_profile):
        folder = tmp_path / "Firma - Titel"
        folder.mkdir()
        pdf = folder / "Anschreiben.pdf"
        pdf.write_bytes(b"%PDF-1.4 demo")
        out = write_followup(_app(dokumente={"anschreiben_de": str(pdf)}), demo_profile)
        assert out == folder / "Follow-up_de.txt"
        assert out.exists()
        assert "Nachfrage" in out.read_text(encoding="utf-8")

    def test_ohne_ordner_wird_nichts_geschrieben(self, tmp_path, demo_profile):
        fehlt = tmp_path / "fehlt" / "Anschreiben.pdf"
        assert write_followup(_app(dokumente={"anschreiben_de": str(fehlt)}),
                              demo_profile) is None


class TestDashboard:
    def test_zeile_markiert_faelligkeit(self):
        row = _to_data(_app(sentAt="2026-09-20"), followup_days=DEFAULT_AFTER_DAYS)
        assert row["followupDue"] is True
        assert row["followupDays"] > DEFAULT_AFTER_DAYS

    def test_nicht_faellige_zeile(self):
        row = _to_data(_app(sentAt="2026-10-24"), followup_days=DEFAULT_AFTER_DAYS)
        assert row["followupDue"] is False
        assert row["followupDays"] == 0

    def test_dashboard_enthaelt_filter_und_flag(self, tmp_path):
        app = {"key": "k", "firma": "X", "titel": "Y", "status": "sent",
               "sentAt": "2026-09-20", "score": 70, "dokumente": {}}
        out = build_dashboard({"applications": [app]}, tmp_path / "d.html",
                              30, None, followup_days=14)
        html = out.read_text(encoding="utf-8")
        assert "followupFilter" in html
        assert '"followupDue": true' in html
