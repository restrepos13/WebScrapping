#!/usr/bin/env python3
"""Detecta ruido de las búsquedas de Google (centros comerciales, grandes superficies,
universidades, bancos) que no son prospectos aunque salgan con mucho score.

Reglas conservadoras: se marca solo por NOMBRE (o tipo inequívoco), nunca por el tipo
genérico que pone Google ("hospital", "wholesaler"), que también tienen negocios buenos.
Nada se borra: con --aplicar se agrega n["ruido"] = motivo y el mapa/listado lo ocultan.

Uso:
  python3 limpieza.py                 # solo lista candidatos → data/registros/limpieza-candidatos.csv
  python3 limpieza.py --aplicar       # marca los candidatos
  python3 limpieza.py --deshacer      # quita todas las marcas
  python3 limpieza.py --pais CO       # filtrar país (default: todos)
"""
import argparse, csv, os, re
from comun import REG_DIR, cargar_zona, guardar_zona, norm, zonas_con_datos

# el negocio ES el centro comercial: lo menciona en el nombre Y Google lo tipifica como mall
# (los locales adentro — "Bella Piel - C.C. Mayorca" — tienen su propio tipo y sí son prospectos)
MALL = re.compile(r"\b(CENTRO COMERCIAL|MALL|PARQUE COMERCIAL|PLAZA COMERCIAL)\b")
GENERICOS = {"point_of_interest", "establishment"}
# el negocio ES la gran superficie (empieza con la cadena) o es una unidad corporativa suya
CADENAS = re.compile(r"^(HOMECENTER|SODIMAC|EXITO|JUMBO|CARULLA|OLIMPICA|ALKOSTO|KTRONIX|FALABELLA|MAKRO|"
                     r"PRICESMART|SURTIMAX|SUPER INTER|WALMART|COSTCO|HOME DEPOT|LEROY MERLIN|CARREFOUR)\b"
                     r"|\bVIAJES EXITO\b|\bFALABELLA\b")
UNIVERSIDAD = re.compile(r"\b(UNIVERSIDAD|UNIVERSITARIA|UNIVERSITARIO|POLITECNICO|TECNOLOGICO|UNIMINUTO|"
                         r"INSTITUCION UNIVERSITARIA|SENA)\b")
BANCO = re.compile(r"\b(BANCO|BANCOLOMBIA|DAVIVIENDA|BBVA|COOPERATIVA|COOMEVA|CONFIAR|COTRAFA|JFK)\b")
# rubros donde un centro comercial / gran superficie nunca es el prospecto
CATS_EDU = {"academia de idiomas", "escuela de conducción", "agencia de modelos"}

def motivo(n):
    nombre = norm(n.get("nombre", ""))
    tipos = set(n.get("tipos") or [])
    cat = n.get("categoria", "")
    if MALL.search(nombre) and ("shopping_mall" in tipos or
                                 (nombre.startswith("CENTRO COMERCIAL") and tipos and tipos <= GENERICOS)):
        return "centro comercial"
    if n.get("pais", "CO") == "CO" and CADENAS.search(nombre):
        return "gran superficie / cadena"
    if UNIVERSIDAD.search(nombre) and cat in CATS_EDU:
        return "universidad / institución"
    if cat == "agencia de seguros" and ("bank" in tipos or BANCO.search(nombre)):
        return "banco / cooperativa"
    if "hypermarket" in tipos:
        return "hipermercado"
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--deshacer", action="store_true")
    ap.add_argument("--pais", choices=["CO", "ES", "TX"])
    args = ap.parse_args()

    filas, marcados = [], 0
    for zona in zonas_con_datos(args.pais):
        negocios = cargar_zona(zona)
        cambio = False
        for n in negocios:
            if args.deshacer:
                if n.pop("ruido", None):
                    cambio = True
                continue
            m = motivo(n)
            if not m:
                continue
            filas.append([m, n["categoria"], n["nombre"], zona, n.get("reviews") or "", n.get("direccion", ""), n["id"]])
            if args.aplicar and n.get("ruido") != m:
                n["ruido"] = m
                cambio = True
                marcados += 1
        if cambio:
            guardar_zona(zona, negocios)

    if args.deshacer:
        print("Marcas de ruido quitadas.")
        return
    os.makedirs(REG_DIR, exist_ok=True)
    ruta = os.path.join(REG_DIR, "limpieza-candidatos.csv")
    filas.sort(key=lambda f: (f[0], f[1], f[2]))
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Motivo", "Rubro", "Nombre", "Zona", "Reseñas", "Dirección", "Id"])
        w.writerows(filas)
    from collections import Counter
    print(f"{len(filas)} candidatos → {ruta}")
    for m, c in Counter(f[0] for f in filas).most_common():
        print(f"  {m}: {c}")
    if args.aplicar:
        print(f"Marcados {marcados} (ocultos en mapa y listado). Deshacer: python3 limpieza.py --deshacer")

if __name__ == "__main__":
    main()
