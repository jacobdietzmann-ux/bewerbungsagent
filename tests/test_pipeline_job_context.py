"""Tests für Kontextanreicherung vor dem Matching."""

from __future__ import annotations

import json
from pathlib import Path

from bewerbungsagent.config import Config
from bewerbungsagent.db import Store
from bewerbungsagent.pipeline import run_match, run_search
from bewerbungsagent.storage import load_json


def test_search_persists_industry_and_commute_before_matching(
    tmp_path: Path, tmp_config: dict, monkeypatch, demo_profile,
):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(tmp_config), encoding="utf-8")
    config = Config(config_path)
    Store(config.db_path()).save_state({
        "applications": [{
            "key": "https://example.test/job",
            "firma": "Diehl Defence",
            "titel": "Testingenieur für Betriebssysteme",
            "url": "https://example.test/job",
            "status": "sent",
            "branche": "Altbranche",
            "pendel_modus": "Auto",
            "pendelzeit_min": 999,
            "pendeldistanz_km": 999.0,
        }],
    })
    job = {
        "firma": "Diehl Defence",
        "titel": "Testingenieur für Betriebssysteme",
        "ort": "Röthenbach an der Pegnitz",
        "url": "https://example.test/job",
    }
    monkeypatch.setattr("bewerbungsagent.pipeline._search",
                        lambda *_args, **_kwargs: ([job], [], 0))

    def add_commute(jobs, _data_dir, home_address=None, contact_email=None):
        assert jobs[0]["branche"] == "Defense / Wehrtechnik"
        jobs[0].update({
            "pendel_modus": "Auto",
            "pendelzeit_min": 75,
            "pendeldistanz_km": 110.0,
        })
        return {"total": 1, "remote": 0, "routed": 1, "cached": 0, "failed": 0}

    monkeypatch.setattr("bewerbungsagent.pipeline.enrich_commute", add_commute)

    result = run_search(config, demo_profile)

    stored_job = load_json(config.jobs_path(), [])[0]
    assert stored_job["branche"] == "Defense / Wehrtechnik"
    assert stored_job["pendelzeit_min"] == 75
    assert stored_job["pendeldistanz_km"] == 110.0
    assert result["context"]["commute"]["routed"] == 1

    run_match(config, demo_profile)

    stored_app = Store(config.db_path()).load_state()["applications"][0]
    assert stored_app["status"] == "sent"
    assert stored_app["branche"] == "Defense / Wehrtechnik"
    assert stored_app["pendelzeit_min"] == 75
    assert stored_app["pendeldistanz_km"] == 110.0
