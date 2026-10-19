"""Regression: Löschen muss alle Ansichten aktualisieren und erhalten bleiben.

Zwei Fehler, die zusammen wie „die Statistik aktualisiert nicht" wirken:

1. ``onDelete`` rief zwar die Render-Funktionen, aber verstreut — jede neue
   Ansicht musste dort nachgetragen werden. Jetzt gibt es ``refreshAllViews``.
2. Ein Pipeline-Lauf konnte die Löschung wieder aufheben: ``_protected_user``
   schützte ``deleted`` nicht, weil ein Lauf das Flag nicht kennt.
"""

from __future__ import annotations

from pathlib import Path

from bewerbungsagent.dashboard import build_dashboard
from bewerbungsagent.db import USER_DELETE_REASON, Store


def _html(tmp_path: Path) -> str:
    apps = [{
        "key": "k1",
        "titel": "Test Engineer",
        "firma": "Acme GmbH",
        "status": "sent",
        "dokumente": {"lebenslauf_de": "output/x/Lebenslauf.pdf"},
    }]
    target = tmp_path / "dashboard.html"
    build_dashboard({"applications": apps}, target)
    return target.read_text(encoding="utf-8")


def test_es_gibt_eine_zentrale_aktualisierung(tmp_path):
    html = _html(tmp_path)
    assert "function refreshAllViews()" in html


def test_refresh_deckt_alle_ansichten_ab(tmp_path):
    html = _html(tmp_path)
    start = html.index("function refreshAllViews()")
    body = html[start:start + 400]
    for fn in ("renderRows()", "renderKpis()", "updateStatusToggleCounts()"):
        assert fn in body, fn


def test_onDelete_nutzt_die_zentrale_aktualisierung(tmp_path):
    html = _html(tmp_path)
    start = html.index("function onDelete(e)")
    body = html[start:start + 500]
    assert "refreshAllViews()" in body
    # Kein vergessenes Einzel-Rendering mehr.
    assert "renderKpis();" not in body


def test_onDelete_markiert_die_loeschung_dauerhaft(tmp_path):
    """Ohne Marker würde ein Pipeline-Lauf die Löschung wieder aufheben."""
    html = _html(tmp_path)
    start = html.index("function onDelete(e)")
    body = html[start:start + 500]
    assert "row.deleted = true;" in body
    assert "row.deleted_reason = USER_DELETE_REASON;" in body
    # Der Marker ist im Frontend und im Backend identisch.
    from bewerbungsagent.dashboard import USER_DELETE_REASON as JS_REASON
    from bewerbungsagent.db import USER_DELETE_REASON as PY_REASON
    assert JS_REASON == PY_REASON
    assert f'const USER_DELETE_REASON = "{PY_REASON}";' in html


def test_onEdit_nutzt_die_zentrale_aktualisierung(tmp_path):
    html = _html(tmp_path)
    start = html.index("function onEdit(e)")
    body = html[start:start + 1600]
    assert "refreshAllViews()" in body


def test_tab_rueckkehr_zeichnet_neu(tmp_path):
    html = _html(tmp_path)
    assert 'addEventListener("visibilitychange"' in html


class TestLoeschungUeberlebtPipelineLauf:
    def _store(self, tmp_path):
        return Store(tmp_path / "jobs.db")

    def test_nutzer_loeschung_bleibt(self, tmp_path):
        """Ein Lauf kennt ``deleted`` nicht — die DB muss gewinnen."""
        store = self._store(tmp_path)
        app = {"key": "k1", "titel": "T", "firma": "A", "status": "sent"}
        store.save_state({"applications": [app], "updated": ""})
        state = store.load_state()
        state["applications"][0]["deleted"] = True
        state["applications"][0]["deleted_reason"] = USER_DELETE_REASON
        store.save_state(state)
        assert store.load_state()["applications"][0]["deleted"] is True

        # Lauf schreibt denselben Eintrag ohne ``deleted``.
        store.save_state({"applications": [dict(app)], "updated": ""})
        row = store.load_state()["applications"][0]
        assert row["deleted"] is True
        assert row["deleted_reason"] == USER_DELETE_REASON

    def test_filter_loeschung_darf_aufgehoben_werden(self, tmp_path):
        """Pipeline-eigene Löschungen bleiben neu bewertbar."""
        store = self._store(tmp_path)
        app = {"key": "k1", "titel": "T", "firma": "A", "status": "research"}
        store.save_state({"applications": [app], "updated": ""})
        state = store.load_state()
        state["applications"][0]["deleted"] = True
        state["applications"][0]["deleted_reason"] = "FIT < 50 %"
        store.save_state(state)

        store.save_state({"applications": [dict(app)], "updated": ""})
        assert not store.load_state()["applications"][0].get("deleted")
