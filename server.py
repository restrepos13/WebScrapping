#!/usr/bin/env python3
"""Backend del Radar Nocturno — optimizado para el plan free de Render.

Diseño para free tier:
  · Todo en memoria: negocios.json y croquis.geojson se cargan y comprimen (gzip)
    UNA vez al arrancar; cada request sirve bytes ya listos (0.1 CPU alcanza).
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
import gzip, hashlib, json, os
from flask import Flask, Response, abort, redirect, request, send_from_directory

BASE = os.path.dirname(os.path.abspath(__file__))
TOKEN = os.environ.get("RADAR_TOKEN", "")
PAGINAS = {"index.html", "mapa.html", "tracker-prospeccion.html", "sync.js"}

app = Flask(__name__, static_folder=None)

# ---------- caché en memoria (se construye una vez por arranque) ----------
_cache = {}

def _cargar(rel, sanitizar_config=False):
    ruta = os.path.join(BASE, rel)
    if not os.path.exists(ruta):
        return None
    mtime = os.path.getmtime(ruta)
    hit = _cache.get(rel)
    if hit and hit["mtime"] == mtime:          # en Render nunca cambia; local sí
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
        "raw": crudo,
        "etag": hashlib.md5(crudo).hexdigest(),
    }
    _cache[rel] = entrada
    return entrada

def _json_gz(rel, sanitizar=False, mime="application/json"):
    e = _cargar(rel, sanitizar)
    if e is None:
        abort(404)
    if request.headers.get("If-None-Match") == e["etag"]:
        return Response(status=304, headers={"ETag": e["etag"]})
    acepta_gz = "gzip" in (request.headers.get("Accept-Encoding") or "")
    cuerpo = e["gz"] if acepta_gz else e["raw"]
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

@app.route("/data/negocios.json")
def negocios():
    return _json_gz("data/negocios.json")

@app.route("/data/croquis.geojson")
def croquis():
    return _json_gz("data/croquis.geojson", mime="application/geo+json")

@app.route("/healthz")
def healthz():
    e = _cargar("data/negocios.json")
    n = len(json.loads(e["raw"])) if e else 0
    return {"ok": True, "negocios": n}

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 8765)))
