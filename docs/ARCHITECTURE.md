# Architektur

## Überblick

Der Bewerbungsagent ist eine lokale Pipeline mit vier Stufen und einem
Dashboard als Lese-/Schreib-Oberfläche:

```
  ┌──────────┐   ┌──────────┐   ┌───────────┐   ┌────────────┐
  │  SEARCH  │──▶│  MATCH   │──▶│ GENERATE  │──▶│ DASHBOARD  │
  │ Provider │   │ Scoring  │   │ PDFs      │   │ HTML+Server│
  └──────────┘   └──────────┘   └───────────┘   └────────────┘
       │              │               │               │
   jobs.json     matches.json   01_Bewerbungen/   state.json
```

SQLite (`data/jobs.db`) ist die Quelle der Wahrheit; `state.json` ist ein
abgeleiteter Snapshot. Stellen mit einer bekannten Pendelzeit über
`max_pendelzeit_min` (Standard 90) werden gar nicht erst angelegt: Sie erhalten
beim Merge das ``deleted``-Flag, es werden keine Unterlagen erzeugt und sie
erscheinen nicht im Dashboard. Das Dashboard bettet den gesamten Bestand ein,
zeigt in der Tabelle aber nur relevante Einträge (mindestens ein vorhandenes
Anschreiben oder Lebenslauf, Pendelweg innerhalb der Grenze). Status-Verteilung,
KPIs und Wochenverlauf lassen zusätzlich reine ``research``-Funde aus.

## Module

| Modul | Verantwortung | Rein? |
|---|---|---|
| `profile.py` | Profil laden, Keywords/Inhaltswörter extrahieren | ✅ deterministisch |
| `matching.py` | Fit-Score (0–100) + Kategorie berechnen | ✅ deterministisch |
| `industry.py` | Branche aus Provider-Metadaten oder Jobtext zuordnen | ✅ deterministisch |
| `salary.py` | Gehalt schätzen, wenn Anzeige keine Zahl nennt | ✅ deterministisch |
| `commute.py` | Pendelweg (Nominatim + OSRM), mit Cache; Obergrenze `max_pendelzeit_min` | ⚠️ Netzwerk |
| `documents.py` | Anschreiben + Lebenslauf als PDF (ReportLab-Vorlagen oder eigene DOCX-Vorlage) | ✅ deterministisch |
| `dashboard.py` | HTML-Dashboard rendern (Template + Daten) | ✅ deterministisch |
| `scripts/build_agent_map.py` | Agenten-Map erzeugen (Ablauf- + Geografie-Karte) | ✅ deterministisch |
| `pipeline.py` | Orchestrierung der Stufen, State-Merge | teils |
| `search/*` | Provider (StepStone, DuckDuckGo, Bing, manuell) | ⚠️ Netzwerk |
| `storage.py` | JSON lesen/schreiben | ✅ |
| `server.py` | Lokaler HTTP-Server (Dashboard + `/state`-API) | ⚠️ |

**Warum das wichtig ist:** Die „reinen" Module (`profile`, `matching`,
`documents`, `dashboard`) sind ohne Netzwerk und ohne Seiteneffekte testbar —
genau dafür gibt es `tests/`.

## Datenfluss im Detail

1. **search** ruft die Provider auf, dedupliziert, ordnet eine Branche zu und
   berechnet vor der Bewertung den Pendelweg; Ergebnis: `data/jobs.json`.
2. **match** scored jeden angereicherten Job gegen das Profil →
   `data/matches.json`, danach Merge in SQLite (bestehende Einträge behalten
   ihren Status — „History-Schutz"). Stellen mit einer Pendelzeit über
   `max_pendelzeit_min` werden dabei als gelöscht markiert und damit gar nicht
   erst angelegt; bereits versendete/abgeschlossene Bewerbungen bleiben
   unangetastet.
3. **generate** erzeugt für geeignete Jobs PDFs unter
   `01_Bewerbungen/<Firma - Titel>/` und verlinkt sie im State. Stellen mit zu
   weitem Pendelweg werden übersprungen. Der Lebenslauf
   stammt standardmäßig aus der eigenen DOCX-Vorlage
   (`documents.lebenslauf_vorlage`, Pfad relativ zum Agent-Root): die DOCX wird
   1:1 übernommen, nur der Profil-Absatz pro Stelle ersetzt und via `soffice`
   zu PDF konvertiert. Fehlt die Vorlage, fällt der Agent auf die
   ReportLab-Vorlagen zurück (`documents.lebenslauf_template`:
   `classic` | `awesome` | `deedy` | `mcdowell` | `sidebar` | `elegant` |
   `clean`), optional per CLI `--template`.
4. **dashboard** rendert `dashboard.html` aus SQLite; Jobs ohne tatsächlich
   vorhandenes Bewerbungsdokument bleiben in der Datenbank und erscheinen nur
   nicht in der Tabelle (``visible``-Flag). Status-Verteilung und KPIs zeigen
   die sichtbaren Stellen, der Wochenverlauf die Historie ohne
   ``research``-Funde.

## Status-Funnel

```
research ──▶ docs ──▶ sent ──▶ followup ──▶ interview
                 └────────▶ rejected
```

`sent`, `followup`, `interview`, `rejected` sind **geschützt**: Sie werden
nie gelöscht oder neu gescored, damit die Bewerbungshistorie erhalten bleibt.

## Externe CV-Vorlagen (LaTeX & Typst)

Zusätzlich zum eingebauten ReportLab-Generator können Lebensläufe direkt aus
**echten Open-Source-Templates** kompiliert werden — statt sie nur nachzubauen:

- **Toolchains** (user-local, kein Root nötig):
  - `tectonic` (XeTeX-Engine, einzelnes statisches Binary, lädt Pakete on demand)
  - `typst` (einzelnes Binary, lädt Pakete aus dem Typst-Universe)
  - Beide liegen unter `~/.local/bin/`.
- **LaTeX-Vorlagen** (Quellen aus GitHub, kompiliert mit `tectonic`):
  - `posquit0/Awesome-CV`, `deedy/Deedy-Resume`, `dnl-blkv/mcdowell-cv`,
    `billryan/resume`, `jankapunkt/latexcv` (Sidebar).
  - Font-/Paket-Anpassungen: `Times New Roman`→`Liberation Serif`,
    `Source Sans 3`→`Noto Sans`, `Roboto`→`Fira Sans`,
    `fontawesome6`→`fontawesome5` (fontawesome6 nicht im tectonic-Bundle),
    `\transparent` (Paket fehlt) als No-op ersetzt.
- **Typst-Vorlagen** (neuere Trend-Templates, kompiliert mit `typst`):
  - `sardorml/vantage-typst`, `steadyfall/simple-technical-resume-template`,
    `davidculemann/typst-templates` (modern/classic), `dialvarezs/neat-cv`.
- Generatoren/Beispieldaten liegen als Session-Artefakte unter
  `~/.copilot/session-state/…/files/cv-external/` (enthalten PII → bewusst
  **nicht** im Repo). Ergebnis-PDFs: `output/Vorlagen-Beispiele/{LaTeX,Typst}/`.

## Design-Entscheidungen

- **Deterministisches Scoring** statt LLM: nachvollziehbar, reproduzierbar,
  testbar. Der Fit-Wert ist eine transparente Summe aus Treffern
  (Titel ×7, Text ×3, Inhaltswort ×1, Standort +10).
- **HTML als Datei + lokaler Server**: Das Dashboard funktioniert als
  statische Datei *und* live (Status-Änderungen via `POST /state`).
- **ReportLab** statt HTML→PDF: keine externen Abhängigkeiten, exakte
  Layout-Kontrolle (A4, ein Seitenumbruch kontrolliert).
- **Caches** für Geocoding/Pendelweg: vermeidet wiederholte API-Aufrufe
  (Nominatim-Politeness ≥ 1 s).

## Bekannte Fallstricke

- **Google-Drive-FUSE + Git**: Niemals ein Repo direkt auf dem gemounteten
  Laufwerk betreiben. rclone-`bisync` kann Dateien mitten im Schreibvorgang
  zurücksetzen → korrupte `.git`-Objekte. Deshalb liegt dieses Repo unter
  `~/git/`.
- **Helvetica/Latin-1**: Zeichen wie `→`, typografische Anführungszeichen und
  Gedankenstriche müssen vor dem PDF-Setzen nach ASCII normalisiert werden
  (`documents._sanitize`).
- **Umlaut-Normalisierung**: `normalize("München") == "munchen"`. Filter und
  Vergleiche müssen die ASCII-Form verwenden.
- **Sprach-Erkennung für Dateinamen**: `key.endswith("_en")` verwenden — nicht
  `"en" in key` (das matcht auch „anschreiben"/„lebenslauf").

## Evaluation (`eval/`)

Offline-Messung des Fit-Scorings gegen die echten Bewerbungsentscheidungen.

```
state.json ──▶ labels.py ──▶ [(score, label)] ──▶ metrics.py ──▶ report.md
                (Ground Truth)                    (Precision/Recall/F1)
```

| Datei | Zweck |
|---|---|
| `labels.py` | Eignungs-Labels (manuell + explizite Verwürfe) + Diagnose |
| `metrics.py` | Reine Metrik-Funktionen (testbar, ohne IO) |
| `label_tool.py` | Interaktives Labeling → `eval/labels.csv` |
| `run_eval.py` | CLI: Evaluation + Markdown-Report |

```bash
python -m eval.label_tool --limit 25                 # Ground Truth erzeugen
python -m eval.run_eval --state <state.json> --out eval/report.md
```

**Label-Quelle (wichtig):** Der `status` ist ein *Prozess*-Signal
(`research → docs → sent → interview → Absage`) und **kein Eignungsmaß**
(ADR-012). Verwendet werden daher nur:

1. manuelle Labels aus `eval/labels.csv`,
2. grobe Negative aus inhaltlichen Verwürfen („Nicht passende Rolle").

Score-basierte Löschungen („Fit ≤ 60 %") sind **zirkulär** und werden
ausgeschlossen. Ohne manuelle Labels gibt `run_eval` bewusst *kein* Ergebnis
aus, sondern den Hinweis auf fehlende Ground Truth.

**Warum getrennt von `tests/`:** Tests prüfen *Code-Korrektheit*
(deterministisch, immer gleich). Die Evaluation prüft *Modellqualität* gegen
echte Daten (verändert sich mit jedem Datensatz). Beides braucht andere
Werkzeuge und andere Aussagekraft.

**Methodische Fallstricke** (im Report dokumentiert):
Klassen-Ungleichgewicht (Accuracy irreführend), Label-Rauschen (abgelaufene
Anzeigen), Selection Bias (der Score beeinflusste die Entscheidung), kleine
Stichprobe (138 Fälle).
