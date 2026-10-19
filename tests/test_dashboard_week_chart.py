"""Regression: Phantom-Woche im „Bewerbungsaktivität im Wochenverlauf".

Einträge ohne ``datum``/``created``/``sentAt`` fielen auf „heute" zurück und
erschienen im Wochenverlauf in der aktuellen Woche — obwohl an dem Tag nichts
gefunden wurde (konkret: 9 Alt-Dashboard-Einträge am 19.10.2026).
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

from bewerbungsagent.dashboard import build_dashboard


def _build(tmp_path: Path, apps: list[dict]) -> str:
    target = tmp_path / "dashboard.html"
    build_dashboard({"applications": apps}, target)
    return target.read_text(encoding="utf-8")


def _data(html: str) -> list[dict]:
    m = re.search(r"^const DATA = (\[.*?\]);$", html, re.M | re.S)
    assert m, "DATA nicht gefunden"
    return json.loads(m.group(1))


def _app(**overrides) -> dict:
    app = {
        "key": "https://example.test/job/1",
        "titel": "Test Engineer",
        "firma": "Acme GmbH",
        "status": "rejected",
        "dokumente": {},
    }
    app.update(overrides)
    return app


def test_eintrag_ohne_zeitstempel_bekommt_kein_datum(tmp_path):
    """Ohne Zeitstempel bleibt das Datum leer statt „heute"."""
    html = _build(tmp_path, [_app()])
    rows = _data(html)
    assert rows[0]["date"] == ""


def test_echtes_funddatum_bleibt_erhalten(tmp_path):
    html = _build(tmp_path, [_app(created="2026-09-24T10:00:00+02:00")])
    assert _data(html)[0]["date"] == "24.09.2026"


def test_wochenverlauf_hat_keine_phantom_woche(tmp_path):
    """Die aktuell laufende Woche darf leer bleiben, wenn nichts gefunden wurde."""
    today = date.today()
    vergangen = today - timedelta(days=30)
    apps = [
        _app(key="a", created=f"{vergangen.isoformat()}T10:00:00+02:00"),
        _app(key="b"),  # ohne jedes Datum: Alt-Eintrag
    ]
    rows = _data(_build(tmp_path, apps))
    dated = [r for r in rows if r["date"]]
    assert len(dated) == 1
    # Der undatierte Eintrag fällt im Chart-Filter (parseDate("") === 0) heraus.
    assert all(r["date"] != "" for r in dated)
