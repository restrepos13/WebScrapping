#!/usr/bin/env python3
"""Barrido de negocios con Google Places API (New) — searchText por zona × categoría.

Uso:
  python3 scan.py                 # barre todas las zonas de config.json
  python3 scan.py --zona medellin # solo una zona
  python3 scan.py --cat "clínica estética"  # solo una categoría

Requiere config.json con "google_api_key" (o variable de entorno GOOGLE_PLACES_KEY).
Escribe/actualiza data/negocios.json (merge por place_id: conserva señales,
gancho y datos de auditoría previos). Después correr audit.py.
"""
import json, os, sys, time, argparse, urllib.request, urllib.error

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(BASE, "config.json")
DATA_DIR = os.path.join(BASE, "data")
DATA = os.path.join(DATA_DIR, "negocios.json")

FIELD_MASK = ",".join([
    "places.id", "places.displayName", "places.formattedAddress",
    "places.location", "places.rating", "places.userRatingCount",
    "places.websiteUri", "places.nationalPhoneNumber",
    "places.internationalPhoneNumber", "places.types",
    "places.businessStatus", "nextPageToken",
])

def search_text(key, query, page_token=None):
    body = {"textQuery": query, "languageCode": "es", "pageSize": 20}
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

def wa_digits(phone):
    if not phone:
        return ""
    d = "".join(c for c in phone if c.isdigit())
    if d and not d.startswith("57") and len(d) == 10:
        d = "57" + d
    return d

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zona", help="clave de zona de config.json (ej. medellin)")
    ap.add_argument("--cat", help="una sola categoría")
    ap.add_argument("--paginas", type=int, default=3, help="páginas por consulta (20 c/u, máx 3)")
    args = ap.parse_args()

    cfg = json.load(open(CONFIG))
    key = cfg.get("google_api_key") or os.environ.get("GOOGLE_PLACES_KEY", "")
    if not key:
        sys.exit("Falta la API key: ponela en config.json (google_api_key) o en GOOGLE_PLACES_KEY.")

    zonas = {args.zona: cfg["zonas"][args.zona]} if args.zona else cfg["zonas"]
    categorias = [args.cat] if args.cat else cfg["categorias"]

    os.makedirs(DATA_DIR, exist_ok=True)
    negocios = {}
    if os.path.exists(DATA):
        for n in json.load(open(DATA)):
            negocios[n["id"]] = n

    nuevos, consultas = 0, 0
    for zkey, zona in zonas.items():
        for sub in zona["subzonas"]:
            for cat in categorias:
                query = f"{cat} en {sub}"
                token = None
                for page in range(max(1, min(args.paginas, 3))):
                    try:
                        res = search_text(key, query, token)
                    except urllib.error.HTTPError as e:
                        print(f"  !! {query}: HTTP {e.code} {e.read().decode()[:200]}")
                        break
                    except Exception as e:
                        print(f"  !! {query}: {e}")
                        break
                    consultas += 1
                    for p in res.get("places", []):
                        pid = p["id"]
                        if p.get("businessStatus") not in (None, "OPERATIONAL"):
                            continue
                        prev = negocios.get(pid, {})
                        tel = p.get("nationalPhoneNumber") or p.get("internationalPhoneNumber") or ""
                        if pid not in negocios:
                            nuevos += 1
                        negocios[pid] = {
                            "id": pid,
                            "nombre": p.get("displayName", {}).get("text", ""),
                            "categoria": cat,
                            "zona": zkey,
                            "subzona": sub,
                            "lat": p["location"]["latitude"],
                            "lng": p["location"]["longitude"],
                            "aprox": False,
                            "direccion": p.get("formattedAddress", ""),
                            "tel": tel,
                            "wa": wa_digits(tel),
                            "web": p.get("websiteUri", ""),
                            "rating": p.get("rating"),
                            "reviews": p.get("userRatingCount"),
                            "tipos": p.get("types", []),
                            # campos que llena audit.py — se conservan si ya existían:
                            "senales": prev.get("senales", {"sin_web": not p.get("websiteUri")}),
                            "gancho": prev.get("gancho", ""),
                            "emails": prev.get("emails", []),
                            "redes": prev.get("redes", {}),
                            "auditado": prev.get("auditado", False),
                            "fuente": "places",
                        }
                    token = res.get("nextPageToken")
                    if not token:
                        break
                    time.sleep(2)  # el token tarda en activarse
                time.sleep(0.2)
        print(f"[{zona['nombre']}] listo — acumulado: {len(negocios)} negocios")

    json.dump(list(negocios.values()), open(DATA, "w"), ensure_ascii=False, indent=1)
    print(f"\n{consultas} consultas · {nuevos} negocios nuevos · total {len(negocios)}")
    print(f"Guardado en {DATA}. Siguiente paso: python3 audit.py")

if __name__ == "__main__":
    main()
