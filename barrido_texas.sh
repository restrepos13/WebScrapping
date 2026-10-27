#!/usr/bin/env bash
# Texas completo con Google Places (fuente principal) + auditoría de webs.
#
# Para qué la fecha: el cupo gratuito mensual de Google se renueva el día 1.
# Correrlo el 1 de noviembre hace que las primeras ~1.000 consultas no se cobren.
#
# Uso:
#   ./barrido_texas.sh            # 2 páginas por búsqueda (58 subzonas × 21 rubros)
#   ./barrido_texas.sh 3          # 3 páginas (más leads, ~US$128 brutos)
set -euo pipefail
cd "$(dirname "$0")"

PAGINAS="${1:-2}"
MAX=$((58 * 21 * PAGINAS + 20))   # tope duro: nunca se pasa del presupuesto
HOY="$(date +%F)"

mkdir -p data/registros
echo "Texas · $PAGINAS página(s) · tope $MAX consultas (≈ US\$$(( MAX * 35 / 1000 )) brutos)"
python3 -u scan.py --pais TX --paginas "$PAGINAS" --max-consultas "$MAX" --si \
  | tee -a "data/registros/scan-tx-$HOY.log"

echo "Auditando webs de Texas (tarda; se puede cortar y retomar)…"
python3 -u audit.py --pais TX | tee -a "data/registros/audit-tx-$HOY.log"

git add data/zonas
git commit -m "Datos Texas $HOY: Google Places + auditoría"
git push origin main || echo "Aviso: no se pudo hacer push (los datos quedaron commiteados en local)."
echo "Listo: Texas completo, auditado y publicado."
