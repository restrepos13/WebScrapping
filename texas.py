#!/usr/bin/env python3
"""Registros oficiales gratuitos de Texas → prospectos y enriquecimiento.

Fuentes (todas abiertas, sin key):
  · Texas Comptroller — Sales Tax Permit Holders (data.texas.gov jrea-zgmq):
    cada local con permiso de ventas, su NAICS, dirección y fecha de primera venta.
    Los permisos recientes en los NAICS del radar = negocios NUEVOS.
  · Texas Comptroller — Franchise Tax Permit Holders (9cir-efmm): n.º de archivo
    del Secretary of State, fecha de constitución y derecho a operar.
  · TBAE — roster de firmas de arquitectura registradas (Excel).
  · US Census Geocoder (batch) para ubicar direcciones; ZCTA Gazetteer para TBAE.

Texas SOS (SOSDirect) es de pago: no se usa; el mapa enlaza la búsqueda gratuita
del Comptroller por n.º de archivo.

Uso:
  python3 texas.py                 # permisos de los últimos 365 días + TBAE
  python3 texas.py --dias 730      # ventana más larga
  python3 texas.py --sin-tbae
"""
import argparse, csv, datetime as dt, io, json, os, re, time, urllib.parse, urllib.request, zipfile
import xml.etree.ElementTree as ET
from comun import REG_DIR, UA, Fusion, base_registro, cargar_zona, guardar_zona, http_json, metros, norm
from categorias import NAICS_A_CAT
from paises import REGION_DE_CONDADO, REGIONES_TX, condado_por_codigo

SOCRATA = "https://data.texas.gov/resource/{}.json"
DS_SALES = "jrea-zgmq"
DS_FRANCHISE = "9cir-efmm"
CENSUS = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
GAZ = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/{}"
TBAE = "https://bizreg.tbae.texas.gov/Home/BusinessRostersDownload"
GEOCACHE = os.path.join(REG_DIR, "geocache_tx.json")

def soql(ds, params, token=""):
    url = SOCRATA.format(ds) + "?" + urllib.parse.urlencode(params)
    return http_json(url, headers={"X-App-Token": token} if token else {}, timeout=90)

def titulo(s):
    s = re.sub(r"\s+", " ", (s or "").strip())
    return s.title() if s.isupper() else s

# ---------------- geocodificación ----------------
def geocodificar(direcciones):
    """{clave: (calle, ciudad, zip)} → {clave: (lat, lng)} con el batch del Census (cacheado)."""
    cache = json.load(open(GEOCACHE)) if os.path.exists(GEOCACHE) else {}
    pend = {k: v for k, v in direcciones.items() if "|".join(v) not in cache}
    claves = list(pend)
    for i in range(0, len(claves), 2000):
        lote = claves[i:i + 2000]
        buf = io.StringIO()
        w = csv.writer(buf)
        for j, k in enumerate(lote):
            calle, ciudad, zp = pend[k]
            w.writerow([j, calle, ciudad, "TX", zp])
        limite = "----radar" + str(int(time.time()))
        cuerpo = (f"--{limite}\r\nContent-Disposition: form-data; name=\"benchmark\"\r\n\r\nPublic_AR_Current\r\n"
                  f"--{limite}\r\nContent-Disposition: form-data; name=\"addressFile\"; filename=\"a.csv\"\r\n"
                  f"Content-Type: text/csv\r\n\r\n{buf.getvalue()}\r\n--{limite}--\r\n").encode()
        for intento in range(3):
            try:
                req = urllib.request.Request(CENSUS, data=cuerpo, headers={
                    "Content-Type": f"multipart/form-data; boundary={limite}", "User-Agent": UA})
                with urllib.request.urlopen(req, timeout=600) as r:
                    salida = r.read().decode("utf-8", "ignore")
                break
            except Exception as e:
                print(f"    · Census: {e} — reintento")
                time.sleep(10)
        else:
            continue
        for fila in csv.reader(io.StringIO(salida)):
            if len(fila) >= 6 and fila[2] == "Match":
                lng, lat = map(float, fila[5].split(","))
                cache["|".join(pend[lote[int(fila[0])]])] = [round(lat, 6), round(lng, 6)]
            elif fila:
                try:
                    cache["|".join(pend[lote[int(fila[0])]])] = None
                except (ValueError, IndexError):
                    pass
        os.makedirs(REG_DIR, exist_ok=True)
        json.dump(cache, open(GEOCACHE, "w"))
        print(f"    geocodificadas {min(i + 2000, len(claves))}/{len(claves)}", flush=True)
    return {k: cache.get("|".join(v)) for k, v in direcciones.items()}

def _gazetteer(nombre, filtro):
    ruta = os.path.join(REG_DIR, nombre.replace(".zip", ".txt"))
    if not os.path.exists(ruta):
        req = urllib.request.Request(GAZ.format(nombre), headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as r:
            z = zipfile.ZipFile(io.BytesIO(r.read()))
        os.makedirs(REG_DIR, exist_ok=True)
        open(ruta, "w").write(z.read(z.namelist()[0]).decode("utf-8", "ignore"))
    filas = [l.rstrip().split("\t") for l in open(ruta)][1:]
    return [f for f in filas if filtro(f)]

def centroides_zip():
    return {f[0]: (float(f[5]), float(f[6])) for f in _gazetteer("2024_Gaz_zcta_national.zip", lambda f: f[0][:2] in ("75", "76", "77", "78", "79", "88"))}

def condado_mas_cercano(lat, lng, condados=[]):
    if not condados:
        condados.extend((f[3].replace(" County", ""), float(f[8]), float(f[9]))
                        for f in _gazetteer("2024_Gaz_counties_national.zip", lambda f: f[0] == "TX"))
    return min(condados, key=lambda c: metros(lat, lng, c[1], c[2]))[0]

# ---------------- franchise tax ----------------
def franquicias(taxpayers, token=""):
    out = {}
    tps = sorted(set(t for t in taxpayers if t))
    for i in range(0, len(tps), 80):
        lista = ",".join(f"'{t}'" for t in tps[i:i + 80])
        try:
            filas = soql(DS_FRANCHISE, {"$where": f"taxpayer_number in ({lista})", "$limit": 1000}, token)
        except Exception:
            continue
        for f in filas:
            out[f["taxpayer_number"]] = f
        time.sleep(0.2)
    return out

def registro_tx(razon, taxpayer, desde, naics, fr=None, confianza=1.0):
    r = {"tipo": "comptroller", "razon_social": titulo(razon), "taxpayer": taxpayer,
         "estado": "ACTIVA", "desde": (desde or "")[:4], "naics": naics, "confianza": confianza}
    if fr:
        r["sos_file"] = fr.get("secretary_of_state_sos_or_coa_file_number", "")
        if fr.get("sos_charter_date"):
            r["constitucion"] = fr["sos_charter_date"][:10]
            r["desde"] = fr["sos_charter_date"][:4]
        if fr.get("right_to_transact_business_code") not in (None, "A"):
            r["estado"] = "SIN DERECHO A OPERAR"
    return r

# ---------------- búsqueda para enrich_empresas.py ----------------
def buscar(nombre, ciudad, token=""):
    """Candidatos del Comptroller para un negocio de Maps/OSM (outlet por nombre + ciudad)."""
    from comun import palabras
    ps = palabras(nombre)
    if not ps:
        return []
    where = f"upper(outlet_city)='{norm(ciudad)}'" if ciudad else "outlet_state='TX'"
    out = []
    for q in ([" ".join(ps)] + ([max(ps, key=len)] if len(ps) > 1 else [])):
        try:
            filas = soql(DS_SALES, {"$q": q, "$where": where, "$limit": 25}, token)
        except Exception:
            filas = []
        for f in filas:
            out.append({"razon_social": f.get("outlet_name", ""), "taxpayer_name": f.get("taxpayer_name", ""),
                        "taxpayer": f.get("taxpayer_number", ""), "desde": f.get("outlet_first_sales_date", ""),
                        "naics": f.get("outlet_naics_code", ""), "estado_matricula": "ACTIVA"})
        if filas:
            break
    return out

# ---------------- prospectos ----------------
def permisos_recientes(dias, token):
    desde = (dt.date.today() - dt.timedelta(days=dias)).isoformat()
    naics = ",".join(f"'{c}'" for c in NAICS_A_CAT)
    where = (f"outlet_naics_code in ({naics}) AND outlet_permit_issue_date >= '{desde}' "
             f"AND outlet_state='TX'")
    filas, off = [], 0
    while True:
        lote = soql(DS_SALES, {"$where": where, "$limit": 50000, "$offset": off, "$order": "taxpayer_number,outlet_number"}, token)
        filas += lote
        if len(lote) < 50000:
            break
        off += 50000
    return filas

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=365, help="permisos emitidos en los últimos N días")
    ap.add_argument("--sin-tbae", action="store_true")
    args = ap.parse_args()
    from comun import cargar_config
    token = cargar_config().get("socrata_app_token", "")

    print("Comptroller · permisos de venta recientes…", flush=True)
    filas = permisos_recientes(args.dias, token)
    print(f"  {len(filas)} locales en los NAICS del radar (últimos {args.dias} días)")
    dirs = {}
    for f in filas:
        k = f"{f['taxpayer_number']}-{f.get('outlet_number', '1')}"
        dirs[k] = (f.get("outlet_address", ""), f.get("outlet_city", ""), (f.get("outlet_zip_code") or "")[:5])
    coords = geocodificar(dirs)
    fr = franquicias([f["taxpayer_number"] for f in filas], token)

    corte = (dt.date.today() - dt.timedelta(days=args.dias)).isoformat()
    por_zona, sin_geo = {}, 0
    for f in filas:
        k = f"{f['taxpayer_number']}-{f.get('outlet_number', '1')}"
        condado = condado_por_codigo(f.get("outlet_county_code"))
        zona = REGION_DE_CONDADO.get(condado)
        c = coords.get(k)
        if not zona or not c:
            sin_geo += 1
            continue
        cat = NAICS_A_CAT[f["outlet_naics_code"]]
        inicio = (f.get("outlet_first_sales_date") or f.get("outlet_permit_issue_date") or "")[:10]
        es_nuevo = inicio >= corte  # permiso reciente pero vendía hace años = cambio de dueño/renovación
        r = base_registro(
            "txst:" + k, titulo(f.get("outlet_name") or f.get("taxpayer_name")), cat, zona, "TX", c[0], c[1],
            "comptroller", direccion=f"{titulo(f.get('outlet_address'))}, {titulo(f.get('outlet_city'))}, TX {f.get('outlet_zip_code', '')[:5]}",
            subzona=titulo(f.get("outlet_city")) + (f" · {condado} County" if condado else ""),
            nuevo={"fecha": inicio, "origen": "Texas Comptroller"} if es_nuevo else None,
            registro=registro_tx(f.get("taxpayer_name"), f["taxpayer_number"], inicio, f["outlet_naics_code"],
                                 fr.get(f["taxpayer_number"])),
        )
        if not es_nuevo:
            del r["nuevo"]
        else:
            r["gancho"] = (f"New business — first sales {inicio}. Still setting up operations: website, booking "
                           f"and 24/7 chat are open decisions. Pitch: launch package.")
        por_zona.setdefault(zona, []).append(r)
    print(f"  {sum(map(len, por_zona.values()))} ubicados · {sin_geo} sin geocodificar (descartados)")

    if not args.sin_tbae:
        print("TBAE · roster de firmas de arquitectura…", flush=True)
        try:
            for r in tbae():
                por_zona.setdefault(r["zona"], []).append(r)
        except Exception as e:
            print(f"  !! TBAE: {e}")

    for zona, lista in por_zona.items():
        fusion = Fusion(cargar_zona(zona))
        for r in lista:
            fusion.agregar(r)
        guardar_zona(zona, fusion.lista(), "TX")
        print(f"  [{REGIONES_TX[zona][0]}] {fusion.nuevos} nuevos · {fusion.fundidos} fundidos · total {len(fusion.por_id)}")

def tbae():
    req = urllib.request.Request(TBAE, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        z = zipfile.ZipFile(io.BytesIO(r.read()))
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    ss = []
    if "xl/sharedStrings.xml" in z.namelist():
        ss = ["".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t"))
              for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns)]
    filas = []
    for row in ET.fromstring(z.read("xl/worksheets/sheet1.xml")).find("m:sheetData", ns):
        vals = []
        for c in row:
            v = c.find("m:v", ns)
            if c.get("t") == "s":
                vals.append(ss[int(v.text)])
            elif c.get("t") == "inlineStr":
                vals.append("".join(x.text or "" for x in c.iter(f"{{{ns['m']}}}t")))
            else:
                vals.append(v.text if v is not None else "")
        filas.append(vals)
    cab = filas[0]
    zips = centroides_zip()
    out = []
    for f in filas[1:]:
        d = dict(zip(cab, f))
        zp = (d.get("Zip") or "")[:5]
        if d.get("State") != "TX" or d.get("Status") != "Active" or zp not in zips:
            continue
        lat, lng = zips[zp]
        zona = REGION_DE_CONDADO.get(condado_mas_cercano(lat, lng))
        if not zona:
            continue
        r = base_registro(
            "tbae:" + d["Reg ID"], d["Firm Name"].strip().lstrip("*.").strip(), "estudio de arquitectura", zona, "TX",
            lat, lng, "tbae", aprox=True, direccion=f"{d.get('City', '')}, TX {zp}", subzona=d.get("City", ""),
            registro={"tipo": "tbae", "razon_social": d["Firm Name"].strip(), "estado": "ACTIVA",
                      "tbae": d["Reg ID"], "confianza": 1.0})
        out.append(r)
    print(f"  {len(out)} firmas activas en Texas")
    return out

if __name__ == "__main__":
    main()
