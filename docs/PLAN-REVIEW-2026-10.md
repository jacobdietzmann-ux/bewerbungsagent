# Plan aus dem externen Review — Oktober 2026

Grundlage: Architektur-/Konzeptreview eines externen Agenten vom 25.10.2026
(GitHub-Repo-Ansicht + README/AGENTS.md/ARCHITECTURE.md). Dieses Dokument
übersetzt das Review in einen verifizierten Arbeitsplan. Es ersetzt keine
ADRs — Entscheidungen werden weiterhin in `docs/DECISIONS.md` festgehalten.

## Verifizierter Ist-Stand (25.10.2026)

| Review-Punkt | Befund im Code |
|---|---|
| Matching „eindimensional“ | Bestätigt: `fit_value` = Titel ×6 + Text ×4 + Inhaltswort ×2 + Standort-Bonus (≤10 aus Pendelzeit). Keine Senioritäts-, Gehalts- oder Arbeitsmodell-Dimension. Harte Ausschlüsse nur Rolle/Student/Techniker/Pendel. |
| Pendelzeit-Doku widersprüchlich | Bestätigt und behoben: `ARCHITECTURE.md` nannte Standard 90, Code/README/Config 30. |
| Kein Qualitäts-Check der Dokumente | Bestätigt: `documents.py` erzeugt deterministisch; `knoten_review` ist ein reiner Durchlauf. Es gibt `_claim_signature`/`gap_terms`, aber keine unabhängige Prüfstufe. |
| Zu wenige Integrationstests | Bestätigt: 946 Tests, überwiegend Unit-Tests der deterministischen Module; keine Pipeline-Fehlerszenarien. |
| Zu viele Provider | Bestätigt: 13 Provider; Indeed/JobSpy real 403, ATS-Rate-Limits real (Qualcomm). |
| Orchestrator fehlt | Falsch: `orchestrator.py` hat bereits einen Knoten-DAG (suche → triage → beschreibung → match → enrich → generate → review → dashboard). |
| JSON vs. SQLite | Halb richtig: Text ist SQLite-first; nur das ASCII-Diagramm zeigt noch JSON-Zwischenstufen. Kosmetik (P2). |
| `/agents`-Ansicht | Irrelevant: Es gibt kein `agents/`- oder `.github/agents/`-Verzeichnis. Die URL lief deshalb leer. |

## Schritt 0 — Sync zwischen Repo und Live-Ordner (erledigt 25.10.2026)

Der Live-Ordner war bei mehreren Dateien neuer als das Repo, das Repo bei
anderen. Übernommen wurden ausschließlich die echten Live-Neuerungen:

- `bewerbungsagent/config.py`, `documents.py`, `pipeline.py` — persönliche
  Dokumentdaten (Name, Headlines, Dateinamen) aus `documents.personal` /
  `documents.doc_names` in der `config.json`, mit Fallback-Konstanten.
- `server.py` — Pfad-Traversal über URL-encoded Backslashes blockiert.
- `scripts/jobwatch.py`, `wochenlauf.sh`, `migrate_state_to_db.py`,
  `repair_fehllauf.py` — liefen bisher nur im Live-Ordner.
- `scripts/tageslauf.sh` — Default `AGENT_DIR` ist jetzt `~/git/bewerbungsagent`
  (kein SQLite-WAL auf dem Sync-Mount).
- `tests/test_config_bug5.py` — Funktionstests für die neuen Config-Methoden.
- `GIT-REPO.md`, `config.example.json` (neue Schlüssel dokumentiert).

Nicht übernommen, weil im Repo neuer: `requirements.txt` (python-docx),
`config.example.json` (Provider-Liste), `docs/BACKUP.md` (Dashboard-Pfad),
`tests/test_profile.py` (Docstrings), `profile.py` (nur Zeilenenden).

Stand: 946 Tests grün. Commits `b9be532`, `f37d201`, `a7b210b`.

## P0a — Matching: Dimensionen + harte K.O.-Kriterien ✅ (Stand 25.10.2026)

**Ziel:** Ein hoher Fit darf eine unpassende Stelle nicht mehr kompensieren.

Umgesetzt in `bewerbungsagent/dimensions.py` (ADR-031):

1. `score_dimensions(profile, job)` liefert sieben Teilwerte (Kompetenz,
   Aufgaben, Seniorität, Technologie/Branche, Gehalt, Arbeitsmodell,
   Entwicklung), jeweils mit Belegliste.
2. `fit_value` bleibt der Default-Score. Die Dimensionen laufen **berichtend**
   mit: `run_enrich` berechnet sie, SQLite speichert sie, das Dashboard zeigt
   „Dim NN %“ mit Tooltip unter dem Fit-Wert.
3. Harte K.O.-Liste als eigene Stufe: Anzeigen-Gehalt, dessen **oberes** Ende
   unter `ko_gehalt_min_tsd` (Standard 55 T€) liegt; optional Titel-Muster aus
   `ko_senioritaet` (Standard leer). K.O. blockiert nur die automatische
   Unterlagenerzeugung, nicht die Anzeige. Schätzungen („Xing-Schätzung“)
   zählen nicht.
4. Gewichte und Schwellen in `matching.dimensions` (`config.py` /
   `config.example.json`), Tests in `tests/test_dimensions.py` (33 Tests).

**Messung (`eval/run_dimensions_eval.py`, 25.10.2026):** 14 gelabelte Fälle,
davon 13 manuelle. AUC (manuell): Keyword-Fit 100,0 %, Dimensionen gesamt
98,8 %. Kein Vorsprung — die Dimensionen bleiben berichtend. Ergebnis ist
**vorläufig**: 20 Labels in `labels.csv`, davon 7 ohne Bestandseintrag; für
eine Entscheidung sind ≥ 50 je Klasse nötig.

**K.O. auf den Realdaten:** 0 von 295 sichtbaren Stellen (Schwelle 55 T€).
Zum Vergleich: 58 T€ trifft 0, 60 T€ trifft 2, 65 T€ trifft 3 Anzeigen mit
echter Gehaltsspanne. Die Schwelle ist eine persönliche Entscheidung und in
`config.json` änderbar.

## P0b — Quality-Knoten (`qualitaet`) vor `review` ✅ (Stand 25.10.2026)

**Ziel:** Keine erfundenen Kompetenzen, keine falschen Zeiträume, keine
unbelegten Behauptungen in versandfertigen Unterlagen.

Umgesetzt in `bewerbungsagent/quality.py` (ADR-032):

1. Deterministische Prüfung des gerenderten Anschreibens gegen das Profil:
   Behauptungen (Signaturvergleich mit den Profil-Bullets), Zeiträume,
   Arbeitgeber/Projektkunden, Pflichtteile (Anrede, Betreff, Grußformel).
2. Anzeige: bestätigte Lücken müssen als Transparenz-Absatz erscheinen
   (Warnung), Kernbegriffe aus dem Titel sollen vorkommen (Hinweis).
3. Datei: PDF vorhanden, `%PDF`-Header, plausible Seitenzahl. Fehlende PDFs
   bei versendeten/abgelehnten Bewerbungen sind ein Hinweis (Ordner
   aufgeräumt), bei offenen ein Fehler.
4. Befunde landen in SQLite (`qualitaet`) und im Dashboard als
   „Prüfung ✓ / ⚠ N / ✗ N / – Datei“ mit Tooltip. Neuer Knoten `qualitaet`
   im Ablauf-Graph und `python agent.py quality` für den Bestand.

**Realdaten:** 169 vorhandene Anschreiben neu gerendert und geprüft —
0 Fehler, 0 Warnungen, 4 Hinweise. Der Bestandslauf fand 22 alte Bewerbungen
mit aufgeräumten PDF-Ordnern (nur Hinweis).

## P1 — Research und Company

1. **Provider-Gesundheit:** Erfolgs-/403-/Rate-Limit-Statistik pro Quelle in
   SQLite; Auto-Deaktivierung nach N Fehlläufen in Folge, manuelle
   Reaktivierung. Priorität ATS > StepStone > Arbeitnow > Rest.
2. **Suchprofile erweitern** (Config): Testingenieur/System Test,
   Testmanager, Test & Verification, E/E-Integration, ADAS, HiL/SiL,
   Teilprojektleiter Funktionsintegration. Danach ein Lauf mit Messung von
   Noise/Coverage — nicht alle Profile gleichzeitig scharf schalten.
3. **Company-Node** nach `match`, vor `generate`: Unternehmen, Abteilung,
   Projekte nur für die Top-Kandidaten nachladen (Kostenbegrenzung).

## P2 — Integrationstests, Doku, Career

1. **Integrationstests:** gemockte Provider mit kaputten Daten, Dubletten-
   Import, verschwindende/geänderte Anzeige, fehlgeschlagene Migration,
   abgebrochenes `generate`, unterbrochener Tageslauf.
2. **Doku vereinheitlichen:** Diagramm in `ARCHITECTURE.md` auf SQLite-first,
   Matching-Gewichte ins README, ADR für die neuen Dimensionen.
3. **Career-Agent zuletzt:** Follow-up- und Interview-Vorlagen als Templates,
   nicht als Automatisierung.

## Nicht-Ziele

- **Kein 6-Agenten-Rebuild.** Der Knoten-DAG bleibt die Struktur; die
  „Agenten“ des Reviews (Research, Matching, Application, Quality, Company,
  Career) werden als Dokumentationsschicht auf die Knoten abgebildet.
- **Keine unvalidierten Gewichte.** Die 30/20/15/10/10/10/5-Tabelle des
  Reviews ist eine Hypothese; sie wird erst nach Messung übernommen.

## Offene Entscheidungen

1. Labels auf 50–100 erweitern (Voraussetzung für P0a-Schritt 4).
2. LLM im Quality-Check: gated auf `generate`-Kandidaten oder rein
   deterministisch starten?
3. Auto-Deaktivierung von Providern: Schwelle (z. B. 3 Fehlläufe in Folge)?
4. Company-Research: Quelle und Tagesbudget.
