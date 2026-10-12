#!/usr/bin/env bash
# Sichert den Copilot-Chat-Verlauf (Transkript + Checkpoints) in ein Backup-
# Verzeichnis und erzeugt daraus zusätzlich ein lesbares Markdown-Protokoll.
#
# Hintergrund: Der Chat liegt in ~/.copilot/session-state/<session>/ und wird
# vom Google-Drive-Sync NICHT erfasst (anderer Pfad!). Ohne dieses Skript ist
# das „Gedächtnis" des Projekts nur lokal vorhanden.
#
# Nutzung:
#   scripts/backup_chat.sh [ZIELVERZEICHNIS]
# Standardziel: ~/backups/bewerbungsagent-chat
set -euo pipefail

SESSION_DIR="${COPILOT_SESSION_DIR:-$HOME/.copilot/session-state/101b4f88-d7a2-4939-9c3e-6065c4a01c6b}"
DEST="${1:-$HOME/backups/bewerbungsagent-chat}"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$DEST/$STAMP"

if [ ! -d "$SESSION_DIR" ]; then
  echo "FEHLER: Session-Verzeichnis nicht gefunden: $SESSION_DIR" >&2
  exit 1
fi

mkdir -p "$OUT"

# 1) Rohtranskript + Checkpoints (vollständiges „Gedächtnis").
[ -f "$SESSION_DIR/events.jsonl" ] && cp "$SESSION_DIR/events.jsonl" "$OUT/"
[ -d "$SESSION_DIR/checkpoints" ] && cp -r "$SESSION_DIR/checkpoints" "$OUT/"
[ -f "$SESSION_DIR/session.db" ] && cp "$SESSION_DIR/session.db" "$OUT/"
[ -d "$SESSION_DIR/files" ] && cp -r "$SESSION_DIR/files" "$OUT/" 2>/dev/null || true

# 2) Lesbares Markdown-Protokoll aus dem JSONL ableiten.
PY="$(command -v python3)"
if [ -f "$OUT/events.jsonl" ] && [ -n "$PY" ]; then
  "$PY" - "$OUT/events.jsonl" "$OUT/chat-log.md" <<'PYEOF'
import json, sys
from datetime import datetime
src, dst = sys.argv[1], sys.argv[2]
lines = []
with open(src, encoding="utf-8") as fh:
    for raw in fh:
        try:
            ev = json.loads(raw)
        except Exception:
            continue
        t = ev.get("type", "")
        data = ev.get("data") or {}
        content = (data.get("content") or "").strip()
        if not content:
            continue
        if t == "user.message":
            lines.append(f"\n## 👤 User\n\n{content}\n")
        elif t == "assistant.message":
            lines.append(f"\n### 🤖 Assistant\n\n{content}\n")
open(dst, "w", encoding="utf-8").write(
    "# Chat-Protokoll (automatisch exportiert)\n"
    f"_Erzeugt: {datetime.now().isoformat(timespec='seconds')}_\n"
    + "".join(lines)
)
print(f"Markdown-Protokoll: {dst} ({len(lines)} Nachrichten)")
PYEOF
fi

# 3) Alte Backups jenseits der Aufbewahrungsgrenze entfernen (Standard: 10).
KEEP="${CHAT_BACKUP_KEEP:-10}"
ls -1dt "$DEST"/*/ 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -rf

echo "Chat-Backup erstellt: $OUT"
du -sh "$OUT" 2>/dev/null || true
