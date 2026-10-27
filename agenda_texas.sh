#!/usr/bin/env bash
# Dispara el barrido de Texas una sola vez (1 de noviembre, 08:00) vía launchd.
# Deja una marca para no repetirlo cada año. Cancelar:
#   launchctl unload ~/Library/LaunchAgents/com.radar.texas.plist
set -uo pipefail
cd "$(dirname "$0")"
MARK="data/registros/.texas-agendado-hecho"
[ -f "$MARK" ] && exit 0
mkdir -p data/registros
echo "== $(date '+%F %H:%M') arranca el barrido agendado de Texas" >> data/registros/texas-agendado.log
./barrido_texas.sh >> data/registros/texas-agendado.log 2>&1
echo "== $(date '+%F %H:%M') terminó con código $?" >> data/registros/texas-agendado.log
touch "$MARK"
