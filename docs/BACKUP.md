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
