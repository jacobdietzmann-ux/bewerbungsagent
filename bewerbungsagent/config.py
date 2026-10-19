"""Konfiguration und Pfadauflösung für den Bewerbungsagenten.

Alle relativen Pfade werden relativ zum Agent-Root (dem Ordner, in dem
``config.json`` liegt) aufgelöst.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# Agent-Root = Ordner, der dieses Package (bewerbungsagent/) enthält.
PACKAGE_DIR = Path(__file__).resolve().parent
AGENT_ROOT = PACKAGE_DIR.parent

DEFAULT_CONFIG: dict = {
    "profile_json": "../02_Profil-und-Assets/Profil-Datenbank.json",
    "data_dir": "data",
    "output_dir": "output",
    # Zielordner für fertige Bewerbungsunterlagen (ein Unterordner pro Stelle).
    "bewerbungen_dir": "../01_Bewerbungen",
    "dashboard_file": "dashboard.html",
    "search": {
        "enabled": True,
        "providers": ["manual", "duckduckgo", "bing"],
        "location": "München",
        "query_terms": [
            "Testingenieur",
            "Systemingenieur",
            "HiL Test Engineer",
            "ADAS Test",
            "Test Manager",
            "Test Automation Engineer",
            "Verification Engineer",
            "Requirements Engineer",
            "Qualitätsingenieur",
        ],
        "max_results_per_provider": 8,
        "timeout_seconds": 15,
        "user_agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
    },
    # Stellen mit längerem Pendelweg (Auto, ab Wohnadresse) werden gar nicht erst
    # angelegt: keine Unterlagen, keine Anzeige im Dashboard. Unbekannte
    # Pendelzeiten (z. B. Remote) gelten nicht als zu weit.
    "max_pendelzeit_min": 30,
    # Persönliche Angaben gehören nicht in den Quelltext: Die Wohnadresse steht
    # hier (bzw. in der lokalen config.json) und wird für Pendelweg-Geocoding
    # benötigt. Beispiel: "Musterstraße 1, 12345 Musterstadt".
    "commute": {
        "home_address": "",
        # Kontakt für Nominatim/OSRM. Leer lassen genügt (Projekt-URL).
        "contact_email": "",
        # Firmensitz je Arbeitgeber, wenn die Anzeige nur die Zentrale nennt.
        # Schlüssel = Firmenname (normalisiert verglichen), Wert = Ort/Adresse.
        # Beispiel: {"STARK Defence": "Maisach"}
        "office_overrides": {},
    },
    "documents": {
        "languages": ["de", "en"],
        "accent_color": "#0B3D5C",
        "min_fit_for_generation": "hoch",  # hoch (65 %) | mittel (50 %) | niedrig (0 %)
        "lebenslauf_template": "classic",  # classic | modern | functional
        # Eigene aktuelle Lebenslauf-Vorlage (DOCX) statt ReportLab-Generierung.
        # Wenn gesetzt, wird das DOCX 1:1 übernommen und nur der Profil-Absatz
        # pro Stelle ersetzt (Konvertierung zu PDF via soffice). Leerer Wert
        # bzw. fehlende Datei => Fallback auf die ReportLab-Vorlage.
        "lebenslauf_vorlage": {
            "de": "../02_Profil-und-Assets/Vorlage-Aktuell/Lebenslauf_Jacob_Dietzmann.docx",
            "en": "../02_Profil-und-Assets/Vorlage-Aktuell/CV_Jacob_Dietzmann_EN.docx",
        },
    },
}


class Config:
    """Lädt ``config.json`` (falls vorhanden) und merged ihn über die Defaults."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else (AGENT_ROOT / "config.json")
        raw: dict = {}
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.data = _deep_merge(DEFAULT_CONFIG, raw)

    # ---- Pfad-Helfer (relativ zum Agent-Root) --------------------------
    @property
    def agent_root(self) -> Path:
        """Ordner, in dem dieser Agent (und config.json) liegt."""
        return AGENT_ROOT

    def resolve(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else (AGENT_ROOT / p).resolve()

    @property
    def profile_path(self) -> Path:
        return self.resolve(self.data["profile_json"])

    @property
    def data_dir(self) -> Path:
        d = self.resolve(self.data["data_dir"])
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def output_dir(self) -> Path:
        d = self.resolve(self.data["output_dir"])
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def bewerbungen_dir(self) -> Path:
        d = self.resolve(self.data["bewerbungen_dir"])
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def dashboard_path(self) -> Path:
        return self.resolve(self.data["dashboard_file"])

    def jobs_path(self) -> Path:
        return self.data_dir / "jobs.json"

    def matches_path(self) -> Path:
        return self.data_dir / "matches.json"

    def state_path(self) -> Path:
        return self.data_dir / "state.json"

    def db_path(self) -> Path:
        """Pfad zur SQLite-Quelle der Wahrheit (``data/jobs.db``).

        Über die Umgebungsvariable ``BEWERBUNGSAGENT_DB`` lässt sich die
        Datenbank in eine lokale, nicht synchronisierte Ablage verschieben.
        Nötig unter Windows, wo Google Drive Desktop einzelne Dateien nicht vom
        Sync ausschließen kann und die WAL-Dateien von SQLite beim Sync
        korrumpieren (siehe docs/BACKUP.md). Ohne die Variable bleibt der
        bisherige Standard unverändert.

        Der Override gilt **nur für die produktive ``config.json``** im
        Agent-Root. Tests und Skripte übergeben eine eigene Config mit eigenem
        ``data_dir``; dort würde der Override sonst die echte Datenbank treffen
        — ein Testlauf hat sie damit auf einen einzigen Testeintrag
        zurückgesetzt (``save_state`` ersetzt den Bestand vollständig).
        """
        override = os.environ.get("BEWERBUNGSAGENT_DB", "").strip()
        if override and self.path.resolve() == (AGENT_ROOT / "config.json").resolve():
            return Path(override).expanduser()
        return self.data_dir / "jobs.db"

    def import_path(self) -> Path:
        return self.data_dir / "import_jobs.json"


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(base[key], value)
        else:
            out[key] = value
    return out
