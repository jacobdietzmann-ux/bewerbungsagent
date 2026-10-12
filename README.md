# Bewerbungsagent

Ein eigenständiger Python-Agent, der den kompletten Bewerbungs-Workflow automatisiert. Er nutzt
die bestehende [`Profil-Datenbank.json`](../02_Profil-und-Assets/Profil-Datenbank.json) als
**einzige Quelle der Wahrheit** und erzeugt daraus massgeschneiderte Bewerbungsunterlagen.

## Was der Agent kann

1. **Stellensuche** – durchsucht das Web nach passenden Stellenangeboten:
   - **StepStone** (neu, empfohlen): liefert *einzelne* Stellenangebote mit Titel, Firma, Ort
     und Detail-URL direkt von der Jobbörse (kein API-Key).
   - **DuckDuckGo/Bing**: allgemeine Websuche (best-effort, unzuverlässig bei deutschsprachigen
     Job-Queries).
   - **Manueller Import** für selbst gesammelte Anzeigen.
2. **Beschreibungs-Fetch** (`fetch`) – lädt die **vollständigen Stellenbeschreibungen**
   (Aufgaben + Anforderungen) über einen echten Headless-Browser (Chromium). StepStone blockiert
   den `requests`-Weg, der Browser rendert die Detailseite aber vollständig — dadurch wird der
   Fit präzise statt nur titelbasiert geschätzt.
3. **Profil-Fitting** – bewertet jede Stelle gegen dein Skill-Profil (Score 0–100,
   Kategorie *hoch/mittel/niedrig*, passende Skills, Begründung).
4. **Dokumentenerstellung** – erzeugt für jede passende Stelle ein auf dich zugeschnittenes
   **Anschreiben** und einen **Lebenslauf** (PDF, wahlweise Deutsch und/oder Englisch).
5. **Dashboard** – interaktives HTML-Dashboard (angelehnt an das alte `00_Dashboard`):
   Suche, Profil-Fit-Filter, Status-Sichtfilter, KPI-Karten, Status- und Wochen-Diagramme,
   sortierbare Tabelle mit **editierbarem Status** und ein-/ausklappbarer Beschreibung —
   Änderungen werden über einen lokalen Server dauerhaft in `data/state.json` gespeichert.
6. **Alt-Dashboard-Import** – übernimmt den kompletten Inhalt des bisherigen Dashboards
   (`00_Dashboard/Bewerbungs-Dashboard.md` + `dashboard-state.json`): alle Bewerbungen mit
   Status, Profil-Fit, Arbeitsort, Gehalt, Ansprechpartner, Stellenanzeige-URL und
   Dokument-Links.

## Projektstruktur

```
04_Agent/
├── agent.py                  # CLI-Einstieg
├── server.py                 # Lokaler Dashboard-Server (liefert HTML + speichert Änderungen)
├── dashboard-oeffnen.sh      # Start: Dashboard bauen + Server starten + Browser öffnen
├── config.json               # Konfiguration (Pfade, Suchbegriffe, Sprachen, …)
├── requirements.txt
├── bewerbungsagent/
│   ├── config.py             # Konfiguration & Pfadauflösung
│   ├── profile.py            # Profil laden & Schlüsselwörter extrahieren
│   ├── matching.py           # Fit-Scoring
│   ├── statuses.py           # Kanonische Statuswerte (6-Stufen-Funnel)
│   ├── documents.py          # Anschreiben + Lebenslauf (ReportLab-PDF)
│   ├── dashboard.py          # Interaktives HTML-Dashboard
│   ├── importer.py           # Import des alten Dashboards
│   ├── pipeline.py           # Orchestrierung der Schritte
│   ├── storage.py            # JSON-Persistenz
│   └── search/               # Such-Provider (StepStone, DuckDuckGo, Bing, Import)
├── data/                     # Arbeitsdaten (jobs.json, matches.json, state.json, …)
└── output/                   # Generierte Dokumente (ein Ordner pro Stelle)
```

## Installation

```bash
cd 04_Agent
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Nutzung

```bash
# Einzelschritte
python agent.py import-old     # Inhalt des alten Dashboards übernehmen
python agent.py search          # Web-Suche (StepStone + DuckDuckGo)
python agent.py fetch           # Vollständige Beschreibungen per Browser laden (Chromium)
python agent.py match           # Präzises Fit-Scoring gegen das Skill-Profil
python agent.py generate --all  # Dokumente für alle passenden Stellen
python agent.py generate --ids 1,2,3   # nur bestimmte Stellen
python agent.py dashboard       # HTML-Dashboard (neu) erzeugen
python agent.py status          # aktuelle Stellen anzeigen

# Alles in einem Durchlauf
python agent.py pipeline        # Suche → Match → Dokumente → Dashboard
```

Das Ergebnis ist [`dashboard.html`](dashboard.html) (nach dem ersten Lauf) sowie pro Stelle ein
Ordner unter `output/<Firma> - <Stelle>/` mit den PDFs.

## Dashboard öffnen & Status ändern

Das Dashboard ist **interaktiv** (Suche, Filter, Diagramme, sortierbare Tabelle). Um den
Status (oder Kontakt/Notiz/Interview-Termin) **dauerhaft ändern** zu können, starte den
lokalen Server:

```bash
./dashboard-oeffnen.sh          # baut das Dashboard, startet den Server, öffnet den Browser
# oder manuell:
python agent.py dashboard
python server.py                # läuft auf http://127.0.0.1:8766/04_Agent/dashboard.html
```

Der Server liefert das Dashboard aus und speichert Änderungen über `GET/POST /state` in
`data/state.json`. Ohne Server (direktes Öffnen der `dashboard.html` als Datei) funktioniert
die Anzeige, aber Statusänderungen werden nur lokal im Browser gehalten (bis der Server läuft).
Über „Ordner ↗“ in der Links-Spalte öffnet der Server den jeweiligen Bewerbungsordner im
Dateimanager.

## Stellensuche & manueller Import

Die freie Websuche ist bewusst **pluggable**:

- **StepStone** (Standard) liefert einzelne Stellenangebote. Die **Detailseiten** blockieren
  zwar den `requests`-Weg, aber `python agent.py fetch` lädt die vollständigen Beschreibungen
  über einen echten Headless-Browser (Chromium) — damit wird das Fit-Scoring präzise.
- **DuckDuckGo** liefert teils Jobbörsen-Treffer, wird aber bei mehreren Anfragen schnell
  rate-limited; **Bing** liefert bei deutschen Job-Queries oft unbrauchbare Treffer.

Manueller Import: Lege `data/import_jobs.json` an (Format siehe
[`data/import_jobs.example.json`](data/import_jobs.example.json)) — diese Einträge werden
immer mit durchsucht und gematcht. Für einen schnellen Offline-Test ohne Internet:

```bash
cp data/sample_jobs.json data/jobs.json
python agent.py match
python agent.py generate --all
python agent.py dashboard
```

## Matching

Das Fit-Scoring (`bewerbungsagent/matching.py`) ist transparent und deterministisch:

- **Phrasen-Treffer im Titel** zählen am stärksten (7 Punkte je Treffer),
- **Phrasen-Treffer im Anzeigentext** (3 Punkte),
- **Inhaltswort-Überschneidung** (1 Punkt),
- **Standort-Bonus** (+10, wenn der Ort zum Suchort passt).

Kategorien: `hoch` ≥ 65, `mittel` ≥ 40, sonst `niedrig`. Die Schwelle für die automatische
Dokumentenerstellung (`min_fit_for_generation`) lässt sich in `config.json` anpassen.

## Konfiguration

Alle Einstellungen stehen in [`config.json`](config.json):

- `profile_json` – Pfad zur Profil-Datenbank (Standard: die bestehende Datei).
- `search.query_terms` / `search.location` / `search.providers` – Suchbegriffe, Ort, Provider
  (verfügbar: `manual`, `stepstone`, `duckduckgo`, `bing`).
- `documents.languages` – erzeugte Sprachen (`["de", "en"]`).
- `documents.accent_color` – Akzentfarbe der PDFs.
- `documents.min_fit_for_generation` – Mindest-Fit für die automatische Erstellung.

## Hinweise

- **Google Drive**: Beim Betrieb direkt im synchronisierten Google-Drive-Ordner können bei sehr
  schnellen, mehrfachen Schreibvorgängen Sync-Konflikte (`*.conflict*`-Dateien) entstehen. Falls
  das auftritt, `data/` und `output/` auf ein lokales Laufwerk legen (Pfade in `config.json`).
- Die PDFs nutzen eingebaute Helvetica-Schriften und benötigen keine Font-Dateien.
- Lebenslauf-Inhalte stammen vollständig aus der Profil-Datenbank – vor der Generierung lohnt ein
  Blick in deren `tailoring_notes`, um die Positionen passend zu gewichten.

## Entwicklung

### Tests

```bash
python -m pytest          # alle Tests
python -m pytest --cov    # mit Coverage
```

Die Tests laufen gegen ein **anonymisiertes Demo-Profil**
(`tests/fixtures/profil-demo.json`) — es werden keine echten Personendaten
benötigt, und es gehen keine in Logs/CI.

Getestet werden die deterministischen Kerne: `profile` (Keyword-Extraktion),
`matching` (Fit-Scoring) und `dashboard` (Datumslogik). Für jeden historisch
aufgetretenen Fehler existiert ein Regressionstest; ein Mutationstest
(Bug absichtlich wieder einbauen) bestätigt, dass die Tests greifen.

### Backup

```bash
scripts/backup_chat.sh    # Chat-Verlauf + Checkpoints → auch als Markdown
scripts/backup_state.sh   # state.json/jobs.json (mit Integritätsprüfung)
```

> ⚠️ Der Chat-Verlauf liegt unter `~/.copilot/session-state/…` und wird vom
> Google-Drive-Sync **nicht** erfasst — dafür gibt es `backup_chat.sh`.

### Wichtig: Repo nicht auf dem Sync-Mount betreiben

Dieses Repository gehört auf ein **lokales** Laufwerk (z. B. `~/git/`), nicht
in den rclone-synchronisierten Google-Drive-Ordner. `bisync` kann Dateien
mitten im Schreiben zurücksetzen und so `.git` korrumpieren.

### Dokumentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — Aufbau, Module, Datenfluss
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — Entscheidungen (ADRs)
- [`docs/CHAT-MEMORY.md`](docs/CHAT-MEMORY.md) — kuratiertes Projektwissen
- [`docs/BACKUP.md`](docs/BACKUP.md) — Backup, Restore-Tests, Automatisierung
