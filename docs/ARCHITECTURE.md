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
   jobs.json      matches.json   01_Bewerbungen/   dashboard.html
   (Zwischenstand) (Zwischenstand) (PDFs)          (aus SQLite)
                              │
                              ▼
                   data/jobs.db     — Quelle der Wahrheit (SQLite)
                   data/state.json  — abgeleiteter Snapshot (Backup)
```

Die JSON-Dateien `jobs.json`/`matches.json` sind nur der Zwischenstand der
jeweiligen Stufe; gelesen und geschrieben wird der Bestand über
`db.Store` (SQLite). `state.json` ist ein Export für Backup und Sync.

SQLite (`data/jobs.db`) ist die Quelle der Wahrheit; `state.json` ist ein
abgeleiteter Snapshot. Stellen mit einer bekannten Pendelzeit über
`max_pendelzeit_min` (Standard 30) werden gar nicht erst angelegt: Sie erhalten
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
| `tailoring.py` | Stellenbezogene Auswahl/Formulierung für den Lebenslauf, prüft Belege gegen das Profil | ✅ deterministisch |
| `quality.py` | Prüft erzeugte Unterlagen gegen Profil, Anzeige und Datei (P0b) | ✅ deterministisch |
| `followup.py` | Fällige Nachfassen erkennen und Texte erzeugen | ✅ deterministisch |
| `dashboard.py` | HTML-Dashboard rendern (Template + Daten) | ✅ deterministisch |
| `scripts/build_agent_map.py` | Agenten-Map erzeugen (Ablauf- + Geografie-Karte) | ✅ deterministisch |
| `pipeline.py` | Orchestrierung der Stufen, State-Merge | teils |
| `search/*` | Provider (StepStone, DuckDuckGo, Bing, manuell) | ⚠️ Netzwerk |
| `provider_health.py` | Erfolg/Fehler je Such-Quelle, automatische Abschaltung | ✅ deterministisch |
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
   Liegt im Bewerbungsordner eine **`Lebenslauf-Tailoring.json`**, wird der
   Lebenslauf daraus gebaut (ReportLab, `tailoring.py`): Headline, Profilabsatz,
   Stations-Bullets, Fähigkeitsgruppen und Kernkompetenz-Karten kommen aus dem
   File. Die DOCX-Vorlage wird dann bewusst nicht verwendet — sie erlaubt nur
   das Ersetzen eines Absatzes. Das Tailoring wählt aus und formuliert um, es
   erfindet nichts: `tailoring.unbacked_terms()` prüft jeden Fachbegriff gegen
   das Profil und meldet Unbelegtes beim Erzeugen.
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
  (Titel ×6, Text ×4, Inhaltswort ×2, Standort +10). Die Faktoren 6/4/2
  mildern die Titel-Dominanz gegenüber dem früheren 7/3/1. Alle Summanden
  werden gespeichert (`title_hits`, `body_hits`, `word_hits`,
  `location_bonus`) — jeder Score ist damit aus dem Bestand nachrechenbar
  (ADR-035).
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
- **`verfuegbar` ist ein Tri-State**: `True`/`False` = geprüft, `None` =
  unbekannt (nie geprüft). Nur `False` bedeutet „abgelaufen". Wer das Feld
  truthy prüft, macht aus „unbekannt" fälschlich „abgelaufen" —
  `dashboard._availability()` kapselt das. Ebenso darf `_merge_state()`
  vorhandene Felder nicht mit `None` überschreiben: Das Matching-Ergebnis
  enthält `verfuegbar` gar nicht, ein blindes `old[f] = m.get(f)` löschte den
  Flag bei jedem Match-Lauf.
- **Abgelaufene Anzeigen kontextgebunden erkennen**: Die Seite wird als
  kompletter `body`-Text gelesen; Jobbörsen listen darauf reihenweise fremde
  Anzeigen. Ein nacktes `"abgelaufen"` oder ein Präfix wie
  `"diese stellenanzeige ist"` traf deshalb auch aktive Stellen. Muster müssen
  Anzeige/Stelle + Aussage verbinden (`fetch_descriptions._EXPIRED_PATTERNS`).
  Nach jeder Muster-Änderung die alten Flags mit
  `python scripts/recheck_expired.py --apply` neu bewerten.

### Fit-Scoring

- **`gap_terms` sperrt bestätigte Lücken**: Ein Profil kann unter `skills` einen
  „Prozessnormen-*Transfer* …“ nennen und dieselben Normen unter
  `confirmed_gaps_do_not_overclaim` als Lücke führen. Ohne Sperre zählte das
  Matching sie als positive Treffer — bei einer Verteidigungsstelle waren 4 von
  10 Text-Treffern solche Normen. Neue Lücken deshalb **immer** zusätzlich in
  `gap_terms` eintragen; das Feld ist die maschinenlesbare Form der Lücke.
- **Mehrwort-Phrasen sind wortreihenfolge-unabhängig**: `test engineer` muss
  auch „Test **Automation** Engineer“ und „Flight **Test Instrumentation**
  Engineer“ treffen. Eine Kontiguitäts-Prüfung verfehlte 30 Stellen (12 davon im
  Titel) mit 0 %.
- **Keyword-Extraktion respektiert Klammern**: Wer an `,`, `/` oder `&` teilt,
  *bevor* er Klammern abtrennt, zerlegt `"…(TCP/UDP, serielle Schnittstellen)"`
  und erzeugt unbalancierte Reste wie `"udp, serielle schnittstellen"`. Klammer
  zuerst abtrennen, dann den klammerfreien Kopf an `/` teilen. `"E/E"` und
  `"C/C++"` sind **ein** Begriff — nur trennen, wenn beide Seiten eigene Wörter
  ergeben.
- **Lücken-Begriffe nur exakt vergleichen**: `system` (aus „Robot Operating
  System“) als Substring zu sperren löschte „Embedded Systems“,
  „Echtzeitsysteme“ und ganze Rollentitel. Die Substring-Regel gilt nur für
  unterscheidungskräftige Begriffe mit Ziffer oder Bindestrich (`do-178c`).
- **`FIT < 50 %` blendet dokumentierte Stellen nicht aus**: Für sie wurden
  bewusst Unterlagen erzeugt — sie sind kein Suchrauschen. Die harte
  Pendelweg-Grenze gilt weiterhin für alle.
- **Ausblende-Flags müssen neu bewertet werden**: Ein `deleted`-Flag friert den
  Zustand seines Entstehungszeitpunkts ein. Ändert sich die Grundlage, bleibt
  die Stelle sonst für immer versteckt. `run_enrich` prüft die Begründung
  deshalb gegen den aktuellen Zustand:
  `FIT < 50 %` → gegen den heutigen Score, `Pendel…` → gegen
  `_commute_blocked()`, aktive Status (`sent`/`interview`/`rejected`) → Flag
  entfernen. **Nicht** neu bewertet werden vom Nutzer gesetzte Kriterien
  (`Nutzerkriterium`, `Neubewertung …`) und Rollen-Ausschlüsse — das sind
  Entscheidungen, keine ableitbaren Zustände. Konkreter Anlass: Nach dem
  Nachladen der Anzeigentexte lagen 14 zuvor gelöschte Stellen bei 50–68 %,
  2 bei einer überholten Pendelgrenze und 3 verschickte Bewerbungen waren
  durch ein veraltetes Flag unsichtbar.
- **Standort-Bonus aus der Pendelzeit, nicht aus dem Ortsnamen**: Ein
  Teilstring-Vergleich („munchen" im Feld `ort`) bewertete Vororte falsch —
  Ismaning (9 min) bekam 0 Punkte, München (25 min) 10. `location_bonus_for()`
  stuft nach Fahrzeit (≤30 → 10, ≤45 → 8, ≤60 → 6, ≤75 → 4, ≤90 → 2, darüber 0,
  Remote 10). Fehlt die Route, greift der Ortsvergleich als Rückfall.
- **Mehr-Standort-Angaben geben keinen Bonus**: „bundesweit, Düsseldorf, …,
  München" belegt keine Nähe; vorher machte der Marker „bundesweit"
  (`_REMOTE_MARKERS`) daraus eine Remote-Stelle mit pauschal +10. Nennt der Ort
  mehrere Standorte und liegt mindestens einer außerhalb der Metropolregion,
  gibt es 0. Land/Bundesland und Adressbestandteile (Hausnummer, PLZ) zählen
  nicht als Standort; „München, Starnberg" behält den Bonus (ADR-035).
- **Auto-Erzeugung verlangt ein Rollen-Signal im Titel**: Ein Fit > 65 % reicht
  nicht, weil Technologie-Begriffe aus dem Skill-Profil (embedded, linux,
  python, can) auch reine Software-Rollen hoch bewerten — „Embedded Linux &
  Release Engineer" kam so auf 73 % und bekam ungefragt Unterlagen.
  `has_role_signal()` prüft den Titel; die Liste ist in `_ROLE_SIGNAL_RE`
  dokumentiert und enthält bewusst `integration`/`mechatronik`, damit
  „Payload Integration Engineer" nicht blockiert wird. Architektur- und
  Beratungstitel (`architekt|architect|consult|berat|presales`) fallen trotzdem
  durch, solange kein Test-/Verifikationskern im Titel steht — sonst bekam eine
  Beratungsstelle „Lead Integration Engineer … Technology Consulting" bei 84 %
  Unterlagen (ADR-035). Der **manuelle** Auftrag (`run_generate --ids`) ist
  nicht betroffen und erzeugt weiterhin alles.

### Mehrdimensionale Bewertung (`dimensions.py`, ADR-031)

Der Keyword-Fit beantwortet nur „wie viel Profil-Vokabular steht in der
Anzeige“. `dimensions.py` bewertet dieselbe Stelle zusätzlich in sieben
Dimensionen (0–100), jeweils mit Belegen:

| Dimension | Startgewicht | Grundlage |
|---|---:|---|
| Fachliche Kompetenz | 30 % | Profil-Keyword-Treffer (Titel doppelt gewichtet) |
| Aufgaben/Tätigkeiten | 20 % | Tätigkeitsfamilien im Anzeigentext |
| Seniorität/Verantwortung | 15 % | Rollenstufe (Junior … Head) vs. Profilrollen |
| Technologie/Branche | 10 % | Branchenzuordnung (`industry.py`) |
| Gehalt | 10 % | Anzeigen-Spanne vs. Zielgehalt (Schätzungen zählen nicht) |
| Arbeitsmodell/Standort | 10 % | Pendelzeit / Remote / Homeoffice |
| Entwicklungspotenzial | 5 % | Weiterbildungs-/Aufstiegssignale |

**Berichtend, nicht entscheidend.** `score` bleibt unverändert. Die Dimensionen
entstehen in `run_enrich` (dort sind Gehalt, Pendelweg und Homeoffice bekannt)
und werden in SQLite gespeichert; das Dashboard zeigt „Dim NN %“ mit Tooltip
unter dem Fit-Wert. Erst wenn `eval/run_dimensions_eval.py` auf den harten
Labels einen Vorsprung zeigt, werden sie zur Bewertung (ADR-014/016,
Baseline AUC 0,715).

**Harte K.O.-Liste.** Sie ist nicht durch Teilwerte kompensierbar: ein
Anzeigen-Gehalt, dessen **oberes** Ende unter `ko_gehalt_min_tsd` liegt
(Standard 55 T€), und optional Titel-Muster aus `ko_senioritaet` (Standard
leer). Eine K.O. blockiert nur die *automatische* Unterlagenerzeugung — die
Stelle bleibt im Dashboard sichtbar und per `--ids` bedienbar. Schätzungen
(„Xing-Schätzung“) zählen nie als Anzeigen-Gehalt.

## Qualitätsprüfung der Unterlagen (`quality.py`, ADR-032)

Jede erzeugte Bewerbung wird unabhängig geprüft — nicht von der Stelle, die sie
geschrieben hat. Drei Quellen, drei Prüfebenen:

| Ebene | Prüft | Schwere bei Verstoß |
|---|---|---|
| Profil | jede Behauptung im Anschreiben hat einen Beleg-Bullet im Profil | Fehler |
| Profil | jeder genannte Zeitraum existiert im Profil | Fehler |
| Profil | jeder genannte Arbeitgeber/Projektkunde steht im Profil oder im Stellentitel | Fehler |
| Anschreiben | Anrede, Betreff mit Stellentitel, Grußformel | Fehler |
| Anzeige | bestätigte Lücke (`gap_terms`) wird als Transparenz-Absatz ausgewiesen | Warnung |
| Anzeige | Kernbegriffe aus dem Titel kommen im Text vor | Hinweis |
| Datei | PDF existiert, beginnt mit `%PDF`, hat plausible Seitenzahl | Fehler/Warnung |

Der Anschreiben-Text wird bei der Generierung mitgeschnitten
(`generate_anschreiben(..., text_out=...)`), nicht aus dem PDF extrahiert —
dafür wäre eine zusätzliche PDF-Abhängigkeit nötig. Alte Bewerbungen, für die
kein Text vorliegt, werden nur auf Dateiebene geprüft; das Feld
`qualitaet.umfang` (`voll` | `datei`) macht den Unterschied im Dashboard
sichtbar („Prüfung ✓“ vs. „Prüfung – Datei“).

**Wo sie läuft:** bei jeder Generierung (`_generate_one`), als eigener
Knoten `qualitaet` im Ablauf-Graph (nach `generate`, vor `review`) und per
`python agent.py quality` für den gesamten Bestand. Ein Lauf ändert keine
Dokumente — er schreibt nur Befunde in die Datenbank. Fehlende PDFs bei
versendeten/abgeschlossenen Bewerbungen sind ein *Hinweis* (Ordner wurde
aufgeräumt), bei offenen Bewerbungen ein *Fehler*.

## Nachfassen (`followup.py`)

Eine versendete Bewerbung ohne Reaktion ist kein Ergebnis. `followup.py`
beantwortet deterministisch, welche Bewerbung eine Nachfrage verdient:

- **Fällig:** Status `sent` mit `sentAt` ≥ `followup.after_days` Tagen
  (Standard 14) oder Status `followup` mit `statusChangedAt` ≥ N Tagen
  (zweite Nachfrage).
- **Nicht fällig:** mit `interviewDate` (es gab eine Reaktion), gelöschte
  Einträge, nie versendete. Fehlt das Datum, wird nichts geraten.

Das Dashboard zeigt „⏰ Nachfassen fällig (N T.)“ in der Status-Spalte, einen
Filter „Nur Nachfassen fällig“ und eine KPI-Karte. `python agent.py followup
[--days N] [--write]` listet die Fälle; `--write` legt `Follow-up_de.txt`
(oder `_en.txt`) in den Bewerbungsordner. Versendet wird nichts automatisch —
der Statuswechsel auf `followup` bleibt eine Entscheidung im Dashboard.

## Provider-Gesundheit (`provider_health.py`)

Jeder Suchlauf verrechnet je Quelle Funde und Fehler in der SQLite-Meta-Tabelle
(`provider_health` — kein Schema-Umbau). Ein Lauf zählt als **Fehler**, wenn er
Fehlermeldungen liefert *und* nichts findet; Treffer trotz einzelner Fehler
(StepStone: 2 von 28 Begriffen) sind ein Erfolg. Nach
`search.provider_health.max_failures` (Standard 3) Fehlläufen in Folge wird die
Quelle deaktiviert und im nächsten Lauf übersprungen. `agent.py providers`
zeigt die Historie; `--enable NAME` schaltet zurück (setzt den Zähler),
`--disable NAME` schaltet manuell ab, `--reset` löscht alles.

JobSpy loggt HTTP-Fehler nur („JobSpy:Indeed - 403“), statt sie zu werfen.
`search/jobspy.py` fängt diese Log-Meldungen ab und wirft, wenn kein einziger
Treffer ankam — sonst wäre eine tote Quelle für die Statistik unsichtbar.

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
