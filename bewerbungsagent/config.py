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

# Fallback-Werte für persönliche Dokumentendaten (wenn config.json keine Werte liefert).
# Diese Konstanten vermeiden einen Import von documents.py (welches reportlab benötigt).
DEFAULT_HEADLINE_DE = "Testingenieur · Testkoordinator · HiL / XiL · ADAS · Domaincontroller"
DEFAULT_HEADLINE_EN = "Test Engineer · Test Coordinator · HiL / XiL · ADAS · Domain Controller"
DEFAULT_HEADLINE_CHIP_DE = "Hardware- & Embedded-Ingenieur · Elektronik / ECU · Test & Integration"
DEFAULT_HEADLINE_CHIP_EN = "Hardware & Embedded Engineer · Electronics / ECU · Test & Integration"

DEFAULT_DOC_NAMES = {
    "de": {
        "anschreiben": "Anschreiben_Jacob_Dietzmann.pdf",
        "lebenslauf": "Lebenslauf_Jacob_Dietzmann.pdf",
    },
    "en": {
        "anschreiben": "Cover_Letter_Jacob_Dietzmann_EN.pdf",
        "lebenslauf": "CV_Jacob_Dietzmann_EN.pdf",
    },
}

DEFAULT_CONFIG: dict = {
    "profile_json": "../02_Profil-und-Assets/Profil-Datenbank.json",
    "data_dir": "data",
    "output_dir": "output",
    # Zielordner für fertige Bewerbungsunterlagen (ein Unterordner pro Stelle).
    "bewerbungen_dir": "../01_Bewerbungen",
    # Dashboard-Ausgabe: eigener Ordner, damit Code (04_Agent) und Artefakt
    # getrennt bleiben. Relativ zum Agent-Root.
    "dashboard_file": "../00_Dashboard/dashboard.html",
    "search": {
        "enabled": True,
        # ``duckduckgo``/``bing`` sind bewusst nicht mehr voreingestellt: live
        # geprüft liefern sie für Stellensuche nichts Verwertbares (DuckDuckGo
        # 0 Treffer, Bing nur ``bing.com/ck/a``-Redirects zu branchenfremden
        # Firmen). ``ats`` deckt die Karriereseiten der Zielunternehmen direkt ab.
        "providers": ["manual", "stepstone", "jobspy", "ats", "arbeitnow"],
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
        # Karriereseiten direkt (Greenhouse/Lever/Ashby). Leer = automatisch aus
        # den vorhandenen Anzeigen ableiten. Beispiel:
        #   [{"firma": "STARK Defence", "ats": "greenhouse", "board": "skdse"}]
        "ats_boards": [],
        # Nur Stellen aus der Münchener Metropolregion übernehmen (oder Remote).
        # Ohne diesen Filter kostet eine Firma mit 141 weltweiten Stellen 141
        # Geocoding-Aufrufe, nur um 130 davon als zu weit zu verwerfen.
        "ats_only_near_munich": True,
        # Arbeitnow liefert 300 Stellen pro Seite ohne serverseitigen Filter.
        "arbeitnow_pages": 3,
        # JobLeads liefert die Trefferliste samt Volltext (JSON-LD) ohne Login.
        # Einträge sind Suchbegriffe (URL wird gebaut) oder Dicts mit fertiger
        # ``list_url``, z. B.:
        #   [{"list_url": "https://www.jobleads.com/de/jobs/...", "max_jobs": 50}]
        # Der Provider ist standardmäßig nicht aktiv, weil jede Suche eine
        # eigene Seite abfragt — die Treffer überlappen mit StepStone/JobSpy.
        "jobleads_searches": [],
        # Obergrenze für den Rückfall auf ``query_terms``, wenn
        # ``jobleads_searches`` leer ist. Jede Suche kostet eine Listenseite
        # plus bis zu 25 Detailseiten; JobLeads drosselt mit HTTP 429.
        "jobleads_max_terms": 6,
        # JobLeads wendet ``minSalary`` nur auf das Ranking an, nicht als harte
        # Grenze (60.000–80.000 kam trotz minSalary=80000 durch). Bleibt aus.
        "jobleads_min_salary": 0,
        # XING und Indeed rendern nur im Browser (XING: 0 Anzeigen im HTML;
        # Indeed: HTTP 403 für einfache Clients). Beide bekommen die ganze
        # Begriffsliste in **einer** Browsersitzung, weil jeder Start ~1 s kostet.
        # ``xing_terms``/``indeed_terms`` übersteuern ``query_terms`` bei Bedarf.
        "xing_max_results": 25,
        "indeed_max_results": 25,
        # jobs.labo.de ist serverseitig gerendert, braucht aber je Begriff eine
        # eigene Anfrage (keine begriffsübergreifende Suche).
        "labo_max_jobs": 120,
        # Zustand der Such-Quellen: Nach so vielen Fehlläufen in Folge wird
        # eine Quelle abgeschaltet (manuell wieder einschaltbar über
        # `agent.py providers --enable NAME`).
        "provider_health": {"max_failures": 3},
    },
    # Stellen mit längerem Pendelweg (Auto, ab Wohnadresse) werden gar nicht erst
    # angelegt: keine Unterlagen, keine Anzeige im Dashboard. Unbekannte
    # Pendelzeiten (z. B. Remote) gelten nicht als zu weit.
    "max_pendelzeit_min": 30,
    # Wie viele ``research``-Funde bleiben? Alles außerhalb dieses Fensters wird
    # als gelöscht markiert (die Daten bleiben in der DB, nur ``deleted``).
    # Begründung: der Research-Bestand war mit 165 Einträgen unübersichtlich;
    # interessant sind nur Treffer knapp unter der Unterlagen-Schwelle sowie
    # Stellen, die knapp über der Pendelgrenze liegen (zweite Chance).
    "research_filter": {
        "enabled": True,
        "fit_min": 60,          # Fenster „knapp unter der Unterlagen-Schwelle“
        "fit_max": 70,
        "commute_grace_min": 10,  # „leicht über der Pendelgrenze“ = Grenze + 10
    },
    # Mehrdimensionale Bewertung (P0a). Läuft **berichtend**: `score` bleibt
    # unverändert, bis die Dimensionen die Keyword-Baseline auf den harten
    # Labels schlagen (ADR-031). Hart ist nur die K.O.-Liste — sie blockiert
    # die automatische Unterlagenerzeugung, nicht die Anzeige.
    "matching": {
        "dimensions": {
            "gewichte": {
                "kompetenz": 0.30,
                "aufgaben": 0.20,
                "senioritaet": 0.15,
                "technologie": 0.10,
                "gehalt": 0.10,
                "arbeitsmodell": 0.10,
                "entwicklung": 0.05,
            },
            "gehalt_ziel_tsd": 65,
            "ko_gehalt_min_tsd": 55,
            # Leer = keine Senioritäts-K.O. Beispiel: ["head of"]
            "ko_senioritaet": [],
            "ziel_branchen": [
                "Automotive", "Luft- und Raumfahrt", "Defense", "Halbleiter",
                "Robotik", "Energie", "Engineering-Dienstleister",
            ],
            "ko_blockiert_generierung": True,
        },
    },
    # Nachfassen: versendete Bewerbungen ohne Reaktion werden nach N Tagen als
    # fällig markiert (Dashboard, `agent.py followup`). Versendet wird nichts
    # automatisch.
    "followup": {
        "after_days": 14,
    },
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
        "min_fit_for_generation": "hoch",  # hoch (> 70 %) | mittel (50 %) | niedrig (0 %)
        "lebenslauf_template": "classic",  # classic | modern | functional
        # Eigene aktuelle Lebenslauf-Vorlage (DOCX) statt ReportLab-Generierung.
        # Wenn gesetzt, wird das DOCX 1:1 übernommen und nur der Profil-Absatz
        # pro Stelle ersetzt (Konvertierung zu PDF via soffice). Leerer Wert
        # bzw. fehlende Datei => Fallback auf die ReportLab-Vorlage.
        "lebenslauf_vorlage": {
            "de": "../02_Profil-und-Assets/Vorlage-Aktuell/Lebenslauf_Jacob_Dietzmann.docx",
            "en": "../02_Profil-und-Assets/Vorlage-Aktuell/CV_Jacob_Dietzmann_EN.docx",
        },
        # Persönliche Daten für Dokumente (Name, Headlines, Dateinamen).
        # Diese Werte gehören nicht in den Quelltext, sondern in die lokale config.json.
        # Leere Defaults hier; die lokale config.json liefert die echten Werte.
        "personal": {
            "name": "",
            "headline_de": "",
            "headline_en": "",
            "headline_chip_de": "",
            "headline_chip_en": "",
        },
        # Dokument-Dateinamen mit Platzhaltern {firstname}, {lastname}, {name}.
        # Beispiel: {"de": {"anschreiben": "Anschreiben_{firstname}_{lastname}.pdf", ...}}
        "doc_names": {},
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

    # ---- Persönliche Daten für Dokumente ------------------------------

    def personal_name(self) -> str:
        """Liefert den vollständigen Namen aus config oder leeren String."""
        return str(self.data["documents"].get("personal", {}).get("name", ""))

    def _personal_first_last(self) -> tuple[str, str]:
        """Zerlegt den Namen in Vor- und Nachname (erstes Leerzeichen)."""
        name = self.personal_name()
        parts = name.split(" ", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return parts[0] if parts else "", ""

    def headline(self, lang: str = "de", chip: bool = False) -> str:
        """Liefert die passende Kopfzeile für Dokumente.

        Liest zuerst aus config ``documents.personal.headline_<lang>[_chip]``.
        Fallback auf die hardkodierten Module-Konstanten (für Abwärtskompatibilität).
        """
        personal = self.data["documents"].get("personal", {})
        key = f"headline_{'chip_' if chip else ''}{lang}"
        value = personal.get(key, "")
        if value:
            return value
        # Fallback auf hardkodierte Defaults (direkt definiert, um reportlab-Abhängigkeit zu vermeiden)
        if chip:
            return DEFAULT_HEADLINE_CHIP_DE if lang == "de" else DEFAULT_HEADLINE_CHIP_EN
        return DEFAULT_HEADLINE_DE if lang == "de" else DEFAULT_HEADLINE_EN

    def doc_names(self, lang: str = "de") -> dict:
        """Liefert Dokument-Dateinamen für die gegebene Sprache.

        Liest aus config ``documents.doc_names.<lang>`` mit Platzhaltern
        {firstname}, {lastname}, {name}. Fallback auf hardkodierte Defaults.
        """
        doc_names = self.data["documents"].get("doc_names", {}).get(lang, {})
        if doc_names:
            firstname, lastname = self._personal_first_last()
            name = self.personal_name()
            return {
                k: v.format(firstname=firstname, lastname=lastname, name=name)
                for k, v in doc_names.items()
            }
        # Fallback auf hardkodierte Defaults (direkt definiert, um reportlab-Abhängigkeit zu vermeiden)
        return DEFAULT_DOC_NAMES.get(lang, DEFAULT_DOC_NAMES["de"])

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
