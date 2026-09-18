#!/usr/bin/env python3
"""Enriquecimiento con registros empresariales oficiales (datos.gov.co / Socrata).

Cruza cada negocio de data/negocios.json contra:
  1. RUES — Establecimientos de comercio (nb3d-v3n7): nombre comercial → NIT,
     estado de matrícula, CIIU, antigüedad. Es la misma fuente de la que se
     alimentan directorios comerciales tipo eInforma.
  2. RUES — Personas jurídicas (c82u-588k): razón social directa.
  3. Supersociedades — 10.000 empresas más grandes (6cat-2gcs): ingresos,
     macrosector (corte 2025) para las que aparezcan.

Uso:
  python3 enrich_empresas.py            # solo los no enriquecidos
  python3 enrich_empresas.py --force    # re-procesa todo
  python3 enrich_empresas.py --max 100  # límite por corrida

Sin API key (datos abiertos). Si config.json trae "socrata_app_token",
se usa para subir el rate limit.
"""
import json, os, re, sys, time, argparse, unicodedata, difflib, urllib.request, urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data", "negocios.json")
CONFIG = os.path.join(BASE, "config.json")

DS_ESTABLECIMIENTOS = "nb3d-v3n7"
DS_JURIDICAS = "c82u-588k"
DS_TOP10K = "6cat-2gcs"

CAMARAS_POR_ZONA = {
    "medellin": ["MEDELLIN PARA ANTIOQUIA", "ABURRA SUR"],
    "bucaramanga": ["BUCARAMANGA"],
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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--max", type=int, default=100000)
    args = ap.parse_args()

    cfg = json.load(open(CONFIG))
    token = cfg.get("socrata_app_token", "")
    negocios = json.load(open(DATA))
    hechos = con_match = 0
    for n in negocios:
        if n.get("registro") is not None and not args.force:
            continue
        if hechos >= args.max:
            break
        camaras = CAMARAS_POR_ZONA.get(n.get("zona"), [])
        if not camaras:
            continue
        hechos += 1
        conf, c = mejor(n["nombre"], candidatos(n["nombre"], camaras, token))
        if c:
            con_match += 1
            reg = {
                "razon_social": c.get("razon_social", ""),
                "nit": c.get("numero_identificacion", ""),
                "camara": c.get("camara_comercio", ""),
                "estado": c.get("estado_matricula", ""),
                "desde": (c.get("fecha_matricula") or "")[:4],
                "ciiu": c.get("cod_ciiu_act_econ_pri", ""),
                "tipo": c.get("_ds", ""),
                "confianza": round(min(conf, 1.0), 2),
            }
            fin = top10k(reg["nit"], token) if reg["nit"] else None
            if fin:
                reg.update(fin)
            n["registro"] = reg
            print(f"  ✓ {n['nombre'][:38]:38} → {reg['razon_social'][:34]:34} NIT {reg['nit']:12} {reg['estado']:9} desde {reg['desde']}"
                  + (f"  ${fin['ingresos']}" if fin else ""))
        else:
            n["registro"] = False  # buscado, sin match confiable
            print(f"  · {n['nombre'][:38]:38} → sin match confiable en RUES")
        time.sleep(0.15)

    json.dump(negocios, open(DATA, "w"), ensure_ascii=False, indent=1)
    print(f"\nProcesados {hechos} · con registro {con_match} · guardado en {DATA}")

if __name__ == "__main__":
    main()
