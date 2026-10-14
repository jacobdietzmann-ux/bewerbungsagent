"""Tests für die Dashboard-Auslieferung des lokalen Servers.

Hintergrund: ``server.py`` hielt das Dashboard nur im Speicher und baute es
ausschließlich bei Zustandsänderungen neu. Ein externer Lauf von
``agent.py dashboard`` blieb damit unsichtbar — im Browser stand weiterhin eine
alte Fassung (z. B. Pendelgrenze 90 min), während auf der Platte längst der neue
Stand lag. Diese Tests halten fest, dass die Datei auf der Platte gewinnt.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parent.parent / "server.py"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("agent_server", SERVER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["agent_server"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def out_file(tmp_path, mod):
    """Ersetzt den Dashboard-Pfad des Servers durch eine temporäre Datei."""
    original_out, original_html, original_mtime = (
        mod.DASHBOARD_OUT, mod._DASH_HTML, mod._DASH_MTIME)
    path = tmp_path / "dashboard.html"
    path.write_text("<html>alt</html>", encoding="utf-8")
    mod.DASHBOARD_OUT = str(path)
    mod._DASH_HTML = b""
    mod._DASH_MTIME = -1.0
    yield path
    mod.DASHBOARD_OUT, mod._DASH_HTML, mod._DASH_MTIME = (
        original_out, original_html, original_mtime)


class TestDashboardWirdVonDerPlatteGelesen:
    def test_liefert_die_datei(self, mod, out_file):
        assert mod._dashboard_html() == b"<html>alt</html>"

    def test_externe_aenderung_wird_erkannt(self, mod, out_file):
        """Der Kern des Bugs: neuere Datei muss durchkommen, ohne Neustart."""
        first = mod._dashboard_html()
        assert b"alt" in first

        time.sleep(0.01)
        out_file.write_text("<html>neu</html>", encoding="utf-8")
        assert mod._dashboard_html() == b"<html>neu</html>"

    def test_ohne_datei_bleibt_der_speicherstand(self, mod, out_file):
        mod._dashboard_html()
        mod._DASH_HTML = b"<html>speicher</html>"
        out_file.unlink()
        assert mod._dashboard_html() == b"<html>speicher</html>"

    def test_leere_datei_ueberschreibt_den_speicher_nicht(self, mod, out_file):
        mod._DASH_HTML = b"<html>speicher</html>"
        mod._DASH_MTIME = -1.0
        out_file.write_text("", encoding="utf-8")
        assert mod._dashboard_html() == b"<html>speicher</html>"


class TestMtimeDerDashboardQuellen:
    def test_erzeugte_datei_zaehlt_zur_mtime(self, mod, out_file):
        """Ohne das erzeugte HTML in der mtime blieb ein externer Lauf unsichtbar."""
        before = mod._dashboard_mtime()
        time.sleep(0.01)
        out_file.write_text("<html>spaeter</html>", encoding="utf-8")
        assert mod._dashboard_mtime() > before


class TestGrenzeKommtAusDerKonfiguration:
    def test_commute_limit_minutes_liest_die_konfiguration(self):
        from bewerbungsagent.commute import MAX_COMMUTE_MINUTES, commute_limit_minutes
        assert commute_limit_minutes({"max_pendelzeit_min": 25}) == 25
        assert commute_limit_minutes({}) == MAX_COMMUTE_MINUTES
        assert commute_limit_minutes({"max_pendelzeit_min": None}) == MAX_COMMUTE_MINUTES
        assert commute_limit_minutes({"max_pendelzeit_min": "kaputt"}) == MAX_COMMUTE_MINUTES

    def test_server_nutzt_dieselbe_quelle_wie_die_pipeline(self, mod):
        """Regression: der Server baute mit dem Modul-Standard statt der Config."""
        import inspect
        src = inspect.getsource(mod._rebuild_dashboard)
        assert "commute_limit_minutes" in src
