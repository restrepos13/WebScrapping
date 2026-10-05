#!/usr/bin/env python3
"""Barrido de OpenStreetMap (Overpass API) — gratis, sin key, los tres países.

Uso:
  python3 osm.py --pais ES                 # las 52 provincias
  python3 osm.py --pais TX                 # las 12 regiones de Texas
  python3 osm.py --pais CO                 # zonas de Colombia (radio alrededor del centro)
  python3 osm.py --zona es-malaga          # una sola zona
  python3 osm.py --pais ES --saltar-hechas # retoma un barrido cortado

Cada zona se guarda apenas termina (data/zonas/<zona>.json), fusionando con lo que
ya había: si el negocio ya vino de Google Places se completa, no se duplica.
Las cadenas (brand:wikidata) se descartan. Datos © OpenStreetMap (ODbL).
"""
import argparse, json, math, sys, time, urllib.parse, urllib.error
from comun import (Fusion, base_registro, bloqueo_index, cargar_config, cargar_index, cargar_zona,
                   escribir_index, guardar_zona, http_json)
from categorias import OSM_FILTROS, clasificar_osm
from paises import PROVINCIAS_ES, REGIONES_TX

MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
RADIO_POR_ZOOM = {11: 22000, 12: 15000, 13: 9000}

def area_ql(zona, z):
    pais = z.get("pais", "CO")
    if pais == "ES":
        return f'area["ISO3166-2"="{PROVINCIAS_ES[zona][1]}"]["boundary"="administrative"]->.a;', "(area.a)"
    if pais == "TX":
        condados = "|".join(REGIONES_TX[zona][3])
        return (f'rel["boundary"="administrative"]["admin_level"="6"]["nist:state_fips"="48"]'
                f'["name"~"^({condados}) County$"];map_to_area->.a;'), "(area.a)"
    lat, lng = z["centro"]
    r = RADIO_POR_ZOOM.get(z.get("zoom", 12), 15000)
    dlat = r / 111320
    dlng = dlat / max(math.cos(math.radians(lat)), 0.2)
    return "", f"({lat - dlat:.4f},{lng - dlng:.4f},{lat + dlat:.4f},{lng + dlng:.4f})"  # bbox: mucho más rápido que around

def consulta(zona, z):
    pre, filtro = area_ql(zona, z)
    cuerpo = "".join(f"nwr{filtro}{f}[name];" for f in OSM_FILTROS)
    return f"[out:json][timeout:900][maxsize:1073741824];{pre}({cuerpo});out center tags;"

def overpass(q):
    ultimo = None
    for vuelta in range(3):
        for url in MIRRORS:
            try:
                return http_json(url, data=urllib.parse.urlencode({"data": q}).encode(),
                                 timeout=960, intentos=1)
            except Exception as e:
                ultimo = e
                print(f"    · {url.split('/')[2]}: {str(e)[:80]} — probando otro mirror", flush=True)
                time.sleep(5)
        time.sleep(30 * (vuelta + 1))
    raise RuntimeError(f"Overpass no respondió: {ultimo}")

def direccion(t):
    calle = " ".join(x for x in (t.get("addr:street"), t.get("addr:housenumber")) if x)
    lugar = " ".join(x for x in (t.get("addr:postcode"), t.get("addr:city")) if x)
    return ", ".join(x for x in (calle, lugar) if x)

def registro(el, zona, pais):
    t = el.get("tags", {})
    cat = clasificar_osm(t, pais)
    if not cat:
        return None
    lat = el.get("lat") or (el.get("center") or {}).get("lat")
    lng = el.get("lon") or (el.get("center") or {}).get("lon")
    if lat is None:
        return None
    web = t.get("website") or t.get("contact:website") or t.get("url") or ""
    if web and not web.startswith("http"):
        web = "https://" + web
    tel = t.get("phone") or t.get("contact:phone") or t.get("contact:mobile") or t.get("mobile") or ""
    tel = tel.split(";")[0].strip()
    emails = [e.strip().lower() for e in (t.get("email") or t.get("contact:email") or "").split(";") if "@" in e]
    redes = {}
    for red in ("instagram", "facebook", "tiktok"):
        v = t.get(f"contact:{red}") or t.get(red)
        if v:
            redes[red] = v.rstrip("/").split("/")[-1].lstrip("@")
    tipo = next((f"{k}={t[k]}" for k in ("amenity", "shop", "leisure", "office", "tourism", "healthcare") if k in t), "")
    return base_registro(
        f"osm:{el['type'][0]}{el['id']}", t["name"], cat, zona, pais, round(lat, 6), round(lng, 6), "osm",
        web=web, tel=tel, emails=emails[:5], redes=redes, tipos=[tipo] if tipo else [],
        direccion=direccion(t), subzona=t.get("addr:suburb") or t.get("addr:city") or "",
    )

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pais", choices=["CO", "ES", "TX"])
    ap.add_argument("--zona")
    ap.add_argument("--saltar-hechas", action="store_true", help="omite zonas que ya tienen datos de OSM")
    args = ap.parse_args()
    if not (args.pais or args.zona):
        sys.exit("Indicá --pais o --zona")

    cfg = cargar_config()
    zonas = {k: z for k, z in cfg["zonas"].items()
             if (not args.zona or k == args.zona) and (not args.pais or z.get("pais", "CO") == args.pais)}
    if not zonas:
        sys.exit("Sin zonas: corré primero  python3 paises.py --sync-config")
    idx = cargar_index()

    total_nuevos = 0
    for i, (zona, z) in enumerate(zonas.items(), 1):
        if args.saltar_hechas and idx.get(zona, {}).get("osm"):
            continue
        pais = z.get("pais", "CO")
        t0 = time.time()
        print(f"[{i}/{len(zonas)}] {z['nombre']} …", flush=True)
        try:
            res = overpass(consulta(zona, z))
        except Exception as e:
            print(f"  !! {e}")
            continue
        fusion = Fusion(cargar_zona(zona))
        descartados = 0
        for el in res.get("elements", []):
            r = registro(el, zona, pais)
            if r:
                fusion.agregar(r)
            else:
                descartados += 1
        guardar_zona(zona, fusion.lista(), pais)
        with bloqueo_index():
            idx = cargar_index()
            idx[zona]["osm"] = time.strftime("%Y-%m-%d")
            escribir_index(idx)
        total_nuevos += fusion.nuevos
        print(f"  {len(res.get('elements', []))} elementos → {fusion.nuevos} nuevos · {fusion.fundidos} fundidos "
              f"con otra fuente · {fusion.actualizados} actualizados · {descartados} fuera de foco/cadenas "
              f"({time.time() - t0:.0f}s)", flush=True)
        time.sleep(3)  # cortesía con los servidores públicos
    print(f"\nListo: {total_nuevos} negocios nuevos. Siguiente: python3 audit.py")

if __name__ == "__main__":
    main()
