# Backup & Gedächtnis

Ziel: **Nichts geht verloren** — weder Code, noch Bewerbungsdaten, noch der
Chat-Verlauf (= das „Gedächtnis" des Projekts).

## Die 3-2-1-Regel

- **3** Kopien: Arbeitsstand + lokales Backup + Cloud
- **2** Medien: lokale Platte + Google Drive
- **1** außer Haus: Cloud oder GitHub

## Was liegt wo?

| Artefakt | Ort | Gesichert durch |
|---|---|---|
| Code | `~/git/bewerbungsagent` (Git) | Git-Historie + `rclone` → GDrive |
| Bewerbungsdaten (`state.json`) | `04_Agent/data/` | `backup_state.sh` + GDrive-Sync |
| Erzeugte PDFs | `01_Bewerbungen/` | GDrive-Sync |
| **Chat-Verlauf** | `~/.copilot/session-state/…` | **`backup_chat.sh`** (nicht in GDrive!) |

> ⚠️ Der Chat-Verlauf liegt **außerhalb** des Google-Drive-Ordners und wird
> vom Sync **nicht** erfasst. Ohne `backup_chat.sh` existiert er nur lokal.

## Backups ausführen

```bash
# Chat-Verlauf (Transkript + Checkpoints + Markdown-Export)
scripts/backup_chat.sh                 # → ~/backups/bewerbungsagent-chat/<zeitstempel>/

# Laufzeitdaten des Agenten (mit Integritätsprüfung)
scripts/backup_state.sh                # → ~/backups/bewerbungsagent-state/<zeitstempel>/
```

Rotation: `CHAT_BACKUP_KEEP` (Standard 10), `STATE_BACKUP_KEEP` (Standard 14).

## Automatisierung (systemd-Timer, optional)

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/bewerbungsagent-backup.service <<'EOF'
[Unit]
Description=Bewerbungsagent Backup
[Service]
Type=oneshot
ExecStart=%h/git/bewerbungsagent/scripts/backup_chat.sh
ExecStart=%h/git/bewerbungsagent/scripts/backup_state.sh
EOF

cat > ~/.config/systemd/user/bewerbungsagent-backup.timer <<'EOF'
[Unit]
Description=Tägliches Bewerbungsagent-Backup
[Timer]
OnCalendar=daily
Persistent=true
[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now bewerbungsagent-backup.timer
systemctl --user list-timers bewerbungsagent-backup.timer
```

## Rclone-Bisync: generierte Dateien ausgenommen

Der `rclone-bisync.timer` (alle 15 min) synchronisiert den Google-Drive-Ordner
**in beide Richtungen**. Schreibt der Agent eine Datei, während Bisync läuft,
sieht Bisync eine Änderung auf *beiden* Seiten und legt eine Konfliktkopie an
(`datei.json.conflict1`, `.conflict2`, …) — im Oktober 2026 hat das mehrfach
`state.json` und `import_jobs.json` umbenannt.

Deshalb sind die vom Agenten **automatisch erzeugten** Dateien ausgenommen
(`~/.config/rclone/bisync-exclude.txt`):

```
/DOKUMENTE/Job/Bewerbung/2026/04_Agent/dashboard.html
/DOKUMENTE/Job/Bewerbung/2026/04_Agent/dashboard.html.pre-*
/DOKUMENTE/Job/Bewerbung/2026/04_Agent/data/jobs.json
/DOKUMENTE/Job/Bewerbung/2026/04_Agent/data/matches.json
/DOKUMENTE/Job/Bewerbung/2026/04_Agent/data/state.json
/DOKUMENTE/Job/Bewerbung/2026/04_Agent/data/geocode_cache.json
/DOKUMENTE/Job/Bewerbung/2026/04_Agent/data/commute_cache.json
/DOKUMENTE/Job/Bewerbung/2026/04_Agent/data/jobs.db*
# Lokale Sicherungskopien vor einem Eingriff
/DOKUMENTE/Job/Bewerbung/2026/04_Agent/data/*.pre-*
/DOKUMENTE/Job/Bewerbung/2026/04_Agent/data/*.backup-*
/DOKUMENTE/Job/Bewerbung/2026/04_Agent/data/*.bak
# Python-Bytecode
/**/__pycache__
# Konflikt-/Temporärkopien
/**/*.conflict*
/**/*.tmp
```

> ⚠️ Sicherungskopien **müssen** einem dieser Muster folgen. Ein Name wie
> `state.json.pre-recheck-<zeit>` passt nur auf `*.pre-*` — das frühere
> `state.pre-*` griff nicht, und die Dateien landeten unbemerkt in der Cloud.

**Wichtig:** `__pycache__` wird nur aus dem Sync genommen, nicht gelöscht —
Python erzeugt die Dateien bei Bedarf selbst neu.

**Kein Datenverlust:** Diese Dateien sind aus `data/jobs.db` reproduzierbar und
werden zusätzlich von `scripts/backup_state.sh` gesichert. Quelle der Wahrheit
(`data/jobs.db`) und generierte Daten bleiben damit bewusst **lokal** — sie
liegen im HDD-Backup (`rclone-backup.timer`), nicht in der Cloud.

> ⚠️ **Nach jeder Änderung der Filterliste** muss einmalig
> `rclone bisync … --resync --resync-mode newer` laufen. Ohne Resync
> interpretiert Bisync die neu ausgenommenen Dateien als „gelöscht“ und würde
> sie propagieren. `--resync-mode newer` (statt Default `path1`) verhindert,
> dass ältere Cloud-Versionen neuere lokale Dateien überschreiben.

## Windows: SQLite-DB aus dem Google-Drive-Sync herausnehmen

Die `bisync-exclude.txt` oben greift nur beim Linux-`rclone`-Sync. **Google
Drive Desktop unter Windows kennt keine Datei-Ausschlüsse** und synchronisiert
`data/jobs.db`, `data/jobs.db-wal` und `data/jobs.db-shm` einzeln. Weil SQLite
im WAL-Modus diese drei Dateien separat schreibt, lädt Drive Desktop einen
inkonsistenten Stand hoch und die Datenbank wird korrupt
(„database disk image is malformed“ → leeres Dashboard).

Deshalb liegt die Quelle der Wahrheit unter Windows in einer **nicht
synchronisierten lokalen Ablage**. Der Pfad wird über die Umgebungsvariable
`BEWERBUNGSAGENT_DB` gesteuert; ohne sie bleibt der Standard (`data/jobs.db`)
unverändert (Linux und Tests).

```powershell
# Einmalig (Server vorher beenden):
$src = "$env:USERPROFILE\GoogleDrive\DOKUMENTE\Job\Bewerbung\2026\04_Agent\data\jobs.db"
$dst = "$env:LOCALAPPDATA\bewerbungsagent\jobs.db"
New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
Move-Item $src $dst
# WAL/SHM-Reste im Sync-Ordner entfernen
Remove-Item "$src-wal","$src-shm" -ErrorAction SilentlyContinue
# Umgebungsvariable dauerhaft setzen (gilt für neue Prozesse)
setx BEWERBUNGSAGENT_DB "$dst"
```

`state.json` bleibt weiterhin der synchronisierte Snapshot in `data/` — das
Backup-Verhalten (`backup_state.sh`, rclone) ändert sich nicht.

## Restore-Test (das Wichtigste!)

Ein Backup ohne Restore-Probe ist kein Backup. Regelmäßig prüfen:

```bash
# 1) Neuestes State-Backup validieren
latest=$(ls -1dt ~/backups/bewerbungsagent-state/*/ | head -1)
python3 -c "import json,sys; d=json.load(open('$latest/data/state.json')); \
print('OK', len(d['applications']), 'Einträge')"

# 2) Chat-Protokoll lesbar?
latestc=$(ls -1dt ~/backups/bewerbungsagent-chat/*/ | head -1)
wc -l "$latestc/chat-log.md"

# 3) Git-Repo intakt?
cd ~/git/bewerbungsagent && git fsck --no-progress && git log --oneline | head -5
```

## Chat als „Memory" ins Repo

Der Roh-Verlauf enthält PII und gehört **nicht** ins Repo. Stattdessen:
- kuratierte Erkenntnisse → `docs/CHAT-MEMORY.md`
- Entscheidungen → `docs/DECISIONS.md`
- roher Export → nur ins Backup-Verzeichnis (`chat-log.md`)
