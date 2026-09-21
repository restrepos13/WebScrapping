#!/bin/bash
# Barrido dirigido: webcam + rubro estético en las ciudades con más industria
CATS=("estudio webcam" "agencia de modelos" "clínica estética" "centro de estética" "dermatólogo" "cirujano plástico" "clínica odontológica" "spa")
for Z in bogota cali pereira cucuta bucaramanga; do
  for C in "${CATS[@]}"; do
    echo "=== $Z · $C ==="
    python3 -u scan.py --zona "$Z" --cat "$C"
  done
done
echo "BARRIDO DIRIGIDO COMPLETO"
