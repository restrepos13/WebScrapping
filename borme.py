#!/usr/bin/env python3
"""BORME (Boletín Oficial del Registro Mercantil) — API de datos abiertos del BOE.

Recorre los sumarios diarios, baja la Sección A (actos inscritos) de cada
provincia en XML y:
  1. arma un índice local de sociedades por provincia (data/registros/borme_empresas.json):
     constitución (fecha, CNAE, objeto, domicilio, capital), último acto, si está
     disuelta/extinguida. enrich_empresas.py lo usa para cruzar negocios de España.
  2. genera prospectos de empresas RECIÉN CONSTITUIDAS en los rubros del radar
     (por CNAE u objeto social), ubicadas en el centro de su municipio (aprox).

Uso:
  python3 borme.py                      # últimos 90 días (retoma lo ya bajado)
  python3 borme.py --desde 2025-10-01   # rango largo (ideal de noche)
  python3 borme.py --sin-prospectos     # solo índice, no agrega negocios al mapa

Gratis, sin key. Fuente: BOE (www.boe.es/datosabiertos).
"""
import argparse, datetime as dt, json, os, re, time, xml.etree.ElementTree as ET
from comun import (REG_DIR, Fusion, base_registro, cargar_zona, guardar_zona, http_json, norm, UA)
from categorias import clasificar_objeto
from paises import PROVINCIAS_ES, zona_por_provincia_borme
import urllib.request

API = "https://www.boe.es/datosabiertos/api/borme/sumario/{}"
INDICE = os.path.join(REG_DIR, "borme_empresas.json")
DIAS = os.path.join(REG_DIR, "borme_dias.json")
FORMAS = r"(SOCIEDAD LIMITADA|SOCIEDAD ANONIMA|S\.?L\.?U?\.?|S\.?A\.?U?\.?|S\.?L\.?L\.?|S\.?L\.?P\.?|S\.?COOP\.?)"

def bajar(url, timeout=60):
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception:
            time.sleep(3 * (i + 1))
    return None

def sumario(fecha):
    try:
        d = http_json(API.format(fecha.strftime("%Y%m%d")), timeout=30)
    except Exception:
        return None  # festivo / sin BORME ese día
    out = []
    for diario in d.get("data", {}).get("sumario", {}).get("diario", []):
        for sec in diario.get("seccion", []):
            if sec.get("codigo") != "A":
                continue
            items = sec.get("item", [])
            for it in items if isinstance(items, list) else [items]:
                if it.get("url_xml"):
                    out.append((it["titulo"], it["url_xml"]))
    return out

def parsear(xml_bytes):
    """XML de una provincia → [(nombre_sociedad, texto_del_acto)]."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    actos, actual = [], None
    for p in root.iter("p"):
        clase, txt = p.get("class", ""), "".join(p.itertext()).strip()
        if clase == "articulo":
            m = re.match(r"^\d+\s*-\s*(.+?)\.?$", txt)
            actual = m.group(1).strip() if m else txt
        elif clase == "parrafo" and actual:
            actos.append((actual, txt))
    return actos

def campo(txt, nombre, hasta=r"\.\s+[A-ZÁÉÍÓÚ][a-záéíóú]+[ .:]"):
    m = re.search(nombre + r":\s*(.+?)(?:" + hasta + r"|$)", txt)
    return m.group(1).strip() if m else ""

def constitucion(txt, fecha):
    objeto = campo(txt, "Objeto social", r"\.\s+Domicilio:|$")
    cnae = re.search(r"Actividad principal:[^()]*\(CNAE\s*(\d{2})\.?(\d{1,2})", objeto) or re.search(r"CNAE\s*:?\s*(\d{2})\.?(\d{1,2})", objeto)
    dom = campo(txt, "Domicilio", r"\.\s+Capital:|$")
    muni = re.findall(r"\(([^()]+)\)", dom)
    cap = re.search(r"Capital:\s*([\d.]+,\d{2})\s*Euros", txt)
    return {
        "fecha": fecha, "cnae": f"{cnae.group(1)}.{cnae.group(2)}" if cnae else "", "objeto": objeto[:400],
        "domicilio": dom, "municipio": muni[-1].strip() if muni else "",
        "capital": cap.group(1) if cap else "",
        "inicio": campo(txt, "Comienzo de operaciones")[:10],
    }

# ---------------- municipios (GeoNames) para ubicar las constituciones ----------------
GEONAMES = "https://download.geonames.org/export/dump/ES.zip"
_lugares = {}
def lugares(zona):
    """{nombre normalizado: [lat, lng]} de los municipios de la provincia (GeoNames, CC BY 4.0)."""
    if not _lugares:
        ruta = os.path.join(REG_DIR, "geonames_ES.txt")
        if not os.path.exists(ruta):
            import io, zipfile
            z = zipfile.ZipFile(io.BytesIO(bajar(GEONAMES, timeout=180)))
            os.makedirs(REG_DIR, exist_ok=True)
            open(ruta, "wb").write(z.read("ES.txt"))
        iso_a_zona = {v[1].split("-")[1]: k for k, v in PROVINCIAS_ES.items()}
        pob = {}
        for linea in open(ruta, encoding="utf-8"):
            f = linea.rstrip("\n").split("\t")
            if len(f) < 15 or f[6] != "P":
                continue
            zk = iso_a_zona.get(f[11])
            if not zk:
                continue
            p = int(f[14] or 0)
            tabla = _lugares.setdefault(zk, {})
            for nombre in {f[1], f[2], *f[3].split(",")[:12]}:
                for parte in re.split(r"\s*/\s*", nombre):
                    k = norm(parte)
                    if k and p >= pob.get((zk, k), -1):
                        pob[(zk, k)] = p
                        tabla[k] = [round(float(f[4]), 5), round(float(f[5]), 5)]
    return _lugares.get(zona, {})

def ubicar(zona, municipio):
    t = lugares(zona)
    k = norm(municipio)
    k2 = norm(re.sub(r"^(EL|LA|LOS|LAS|L|ELS|ES|SA|O|A)\s+", "", municipio, flags=re.I))
    for c in (k, k2, norm(re.sub(r"\s*\(.*", "", municipio))):
        if c in t:
            return t[c], True
    return PROVINCIAS_ES[zona][3], False

# ---------------- main ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", help="AAAA-MM-DD (default: hace 90 días)")
    ap.add_argument("--hasta", help="AAAA-MM-DD (default: hoy)")
    ap.add_argument("--sin-prospectos", action="store_true")
    args = ap.parse_args()

    hoy = dt.date.today()
    desde = dt.date.fromisoformat(args.desde) if args.desde else hoy - dt.timedelta(days=90)
    hasta = dt.date.fromisoformat(args.hasta) if args.hasta else hoy
    os.makedirs(REG_DIR, exist_ok=True)
    indice = json.load(open(INDICE)) if os.path.exists(INDICE) else {}
    hechos = set(json.load(open(DIAS))) if os.path.exists(DIAS) else set()

    d, dias_nuevos = desde, 0
    while d <= hasta:
        f = d.isoformat()
        if d.weekday() >= 5 or f in hechos:
            d += dt.timedelta(days=1)
            continue
        items = sumario(d)
        if items is None:
            hechos.add(f)
            d += dt.timedelta(days=1)
            continue
        n_const = 0
        for titulo, url in items:
            zona = zona_por_provincia_borme(titulo)
            if not zona:
                continue  # índice alfabético u otros
            xml = bajar(url)
            if not xml:
                continue
            for nombre, txt in parsear(xml):
                k = f"{zona}|{norm(nombre)}"
                e = indice.setdefault(k, {"nombre": nombre, "zona": zona})
                e["ultimo"] = f
                hoja = re.search(r"H\s+([A-Z]{1,2}\s*\d+)", txt)
                if hoja:
                    e["hoja"] = hoja.group(1).replace(" ", "")
                if txt.startswith("Constitución"):
                    e["constitucion"] = constitucion(txt, f)
                    n_const += 1
                if re.search(r"\bExtinción\b", txt):
                    e["extinguida"] = f
                elif re.search(r"\bDisolución\b", txt):
                    e["disuelta"] = f
                elif "Cambio de domicilio social" in txt:
                    dom = re.search(r"Cambio de domicilio social\.\s*(.+?)(?:\.\s+[A-Z][a-z]+|$)", txt)
                    if dom and "constitucion" in e:
                        e["constitucion"]["domicilio"] = dom.group(1)
            time.sleep(0.15)
        hechos.add(f)
        dias_nuevos += 1
        print(f"  {f}: {len(items)} provincias · {n_const} constituciones · índice {len(indice)}", flush=True)
        if dias_nuevos % 10 == 0:  # checkpoint
            json.dump(indice, open(INDICE, "w"), ensure_ascii=False)
            json.dump(sorted(hechos), open(DIAS, "w"))
        d += dt.timedelta(days=1)

    json.dump(indice, open(INDICE, "w"), ensure_ascii=False)
    json.dump(sorted(hechos), open(DIAS, "w"))
    print(f"\nÍndice BORME: {len(indice)} sociedades ({dias_nuevos} días nuevos procesados)")

    if args.sin_prospectos:
        return
    # prospectos: constituciones de la ventana pedida en rubros del radar (sale del índice → repetible)
    prospectos = {}
    for k, e in indice.items():
        c = e.get("constitucion")
        if not c or not (desde.isoformat() <= c["fecha"] <= hasta.isoformat()):
            continue
        cat = clasificar_objeto(c["cnae"], c["objeto"])
        if cat:
            prospectos.setdefault(e["zona"], []).append((k, e, cat))
    total = 0
    for zona, lista in prospectos.items():
        fusion = Fusion(cargar_zona(zona))
        for k, e, cat in lista:
            if e.get("extinguida") or e.get("disuelta"):
                continue
            c = e["constitucion"]
            (lat, lng), exacto = ubicar(zona, c["municipio"])
            nombre = re.sub(r"\s+" + FORMAS + r"$", "", e["nombre"], flags=re.I).strip() or e["nombre"]
            r = base_registro(
                "borme:" + norm(k).replace(" ", "-").lower()[:80], nombre.title(), cat, zona, "ES",
                lat, lng, "borme", aprox=True, direccion=c["domicilio"].title(),
                subzona=c["municipio"].title() if exacto else PROVINCIAS_ES[zona][0],
                nuevo={"fecha": c["fecha"], "origen": "BORME"},
                registro={"tipo": "borme", "razon_social": e["nombre"], "estado": "ACTIVA",
                          "desde": c["fecha"][:4], "constitucion": c["fecha"], "cnae": c["cnae"],
                          "capital": c["capital"], "objeto": c["objeto"][:200], "provincia": PROVINCIAS_ES[zona][0],
                          "hoja": e.get("hoja", ""), "confianza": 1.0},
            )
            r["gancho"] = (f"Sociedad recién constituida ({c['fecha']}) — está montando su operación: "
                           f"nadie le vendió todavía web, WhatsApp ni agendamiento. Pitch: paquete de arranque.")
            fusion.agregar(r)
        guardar_zona(zona, fusion.lista(), "ES")
        total += fusion.nuevos
        print(f"  [{PROVINCIAS_ES[zona][0]}] {fusion.nuevos} sociedades nuevas en rubros del radar")
    print(f"Prospectos BORME agregados: {total}")

if __name__ == "__main__":
    main()
