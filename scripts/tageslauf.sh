#!/usr/bin/env bash
# Tageslauf des Bewerbungsagenten, gedacht für einen systemd-User-Timer
# (täglich 12:00). Läuft auch von Hand: scripts/tageslauf.sh [AGENT_DIR]
exec "$(dirname "$(readlink -f "$0")")/lauf.sh" tageslauf "$@"
