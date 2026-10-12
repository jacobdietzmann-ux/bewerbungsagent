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
