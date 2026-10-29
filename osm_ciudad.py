#!/usr/bin/env python3
"""Barrido OSM para ciudades grandes (Quito, Lima) por celdas.

Overpass devuelve 502 cuando se le pide un radio urbano de 20-30 km con todos
los filtros. Acá se parte el área en celdas de ~0.10° (11 km) con radio de 8 km
—se solapan, no quedan huecos— y se fusionan con lo que ya haya en la zona
(Google Places incluido), sin duplicar.

Uso:
  python3 osm_ciudad.py --zona quito
  python3 osm_ciudad.py --zona lima --radio-km 16
"""
import argparse, math, time
from comun import (Fusion, bloqueo_index, cargar_config, cargar_index, cargar_zona,
                   escribir_index, guardar_zona)
from categorias import OSM_FILTROS
from osm import overpass, registro

PASO = 0.10  # grados entre centros de celda (~11 km)


def celdas(centro, radio_km):
    lat, lng = centro
    dlat = radio_km / 111.32
    dlng = dlat / max(math.cos(math.radians(lat)), 0.2)
    n_lat = max(1, math.ceil(2 * dlat / PASO))
    n_lng = max(1, math.ceil(2 * dlng / PASO))
    paso_lat = (2 * dlat) / n_lat
    paso_lng = (2 * dlng) / n_lng
    for i in range(n_lat):
        for j in range(n_lng):
            yield (lat - dlat + paso_lat * (i + 0.5), lng - dlng + paso_lng * (j + 0.5))


def consulta_celda(lat, lng, radio_km):
    r = int(radio_km * 1000)
    cuerpo = "".join(f'nwr(around:{r},{lat:.5f},{lng:.5f}){f}["name"];' for f in OSM_FILTROS)
    return f"[out:json][timeout:300][maxsize:268435456];({cuerpo});out center tags;"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zona", required=True)
    ap.add_argument("--radio-km", type=int, default=14, help="radio total a cubrir desde el centro")
    ap.add_argument("--celda-km", type=int, default=8, help="radio de cada consulta")
    args = ap.parse_args()

    cfg = cargar_config()
    z = (cfg.get("zonas") or {}).get(args.zona)
    if not z:
        raise SystemExit(f"No existe la zona {args.zona} en config.json")
    pais = z.get("pais", "CO")
    centros = list(celdas(z["centro"], args.radio_km))
    print(f"{z['nombre']}: {len(centros)} celdas de {args.celda_km} km", flush=True)

    fusion = Fusion(cargar_zona(args.zona))
    vistos = set()
    for i, (lat, lng) in enumerate(centros, 1):
        t0 = time.time()
        try:
            res = overpass(consulta_celda(lat, lng, args.celda_km))
        except Exception as e:
            print(f"  [{i}/{len(centros)}] {lat:.3f},{lng:.3f} !! {str(e)[:120]}", flush=True)
            continue
        elementos = res.get("elements", [])
        for el in elementos:
            vistos.add(f"{el['type']}{el['id']}")
            r = registro(el, args.zona, pais)
            if r:
                fusion.agregar(r)
        print(f"  [{i}/{len(centros)}] {lat:.3f},{lng:.3f} · {len(elementos)} elementos "
              f"({time.time() - t0:.0f}s)", flush=True)
        time.sleep(2)

    guardar_zona(args.zona, fusion.lista(), pais)
    with bloqueo_index():
        idx = cargar_index()
        idx.setdefault(args.zona, {})["osm"] = time.strftime("%Y-%m-%d")
        escribir_index(idx)
    print(f"Listo: {len(fusion.lista())} negocios en {args.zona} "
          f"({fusion.nuevos} nuevos, {fusion.fundidos} fundidos, {len(vistos)} POIs vistos).", flush=True)


if __name__ == "__main__":
    main()
