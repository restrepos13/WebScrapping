#!/usr/bin/env python3
"""Backend del Radar Nocturno — optimizado para el plan free de Render.

Diseño para free tier:
  · Datos por zona (data/zonas/<zona>.json): cada zona se comprime (gzip) la
    primera vez que se pide y queda en un caché LRU acotado — España + Texas no
    entran enteros en los 512MB, pero el mapa solo pide la zona que mira.
  · ETag + Cache-Control: el navegador no re-descarga los ~1MB del dataset.
  · Disco efímero de Render: acá NO se escribe nada en runtime. El pipeline
    (scan/audit/enrich) corre local y los datos se despliegan con el repo.
  · config.json se sirve SANITIZADO (nunca expone google_api_key ni tokens).
  · Acceso opcional por token: si existe la env RADAR_TOKEN, la primera visita
    necesita ?key=<token> (queda en cookie). Sin la env, es abierto.
  · /healthz para pings de keep-alive (cron-job.org cada 10 min evita el sleep).

Local:   python3 server.py            → http://localhost:8765
Render:  gunicorn -w 1 --threads 8 -b 0.0.0.0:$PORT server:app
"""
import gzip, hashlib, json, os, re
from collections import OrderedDict
from flask import Flask, Response, abort, redirect, request, send_from_directory

BASE = os.path.dirname(os.path.abspath(__file__))
TOKEN = os.environ.get("RADAR_TOKEN", "")
PAGINAS = {"index.html", "mapa.html", "tracker-prospeccion.html", "sync.js", "radar-comun.js"}

app = Flask(__name__, static_folder=None)

# ---------- caché en memoria (se construye una vez por arranque) ----------
_cache = OrderedDict()
MAX_CACHE = 24  # zonas comprimidas en memoria a la vez

def _cargar(rel, sanitizar_config=False):
    ruta = os.path.join(BASE, rel)
    if not os.path.exists(ruta):
        return None
    mtime = os.path.getmtime(ruta)
    hit = _cache.get(rel)
    if hit and hit["mtime"] == mtime:          # en Render nunca cambia; local sí
        _cache.move_to_end(rel)
        return hit
    with open(ruta, "rb") as f:
        crudo = f.read()
    if sanitizar_config:
        cfg = json.loads(crudo)
        for k in ("google_api_key", "socrata_app_token"):
            cfg.pop(k, None)
        crudo = json.dumps(cfg, ensure_ascii=False).encode()
    entrada = {
        "mtime": mtime,
        "gz": gzip.compress(crudo, 6),
        "raw": crudo if len(crudo) < 2_000_000 else None,  # los grandes solo en gzip
        "etag": hashlib.md5(crudo).hexdigest(),
    }
    _cache[rel] = entrada
    while len(_cache) > MAX_CACHE:
        _cache.popitem(last=False)
    return entrada

def _json_gz(rel, sanitizar=False, mime="application/json"):
    e = _cargar(rel, sanitizar)
    if e is None:
        abort(404)
    if request.headers.get("If-None-Match") == e["etag"]:
        return Response(status=304, headers={"ETag": e["etag"]})
    acepta_gz = "gzip" in (request.headers.get("Accept-Encoding") or "")
    if acepta_gz:
        cuerpo = e["gz"]
    else:
        cuerpo = e["raw"] if e["raw"] is not None else gzip.decompress(e["gz"])
    h = {"ETag": e["etag"], "Cache-Control": "public, max-age=300",
         "Content-Type": mime + "; charset=utf-8"}
    if acepta_gz:
        h["Content-Encoding"] = "gzip"
    return Response(cuerpo, headers=h)

# ---------- acceso ----------
@app.before_request
def _puerta():
    if not TOKEN or request.path == "/healthz":
        return
    if request.args.get("key") == TOKEN or request.cookies.get("rk") == TOKEN:
        return  # autorizado; la cookie se siembra en after_request
    return Response("<body style='background:#05060A;color:#9CA2AD;font-family:monospace;"
                    "display:grid;place-items:center;height:100vh'>acceso: agregá ?key=… a la URL</body>",
                    status=401, content_type="text/html")

@app.after_request
def _cookie(resp):
    if TOKEN and request.args.get("key") == TOKEN:
        resp.set_cookie("rk", TOKEN, max_age=90 * 24 * 3600, httponly=True, samesite="Lax")
    return resp

# ---------- rutas ----------
@app.route("/")
def raiz():
    return send_from_directory(BASE, "index.html", max_age=60)

@app.route("/<pagina>")
def paginas(pagina):
    if pagina not in PAGINAS:                  # lista blanca: nada más se sirve
        abort(404)
    return send_from_directory(BASE, pagina, max_age=60)

@app.route("/config.json")
def config():
    # local usa config.json (sanitizado); en Render cae al público y las credenciales
    # de Supabase entran por variables de entorno (nunca viajan en el repo público)
    rel = "config.json" if os.path.exists(os.path.join(BASE, "config.json")) else "config.public.json"
    cfg = json.loads(open(os.path.join(BASE, rel), "rb").read())
    for k in ("google_api_key", "socrata_app_token"):
        cfg.pop(k, None)
    if os.environ.get("SUPABASE_URL"):
        cfg["supabase_url"] = os.environ["SUPABASE_URL"]
        cfg["supabase_anon_key"] = os.environ.get("SUPABASE_ANON_KEY", "")
    return Response(json.dumps(cfg, ensure_ascii=False),
                    headers={"Content-Type": "application/json; charset=utf-8",
                             "Cache-Control": "no-store"})

@app.route("/data/zonas/index.json")
def zonas_index():
    return _json_gz("data/zonas/index.json")

@app.route("/data/zonas/<zona>.json")
def zona(zona):
    if not re.fullmatch(r"[a-z0-9-]{2,40}", zona):
        abort(404)
    return _json_gz(f"data/zonas/{zona}.json")

@app.route("/data/croquis.geojson")
def croquis():
    return _json_gz("data/croquis.geojson", mime="application/geo+json")

@app.route("/healthz")
def healthz():
    ruta = os.path.join(BASE, "data", "zonas", "index.json")
    idx = json.load(open(ruta)) if os.path.exists(ruta) else {}
    return {"ok": True, "zonas": len(idx), "negocios": sum(v.get("n", 0) for v in idx.values())}

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 8765)))
