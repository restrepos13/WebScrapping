#!/usr/bin/env python3
"""Barrido de negocios con Google Places API (New) — searchText por zona × categoría.
Google es la fuente principal: si el negocio ya existía por OSM/registros, el
registro de Google pasa a ser el principal y los otros solo completan datos.

Uso:
  python3 scan.py --zona medellin            # una zona (Colombia: subzonas de config.json)
  python3 scan.py --pais TX                  # todas las regiones de Texas
  python3 scan.py --zona es-madrid --cat "clínica estética"
  python3 scan.py --pais ES --max-consultas 2000 --si   # sin pedir confirmación

Costo: cada página de resultados es una consulta Text Search (~US$0.035 con
web/teléfono/rating; ~1.000 gratis al mes). Antes de arrancar se muestra el
máximo de consultas y el costo estimado, y se pide confirmar.

Requiere "google_api_key" en config.json (o GOOGLE_PLACES_KEY).
Escribe en data/zonas/<zona>.json. Después correr audit.py.
"""
import json, os, sys, time, argparse, urllib.request, urllib.error
from comun import Fusion, base_registro, cargar_config, cargar_zona, guardar_zona
from categorias import consultas_google
from paises import subzonas

COSTO_CONSULTA = 0.035
FIELD_MASK = ",".join([
    "places.id", "places.displayName", "places.formattedAddress",
    "places.location", "places.rating", "places.userRatingCount",
    "places.websiteUri", "places.nationalPhoneNumber",
    "places.internationalPhoneNumber", "places.types",
    "places.businessStatus", "nextPageToken",
])
IDIOMA = {"CO": "es", "ES": "es", "TX": "en"}
REGION = {"CO": "co", "ES": "es", "TX": "us"}

def search_text(key, query, pais, page_token=None):
    body = {"textQuery": query, "languageCode": IDIOMA[pais], "regionCode": REGION[pais], "pageSize": 20}
    if page_token:
        body["pageToken"] = page_token
    req = urllib.request.Request(
        "https://places.googleapis.com/v1/places:searchText",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": key,
            "X-Goog-FieldMask": FIELD_MASK,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zona", help="clave de zona de config.json (ej. medellin, es-malaga, tx-capital)")
    ap.add_argument("--pais", choices=["CO", "ES", "TX"])
    ap.add_argument("--cat", help="una sola categoría (nombre canónico, ej. 'clínica estética')")
    ap.add_argument("--paginas", type=int, default=3, help="páginas por consulta (20 c/u, máx 3)")
    ap.add_argument("--max-consultas", type=int, default=900, help="tope duro de consultas (default 900 ≈ cupo gratis)")
    ap.add_argument("--si", action="store_true", help="no pedir confirmación")
    args = ap.parse_args()

    cfg = cargar_config()
    key = cfg.get("google_api_key") or os.environ.get("GOOGLE_PLACES_KEY", "")
    if not key:
        sys.exit("Falta la API key: ponela en config.json (google_api_key) o en GOOGLE_PLACES_KEY.")
    if not (args.zona or args.pais):
        sys.exit("Indicá --zona o --pais")

    zonas = {k: z for k, z in cfg["zonas"].items()
             if (not args.zona or k == args.zona) and (not args.pais or z.get("pais", "CO") == args.pais)}
    plan = []
    for zkey, zona in zonas.items():
        pais = zona.get("pais", "CO")
        cats = [c for c in consultas_google(pais, cfg.get("categorias", [])) if not args.cat or c[0] == args.cat]
        for sub in subzonas(zkey, zona):
            for cat, texto in cats:
                plan.append((zkey, pais, sub, cat, texto))
    paginas = max(1, min(args.paginas, 3))
    peor = min(len(plan) * paginas, args.max_consultas)
    print(f"{len(plan)} búsquedas en {len(zonas)} zona(s) · hasta {peor} consultas ≈ US${peor * COSTO_CONSULTA:.0f} "
          f"(tope --max-consultas {args.max_consultas})")
    if not args.si and input("¿Seguir? [s/N] ").strip().lower() not in ("s", "si", "sí", "y"):
        sys.exit("Cancelado.")

    fusiones, consultas = {}, 0
    for zkey, pais, sub, cat, texto in plan:
        if consultas >= args.max_consultas:
            print(f"Tope de {args.max_consultas} consultas alcanzado — se corta acá.")
            break
        if zkey not in fusiones:
            fusiones[zkey] = Fusion(cargar_zona(zkey))
        fusion = fusiones[zkey]
        query = f"{texto} en {sub}" if pais != "TX" else f"{texto} in {sub}"
        token = None
        for _ in range(paginas):
            if consultas >= args.max_consultas:
                break
            try:
                res = search_text(key, query, pais, token)
            except urllib.error.HTTPError as e:
                print(f"  !! {query}: HTTP {e.code} {e.read().decode()[:200]}")
                break
            except Exception as e:
                print(f"  !! {query}: {e}")
                break
            consultas += 1
            for p in res.get("places", []):
                if p.get("businessStatus") not in (None, "OPERATIONAL"):
                    continue
                tel = p.get("internationalPhoneNumber") or p.get("nationalPhoneNumber") or ""
                fusion.agregar(base_registro(
                    p["id"], p.get("displayName", {}).get("text", ""), cat, zkey, pais,
                    p["location"]["latitude"], p["location"]["longitude"], "places",
                    direccion=p.get("formattedAddress", ""), tel=tel, web=p.get("websiteUri", ""),
                    rating=p.get("rating"), reviews=p.get("userRatingCount"), tipos=p.get("types", []),
                    subzona=sub))
            token = res.get("nextPageToken")
            if not token:
                break
            time.sleep(2)  # el token tarda en activarse
        time.sleep(0.2)
        if consultas % 50 == 0:
            guardar_zona(zkey, fusion.lista(), pais)

    for zkey, fusion in fusiones.items():
        guardar_zona(zkey, fusion.lista(), zonas[zkey].get("pais", "CO"))
        print(f"[{zonas[zkey]['nombre']}] {fusion.nuevos} nuevos · {fusion.fundidos} fundidos con OSM/registros · "
              f"{fusion.actualizados} actualizados · total {len(fusion.por_id)}")
    print(f"\n{consultas} consultas (≈ US${consultas * COSTO_CONSULTA:.2f}). Siguiente paso: python3 audit.py")

if __name__ == "__main__":
    main()
