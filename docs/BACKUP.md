# Backup

| Was | Wo | Sicherung |
|---|---|---|
| Bestand (`jobs.db`, SQLite) | `%LOCALAPPDATA%\bewerbungsagent\jobs.db` (`BEWERBUNGSAGENT_DB`) | Snapshot `state.json` nach jedem Schreiben |
| Snapshot `state.json` | `04_Agent/data/` | Google Drive Desktop |
| Konfiguration, Profil | `04_Agent/` | Google Drive Desktop |
| Unterlagen (PDF) | `01_Bewerbungen/` | Google Drive Desktop |
| Code | `~/git/bewerbungsagent` | GitHub |

Die Datenbank liegt bewusst **außerhalb** des Drive-Ordners: Google Drive Desktop kennt
keine Datei-Ausschlüsse und würde die Binärdatei mitten im Schreiben synchronisieren.
`state.json` ist der abgeleitete, sync-sichere Snapshot (ADR-018). Änderungen am Bestand
laufen nur über `db.Store`, nie über `state.json`.

**Wiederherstellen:** Fehlt `jobs.db`, legt der Agent sie beim nächsten Start neu an
(Alembic). Den Bestand aus dem Snapshot übernimmt
`Store(...).save_state(json.load(open("data/state.json")))`.

Sicherungen von Konfiguration und Hermes-Skripten vor größeren Änderungen liegen in
`05_Backups/` (Datum im Dateinamen).
