#!/usr/bin/env bash
# Sichert die Laufzeitdaten des Bewerbungsagenten (state.json, jobs.json,
# Caches) rotationsbasiert und prüft die Integrität der Kopie.
#
# Wichtig: state.json ist die einzige Quelle der Wahrheit für das Dashboard.
# Ein Backup ohne *Restore-Test* ist kein Backup — deshalb wird die Kopie
# anschließend validiert (valides JSON + erwartete Struktur).
#
# Nutzung:
#   scripts/backup_state.sh [AGENT_DIR] [ZIELVERZEICHNIS]
set -euo pipefail

AGENT_DIR="${1:-$HOME/GoogleDrive/DOKUMENTE/Job/Bewerbung/2026/04_Agent}"
DEST="${2:-$HOME/backups/bewerbungsagent-state}"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$DEST/$STAMP"

mkdir -p "$OUT/data"

for f in state.json jobs.json matches.json commute_cache.json geocode_cache.json; do
  [ -f "$AGENT_DIR/data/$f" ] && cp "$AGENT_DIR/data/$f" "$OUT/data/"
done

# Integritätsprüfung (Restore-Test): JSON muss parsebar sein und Anwendungen enthalten.
PY="$(command -v python3)"
if [ -n "$PY" ]; then
  "$PY" - "$OUT/data/state.json" <<'PYEOF'
import json, sys
p = sys.argv[1]
with open(p, encoding="utf-8") as fh:
    data = json.load(fh)
assert isinstance(data.get("applications"), list), "applications fehlt/kein Array"
print(f"OK: state.json valide ({len(data['applications'])} Einträge)")
PYEOF
fi

# Rotation (Standard: 14 Backups behalten).
KEEP="${STATE_BACKUP_KEEP:-14}"
ls -1dt "$DEST"/*/ 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -rf

echo "State-Backup erstellt: $OUT"
