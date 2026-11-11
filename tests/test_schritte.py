"""Der Tageslauf (jobwatch) folgt der Schrittliste (ADR-056).

Früher kannte ``jobwatch`` weder ``generate`` noch ``quality``. Die Tests hier
schlagen an, sobald der Lauf wieder eine eigene Schrittliste führt.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

from bewerbungsagent.schritte import FETCH_LIMIT, SCHRITT_NAMEN, SCHRITTE

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("jobwatch_schritte",
                                               ROOT / "scripts" / "jobwatch.py")
jobwatch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(jobwatch)  # type: ignore[union-attr]


class TestListe:
    def test_reihenfolge(self):
        assert SCHRITT_NAMEN == ("search", "fetch", "match", "enrich", "generate",
                                 "quality", "dashboard")

    def test_nur_nachladen_und_pruefen_duerfen_scheitern(self):
        assert {s.name for s in SCHRITTE if s.optional} == {"fetch", "quality"}

    def test_fetch_ist_begrenzt(self):
        fetch = next(s for s in SCHRITTE if s.name == "fetch")
        assert fetch.argumente == ("--limit", str(FETCH_LIMIT))

    @pytest.mark.parametrize("schritt", SCHRITTE, ids=lambda s: s.name)
    def test_jeder_schritt_ist_ein_befehl_von_agent_py(self, schritt, capsys):
        """``jobwatch`` ruft ``agent.py <name> <argumente>``: Das muss parsen."""
        pytest.importorskip("reportlab")
        import agent
        with pytest.raises(SystemExit) as beendet:
            agent.main([schritt.name, *schritt.argumente, "--help"])
        assert beendet.value.code == 0

class TestJobwatch:
    def _lauf(self, monkeypatch, tmp_path, fehlschlag=""):
        monkeypatch.setattr(jobwatch, "RUN_OUTPUT", tmp_path / "lauf.log")
        befehle: list[list[str]] = []

        def run(befehl, **_k):
            befehle.append(befehl)
            return subprocess.CompletedProcess(befehl, 1 if befehl[2] == fehlschlag else 0)

        monkeypatch.setattr(jobwatch.subprocess, "run", run)
        return jobwatch.run_pipeline(), [b[2:] for b in befehle]

    def test_ruft_jeden_schritt_mit_seinen_argumenten(self, monkeypatch, tmp_path):
        ok, befehle = self._lauf(monkeypatch, tmp_path)
        assert ok is True
        assert befehle == [[s.name, *s.argumente] for s in SCHRITTE]

    @pytest.mark.parametrize("name", [s.name for s in SCHRITTE if s.optional])
    def test_optionaler_schritt_stoppt_nicht(self, monkeypatch, tmp_path, name):
        ok, befehle = self._lauf(monkeypatch, tmp_path, fehlschlag=name)
        assert ok is False
        assert [b[0] for b in befehle] == list(SCHRITT_NAMEN)

    @pytest.mark.parametrize("name", [s.name for s in SCHRITTE if not s.optional])
    def test_pflichtschritt_stoppt(self, monkeypatch, tmp_path, name):
        ok, befehle = self._lauf(monkeypatch, tmp_path, fehlschlag=name)
        assert ok is False
        assert befehle[-1][0] == name


class TestDoku:
    def test_kein_laufweg_nennt_die_alte_folge(self):
        """Die feste Liste und ihre Sonderregel dürfen nicht zurückkommen."""
        text = (ROOT / "scripts" / "jobwatch.py").read_text(encoding="utf-8")
        assert "OPTIONAL_STEPS" not in text
        assert 'steps = [' not in text
