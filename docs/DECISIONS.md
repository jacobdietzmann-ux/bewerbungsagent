# Entscheidungen (ADR-Kurzprotokoll)

Architecture Decision Records im Kurzformat: *Kontext → Entscheidung → Grund*.
Diese Datei ist das „Langzeitgedächtnis" des Projekts.

---

## ADR-001 — Deterministisches Scoring statt LLM-Bewertung

**Kontext:** Der Fit-Wert entscheidet, ob Unterlagen erzeugt werden.
**Entscheidung:** Regelbasierte Keyword-/Inhaltswort-Überschneidung
(`matching.py`), kein LLM im Scoring.
**Grund:** Nachvollziehbar, reproduzierbar, unit-testbar, kostenlos.
Ein LLM-Score wäre nicht deterministisch und schwer zu prüfen.

---

## ADR-002 — History-Schutz für versendete Bewerbungen

**Kontext:** Massenlöschungen von Stellen mit niedrigem Fit.
**Entscheidung:** Status `sent`/`followup`/`interview`/`rejected` werden nie
gelöscht oder neu gescored.
**Grund:** Die Bewerbungshistorie ist ein Nachweis; ein späteres
Re-Scoring darf sie nicht rückwirkend „verschwinden" lassen.

---

## ADR-003 — Repo liegt NICHT auf dem Google-Drive-Mount

**Kontext:** Der Projektordner wird per rclone-`bisync` (alle 15 min)
mit Google Drive synchronisiert.
**Entscheidung:** Git-Repository unter `~/git/bewerbungsagent` (lokale Platte).
**Grund:** `bisync` kann lokale Änderungen zurücksetzen; Schreibvorgänge
mitten im Sync korrumpieren `.git`. FUSE ist zudem langsam.

---

## ADR-004 — Anonymisierte Fixtures für Tests

**Kontext:** Tests brauchen ein Profil, das echte Profil enthält PII.
**Entscheidung:** `tests/fixtures/profil-demo.json` mit fiktiven Daten;
`.gitignore` schließt `Profil-Datenbank.json` aus.
**Grund:** Keine echten Adressen/Telefonnummern in Repo oder CI-Logs.

---

## ADR-005 — Dashboard-Cache im Server invalidiert auch bei Template-Änderung

**Kontext:** `server.py` cached das gerenderte HTML und baute nur bei
Änderung von `state.json` neu. Änderungen an `dashboard.py` wurden ignoriert.
**Entscheidung:** Watcher vergleicht Änderungszeit von `state.json` **und**
`bewerbungsagent/dashboard.py`; beim Neubau wird das Modul per
`importlib.reload` frisch geladen.
**Grund:** Sonst zeigt das Live-Dashboard alte Templates, bis der Server
manuell neu gestartet wird.

---

## ADR-006 — „Gefunden am" nutzt `created`, nicht „heute"

**Kontext:** Die Wochenstatistik war falsch (alles in der aktuellen Woche).
**Entscheidung:** Datumspriorität `datum` → `created` → `sentAt` → heute.
**Grund:** `created` ist der echte Erfassungszeitpunkt; ohne ihn fielen alle
neu gefundenen Stellen auf „heute".

---

## ADR-007 — Klammerzusätze in Skill-Strings werden gesplittet (nach dem Strippen)

**Kontext:** `"ISO 26262 (funktionale Sicherheit)"` wurde verstümmelt.
**Entscheidung:** Erst Split-Regex, **dann** `strip("()")` auf die Teile.
**Grund:** Ein vorheriges `strip("()")` entfernt die schließende Klammer →
Split-Regex greift nicht mehr → `iso 26262` ist nie matchbar.

---

## ADR-008 — Zweisprachige Dokumente mit translations-Mapping

**Kontext:** In englischen PDFs blieben deutsche Skill-Labels.
**Entscheidung:** Explizite `*_TRANSLATIONS_EN`-Mappings in `documents.py`,
angewendet nur bei `lang == "en"`.
**Grund:** Sauber trennbar, testbar, und die deutschen Dokumente bleiben
unverändert. Jobtitel bleiben in Originalsprache (System-Abgleich).

---

## ADR-009 — Offline-Evaluation vor jeder „Verbesserung"

**Kontext:** Der Wunsch, das Matching durch KI-Methoden (Embeddings, LLM)
zu verbessern, ist ohne Messinstrument nicht überprüfbar.
**Entscheidung:** `eval/` mit Konfusionsmatrix, Precision/Recall/F1,
Threshold-Sweep und Majority-Baseline; Labels aus `state.json`.
**Grund:** Ohne Baseline ist jede „Verbesserung" eine Behauptung. Die
Evaluation zeigt zudem, dass **Accuracy** bei 83 % Negativ-Anteil irreführend
ist (Baseline erreicht 83 % Accuracy bei Recall 0).

**Ergebnis der ersten Messung:** F1 ≈ 41 % (beste Schwelle 75 %),
Precision ≈ 43 % / Recall ≈ 39 %. Der aktuelle Keyword-Matcher ist also
**deutlich schwächer als angenommen** — genau das war vorher unsichtbar.

---

## ADR-010 — Label-Semantik: `rejected` = Nutzerentscheidung

**Kontext:** Unklar, ob `rejected` („Abgelehnt/Abgelaufen") eine Firmenabsage
oder eine Triage-Entscheidung des Nutzers ist.
**Entscheidung:** `rejected` gilt als **negativ** (nicht verfolgt).
**Beleg:** In der Tracking-Tabelle sind Stellen mit 87 % und 78 % Fit als
„Abgelehnt/Abgelaufen" markiert, während 71 %-Stellen auf „Dokumente erstellt"
stehen. Bei fehlendem `sentAt` kann es keine Firmenabsage sein.
**Konsequenz:** `research`/`docs`/`neu` bleiben unlabeled (Entscheidung offen).

---

## ADR-011 — Automatisch gelöschte Einträge sind keine Labels

**Kontext:** Die Pipeline löscht Stellen mit „Fit unter 60 %" automatisch.
**Entscheidung:** Solche Einträge werden aus dem Label-Set ausgeschlossen
(`include_auto_deleted=False`).
**Grund:** Es sind **Modell-Entscheidungen, keine Nutzerentscheidungen** —
sie als Ground Truth zu verwenden würde das Modell gegen sich selbst messen.
