#!/usr/bin/env bash
# Wochenlauf des Bewerbungsagenten: Stellen suchen, Texte nachladen, bewerten,
# Unterlagen erzeugen und das Dashboard aktualisieren.
#
# Gedacht für einen systemd-User-Timer (Montag früh), läuft aber auch von Hand:
#   scripts/wochenlauf.sh [AGENT_DIR]
#
# Besonderheiten:
#  * ``flock`` verhindert, dass zwei Läufe gleichzeitig schreiben (z. B. wenn der
#    Rechner nach einer verpassten Ausführung aufholt und der Timer feuert).
#  * Alle Ausgaben gehen in ``data/wochenlauf.log`` (rotierend auf die letzten
#    2000 Zeilen), damit ein Blick in die Vergangenheit möglich ist.
#  * Das Ergebnis landet als JSON in ``data/wochenlauf-status.json`` — der
#    ``LAUFEND``-Zustand ist sofort sichtbar.
#  * Fehler werden per ``notify-send`` gemeldet, *falls* eine Sitzung läuft.
#    Ein Hintergrunddienst hat oft kein Display; dann bleibt es im Log/Status.
set -euo pipefail

AGENT_DIR="${1:-$HOME/git/bewerbungsagent}"
# WICHTIG: AGENT_DIR darf NICHT auf einem Google Drive / rclone / bisync
# synchronisierten Mount liegen. SQLite-WAL-Dateien (data/jobs.db) werden
# durch gleichzeitigen Sync korrumpiert. Siehe AGENTS.md / docs/BACKUP.md.
LOG="$AGENT_DIR/data/wochenlauf.log"
STATUS="$AGENT_DIR/data/wochenlauf-status.json"
LOCK="$AGENT_DIR/data/wochenlauf.lock"

mkdir -p "$AGENT_DIR/data"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG"; }

# Status schreiben (atomar, damit kein halber JSON-Stand gelesen wird).
write_status() {
  local zustand="$1" meldung="$2" dauer="$3"
  printf '{\n  "zeitpunkt": "%s",\n  "zustand": "%s",\n  "meldung": "%s",\n  "dauer_sekunden": %s\n}\n' \
    "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$zustand" "$meldung" "$dauer" >"$STATUS.tmp"
  mv "$STATUS.tmp" "$STATUS"
}

# Interpreter bestimmen: erst die venv des Agenten, sonst ein passendes python3.
PY=""
for kandidat in "$AGENT_DIR/.venv/bin/python" "$HOME/.venvs/bewerbungsagent/bin/python"; do
  [ -x "$kandidat" ] && PY="$kandidat" && break
done
if [ -z "$PY" ]; then
  echo "FEHLER: Kein Python-Interpreter gefunden (erwartet: ~/.venvs/bewerbungsagent)." >&2
  exit 1
fi

# Schreiben ausschließlich über den Lock.
exec 9>"$LOCK"
if ! flock -n 9; then
  log "Übersprungen: ein Wochenlauf läuft bereits."
  exit 0
fi

START="$(date +%s)"
write_status "LAUFEND" "Wochenlauf gestartet" 0
log "Wochenlauf gestartet (Interpreter: $PY)"

cd "$AGENT_DIR"

# ``--beschreibung alle``: vollständige Anzeigentexte für einen präzisen Fit.
# ``--ohne-review``: die Bewertung erfolgt im Dashboard.
# ``-u`` = ungepuffert. Ohne das sammelt Python die Ausgabe, wenn es nicht am
# Terminal läuft (also genau hier) — das Log sähe dann 10 Minuten lang aus, als
# hinge der Lauf, obwohl Chromium bereits Anzeigen lädt. Die Fortschrittszeilen
# sind der einzige Hinweis, dass gearbeitet wird.
set +e
PYTHONPATH="$AGENT_DIR" PYTHONUNBUFFERED=1 "$PY" -u agent.py ablauf \
  --beschreibung alle --ohne-review >>"$LOG" 2>&1
CODE=$?
set -e

DAUER=$(( $(date +%s) - START ))

if [ "$CODE" -eq 0 ]; then
  log "Wochenlauf fertig in ${DAUER}s."
  write_status "OK" "Wochenlauf erfolgreich" "$DAUER"
else
  log "FEHLER: Wochenlauf mit Code $CODE nach ${DAUER}s abgebrochen."
  write_status "FEHLER" "Abbruch mit Code $CODE (siehe data/wochenlauf.log)" "$DAUER"
  if command -v notify-send >/dev/null 2>&1 \
     && [ -n "${DBUS_SESSION_BUS_ADDRESS:-}${XDG_RUNTIME_DIR:-}" ]; then
    notify-send -u critical "Bewerbungsagent: Wochenlauf fehlgeschlagen" \
      "Exit-Code $CODE. Details: $LOG" 2>/dev/null || true
  fi
fi

# Log klein halten (die letzten 2000 Zeilen genügen für die Diagnose).
if [ -f "$LOG" ]; then
  tail -n 2000 "$LOG" >"$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

exit "$CODE"
