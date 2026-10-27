"""Button „Pfad kopieren" neben „Ordner ↗".

Der Ordner-Link öffnet den Ordner im Dateimanager. Für alles andere (Explorer-
Adresszeile, anderes Programm, Mail) braucht man den **absoluten** Pfad in der
Zwischenablage — ``folder`` allein ist relativ zum Server-Root und damit
außerhalb des Dashboards unbrauchbar.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from bewerbungsagent import dashboard


def _embedded_row(html: str, firma: str) -> dict:
    # ``DATA`` ist mehrzeilig formatiert; ein Regex auf ``\\[.*?\\]`` wäre
    # fehleranfällig, sobald ein verschachteltes Array endet. Deshalb echtes JSON.
    start = html.index("const DATA = ") + len("const DATA = ")
    rows, _ = json.JSONDecoder().raw_decode(html[start:])
    return next(r for r in rows if r["company"] == firma)


# Produktionsform: ``dokumente`` speichert Pfade relativ zu 04_Agent.
DOC_REL = "../01_Bewerbungen/Firma - Stelle/Anschreiben.pdf"


def _setup(tmp_path: Path, monkeypatch) -> Path:
    agent_root = tmp_path / "04_Agent"
    agent_root.mkdir()
    folder = tmp_path / "01_Bewerbungen" / "Firma - Stelle"
    folder.mkdir(parents=True)
    (folder / "Anschreiben.pdf").write_bytes(b"pdf")
    monkeypatch.setattr(dashboard, "AGENT_ROOT", agent_root)
    # ROOT wird beim Import aus AGENT_ROOT abgeleitet — im Test mitziehen.
    monkeypatch.setattr(dashboard, "ROOT", tmp_path)
    return folder


def _app(dokumente: dict | None = None) -> dict:
    return {
        "firma": "Firma", "titel": "Testingenieur", "status": "docs",
        "pendelzeit_min": 20,
        "dokumente": dokumente if dokumente is not None
                     else {"anschreiben_de": DOC_REL},
    }


def _build(tmp_path: Path, apps: list[dict]) -> str:
    out = tmp_path / "dashboard.html"
    dashboard.build_dashboard({"applications": apps}, out)
    return out.read_text(encoding="utf-8")


class TestFolderAbsPath:
    def test_relativer_und_absoluter_pfad(self, tmp_path, monkeypatch):
        folder = _setup(tmp_path, monkeypatch)
        row = _embedded_row(_build(tmp_path, [_app()]), "Firma")

        # relativ (für /open?path=…) …
        assert row["folder"] == "01_Bewerbungen/Firma - Stelle"
        assert not os.path.isabs(row["folder"])
        # … und absolut (für die Zwischenablage).
        assert row["folderAbs"] == str(folder)
        assert os.path.isabs(row["folderAbs"])

    def test_pfad_zeigt_auf_den_ordner(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        row = _embedded_row(_build(tmp_path, [_app()]), "Firma")
        assert Path(row["folderAbs"]).name == "Firma - Stelle"
        assert Path(row["folderAbs"]).is_dir()

    def test_ohne_unterlagen_leerer_pfad(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        html = _build(tmp_path, [{
            "firma": "Ohne", "titel": "X", "status": "docs", "dokumente": {},
        }])
        row = _embedded_row(html, "Ohne")
        assert row["folderAbs"] == ""
        assert row["folder"] == ""


class TestCopyButtonTemplate:
    def test_button_im_template(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        html = _build(tmp_path, [_app()])
        assert "button.copy-btn" in html
        assert 'data-copy="${encodeURIComponent(r.folderAbs)}"' in html
        # Im dichten Layout ist die Beschriftung ein Kürzel (⧉), damit die Zeile
        # flach bleibt. Der Klartext steht im Tooltip und im aria-label — ohne
        # das läse ein Screenreader nur „⧉".
        assert ">⧉</button>" in html
        assert 'aria-label="Pfad kopieren"' in html
        assert 'title="Absoluten Ordnerpfad kopieren"' in html

    def test_button_nur_mit_ordner(self, tmp_path, monkeypatch):
        """Ohne ``folderAbs`` wird der Button nicht gerendert (JS-Guard)."""
        _setup(tmp_path, monkeypatch)
        html = _build(tmp_path, [_app()])
        assert "(r.folderAbs" in html

    def test_handler_wird_gebunden(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        html = _build(tmp_path, [_app()])
        assert 'button.copy-btn").forEach(el => el.addEventListener("click", copyFolderPath))' in html

    def test_clipboard_mit_fallback(self, tmp_path, monkeypatch):
        """file:// kennt navigator.clipboard nicht — execCommand-Fallback nötig."""
        _setup(tmp_path, monkeypatch)
        html = _build(tmp_path, [_app()])
        assert "navigator.clipboard.writeText" in html
        assert 'document.execCommand("copy")' in html

    def test_rueckmeldung_per_toast(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        html = _build(tmp_path, [_app()])
        assert "Pfad kopiert:" in html
