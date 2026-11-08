#!/usr/bin/env bash
# Wochenlauf des Bewerbungsagenten, gedacht für einen systemd-User-Timer
# (Montag früh). Läuft auch von Hand: scripts/wochenlauf.sh [AGENT_DIR]
exec "$(dirname "$(readlink -f "$0")")/lauf.sh" wochenlauf "$@"
