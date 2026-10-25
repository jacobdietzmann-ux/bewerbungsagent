"""Lokaler Helfer-Server für das Bewerbungsagent-Dashboard.

Angelehnt an ``00_Dashboard/Dashboard-Server.py``, angepasst an den Agenten:

- liefert das Dashboard unter http://127.0.0.1:8766/04_Agent/dashboard.html
- ``GET  /state``  -> Overlay { "<key>": {status, contact, deleted, notes, …} } aus data/jobs.db
- ``POST /state``  -> merged die vom Browser gesendeten Overlay-Einträge (per key) in data/jobs.db
- ``GET  /open?path=…`` -> öffnet einen Bewerbungsordner im Dateimanager (Path-Traversal-geschützt)

Sicherheit: bindet nur an 127.0.0.1; /open erlaubt nur Pfade innerhalb von ROOT.
Start: ``python server.py`` oder über ``dashboard-oeffnen.sh``.
"""

from __future__ import annotations

import importlib
import json
import os
import platform
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

# Normalisierung der Statuswerte aus dem Agent-Package (einzelne Quelle der Wahrheit).
try:
    from bewerbungsagent.statuses import normalize_status
except Exception:
    _LEGACY = {
        "neu": "research", "passend": "research", "dokumente_erstellt": "docs",
        "beworben": "sent", "antwort": "followup", "absage": "rejected",
        "archiviert": "rejected", "zusage": "interview", "offer": "interview",
    }
    normalize_status = lambda s: _LEGACY.get(s, s if s else "research")  # noqa: E731

try:
    from bewerbungsagent.config import Config
    from bewerbungsagent.dashboard import build_dashboard
    from bewerbungsagent.db import Store
except Exception:
    Config = None  # type: ignore[assignment]
    build_dashboard = None  # type: ignore[assignment]
    Store = None  # type: ignore[assignment]

# Agent-Root = Ordner, der dieses Skript enthält (04_Agent).
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Server-Root = eine Ebene darüber (der alte Bewerbungsordner 2026/), damit
# sowohl 01_Bewerbungen/ als auch 04_Agent/output/ erreichbar sind.
ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
HOST = "127.0.0.1"
PORT = 8766
# Das Dashboard liegt seit der Trennung von Code und Ausgabe in ``00_Dashboard``
# (Ordner für alle Dashboard-Artefakte). Der Code bleibt in ``04_Agent``.
DASHBOARD_DIR = os.path.join(ROOT, "00_Dashboard")
DASHBOARD_PATH = "/00_Dashboard/dashboard.html"
STATE_FILE = os.path.join(SCRIPT_DIR, "data", "state.json")
# SQLite-Datenbank = Single Source of Truth (ADR-018). ``state.json`` bleibt nur
# als abgeleiteter Snapshot für bisync/Backup bestehen. Der Pfad kommt aus der
# Config, damit ``BEWERBUNGSAGENT_DB`` (nicht synchronisierte Ablage unter
# Windows) greift; ohne Config/Env-Variable bleibt der Standard unter data/.
def _resolve_db_file() -> str:
    if Config is not None:
        try:
            return str(Config().db_path())
        except Exception:
            pass
    return os.path.join(SCRIPT_DIR, "data", "jobs.db")


DB_FILE = _resolve_db_file()
# Dashboard-Template/Quellcode, dessen Änderung einen Neubau auslösen soll.
DASHBOARD_SRC = os.path.join(SCRIPT_DIR, "bewerbungsagent", "dashboard.py")
# Das erzeugte Dashboard. Änderungen daran (z. B. durch ``agent.py dashboard``)
# müssen der laufende Server ebenfalls bemerken.
DASHBOARD_OUT = os.path.join(DASHBOARD_DIR, "dashboard.html")

EDITABLE = ("status", "contact", "deleted", "deleted_reason", "notes", "interviewDate",
            "statusChangedAt", "sentAt")


def open_in_file_manager(path):
    system = platform.system()
    if system == "Windows":
        os.startfile(path)
    elif system == "Darwin":
        subprocess.run(["open", path], check=True)
    else:
        subprocess.run(["xdg-open", path], check=True)


def _store() -> Store:
    """SQLite-Store (Single Source of Truth, ADR-018)."""
    return Store(DB_FILE)


def _read_state() -> dict:
    try:
        return _store().load_state()
    except Exception:
        return {"applications": []}


def _overlay_from_state(state: dict) -> dict:
    overlay = {}
    for app in state.get("applications", []):
        key = app.get("key")
        if not key:
            continue
        overlay[key] = {
            "status": normalize_status(app.get("status")),
            "contact": app.get("contact") or "",
            "deleted": bool(app.get("deleted")),
            "deleted_reason": app.get("deleted_reason") or "",
            "notes": app.get("notes") or "",
            "interviewDate": app.get("interviewDate") or "",
            "statusChangedAt": app.get("statusChangedAt") or "",
            "sentAt": app.get("sentAt") or "",
        }
    return overlay


def _apply_overlay(overlay: dict) -> None:
    """Schreibt Nutzer-Feldänderungen aus dem Dashboard in die DB (nur ``user``)."""
    normalized = {}
    for key, entry in (overlay or {}).items():
        if not isinstance(entry, dict):
            continue
        cleaned = {}
        for k in EDITABLE:
            if k in entry and entry[k] is not None:
                cleaned[k] = normalize_status(entry[k]) if k == "status" else entry[k]
        if cleaned:
            normalized[key] = cleaned
    _store().apply_overlay(normalized)


# --------------------------------------------------------------------------
# In-Memory-Dashboard: wird beim Start einmal gebaut und bei Änderungen an
# state.json (z. B. durch POST /state) automatisch neu erzeugt. Dadurch ist das
# Öffnen sofort und der Inhalt immer aktuell, ohne dass der Launcher vorher
# ``agent.py dashboard`` ausführen muss.
# --------------------------------------------------------------------------

_DASH_HTML = b""
_DASH_MTIME = -1.0
_DASH_LOCK = threading.Lock()
_DASH_BUILDING = False

_DASH_LOADING = b"""<!doctype html>
<html lang="de"><meta charset="utf-8"><meta http-equiv="refresh" content="2">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bewerbungs-Dashboard wird geladen</title>
<body style="font:16px system-ui,sans-serif;background:#0f172a;color:#e2e8f0;
padding:3rem"><h1>Dashboard wird geladen</h1>
<p>Die Bewerbungsdaten werden vorbereitet. Diese Seite aktualisiert sich automatisch.</p>
</body></html>"""


def _state_mtime() -> float:
    """Neueste Änderung an der SQLite-DB (inkl. WAL/SHM, da WAL-Mode die
    Änderungen zunächst in die -wal-Datei schreibt)."""
    mtime = -1.0
    for path in (DB_FILE, DB_FILE + "-wal", DB_FILE + "-shm"):
        try:
            mtime = max(mtime, os.path.getmtime(path))
        except OSError:
            continue
    return mtime


def _dashboard_mtime() -> float:
    """Neueste Änderung an der DB, am Dashboard-Template ODER am erzeugten HTML.

    Das erzeugte ``dashboard.html`` muss mitgezählt werden: sonst erkennt der
    Server einen externen Lauf von ``agent.py dashboard`` nicht und liefert
    weiter seinen In-Memory-Stand aus. Genau das passierte — im Browser stand
    eine alte Fassung (Grenze 90 min), während auf der Platte längst 30 min
    geschrieben war.
    """
    src_mtime = os.path.getmtime(DASHBOARD_SRC) if os.path.exists(DASHBOARD_SRC) else -1.0
    out_mtime = os.path.getmtime(DASHBOARD_OUT) if os.path.exists(DASHBOARD_OUT) else -1.0
    return max(_state_mtime(), src_mtime, out_mtime)


def _rebuild_dashboard() -> bytes:
    """Baut das Dashboard aus der SQLite-DB und aktualisiert den Cache.

    Lädt das Dashboard-Modul vorher neu, damit Änderungen am Template
    (``bewerbungsagent/dashboard.py``) ohne Server-Neustart übernommen werden.
    """
    global _DASH_HTML, _DASH_MTIME
    html = b"Dashboard konnte nicht erzeugt werden."
    if build_dashboard is not None and Config is not None:
        try:
            import bewerbungsagent.dashboard as _dash
            importlib.reload(_dash)
            config = Config()
            state = _read_state()
            # Grenze aus der Konfiguration mitgeben: ohne sie baute der Server
            # das Dashboard mit dem Modul-Standard und ignorierte
            # ``max_pendelzeit_min`` aus der config.json.
            from bewerbungsagent.commute import commute_limit_minutes
            from bewerbungsagent.pipeline import letzter_fund_meta
            path = _dash.build_dashboard(state, config.dashboard_path,
                                         commute_limit_minutes(config.data),
                                         letzter_fund_meta(config))
            with open(path, "rb") as fh:
                html = fh.read()
        except Exception as exc:
            html = ("Dashboard-Fehler: " + str(exc)).encode("utf-8")
    _DASH_HTML = html
    _DASH_MTIME = _dashboard_mtime()
    return html


def _dashboard_html() -> bytes:
    """Aktueller HTML-Stand — die Datei auf der Platte hat Vorrang.

    Der Server hielt das Dashboard nur im Speicher und baute es ausschließlich
    bei Zustandsänderungen neu. Ein externer Lauf von ``agent.py dashboard``
    blieb dadurch unsichtbar: der Browser zeigte weiter den alten Stand.
    Deshalb wird vor jeder Auslieferung die Datei geprüft.
    """
    global _DASH_HTML, _DASH_MTIME
    try:
        disk_mtime = os.path.getmtime(DASHBOARD_OUT)
    except OSError:
        disk_mtime = -1.0
    if disk_mtime > _DASH_MTIME:
        try:
            with open(DASHBOARD_OUT, "rb") as fh:
                data = fh.read()
        except OSError:
            data = b""
        if data:
            _DASH_HTML = data
            _DASH_MTIME = disk_mtime
            return data
    if not _DASH_HTML:
        _schedule_dashboard_rebuild()
        return _DASH_LOADING
    return _DASH_HTML


def _schedule_dashboard_rebuild() -> None:
    global _DASH_BUILDING
    with _DASH_LOCK:
        if _DASH_BUILDING:
            return
        _DASH_BUILDING = True

    def rebuild():
        global _DASH_BUILDING
        try:
            _rebuild_dashboard()
        finally:
            with _DASH_LOCK:
                _DASH_BUILDING = False

    threading.Thread(target=rebuild, name="dashboard-build", daemon=True).start()


def _watch_state() -> None:
    while True:
        try:
            if _dashboard_mtime() != _DASH_MTIME:
                _schedule_dashboard_rebuild()
        except OSError as exc:
            print("[dashboard] Zustandsdatei konnte nicht geprüft werden: " + str(exc), flush=True)
        time.sleep(2)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def log_message(self, fmt, *args):
        pass  # ruhige Konsole

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            return self._text(200, "ok")
        if parsed.path == "/open":
            return self._handle_open(parsed)
        if parsed.path == "/state":
            return self._handle_state_get()
        if parsed.path == DASHBOARD_PATH:
            return self._serve_dashboard()
        return super().do_GET()

    def _serve_dashboard(self):
        body = _dashboard_html()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/state":
            return self._handle_state_post()
        return self._text(404, "Nicht gefunden.")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _handle_state_get(self):
        try:
            data = json.dumps(_overlay_from_state(_read_state()), ensure_ascii=False)
        except Exception:
            data = "{}"
        body = data.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_state_post(self):
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length > 0 else b"{}"
            obj = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(obj, dict):
                return self._text(400, "Ungültiger Zustand (kein Objekt).")
            _apply_overlay(obj)
            # JSON-Snapshot für bisync/Backup nachziehen.
            _store().export_json(STATE_FILE)
            _schedule_dashboard_rebuild()
            return self._text(200, "ok")
        except Exception as exc:
            return self._text(500, "Fehler beim Speichern: " + str(exc))

    def _handle_open(self, parsed):
        params = parse_qs(parsed.query)
        rel = unquote((params.get("path") or [""])[0])
        # Backslashes zu Slashes normalisieren (schützt vor URL-encoded
        # Backslash-Traversal auf Windows, z. B. %5c%5c..%5c..%5c)
        rel = rel.replace("\\", "/")
        # ..-Segmente ablehnen, bevor der Pfad aufgelöst wird
        if ".." in rel.split("/"):
            return self._text(403, "Pfad enthält nicht erlaubte ..-Segmente.")
        target = (Path(ROOT) / rel).resolve()
        root_resolved = Path(ROOT).resolve()
        try:
            target.relative_to(root_resolved)
        except ValueError:
            return self._text(403, "Pfad ausserhalb des erlaubten Bereichs.")
        if not target.is_dir():
            return self._text(404, "Ordner nicht gefunden: " + rel)

        try:
            open_in_file_manager(str(target))
            print("[open] " + str(target))
            return self._text(200, "ok")
        except Exception as exc:
            return self._text(500, "Fehler beim Öffnen: " + str(exc))

    def _text(self, code, msg):
        body = msg.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    url = f"http://{HOST}:{PORT}{DASHBOARD_PATH}"
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print("Bewerbungsagent-Dashboard läuft auf: " + url, flush=True)
    _schedule_dashboard_rebuild()
    threading.Thread(target=_watch_state, name="dashboard-state-watch", daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBeendet.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
