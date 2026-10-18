# Project Guidelines — Bewerbungsagent

## Build & Test

```bash
# Abhängigkeiten liegen in einem eigenen venv (nicht im System-Python):
python -m pip install -e ".[dev]"
python -m pytest -q

# Evaluation (Arbeitsartefakte → Google Drive, nie committen):
python -m eval.run_eval --out eval/report.md
```

Im Live-Arbeitsordner (`04_Agent/`) immer mit `PYTHONPATH=$PWD` laufen lassen,
damit `bewerbungsagent` importierbar ist.

## Hard Rules (aus echten Fehlern dieser Session — verifizieren, nicht annehmen)

1. **Datei-Schreibvorgänge verifizieren.** Nach jedem Code, der eine Datei
   schreibt (Report, CSV, PDF): prüfen, dass sie existiert und Inhalt hat.
   Die Log-Ausgabe „Report geschrieben" ist *kein* Beweis. (Fehler:
   `run_semantic_eval`/`run_rerank_eval` hatten gar keinen `write_text`-Aufruf.)

2. **Token-Limits vor dem Einbetten prüfen.** E5 schneidet bei 512 Token ab;
   der Cross-Encoder hat 512 Token für Anfrage **und** Dokument **gemeinsam**.
   Ein langes Profil wird stillschweigend beschnitten. Vor jedem Embedding:
   Tokenzahl ausgeben. (ADR-015, ADR-016.)

3. **Keine Schlüsse aus Mini-Stichproben.** 4 handgeprüfte Beispiele sind kein
   Datensatz; aus 8 Labels kann man nicht „der Score ist blind" folgern.
   Eine Konfiguration auf Einzelfälle zu optimieren ist Overfitting. (ADR-014,
   ADR-016.)

4. **Labels gehören zur Spezifikation.** `status` ist ein *Prozess*-Zustand,
   kein Eignungsmaß. `rejected` heißt „beworben, von der Firma abgelehnt" —
   NICHT „passt nicht". (ADR-012.)

5. **Google-Drive-Sync revert-et lokale Änderungen.** Nach jeder Änderung im
   synchronisierten Arbeitsordner zurück zum Remote hochladen
   (`rclone copyto` für Dateien, `rclone copy` für Ordner) oder auf den
   nächsten Bisync-Lauf warten. Persönliche Angaben (Wohnadresse, Kontakt)
   stehen ausschließlich in der dortigen `config.json` — nie im Quelltext.

6. **Es gibt zwei Code-Orte.** Versioniertes Repo (`~/git/bewerbungsagent`)
   und Live-Arbeitsordner (`04_Agent/`). Änderungen im Repo müssen in den
   Arbeitsordner kopiert werden (und umgekehrt relevant fürs Laufen).

7. **SQLite ist die Quelle der Wahrheit, `state.json` nur ein Snapshot.**
   Seit ADR-018 liegt der Bestand in `data/jobs.db` (Alembic-migriert).
   `data/jobs.db*` ist von bisync **ausgeschlossen** (Binärdatei!). Nach jedem
   Schreiben wird `state.json` als abgeleiteter Snapshot exportiert — der ist
   bisync-sicher und dient als Backup. DB-Veränderungen nur über `db.Store`,
   nie durch direktes JSON-Editing von `state.json`. Unter Windows (Google
   Drive Desktop, keine Datei-Ausschlüsse) liegt die DB stattdessen unter
   `%LOCALAPPDATA%\bewerbungsagent\jobs.db` (Env-Variable
   `BEWERBUNGSAGENT_DB`, siehe docs/BACKUP.md).

8. **`uv.lock` nach Dependency-Änderungen aktualisieren.** Nach jeder Änderung an
   `pyproject.toml` (Dependencies/Extras) `uv lock` ausführen und `uv.lock`
   committen — sonst driftet der reproduzierbare Stand von der Realität weg.

## Konventionen

- **Keine PII im Repo.** `config.json`, `Profil-Datenbank.json`, `labels.csv`
  und alle `*report.md` sind gitignored — Arbeitsartefakte gehören nach
  Google Drive.
- **Deterministische Module bleiben abhängigkeitsfrei.** `profile`,
  `matching`, `metrics` dürfen kein numpy/torch importieren, damit die
  Minimal-CI (nur pytest) grün bleibt.
- **Neue Methode → erst gegen Baseline messen.** Ein Verfahren wird nur
  eingebaut, wenn es den Keyword-Fit auf den harten Labels schlägt
  (AUC 0.715). Baseline zuerst, sonst ist „Verbesserung" nur eine Behauptung.

## Architektur & Entscheidungen

Siehe `docs/ARCHITECTURE.md` (Aufbau) und `docs/DECISIONS.md` (ADRs).
Kuratiertes Session-Wissen: `docs/CHAT-MEMORY.md`.
