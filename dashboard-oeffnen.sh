#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Dieser Launcher liegt in 00_Dashboard; der Server und seine Daten in 04_Agent.
AGENT_DIR="$(cd "$HERE/../04_Agent" && pwd)"
URL="http://127.0.0.1:8766/00_Dashboard/dashboard.html"
DATA_DIR="$AGENT_DIR/data"
LOG="$DATA_DIR/launcher.log"
SERVER_LOG="$DATA_DIR/server.log"
mkdir -p "$DATA_DIR"
exec >>"$LOG" 2>&1
printf '[%s] Launcher gestartet\n' "$(date --iso-8601=seconds)"
cd "$AGENT_DIR"

# Python-Interpreter des Agents finden.
if [ -x "$AGENT_DIR/.venv/bin/python" ]; then
  PY="$AGENT_DIR/.venv/bin/python"
elif [ -x "$HOME/.venvs/bewerbungsagent/bin/python" ]; then
  PY="$HOME/.venvs/bewerbungsagent/bin/python"
else
  PY="$(command -v python3 || true)"
fi

if [ -z "$PY" ]; then
  echo "FEHLER: Python 3 wurde nicht gefunden." >&2
  command -v notify-send >/dev/null 2>&1 && notify-send -u critical "Bewerbungs-Dashboard" "Python 3 wurde nicht gefunden."
  exit 1
fi

HEALTH_URL="http://127.0.0.1:8766/healthz"
if ! curl -fsS --connect-timeout 1 --max-time 2 "$HEALTH_URL" >/dev/null 2>&1; then
  nohup "$PY" "$AGENT_DIR/server.py" >>"$SERVER_LOG" 2>&1 </dev/null &
  SERVER_PID=$!
  disown "$SERVER_PID" 2>/dev/null || true
  printf '[%s] Serverstart angefordert (PID %s)\n' "$(date --iso-8601=seconds)" "$SERVER_PID"
fi

READY=0
for _ in $(seq 1 50); do
  if curl -fsS --connect-timeout 1 --max-time 2 "$HEALTH_URL" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 0.2
done

if [ "$READY" -ne 1 ]; then
  echo "FEHLER: Dashboard-Server wurde nicht erreichbar. Siehe $SERVER_LOG" >&2
  command -v notify-send >/dev/null 2>&1 && notify-send -u critical "Bewerbungs-Dashboard" "Der lokale Server startet nicht. Details: $SERVER_LOG"
  exit 1
fi

if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL" >>"$LOG" 2>&1 </dev/null &
elif command -v gio >/dev/null 2>&1; then
  gio open "$URL" >>"$LOG" 2>&1 </dev/null &
elif command -v kde-open >/dev/null 2>&1; then
  kde-open "$URL" >>"$LOG" 2>&1 </dev/null &
else
  echo "FEHLER: Kein Browser-Öffner (xdg-open, gio oder kde-open) gefunden." >&2
  command -v notify-send >/dev/null 2>&1 && notify-send -u critical "Bewerbungs-Dashboard" "Kein Browser-Öffner gefunden."
  exit 1
fi

printf '[%s] Browser für %s geöffnet\n' "$(date --iso-8601=seconds)" "$URL"
