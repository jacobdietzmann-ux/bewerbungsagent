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

`state.json` ist die **einzige Quelle der Wahrheit** für das Dashboard.
Alle Stufen schreiben dorthin; das Dashboard liest daraus.

## Module

| Modul | Verantwortung | Rein? |
|---|---|---|
| `profile.py` | Profil laden, Keywords/Inhaltswörter extrahieren | ✅ deterministisch |
| `matching.py` | Fit-Score (0–100) + Kategorie berechnen | ✅ deterministisch |
| `salary.py` | Gehalt schätzen, wenn Anzeige keine Zahl nennt | ✅ deterministisch |
| `commute.py` | Pendelweg (Nominatim + OSRM), mit Cache | ⚠️ Netzwerk |
| `documents.py` | Anschreiben + Lebenslauf als PDF (ReportLab) | ✅ deterministisch |
| `dashboard.py` | HTML-Dashboard rendern (Template + Daten) | ✅ deterministisch |
| `pipeline.py` | Orchestrierung der Stufen, State-Merge | teils |
| `search/*` | Provider (StepStone, DuckDuckGo, Bing, manuell) | ⚠️ Netzwerk |
| `storage.py` | JSON lesen/schreiben | ✅ |
| `server.py` | Lokaler HTTP-Server (Dashboard + `/state`-API) | ⚠️ |

**Warum das wichtig ist:** Die „reinen" Module (`profile`, `matching`,
`documents`, `dashboard`) sind ohne Netzwerk und ohne Seiteneffekte testbar —
genau dafür gibt es `tests/`.

## Datenfluss im Detail

1. **search** ruft die Provider auf, dedupliziert, schreibt `data/jobs.json`.
2. **match** scored jeden Job gegen das Profil → `data/matches.json`,
   danach Merge in `data/state.json` (bestehende Einträge behalten ihren
   Status — „History-Schutz").
3. **generate** erzeugt für geeignete Jobs PDFs unter
   `01_Bewerbungen/<Firma - Titel>/` und verlinkt sie im State.
4. **dashboard** rendert `dashboard.html` aus `state.json`.

## Status-Funnel

```
research ──▶ docs ──▶ sent ──▶ followup ──▶ interview
                 └────────▶ rejected
```

`sent`, `followup`, `interview`, `rejected` sind **geschützt**: Sie werden
nie gelöscht oder neu gescored, damit die Bewerbungshistorie erhalten bleibt.

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
