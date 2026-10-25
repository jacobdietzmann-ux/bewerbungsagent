"""Ausdrücklich angeforderte Unterlagen bleiben stehen.

Ausgangslage: ``run_enrich`` Schritt 6 nimmt Unterlagen im Mittelband zurück —
ein 60-%-Treffer gilt nicht als Bewerbung, ``docs`` wird wieder ``research``
(die Dateien bleiben liegen). Wer für eine Research-Stelle aber ausdrücklich
Unterlagen anfordert, will sie behalten; ohne Sperre wäre die Anforderung nach
dem nächsten Lauf still aufgehoben.

Die Sperre ist ``unterlagen_gewuenscht`` — ein Nutzerfeld (``db.USER_FIELDS``),
damit ein Suchlauf es nicht überschreiben kann.
"""

from __future__ import annotations

import pytest

from bewerbungsagent.db import USER_FIELDS


def test_flag_ist_nutzerfeld():
    """Sonst würde ein Suchlauf das Flag in den Provider-Anteil schreiben."""
    assert "unterlagen_gewuenscht" in USER_FIELDS


@pytest.fixture
def umgebung(tmp_path, monkeypatch, demo_profile_data):
    """Bestand mit einer dokumentierten Stelle unterhalb der Schwelle."""
    import json

    from bewerbungsagent.config import Config
    from bewerbungsagent.db import Store

    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)
    (tmp_path / "profil.json").write_text(json.dumps(demo_profile_data), encoding="utf-8")
    cfg = {
        "profile_json": str(tmp_path / "profil.json"),
        "data_dir": str(tmp_path / "data"),
        "output_dir": str(tmp_path / "output"),
        "search": {"enabled": False, "providers": [], "query_terms": []},
        "documents": {"languages": ["de"]},
    }
    (tmp_path / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    config = Config(tmp_path / "config.json")

    # Pendelweg/Gehalt nicht berechnen (kein Netzwerk).
    monkeypatch.setattr("bewerbungsagent.pipeline.enrich_commute",
                        lambda apps, data_dir, *a, **k: {"total": len(apps)})
    monkeypatch.setattr("bewerbungsagent.pipeline.enrich_salary",
                        lambda apps: {"kept": 0, "estimated": 0})
    monkeypatch.setattr("bewerbungsagent.pipeline._generate_one", lambda *a, **k: [])

    doc = tmp_path / "anschreiben.pdf"
    doc.write_bytes(b"%PDF-1.4 test")

    def anlegen(**extra):
        app = {
            "key": "k1", "firma": "Acme", "titel": "Test Engineer",
            "status": "docs", "score": 62, "pendelzeit_min": 20,
            "dokumente": {"anschreiben_de": str(doc)},
        }
        app.update(extra)
        Store(config.db_path()).save_state(
            {"applications": [app], "updated": "2026-10-25T10:00:00+01:00"})
        return config

    return anlegen


def _status(config):
    from bewerbungsagent.db import Store
    return Store(config.db_path()).load_state()["applications"][0]


def test_ohne_flag_wird_zurueckgenommen(umgebung):
    """Das bestehende Verhalten bleibt: 62 % ist keine Bewerbung."""
    from bewerbungsagent.pipeline import run_enrich

    config = umgebung()
    ergebnis = run_enrich(config, None)
    assert _status(config)["status"] == "research"
    assert len(ergebnis["zurueckgenommen"]) == 1


def test_mit_flag_bleibt_der_status(umgebung):
    """Angeforderte Unterlagen bleiben als ``docs`` stehen."""
    from bewerbungsagent.pipeline import run_enrich

    config = umgebung(unterlagen_gewuenscht=True)
    ergebnis = run_enrich(config, None)
    assert _status(config)["status"] == "docs"
    assert ergebnis["zurueckgenommen"] == []


def test_flag_ueberlebt_einen_lauf(umgebung):
    """Das Flag selbst bleibt gesetzt — sonst wäre der Schutz einmalig."""
    from bewerbungsagent.pipeline import run_enrich

    config = umgebung(unterlagen_gewuenscht=True)
    run_enrich(config, None)
    run_enrich(config, None)
    assert _status(config)["unterlagen_gewuenscht"] is True


def test_ueber_der_schwelle_bleibt_es_ohne_flag_docs(umgebung):
    """Gegenprobe: das Flag ist nur für das Mittelband nötig."""
    from bewerbungsagent.pipeline import run_enrich

    config = umgebung()
    from bewerbungsagent.db import Store
    state = Store(config.db_path()).load_state()
    state["applications"][0]["score"] = 85
    Store(config.db_path()).save_state(state)
    run_enrich(config, None)
    assert _status(config)["status"] == "docs"
