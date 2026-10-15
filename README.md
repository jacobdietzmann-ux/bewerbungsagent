# Bewerbungsagent

Ein eigenständiger Python-Agent, der den kompletten Bewerbungs-Workflow automatisiert. Er nutzt
die bestehende [`Profil-Datenbank.json`](../02_Profil-und-Assets/Profil-Datenbank.json) als
**einzige Quelle der Wahrheit** und erzeugt daraus massgeschneiderte Bewerbungsunterlagen.

## Wie dieses Repository aufgebaut ist

Dieses Repo enthält den **versionierten Code**. Ausgeführt wird er in einem *Arbeitsordner*
neben den persönlichen Daten — die Codezeilen in der Doku (`cd 04_Agent`) beziehen sich darauf:

```
Bewerbung/2026/
├── 01_Bewerbungen/          # erzeugte Unterlagen (pro Stelle ein Ordner) – nicht im Repo
├── 02_Profil-und-Assets/    # Profil-Datenbank, CV-Vorlagen                – nicht im Repo
└── 04_Agent/                # ← dieses Repo läuft hier
    ├── bewerbungsagent/     # Paket: Suche, Matching, Dokumente, Dashboard
    ├── data/jobs.db         # SQLite, Quelle der Wahrheit (gitignored)
    └── config.json          # persönliche Angaben (gitignored)
```

**Nicht im Repo** (alle gitignored): das Profil mit echten Lebenslaufdaten, die erzeugten
PDFs/DOCX, die Datenbank und die `config.json` mit Wohnadresse und Kontakt. Der Agent ist
dadurch ohne persönliche Daten lauffähig — für einen Testlauf genügt ein eigenes Profil-JSON
nach dem Muster von [`tests/fixtures/profil-demo.json`](tests/fixtures/profil-demo.json).

## Was der Agent kann

1. **Stellensuche** – durchsucht das Web nach passenden Stellenangeboten:
   - **StepStone** (neu, empfohlen): liefert *einzelne* Stellenangebote mit Titel, Firma, Ort
     und Detail-URL direkt von der Jobbörse (kein API-Key).
   - **DuckDuckGo/Bing**: allgemeine Websuche (best-effort, unzuverlässig bei deutschsprachigen
     Job-Queries).
   - **JobSpy** (`python-jobspy`): aggregiert **LinkedIn**, **Indeed** und **Google Jobs** und
     liefert inklusive vollständiger Anzeigenbeschreibung (kein API-Key). LinkedIn funktioniert
     zuverlässig; Indeed (403) und Google Jobs (deprecated) liefern in vielen Umgebungen leer.
     Siehe [ADR-017](docs/DECISIONS.md).
   - **Manueller Import** für selbst gesammelte Anzeigen.
2. **Beschreibungs-Fetch** (`fetch`) – lädt die **vollständigen Stellenbeschreibungen**
   (Aufgaben + Anforderungen) über einen echten Headless-Browser (Chromium). StepStone blockiert
   den `requests`-Weg, der Browser rendert die Detailseite aber vollständig — dadurch wird der
   Fit präzise statt nur titelbasiert geschätzt.
3. **Profil-Fitting** – bewertet jede Stelle gegen dein Skill-Profil (Score 0–100,
   Kategorie *hoch/mittel/niedrig*, passende Skills, Begründung).
4. **Dokumentenerstellung** – erzeugt für jede passende Stelle ein auf dich zugeschnittenes
   **Anschreiben** und einen **Lebenslauf** (PDF, wahlweise Deutsch und/oder Englisch).
   Mit `documents.anschreiben_quellen` wird jeder Anspruch im Anschreiben mit **Quelle und
   Zeitraum belegt** (Retrieval-Schicht `bewerbungsagent/rag.py`); mit
   `documents.anschreiben_luecken` werden bestätigte Lücken transparent benannt statt
   verschwiegen.
5. **Dashboard** – interaktives HTML-Dashboard (angelehnt an das alte `00_Dashboard`):
   Suche, Profil-Fit-Filter, Status-Sichtfilter, KPI-Karten, Status- und Wochen-Diagramme,
   sortierbare Tabelle mit **editierbarem Status** und ein-/ausklappbarer Beschreibung —
   Änderungen werden über einen lokalen Server dauerhaft in `data/jobs.db` (SQLite)
   gespeichert.
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
│   ├── db.py                 # SQLite-Persistenz (Provider-/Nutzer-Feldtrennung)
│   ├── storage.py            # JSON-Persistenz (jobs.json, matches.json)
│   └── search/               # Such-Provider (StepStone, DuckDuckGo, Bing, JobSpy, Import)
├── data/                     # Arbeitsdaten (jobs.db, jobs.json, matches.json, state.json, …)
└── output/                   # Generierte Dokumente (ein Ordner pro Stelle)
```

## Schnellstart ohne persönliche Daten

Der Agent ist so aufgebaut, dass er **auch ohne echte Lebenslaufdaten** läuft —
für einen Reviewer oder ersten Test genügen zwei Befehle:

```bash
cp config.example.json config.json     # Beispiel nutzt das mitgelieferte Demo-Profil
pip install -e .                       # Basis-Abhängigkeiten (siehe Installation)
python agent.py match                  # Fit-Scoring gegen das Demo-Profil
```

`match` ist der sichere Einstieg: er braucht weder Netzwerk noch Browser.
`search`/`fetch` benötigen zusätzlich `playwright install chromium`; die
Dokument-Erzeugung (`generate`) erwartet eine DOCX-Vorlage oder fällt auf die
eingebaute ReportLab-Vorlage zurück.

## Installation

### Reproduzierbar mit `uv` (empfohlen)

`uv` friert die exakten Versionen in [`uv.lock`](uv.lock) ein — jede Neuinstallation
liefert **garantiert denselben Stand** wie zum Zeitpunkt des Locks.

```bash
# uv einmalig installieren (siehe https://docs.astral.sh/uv):
#   curl -LsSf https://astral.sh/uv/install.sh | sh

cd 04_Agent
uv sync                # installiert die Basis-Abhängigkeiten aus uv.lock
uv sync --extra jobspy # optional: JobSpy (LinkedIn/Indeed/Google) mit installieren
uv run python agent.py search
```

Nach einer Änderung an `pyproject.toml` den Lock aktualisieren: `uv lock`.

### Klassisch mit `pip` (Fallback)

```bash
cd 04_Agent
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# Browser für Suche-Beschreibungen (fetch) und den PDF-Export der Karte:
playwright install chromium
```

Optionale Extras: JobSpy (LinkedIn/Indeed/Google) und semantisches Matching sind
bewusst **nicht** in `requirements.txt` enthalten — sie ziehen schwere
Abhängigkeiten (pandas/pydantic bzw. torch). Mit `pip` nachinstallieren:

```bash
pip install -e ".[jobspy]"       # JobSpy-Provider
pip install -e ".[semantic]"     # experimentelles semantisches Matching
```

## Nutzung

```bash
# Einzelschritte
python agent.py import-old     # Inhalt des alten Dashboards übernehmen
python agent.py search          # Web-Suche (StepStone + DuckDuckGo)
python agent.py searches        # gespeicherte Suchen auflisten
python agent.py search "Test & Verification"  # nur eine gespeicherte Suche ausführen
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
`data/jobs.db` (SQLite, Alembic-migriert). `data/state.json` bleibt als abgeleiteter Snapshot
für bisync/Backup bestehen. Ohne Server (direktes Öffnen der `dashboard.html` als Datei)
funktioniert die Anzeige, aber Statusänderungen werden nur lokal im Browser gehalten
(bis der Server läuft).
Über „Ordner ↗“ in der Links-Spalte öffnet der Server den jeweiligen Bewerbungsordner im
Dateimanager.

## Agenten-Map (was der Agent tut)

Eine eigenständige Übersichtsseite zeigt in einer einzigen HTML-Datei, **was der Agent
macht, was er kann und wo er was verarbeitet**:

```bash
python scripts/build_agent_map.py            # → output/agent-map.html
python scripts/build_agent_map.py --pdf      # zusätzlich → output/agent-map.pdf
python scripts/build_agent_map.py --pdf --pdf-format hoch   # PDF hochkant
```

Die Karte dient auch als Arbeitsnachweis. Für eine Bewerbung ist das PDF
praktischer als die HTML, weil es sich anhängen und überall öffnen lässt.
Standard ist **Querformat**: Die Karten sind 1180 px breit und würden hochkant
auf 632 px verkleinert (Ortslabels ~4,4 pt statt ~6,7 pt).

Enthalten sind:

- **System-Map** — klickbares Ablaufdiagramm (Quellen → vier Stufen → Ausgabe) mit
  Dienste-Schicht; jeder Knoten erklärt Eingang und Ausgang.
- **Geografie-Map** — echte Koordinaten der Stellen aus dem Geocode-Cache, Mittelpunkt
  ist der Wohnort, Linien zeigen den Pendelweg, gefärbt nach Fahrzeit.
- **Befehle, Ablageplan, Dienste und Module** mit Verantwortung und Reichweite
  (Netzwerk vs. deterministisch).

Die Seite ist offline nutzbar (keine externen Bibliotheken) und liest die Zahlen direkt
aus `data/jobs.db`.

## Stellensuche & manueller Import

Die freie Websuche ist bewusst **pluggable**:

- **StepStone** (Standard) liefert einzelne Stellenangebote. Die **Detailseiten** blockieren
  zwar den `requests`-Weg, aber `python agent.py fetch` lädt die vollständigen Beschreibungen
  über einen echten Headless-Browser (Chromium) — damit wird das Fit-Scoring präzise.
  Erkennt der Fetcher eine abgelaufene Anzeige, setzt er `verfuegbar: False`
  (Badge „abgelaufen" im Dashboard). Weil die Seite als kompletter Seitentext gelesen wird und
  Jobbörsen darauf fremde Anzeigen auflisten, sind die Muster bewusst kontextgebunden. Nach einer
  Änderung an den Mustern die alten Flags neu bewerten:

  ```bash
  python scripts/recheck_expired.py            # Probelauf: nur prüfen
  python scripts/recheck_expired.py --apply    # Korrekturen speichern
  ```
- **DuckDuckGo** liefert teils Jobbörsen-Treffer, wird aber bei mehreren Anfragen schnell
  rate-limited; **Bing** liefert bei deutschen Job-Queries oft unbrauchbare Treffer.
- **JobSpy** aggregiert LinkedIn/Indeed/Google Jobs inklusive Beschreibung; läuft auf den ersten
  `jobspy_max_terms` (Standard 4) Suchbegriffen, weil es langsam ist und verwandte Begriffe
  stark überlappen. Optional installieren: `pip install -e ".[jobspy]"`.

### Gespeicherte Suchen

Statt immer alle `search.query_terms` durchzugehen, kannst du **benannte Suchen** definieren
und einzeln starten. Lege dazu `data/saved_searches.json` an:

```json
[
  {
    "name": "Test & Verification",
    "query_terms": ["Testingenieur", "ADAS Test", "HiL Test Engineer"],
    "location": "München",
    "providers": ["stepstone", "jobspy"]
  },
  {
    "name": "Embedded",
    "query_terms": ["Embedded Test", "E/E Integration", "Systemingenieur"],
    "location": "München",
    "providers": ["stepstone"]
  }
]
```

- `python agent.py searches` listet alle gespeicherten Suchen.
- `python agent.py search "Test & Verification"` führt nur diese aus.
- Ohne Datei existiert automatisch eine „Standard"-Suche aus `config.json`.
- Der manuelle Import (`data/import_jobs.json`) läuft unabhängig von der gewählten Suche immer mit.

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

- **Phrasen-Treffer im Titel** zählen am stärksten (6 Punkte je Treffer),
- **Phrasen-Treffer im Anzeigentext** (4 Punkte),
- **Inhaltswort-Überschneidung** (2 Punkte),
- **Standort-Bonus** (+10, wenn der Ort zum Suchort passt).

Deutsch/englische Varianten werden über eine Synonym-Brücke zusammengeführt („Testautomatisierung“
matcht auch „test automation“/„testautomation“). Kategorien: `hoch` ≥ 65, `mittel` ≥ 40, sonst
`niedrig`. Die Schwelle für die automatische Dokumentenerstellung (`min_fit_for_generation`)
lässt sich in `config.json` anpassen.

## Konfiguration

Alle Einstellungen stehen in [`config.json`](config.json):

- `profile_json` – Pfad zur Profil-Datenbank (Standard: die bestehende Datei).
- `search.query_terms` / `search.location` / `search.providers` – Suchbegriffe, Ort, Provider
  (verfügbar: `manual`, `stepstone`, `duckduckgo`, `bing`, `jobspy`).
- `search.jobspy_max_terms` – Anzahl der Suchbegriffe, auf denen der JobSpy-Provider läuft
  (Standard 4).
- `max_pendelzeit_min` – Obergrenze des Pendelwegs in Minuten (Standard 30). Zu weit
  entfernte Stellen werden gar nicht erst angelegt: keine Unterlagen, kein Eintrag im
  Dashboard. Unbekannte Pendelzeiten (z. B. Remote) sind kein Ausschlussgrund.
- `commute.home_address` – Ausgangspunkt für die Pendelweg-Berechnung. Bewusst **nicht** im
  Quelltext, sondern hier (bzw. in der privaten `config.json`).
- `commute.contact_email` – Kontakt für die Nominatim-/OSRM-Anfragen; leer lassen genügt
  (dann nennt der User-Agent nur die Projekt-URL).
- `documents.languages` – erzeugte Sprachen (`["de", "en"]`).
- `documents.accent_color` – Akzentfarbe der PDFs.
- `documents.min_fit_for_generation` – Mindest-Fit für die automatische Erstellung.
- `documents.anschreiben_quellen` – `true`: belegt jeden Anspruch im Anschreiben mit
  Quelle und Zeitraum (siehe `bewerbungsagent/rag.py`). Standard `false`.
- `documents.anschreiben_luecken` – `true`: benennt im Anschreiben transparent die
  bestätigten Lücken, die für *diese* Stelle relevant sind (z. B. DO-178C bei einer
  Verteidigungs-Stelle). Standard `false`.
- `documents.lebenslauf_vorlage` – eigene DOCX-Vorlage (`{"de": …, "en": …}`); nur der
  Profil-Absatz wird pro Stelle ersetzt.

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

### Evaluation (Modellqualität)

Neben den Unit-Tests gibt es eine **Offline-Evaluation** des Fit-Scorings
gegen die echten Bewerbungsentscheidungen:

```bash
python -m eval.run_eval --out eval/report.md
```

Sie liefert Precision/Recall/F1, einen Threshold-Sweep und eine
Majority-Baseline.

**Zuerst Labels setzen** — der `status` im Bestand ist ein *Prozess*-Signal
und **kein Eignungsmaß** (ADR-012):

```bash
python -m eval.label_tool --limit 25    # j/n/s je Stelle → eval/labels.csv
python -m eval.run_eval --out eval/report.md
```

Ohne manuelle Labels gibt das Skript **kein** Ergebnis aus, sondern weist auf
die fehlende Ground Truth hin. Das ist Absicht: eine plausible Zahl ohne
belastbare Labels wäre irreführend.

**Vergleich mit semantischem Matching** (Embeddings, optionales Extra
`[semantic]`):

```bash
python -m eval.run_semantic_eval --model intfloat/multilingual-e5-base
```

**Vergleich mit Cross-Encoder-Reranking:**

```bash
python -m eval.run_rerank_eval --model BAAI/bge-reranker-base
```

**Ergebnis: Beide neuronalen Verfahren verlieren** (ADR-015, ADR-016).
Auf den harten Fällen (technische, aber unpassende Stellen):

| Verfahren | AUC | Kosten |
|---|---:|---|
| **Keyword-Fit** | **0.715** | ~0 ms |
| Bi-Encoder (e5-base) | 0.560 | vorberechenbar |
| Cross-Encoder (bge-reranker) | 0.460 | ~150 ms/Stelle |

Der Cross-Encoder liegt auf **Zufallsniveau**, der Bi-Encoder knapp darüber.
Der einfache Keyword-Matcher gewinnt — jetzt **belegt** statt vermutet.

Die lehrreichste Erkenntnis war ein Fehlertyp, der dreimal auftrat: *Annahmen
über Randbedingungen nicht geprüft* (E5-Limit 512 Token, Cross-Encoder-Limit
für Anfrage+Dokument gemeinsam, eine Report-Datei die nie geschrieben wurde).
Und: Eine auf 4 Beispielen optimierte Konfiguration war auf 20 echten Labels
schlechter — **Overfitting an einer Mini-Stichprobe**.

Nächster sinnvoller Schritt ist daher nicht „noch ein Modell", sondern
**mehr Labels** zum Kalibrieren der bestehenden Lösung.

Details: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

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
