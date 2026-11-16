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


class TestInterpreterWahl:
    """Der Lauf muss auf Windows **und** Linux starten.

    ``jobwatch`` startet jeden Schritt als eigenen Prozess. Der Interpreter war
    fest auf ``~/.venvs/bewerbungsagent/Scripts/python.exe`` verdrahtet — unter
    Windows richtig, unter Linux gibt es diesen Pfad nicht (dort ``bin/python``).
    Der Tageslauf scheiterte dadurch ab dem 20.10. bei jedem Schritt.
    """

    def test_venv_pfad_kennt_beide_plattformen(self, monkeypatch, tmp_path):
        heim = tmp_path / "home"
        monkeypatch.setattr(jobwatch.Path, "home", classmethod(lambda cls: heim))

        # Nichts vorhanden → der Linux-Pfad als Vorgabe.
        assert jobwatch._venv_python() == heim / ".venvs" / "bewerbungsagent" / "bin" / "python"

        # Windows-Ablage gewinnt, wenn sie existiert.
        win = heim / ".venvs" / "bewerbungsagent" / "Scripts"
        win.mkdir(parents=True)
        (win / "python.exe").write_text("")
        assert jobwatch._venv_python().name == "python.exe"

    def test_linux_venv_wird_erkannt(self, monkeypatch, tmp_path):
        heim = tmp_path / "home"
        monkeypatch.setattr(jobwatch.Path, "home", classmethod(lambda cls: heim))
        posix = heim / ".venvs" / "bewerbungsagent" / "bin"
        posix.mkdir(parents=True)
        (posix / "python").write_text("")
        assert jobwatch._venv_python() == posix / "python"

    def test_env_var_hat_vorrang(self):
        assert jobwatch._python_fuer_schritte({"JOBWATCH_PYTHON": "/x/python"}) == "/x/python"

    def test_venv_kommt_vor_dem_laufenden_interpreter(self, monkeypatch, tmp_path):
        """Mit System-Python gestartet fehlten den Schritten die Abhängigkeiten."""
        heim = tmp_path / "home"
        monkeypatch.setattr(jobwatch.Path, "home", classmethod(lambda cls: heim))
        posix = heim / ".venvs" / "bewerbungsagent" / "bin"
        posix.mkdir(parents=True)
        (posix / "python").write_text("")
        assert jobwatch._python_fuer_schritte({}) == str(posix / "python")

    def test_ohne_venv_der_laufende_interpreter(self, monkeypatch, tmp_path):
        heim = tmp_path / "home"
        heim.mkdir()
        monkeypatch.setattr(jobwatch.Path, "home", classmethod(lambda cls: heim))
        assert jobwatch._python_fuer_schritte({}) == jobwatch.sys.executable

    def test_schritte_laufen_mit_diesem_interpreter(self, monkeypatch, tmp_path):
        """Ende-zu-Ende: der gewählte Pfad landet im Aufruf, nicht ein fester."""
        monkeypatch.setattr(jobwatch, "RUN_OUTPUT", tmp_path / "lauf.log")
        monkeypatch.setattr(jobwatch, "_python_fuer_schritte", lambda env: "/custom/python")
        befehle = []

        def run(befehl, **_k):
            befehle.append(befehl)
            return subprocess.CompletedProcess(befehl, 0)

        monkeypatch.setattr(jobwatch.subprocess, "run", run)
        jobwatch.run_pipeline()
        assert {b[0] for b in befehle} == {"/custom/python"}


class TestDatenordner:
    """Ein frischer Datenordner hat noch kein ``data/``.

    ``jobwatch`` schrieb Protokoll und Snapshot dorthin, ohne den Ordner
    anzulegen — der Lauf brach mit ``FileNotFoundError`` ab, bevor ein Schritt lief.
    """

    def _umlenken(self, monkeypatch, daten: Path) -> None:
        monkeypatch.setattr(jobwatch, "DATA", daten)
        monkeypatch.setattr(jobwatch, "SNAPSHOT", daten / "watch_snapshot.json")
        monkeypatch.setattr(jobwatch, "RUN_LOG", daten / "watch_runs.json")
        monkeypatch.setattr(jobwatch, "RUN_OUTPUT", daten / "watch_last_run.log")

    def test_run_pipeline_legt_data_an(self, monkeypatch, tmp_path):
        daten = tmp_path / "frisch" / "data"
        self._umlenken(monkeypatch, daten)
        monkeypatch.setattr(jobwatch, "_python_fuer_schritte", lambda env: "/custom/python")
        monkeypatch.setattr(jobwatch.subprocess, "run",
                            lambda befehl, **_k: subprocess.CompletedProcess(befehl, 0))
        assert jobwatch.run_pipeline() is True
        assert (daten / "watch_last_run.log").is_file()

    def test_main_legt_data_an(self, monkeypatch, tmp_path):
        daten = tmp_path / "frisch" / "data"
        self._umlenken(monkeypatch, daten)
        monkeypatch.setattr(jobwatch, "load_jobs", lambda: [])
        monkeypatch.setattr(jobwatch, "quellen_aenderungen", lambda gemeldet: ({}, []))
        monkeypatch.setattr(jobwatch, "send_telegram", lambda text: pytest.fail("Probelauf sendet nicht"))
        assert jobwatch.main(["--no-search", "--dry-run"]) == 0
        assert (daten / "watch_snapshot.json").is_file()
        assert (daten / "watch_runs.json").is_file()


class TestSystemdUnit:
    """Die Unit-Vorlage muss auf einen Starter zeigen, den es gibt.

    Sie rief ``scripts/tageslauf.sh``; ``fcd9d8d`` hat das Skript entfernt, der
    Timer scheiterte ab dem 20.10. bei jedem Lauf.
    """

    UNIT = ROOT / "docs" / "systemd" / "bewerbungsagent-tageslauf.service"

    def _exec_start(self) -> str:
        zeilen = [z for z in self.UNIT.read_text(encoding="utf-8").splitlines()
                  if z.startswith("ExecStart=")]
        assert len(zeilen) == 1
        return zeilen[0]

    def test_kein_verweis_auf_geloeschte_skripte(self):
        assert "tageslauf.sh" not in self._exec_start()
        assert "lauf.sh" not in self._exec_start()

    def test_startet_jobwatch_und_das_skript_existiert(self):
        zeile = self._exec_start()
        assert "%h/git/bewerbungsagent/scripts/jobwatch.py" in zeile
        assert (ROOT / "scripts" / "jobwatch.py").is_file()

    def test_datenordner_ist_gesetzt(self):
        text = self.UNIT.read_text(encoding="utf-8")
        assert "Environment=BEWERBUNGSAGENT_HOME=" in text
        assert "WorkingDirectory=" in text
