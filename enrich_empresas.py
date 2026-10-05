#!/usr/bin/env python3
"""Enriquecimiento con registros empresariales oficiales y gratuitos, por país.

COLOMBIA — cruza cada negocio contra:
  1. RUES — Establecimientos de comercio (nb3d-v3n7): nombre comercial → NIT,
     estado de matrícula, CIIU, antigüedad. Es la misma fuente de la que se
     alimentan directorios comerciales tipo eInforma.
  2. RUES — Personas jurídicas (c82u-588k): razón social directa.
  3. Supersociedades — 10.000 empresas más grandes (6cat-2gcs): ingresos,
     macrosector (corte 2025) para las que aparezcan.

ESPAÑA — índice local del BORME (correr antes borme.py) + OpenMercantil
  (openmercantil.es, API abierta: CIF, CNAE, provincia). OpenMercantil es
  opcional: si no responde, se apaga sola y sigue con el BORME.

TEXAS — Texas Comptroller: permisos de venta por nombre de local + ciudad
  (taxpayer, NAICS, fecha de primera venta) y franchise tax (n.º de archivo del
  Secretary of State, fecha de constitución, derecho a operar).

Uso:
  python3 enrich_empresas.py               # solo los no enriquecidos, todos los países
  python3 enrich_empresas.py --pais ES     # un país
  python3 enrich_empresas.py --zona cali   # una zona
  python3 enrich_empresas.py --force       # re-procesa todo
  python3 enrich_empresas.py --max 100     # límite por corrida

Sin API key (datos abiertos). Si config.json trae "socrata_app_token",
se usa para subir el rate limit.
"""
import json, os, re, sys, time, argparse, unicodedata, difflib, urllib.request, urllib.parse

from comun import REG_DIR, cargar_config, cargar_zona, guardar_zona, zonas_con_datos, http_json

DS_ESTABLECIMIENTOS = "nb3d-v3n7"
DS_JURIDICAS = "c82u-588k"
DS_TOP10K = "6cat-2gcs"

CAMARAS_POR_ZONA = {
    "medellin": ["MEDELLIN PARA ANTIOQUIA", "ABURRA SUR"],
    "bucaramanga": ["BUCARAMANGA"],
    "bogota": ["BOGOTA"],
    "cali": ["CALI"],
    "pereira": ["PEREIRA", "DOSQUEBRADAS"],
    "cucuta": ["CUCUTA"],
}
STOP = {"DE", "LA", "EL", "LOS", "LAS", "Y", "DEL", "EN", "SAS", "S", "A", "LTDA", "CIA", "DR", "DRA"}
# palabras que NO pueden sostener un match por sí solas (demasiado comunes en el registro)
GENERICAS = {"STUDIO", "STUDIOS", "ESTUDIO", "ESTUDIOS", "CLINICA", "SPA", "CENTRO",
             "MEDICAL", "MEDICO", "MEDICA", "CENTER", "DERMATOLOGIA", "ODONTOLOGIA",
             "ODONTOLOGICA", "AGENCY", "AGENCIA", "GROUP", "GRUPO", "HOTEL", "HOSTAL",
             "BAR", "RESTAURANTE", "SALON", "MODELS", "WEBCAM"}

def norm(s):
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").upper()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", s)).strip()

def palabras(s):
    return [w for w in norm(s).split() if w not in STOP and len(w) >= 2]

def _token_match(a, b):
    return a == b or (len(a) >= 4 and len(b) >= 4 and (a.startswith(b) or b.startswith(a)))

def soql(dataset, params, token=""):
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"https://www.datos.gov.co/resource/{dataset}.json?{qs}",
        headers={"X-App-Token": token} if token else {})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())

def candidatos(nombre, camaras, token):
    """Búsqueda full-text ($q, indexada y rápida) filtrada por cámara."""
    ps = palabras(nombre)
    if not ps:
        return []
    cam = "camara_comercio in (" + ",".join(f"'{c}'" for c in camaras) + ")"
    intentos = [" ".join(ps)]
    if len(ps) > 2:
        intentos.append(" ".join(sorted(ps, key=len, reverse=True)[:2]))
    if len(ps) >= 2:
        intentos.append(max(ps, key=len))
    vistos, out = set(), []
    for ds in (DS_ESTABLECIMIENTOS, DS_JURIDICAS):
        for q in intentos:
            try:
                filas = soql(ds, {"$q": q, "$where": cam, "$limit": 25}, token)
            except Exception:
                filas = []
            for f in filas:
                key = (f.get("razon_social"), f.get("numero_identificacion"))
                if key in vistos:
                    continue
                vistos.add(key)
                f["_ds"] = "establecimiento" if ds == DS_ESTABLECIMIENTOS else "juridica"
                out.append(f)
            if filas:
                break  # el intento más específico que dio resultados basta
        time.sleep(0.1)
    return out

def mejor(nombre, cands):
    """Matching por tokens distintivos: las palabras genéricas no sostienen un match."""
    objetivo = norm(nombre)
    toks_n = set(palabras(nombre))
    dist_n = toks_n - GENERICAS
    scored = []
    for c in cands:
        razon = c.get("razon_social", "")
        toks_r = set(palabras(razon))
        dist_r = toks_r - GENERICAS
        if dist_n:
            shared = {t for t in dist_n if any(_token_match(t, r) for r in toks_r)}
            if not shared:
                continue  # sin ningún token distintivo en común → descartado
            share_n = len(shared) / len(dist_n)
            share_r = len({t for t in dist_r if any(_token_match(t, x) for x in toks_n)}) / max(len(dist_r), 1)
        else:  # nombre 100% genérico: exigir frase casi idéntica
            share_n = share_r = 1.0 if difflib.SequenceMatcher(None, objetivo, norm(razon)).ratio() >= 0.85 else 0.0
            if not share_n:
                continue
        ratio = difflib.SequenceMatcher(None, objetivo, norm(razon)).ratio()
        conf = 0.55 * share_n + 0.15 * share_r + 0.30 * ratio
        if c.get("estado_matricula") == "ACTIVA":
            conf += 0.05
        if c.get("_ds") == "establecimiento":
            conf += 0.02  # el nombre comercial de Maps suele ser el establecimiento
        scored.append((conf, c))
    scored.sort(key=lambda x: -x[0])
    if not scored or scored[0][0] < 0.5:
        return (0, None)
    top = scored[0]
    if top[1].get("estado_matricula") != "ACTIVA":
        activa = next((s for s in scored if s[1].get("estado_matricula") == "ACTIVA" and s[0] >= 0.5), None)
        if activa and top[0] - activa[0] <= 0.15:
            return activa  # ante casi-empate, la matrícula viva manda
    return top

def top10k(nit, token):
    try:
        filas = soql(DS_TOP10K, {"$where": f"starts_with(nit,'{nit}')", "$limit": 1}, token)
        if filas:
            f = filas[0]
            return {"ingresos": f.get("ingresos_operacionales"),
                    "macrosector": f.get("macrosector"),
                    "corte": (f.get("a_o_de_corte") or "").split(".")[0]}
    except Exception:
        pass
    return None

# ---------------- España ----------------
class IndiceBorme:
    """Búsqueda por tokens sobre data/registros/borme_empresas.json, por provincia."""
    def __init__(self):
        ruta = os.path.join(REG_DIR, "borme_empresas.json")
        self.por_zona = {}
        if not os.path.exists(ruta):
            print("  (sin índice BORME: corré antes  python3 borme.py)")
            return
        for e in json.load(open(ruta)).values():
            z = self.por_zona.setdefault(e["zona"], {"filas": [], "tok": {}})
            i = len(z["filas"])
            z["filas"].append(e)
            for t in set(palabras(e["nombre"])) - GENERICAS:
                z["tok"].setdefault(t, []).append(i)

    def candidatos(self, nombre, zona):
        z = self.por_zona.get(zona)
        if not z:
            return []
        idx = set()
        for t in set(palabras(nombre)) - GENERICAS:
            idx.update(z["tok"].get(t, [])[:200])
        out = []
        for i in list(idx)[:300]:
            e = z["filas"][i]
            c = e.get("constitucion") or {}
            out.append({"razon_social": e["nombre"], "numero_identificacion": "",
                        "estado_matricula": "EXTINGUIDA" if e.get("extinguida") else "DISUELTA" if e.get("disuelta") else "ACTIVA",
                        "fecha_matricula": c.get("fecha", ""), "cnae": c.get("cnae", ""), "hoja": e.get("hoja", ""),
                        "_ds": "borme"})
        return out

class OpenMercantil:
    URL = "https://openmercantil.es/api/v1/search?"
    def __init__(self):
        self.fallos, self.activa = 0, True

    def candidatos(self, nombre, provincia):
        if not self.activa:
            return []
        q = " ".join(palabras(nombre))[:120]
        if len(q) < 2:
            return []
        try:
            d = http_json(self.URL + urllib.parse.urlencode({"q": q, "limit": 20}), timeout=15, intentos=1)
            self.fallos = 0
        except Exception:
            self.fallos += 1
            if self.fallos >= 3:
                self.activa = False
                print("  (OpenMercantil no responde: sigo solo con el BORME)")
            return []
        out = []
        for it in d.get("items", []):
            if it.get("province") and norm(it["province"]) not in norm(provincia) and norm(provincia) not in norm(it["province"]):
                continue
            out.append({"razon_social": it.get("name", ""), "numero_identificacion": it.get("cif", ""),
                        "estado_matricula": "ACTIVA", "fecha_matricula": it.get("first_seen") or "",
                        "cnae": it.get("cnae_code") or "", "slug": it.get("slug", ""), "_ds": "openmercantil"})
        time.sleep(0.5)
        return out

def registro_es(c, conf, provincia):
    return {"tipo": c["_ds"], "razon_social": c["razon_social"], "cif": c.get("numero_identificacion", ""),
            "estado": c.get("estado_matricula", ""), "desde": (c.get("fecha_matricula") or "")[:4],
            "cnae": c.get("cnae", ""), "provincia": provincia, "slug": c.get("slug", ""),
            "hoja": c.get("hoja", ""), "confianza": round(min(conf, 1.0), 2)}

# ---------------- Texas ----------------
def ciudad_tx(n):
    m = re.search(r"([^,]+),\s*TX\b", n.get("direccion", ""))
    if m:
        return m.group(1).strip()
    return (n.get("subzona") or "").split("·")[0].split(",")[0].strip()

# ---------------- main ----------------
def procesar(n, zona, token, fuentes):
    """Un negocio → (registro | None). Sin estado compartido mutable: corre en hilos."""
    from paises import PROVINCIAS_ES
    import texas
    pais = n.get("pais", "CO")
    if pais == "CO":
        conf, c = mejor(n["nombre"], candidatos(n["nombre"], CAMARAS_POR_ZONA[zona], token))
        if not c:
            return None
        reg = {
            "tipo": "rues",
            "razon_social": c.get("razon_social", ""),
            "nit": c.get("numero_identificacion", ""),
            "camara": c.get("camara_comercio", ""),
            "estado": c.get("estado_matricula", ""),
            "desde": (c.get("fecha_matricula") or "")[:4],
            "ciiu": c.get("cod_ciiu_act_econ_pri", ""),
            "confianza": round(min(conf, 1.0), 2),
        }
        fin = top10k(reg["nit"], token) if reg["nit"] else None
        if fin:
            reg.update(fin)
        return reg
    if pais == "ES":
        borme, om = fuentes["borme"], fuentes["om"]
        provincia = PROVINCIAS_ES[zona][0]
        conf, c = mejor(n["nombre"], borme.candidatos(n["nombre"], zona))
        if not c or conf < 0.8:  # OpenMercantil suma el CIF cuando responde
            conf2, c2 = mejor(n["nombre"], om.candidatos(n["nombre"], provincia))
            if c2 and conf2 > conf:
                conf, c = conf2, c2
        return registro_es(c, conf, provincia) if c else None
    conf, c = mejor(n["nombre"], texas.buscar(n["nombre"], ciudad_tx(n), token))
    if not c:
        return None
    fr = texas.franquicias([c["taxpayer"]], token).get(c["taxpayer"])
    reg = texas.registro_tx(c.get("taxpayer_name") or c["razon_social"], c["taxpayer"],
                            c.get("desde"), c.get("naics"), fr, round(min(conf, 1.0), 2))
    reg["razon_social"] = texas.titulo(c.get("taxpayer_name") or c["razon_social"])
    return reg

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--max", type=int, default=100000)
    ap.add_argument("--pais", choices=["CO", "ES", "TX"])
    ap.add_argument("--zona")
    ap.add_argument("--hilos", type=int, default=8, help="consultas en paralelo (datos abiertos toleran ~8)")
    args = ap.parse_args()
    from concurrent.futures import ThreadPoolExecutor, as_completed

    token = cargar_config().get("socrata_app_token", "")
    fuentes = {}
    hechos = con_match = 0
    for zona in zonas_con_datos(args.pais, args.zona):
        negocios = cargar_zona(zona)
        pend = [n for n in negocios if args.force or n.get("registro") is None]
        pend = [n for n in pend if n.get("pais", "CO") != "CO" or zona in CAMARAS_POR_ZONA]
        pend = pend[:max(0, args.max - hechos)]
        if not pend:
            continue
        if any(n.get("pais") == "ES" for n in pend) and not fuentes:
            fuentes = {"borme": IndiceBorme(), "om": OpenMercantil()}
        print(f"[{zona}] cruzando {len(pend)} negocios con {args.hilos} hilos…", flush=True)
        cambios = 0
        with ThreadPoolExecutor(max_workers=args.hilos) as pool:
            futuros = {pool.submit(procesar, n, zona, token, fuentes): n for n in pend}
            for fut in as_completed(futuros):
                n = futuros[fut]
                try:
                    reg = fut.result()
                except Exception:
                    continue  # error de red: queda pendiente para la próxima corrida
                n["registro"] = reg if reg else False  # False = buscado, sin match confiable
                hechos += 1
                cambios += 1
                if reg:
                    con_match += 1
                if cambios % 250 == 0:
                    guardar_zona(zona, negocios)
                    print(f"  …{cambios}/{len(pend)} · con registro {con_match}", flush=True)
        guardar_zona(zona, negocios)
        print(f"[{zona}] {cambios} procesados", flush=True)

    print(f"\nProcesados {hechos} · con registro {con_match}")

if __name__ == "__main__":
    main()
