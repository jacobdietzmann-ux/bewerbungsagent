"""Tests für die Pendelweg-Obergrenze: zu weite Stellen werden nicht angelegt."""

from __future__ import annotations

from bewerbungsagent.commute import (
    MAX_COMMUTE_MINUTES,
    exceeds_commute_limit,
)
from bewerbungsagent.pipeline import _commute_blocked, _flag_far_commute, _merge_state


def test_default_limit_is_35_minutes():
    assert MAX_COMMUTE_MINUTES == 35


def test_exceeds_commute_limit_known_values():
    assert exceeds_commute_limit({"pendelzeit_min": 36}) is True
    assert exceeds_commute_limit({"pendelzeit_min": 35}) is False
    assert exceeds_commute_limit({"pendelzeit_min": 25}) is False


def test_exceeds_commute_limit_unknown_is_not_a_blocker():
    """Unbekannte Pendelzeit (Remote/fehlgeschlagen) schließt niemanden aus."""
    assert exceeds_commute_limit({"pendelzeit_min": None}) is False
    assert exceeds_commute_limit({"pendelzeit_min": ""}) is False
    assert exceeds_commute_limit({}) is False
    assert exceeds_commute_limit({"pendelzeit_min": "unbekannt"}) is False


def test_exceeds_commute_limit_custom_limit():
    assert exceeds_commute_limit({"pendelzeit_min": 60}, limit=45) is True
    assert exceeds_commute_limit({"pendelzeit_min": 60}, limit=120) is False


def test_commute_blocked_reads_config(tmp_config):
    tmp_config["max_pendelzeit_min"] = 60

    class _Cfg:
        data = tmp_config

    assert _commute_blocked(_Cfg(), {"pendelzeit_min": 61}) is True
    assert _commute_blocked(_Cfg(), {"pendelzeit_min": 59}) is False


def test_commute_blocked_falls_back_to_default(tmp_config):
    tmp_config.pop("max_pendelzeit_min", None)

    class _Cfg:
        data = tmp_config

    assert _commute_blocked(_Cfg(), {"pendelzeit_min": 36}) is True
    assert _commute_blocked(_Cfg(), {"pendelzeit_min": 34}) is False


class TestFlagFarCommute:
    def test_marks_new_job_as_deleted(self):
        app = {"firma": "Weit", "status": "research", "pendelzeit_min": 44}
        assert _flag_far_commute(app, limit=30) is True
        assert app["deleted"] is True
        assert "Pendelweg" in app["deleted_reason"]

    def test_keeps_close_job(self):
        app = {"firma": "Nah", "status": "research", "pendelzeit_min": 25}
        assert _flag_far_commute(app, limit=30) is False
        assert "deleted" not in app

    def test_never_touches_sent_applications(self):
        """Echte Bewerbungsaktivität bleibt erhalten."""
        for status in ("sent", "followup", "interview", "rejected"):
            app = {"firma": "Alt", "status": status, "pendelzeit_min": 150}
            assert _flag_far_commute(app, limit=30) is False
            assert "deleted" not in app

    def test_does_not_reset_existing_deletion(self):
        app = {"firma": "Weg", "status": "research", "pendelzeit_min": 150,
               "deleted": True, "deleted_reason": "FIT < 50 %"}
        assert _flag_far_commute(app, limit=30) is False
        assert app["deleted_reason"] == "FIT < 50 %"


class TestMergeState:
    def test_new_far_job_is_not_created(self):
        matches = [{"key": "k1", "firma": "Weit", "pendelzeit_min": 44}]
        state = _merge_state({}, matches, limit=30)
        app = state["applications"][0]
        assert app["deleted"] is True
        assert "Pendelweg" in app["deleted_reason"]

    def test_new_close_job_is_kept(self):
        matches = [{"key": "k2", "firma": "Nah", "pendelzeit_min": 25}]
        state = _merge_state({}, matches, limit=30)
        assert state["applications"][0].get("deleted") is not True

    def test_existing_far_job_gets_flagged_on_merge(self):
        existing = {"applications": [
            {"key": "k3", "firma": "Weit", "status": "research", "pendelzeit_min": 41},
        ]}
        matches = [{"key": "k3", "firma": "Weit", "pendelzeit_min": 41}]
        state = _merge_state(existing, matches, limit=30)
        assert state["applications"][0]["deleted"] is True

    def test_existing_sent_job_survives(self):
        existing = {"applications": [
            {"key": "k4", "firma": "Versendet", "status": "sent", "pendelzeit_min": 200},
        ]}
        matches = [{"key": "k4", "firma": "Versendet", "pendelzeit_min": 200}]
        state = _merge_state(existing, matches, limit=30)
        assert state["applications"][0].get("deleted") is not True

    def test_untouched_jobs_are_preserved(self):
        existing = {"applications": [
            {"key": "alt", "firma": "Alt", "status": "research", "pendelzeit_min": 20},
        ]}
        state = _merge_state(existing, [], limit=30)
        assert [a["key"] for a in state["applications"]] == ["alt"]
