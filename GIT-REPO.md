# Git-Repository & Dokumentation

Dieses Projekt ist zusätzlich als **öffentliches GitHub-Repository** versioniert
(für Bewerbungen als Code-Nachweis teilbar).

## Repository

**https://github.com/jacobdietzmann-ux/bewerbungsagent** (öffentlich)

Lokaler Klon: `~/git/bewerbungsagent`

Der Link liegt zusätzlich als [`output/GIT-LINK.txt`](output/GIT-LINK.txt) bereit
und ist in `output/agent-map.html` / `.pdf` als Fußzeile verlinkt.

> Hinweis: In der Git-Historie sind **keine personenbezogenen Daten** — Adresse
> und Kontakt-E-Mail stehen ausschließlich in der lokalen, nicht versionierten
> `config.json`.

## Aufteilung (wer lebt wo?)

| Inhalt | Ort | Grund |
|---|---|---|
| **Code / Skripte** | Git-Repo (`~/git/`, GitHub) | Versionierung, Tests, CI |
| **Tests & Doku** | Git-Repo | Reproduzierbar, reviewbar |
| **Arbeitsergebnisse** (PDFs, state.json, Dashboard) | Google Drive (dieser Ordner) | Große/laufende Daten, Cloud-Backup |
| **Profil (PII)** | NUR Google Drive | Nicht versionieren (Datenschutz) |
| **Chat-Verlauf** | `~/backups/bewerbungsagent-chat/` | Sicherung per Timer |

> Wichtig: Das Git-Repo liegt **bewusst nicht** im rclone-synchronisierten
> Google-Drive-Ordner — `bisync` würde `.git` korrumpieren.

## Dokumentation (im Repo)

- `docs/ARCHITECTURE.md` — Aufbau & Datenfluss
- `docs/DECISIONS.md` — Entscheidungen (ADRs)
- `docs/CHAT-MEMORY.md` — kuratiertes Projektwissen
- `docs/BACKUP.md` — Backup, Restore-Tests, Automatisierung

Direktlinks:
- https://github.com/jacobdietzmann-ux/bewerbungsagent/blob/main/docs/ARCHITECTURE.md
- https://github.com/jacobdietzmann-ux/bewerbungsagent/blob/main/docs/DECISIONS.md
- https://github.com/jacobdietzmann-ux/bewerbungsagent/blob/main/docs/BACKUP.md
- https://github.com/jacobdietzmann-ux/bewerbungsagent/blob/main/docs/CHAT-MEMORY.md

## Sicherung (dauerhaft)

- systemd-Timer `bewerbungsagent-backup.timer` — täglich 07:30
- Chat-Verlauf → `~/backups/bewerbungsagent-chat/`
- Agent-State → `~/backups/bewerbungsagent-state/`
