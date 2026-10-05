#!/bin/bash
# Barrido nocturno de España (fuentes gratuitas): OSM por provincia → BORME del
# último año → cruce con registros → auditoría de webs. Retoma donde quedó si se
# corta. caffeinate evita que el Mac se duerma. Log en data/registros/nocturno.log
#
#   ./barrido_nocturno.sh            # España completa
#   ./barrido_nocturno.sh TX         # otro país (CO, ES, TX)
cd "$(dirname "$0")"
PAIS="${1:-ES}"
mkdir -p data/registros
LOG="data/registros/nocturno.log"
{
  echo "=== $(date '+%F %T') · barrido nocturno $PAIS"
  python3 osm.py --pais "$PAIS" --saltar-hechas
  if [ "$PAIS" = "ES" ]; then
    python3 borme.py --desde "$(date -v-365d +%F)"
  fi
  python3 enrich_empresas.py --pais "$PAIS"
  python3 audit.py --pais "$PAIS"
  echo "=== $(date '+%F %T') · listo. Revisá y publicá con:  git add data/zonas && git commit -m 'datos $PAIS' && git push"
} 2>&1 | caffeinate -i tee -a "$LOG"
