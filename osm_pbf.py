#!/usr/bin/env python3
"""Barrido OSM local desde el extracto PBF de Geofabrik (sin Overpass).

Overpass rechaza las consultas de un área metropolitana entera (502). El PBF
del país se descarga una vez y acá se filtran solo los POI dentro del bbox de
la ciudad, con las mismas reglas de clasificación que osm.py.

Uso:
  python3 osm_pbf.py --zona quito --pbf /tmp/ecuador.osm.pbf
  python3 osm_pbf.py --zona lima --pbf /tmp/peru.osm.pbf
"""
import argparse, json, time
import osmium

from comun import (Fusion, bloqueo_index, cargar_config, cargar_index, cargar_zona,
                   escribir_index, guardar_zona)
from osm import registro

CAMPOS_OSM = ("amenity", "shop", "leisure", "office", "tourism", "healthcare", "craft")


def en_caja(lat, lng, caja):
    return caja[0] <= lat <= caja[2] and caja[1] <= lng <= caja[3]


class Extracto(osmium.SimpleHandler):
    def __init__(self, zona, pais, caja, fusion):
        super().__init__()
        self.zona, self.pais, self.caja, self.fusion = zona, pais, caja, fusion
        self.vistos = 0
        self.dentro = 0
        self.ultimo = time.time()

    def _probar(self, tipo, id_, lat, lng, tags):
        self.vistos += 1
        if time.time() - self.ultimo > 20:
            print(f"    … {self.vistos:,} objetos leídos · {self.dentro:,} POI en el área", flush=True)
            self.ultimo = time.time()
        if not en_caja(lat, lng, self.caja):
            return
        t = {k: v for k, v in tags}
        if not t.get("name") or not any(t.get(c) for c in CAMPOS_OSM):
            return
        self.dentro += 1
        r = registro({"type": tipo, "id": id_, "lat": lat, "lon": lng, "tags": t}, self.zona, self.pais)
        if r:
            self.fusion.agregar(r)

    def node(self, n):
        if n.tags and n.location.valid():
            self._probar("node", n.id, n.location.lat, n.location.lon, n.tags)

    def way(self, w):
        if not w.tags:
            return
        lats, lngs = [], []
        for nd in w.nodes:
            if nd.location.valid():
                lats.append(nd.location.lat)
                lngs.append(nd.location.lon)
        if not lats:
            return
        self._probar("way", w.id, sum(lats) / len(lats), sum(lngs) / len(lngs), w.tags)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zona", required=True)
    ap.add_argument("--pbf", required=True)
    ap.add_argument("--caja", help="latmin,lngmin,latmax,lngmax (por defecto, radio de la zona)")
    args = ap.parse_args()

    cfg = cargar_config()
    z = (cfg.get("zonas") or {}).get(args.zona)
    if not z:
        raise SystemExit(f"No existe la zona {args.zona}")
    if args.caja:
        caja = tuple(float(x) for x in args.caja.split(","))
    else:
        lat, lng = z["centro"]
        d = {"quito": 0.30, "lima": 0.36}.get(args.zona, 0.20)
        caja = (lat - d, lng - d * 1.05, lat + d, lng + d * 1.05)

    fusion = Fusion(cargar_zona(args.zona))
    h = Extracto(args.zona, z.get("pais", "CO"), caja, fusion)
    t0 = time.time()
    print(f"{z['nombre']}: filtrando {args.pbf} en caja {caja}", flush=True)
    h.apply_file(args.pbf, locations=True)
    guardar_zona(args.zona, fusion.lista(), z.get("pais", "CO"))
    with bloqueo_index():
        idx = cargar_index()
        idx.setdefault(args.zona, {})["osm"] = time.strftime("%Y-%m-%d")
        escribir_index(idx)
    print(f"Listo: {len(fusion.lista())} negocios en {args.zona} "
          f"({fusion.nuevos} nuevos, {fusion.fundidos} fundidos, {h.dentro:,} POI en área, "
          f"{h.vistos:,} objetos leídos, {time.time() - t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
