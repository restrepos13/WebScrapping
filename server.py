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
  · Acceso privado: login con correo + contraseña (sin registro). Todo el sitio
    queda cerrado salvo /login, /api/*, /healthz y los JS públicos.
  · Cada intento de entrada (bueno o malo) se registra con IP, ciudad, país,
    operador y dispositivo. Se guarda en Supabase (tabla radar_estados con
    app='accesos') y se puede ver en /accesos. Sin Supabase queda en memoria.
  · /healthz para pings de keep-alive (cron-job.org cada 10 min evita el sleep).

Credenciales (van en el entorno de Render; sin ellas valen las de aquí):
  RADAR_USER       correo autorizado (por defecto restrepos591@gmail.com)
  RADAR_PASS_HASH  hash scrypt de la contraseña (generar con: python3 server.py --hash)
  RADAR_SECRETO    clave para firmar la sesión (opcional; si falta se deriva)

Local:   python3 server.py            → http://localhost:8765
Render:  gunicorn -w 1 --threads 8 -b 0.0.0.0:$PORT server:app
"""
import gzip, hashlib, hmac, html, ipaddress, json, os, re, threading, time
import urllib.parse, urllib.request
from collections import OrderedDict, deque
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import Flask, Response, abort, jsonify, redirect, request, send_from_directory
from itsdangerous import URLSafeTimedSerializer

BASE = os.path.dirname(os.path.abspath(__file__))
TOKEN = os.environ.get("RADAR_TOKEN", "")

# ---------- credenciales ----------
USUARIO = (os.environ.get("RADAR_USER") or "restrepos591@gmail.com").strip().lower()
# scrypt$n$r$p$salt$hash — la contraseña nunca viaja ni se guarda en claro.
CLAVE_HASH = os.environ.get("RADAR_PASS_HASH") or (
    "scrypt$16384$8$1$b8272b05e31333071e7b503b6bd364d1$"
    "8118f78cc91a37df2c21e693eba8f84b997e292c3b89709e26b25207909a8006")
SECRETO = os.environ.get("RADAR_SECRETO") or hashlib.sha256(
    f"radar-sesion|{USUARIO}|{CLAVE_HASH}".encode()).hexdigest()
SESION_DIAS = 30
_firmador = URLSafeTimedSerializer(SECRETO, salt="radar-sesion")

PAGINAS = {"index.html", "mapa.html", "tracker-prospeccion.html",
           "sync.js", "radar-comun.js", "auth.js"}
# lo que se puede pedir sin sesión: pantalla de entrada, API de sesión y assets sin datos
LIBRES = {"/login", "/api/login", "/api/logout", "/api/sesion", "/healthz", "/robots.txt"}
PUBLICOS = {"/auth.js", "/sync.js", "/radar-comun.js"}

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
    h = {"ETag": e["etag"], "Cache-Control": "private, max-age=300",
         "Content-Type": mime + "; charset=utf-8"}
    if acepta_gz:
        h["Content-Encoding"] = "gzip"
    return Response(cuerpo, headers=h)

# ---------- sesión ----------
def _clave_ok(clave):
    try:
        alg, n, r, p, salt, esperado = CLAVE_HASH.split("$")
        if alg != "scrypt":
            return False
        calc = hashlib.scrypt(clave.encode(), salt=bytes.fromhex(salt), n=int(n),
                              r=int(r), p=int(p), dklen=len(bytes.fromhex(esperado)))
        return hmac.compare_digest(calc, bytes.fromhex(esperado))
    except Exception:
        return False

def _firmar():
    return _firmador.dumps({"u": USUARIO})

def sesion_valida():
    tok = request.cookies.get("radar_ses") or request.headers.get("X-Radar-Sesion") or ""
    if not tok:
        return None
    try:
        datos = _firmador.loads(tok, max_age=SESION_DIAS * 24 * 3600)
        return datos.get("u") if datos.get("u") == USUARIO else None
    except Exception:
        return None

def _https():
    proto = (request.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip()
    return request.is_secure or proto == "https"

def _autorizado():
    # enlace antiguo ?key=… (sigue sirviendo para no romper marcadores viejos)
    if TOKEN and (request.args.get("key") == TOKEN or request.cookies.get("rk") == TOKEN):
        return USUARIO
    return sesion_valida()

# ---------- registro de accesos ----------
# Se guarda en Supabase como filas de radar_estados con app='accesos' (ya existe,
# tiene política anon y el mapa nunca las pide: filtra por app='mapa'/'tracker').
_mem = deque(maxlen=400)
_visto = {}            # ip|ruta → ts, para no repetir el mismo aviso cada minuto
_fallos = {}           # ip → deque de timestamps de claves erradas
_geo_cache = {}        # ip → (ts, datos)
MAX_FALLOS, VENTANA = 10, 600

def _supabase():
    url = os.environ.get("SUPABASE_URL") or ""
    key = os.environ.get("SUPABASE_ANON_KEY") or ""
    if not (url and key):
        try:
            cfg = json.load(open(os.path.join(BASE, "config.json")))
            url = url or cfg.get("supabase_url") or ""
            key = key or cfg.get("supabase_anon_key") or ""
        except Exception:
            pass
    return url.rstrip("/"), key

def ip_cliente():
    # El sitio se entra por Render o por el proxy de Vercel. Vercel manda la IP
    # original en X-Vercel-Forwarded-For; Cloudflare (delante de Render) la pone
    # en CF-Connecting-IP. Sin esto, las visitas que pasan por Vercel quedaban
    # anotadas con la IP del borde de Vercel (AWS), no con la de la persona.
    candidatas = []
    for cabecera in ("X-Vercel-Forwarded-For", "CF-Connecting-IP"):
        candidatas += [x.strip() for x in (request.headers.get(cabecera) or "").split(",") if x.strip()]
    cadena = request.headers.get("X-Forwarded-For") or ""
    candidatas += [x.strip() for x in cadena.split(",") if x.strip()]
    extra = request.headers.get("X-Real-IP")
    if extra:
        candidatas.append(extra.strip())
    for ip in candidatas:
        try:
            if ipaddress.ip_address(ip).is_global:
                return ip
        except ValueError:
            continue
    return request.remote_addr or ""

def _geo(ip):
    try:
        privada = not ipaddress.ip_address(ip).is_global
    except ValueError:
        privada = True
    if privada:
        return {"ciudad": "red local", "region": "", "pais": "", "isp": ""}
    guardado = _geo_cache.get(ip)
    if guardado and time.time() - guardado[0] < 3600:
        return guardado[1]
    datos = {"ciudad": "", "region": "", "pais": "", "isp": ""}
    try:
        req = urllib.request.Request(f"https://ipwho.is/{urllib.parse.quote(ip)}",
                                     headers={"User-Agent": "radar-nocturno/1.0"})
        with urllib.request.urlopen(req, timeout=4) as r:
            d = json.loads(r.read().decode())
        if d.get("success"):
            datos = {"ciudad": d.get("city") or "", "region": d.get("region") or "",
                     "pais": d.get("country") or "",
                     "isp": (d.get("connection") or {}).get("isp") or ""}
    except Exception:
        pass
    _geo_cache[ip] = (time.time(), datos)
    return datos

def _dispositivo(ua):
    ua = ua or ""
    if re.search(r"iPhone", ua): base = "iPhone"
    elif re.search(r"iPad", ua): base = "iPad"
    elif re.search(r"Android", ua): base = "Android"
    elif re.search(r"Windows", ua): base = "Windows"
    elif re.search(r"Macintosh|Mac OS X", ua): base = "Mac"
    elif re.search(r"Linux", ua): base = "Linux"
    elif re.search(r"curl|Wget|python|bot|crawler|spider", ua, re.I): base = "script/bot"
    else: base = "otro"
    for patron, nombre in ((r"Edg/", "Edge"), (r"OPR/|Opera", "Opera"), (r"Firefox/", "Firefox"),
                           (r"Chrome/", "Chrome"), (r"Safari/", "Safari")):
        if re.search(patron, ua):
            return f"{base} · {nombre}"
    return base

def _enriquecer(d):
    g = _geo(d.get("ip", ""))
    d.update(ciudad=g["ciudad"], region=g["region"], pais=g["pais"], isp=g["isp"])
    url, key = _supabase()
    if not (url and key):
        return
    fila = [{"app": "accesos", "id": d["id"], "data": {k: d.get(k, "") for k in (
        "ts", "ok", "email", "ip", "ciudad", "region", "pais", "isp", "dispositivo",
        "ua", "ruta", "motivo", "ref", "via")}}]
    try:
        req = urllib.request.Request(
            f"{url}/rest/v1/radar_estados", data=json.dumps(fila).encode(),
            headers={"apikey": key, "Authorization": "Bearer " + key,
                     "Content-Type": "application/json", "Prefer": "return=minimal"},
            method="POST")
        urllib.request.urlopen(req, timeout=6).read()
    except Exception:
        pass

def registrar(ok, email="", ruta="", motivo=""):
    ahora = time.time()
    d = {
        "id": f"{int(ahora * 1000)}-{os.urandom(3).hex()}",
        "ts": datetime.fromtimestamp(ahora, timezone.utc).isoformat(timespec="seconds"),
        "ok": bool(ok), "email": email or "", "ip": ip_cliente(),
        "ciudad": "", "region": "", "pais": "", "isp": "",
        "dispositivo": _dispositivo(request.headers.get("User-Agent")),
        "ua": (request.headers.get("User-Agent") or "")[:300],
        "ruta": ruta or request.path, "motivo": motivo,
        "ref": (request.referrer or "")[:200],
        # cadena de proxies tal como llegó: sirve para saber por dónde entró
        # (Vercel, Cloudflare, directo) y depurar la IP si alguna vez no cuadra
        "via": (request.headers.get("X-Forwarded-For") or "")[:160],
    }
    _mem.appendleft(d)
    threading.Thread(target=_enriquecer, args=(d,), daemon=True).start()
    return d

def _denegado(ruta):
    ip = ip_cliente()
    llave = f"{ip}|{ruta}"
    if time.time() - _visto.get(llave, 0) < 600:
        return
    _visto[llave] = time.time()
    registrar(False, "", ruta, "sin sesión")

def _bloqueado(ip):
    cola = _fallos.get(ip)
    if not cola:
        return False
    while cola and time.time() - cola[0] > VENTANA:
        cola.popleft()
    return len(cola) >= MAX_FALLOS

# ---------- puerta ----------
@app.before_request
def _puerta():
    p = request.path
    if p in LIBRES or p in PUBLICOS or request.method == "OPTIONS":
        return
    if _autorizado():
        return
    _denegado(p)
    if p.startswith("/data/") or p == "/config.json":
        return jsonify({"error": "sesion"}), 401
    destino = "/login" + ("?next=" + urllib.parse.quote(p) if p not in ("/", "") else "")
    return redirect(destino)

@app.after_request
def _cabeceras(resp):
    resp.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    if TOKEN and request.args.get("key") == TOKEN and request.path != "/healthz":
        resp.set_cookie("rk", TOKEN, max_age=90 * 24 * 3600, httponly=True, samesite="Lax")
    return resp

# ---------- entrada ----------
ESTILO_LOGIN = """
:root{--ink:#ECEDEF;--ink2:#9CA2AD;--ink3:#5E6470;--line:rgba(255,255,255,.10);--amber:#FFB020}
*{box-sizing:border-box}
body{margin:0;min-height:100dvh;display:grid;place-items:center;padding:24px;background:
 radial-gradient(700px 340px at 72% 18%,rgba(255,176,32,.07),transparent),
 radial-gradient(520px 320px at 22% 88%,rgba(57,255,110,.05),transparent),#05060A;
 color:var(--ink);font-family:"Archivo",system-ui,-apple-system,sans-serif}
.caja{width:min(390px,100%)}
.mono{font-family:ui-monospace,"SF Mono",Menlo,monospace}
.kicker{font-size:10px;letter-spacing:.22em;text-transform:uppercase;color:var(--ink3);margin:0 0 10px}
h1{font-size:30px;font-weight:900;letter-spacing:-.02em;margin:0 0 6px}
.sub{font-size:13px;color:var(--ink2);margin:0 0 26px;line-height:1.6}
label{display:block;font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink3);margin:0 0 6px}
input{width:100%;padding:12px 13px;border-radius:10px;border:1px solid var(--line);
 background:rgba(255,255,255,.04);color:var(--ink);font-size:14px;outline:none;font-family:inherit}
input:focus{border-color:rgba(255,176,32,.6);background:rgba(255,255,255,.06)}
.campo{margin-bottom:14px}
button{width:100%;margin-top:8px;padding:12px;border:0;border-radius:10px;background:var(--amber);
 color:#161006;font-weight:800;font-size:14px;letter-spacing:.01em;cursor:pointer}
button:disabled{opacity:.6;cursor:wait}
.pie{margin-top:18px;font-size:10.5px;color:var(--ink3);line-height:1.7;text-align:center}
.error{display:none;margin:0 0 14px;padding:10px 12px;border-radius:9px;font-size:12px;
 border:1px solid rgba(255,51,85,.35);background:rgba(255,51,85,.09);color:#FF8FA3}
"""

def _pagina_login(next_url="/"):
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Acceso · Radar</title>
<style>{ESTILO_LOGIN}</style></head><body>
<div class="caja">
  <p class="kicker mono">Radar Nocturno</p>
  <h1>Acceso privado</h1>
  <p class="sub">Este panel es de uso personal. Entrá con el correo y la contraseña del propietario.</p>
  <div class="error" id="error"></div>
  <form id="f" autocomplete="on">
    <div class="campo"><label for="email">Correo</label>
      <input id="email" type="email" autocomplete="username" required autofocus></div>
    <div class="campo"><label for="clave">Contraseña</label>
      <input id="clave" type="password" autocomplete="current-password" required></div>
    <button id="b" type="submit">Entrar</button>
  </form>
  <p class="pie">Los intentos de acceso quedan registrados con IP y ubicación aproximada.</p>
</div>
<script>
const destino={json.dumps(next_url)};
const $=s=>document.querySelector(s);
$("#f").addEventListener("submit",async e=>{{
  e.preventDefault();
  const b=$("#b"), err=$("#error");
  b.disabled=true; b.textContent="Entrando…"; err.style.display="none";
  try{{
    const r=await fetch("/api/login",{{method:"POST",headers:{{"Content-Type":"application/json"}},
      body:JSON.stringify({{email:$("#email").value.trim(),password:$("#clave").value}})}});
    const d=await r.json().catch(()=>({{}}));
    if(r.ok&&d.ok){{
      try{{ if(d.token) localStorage.setItem("radar-sesion",d.token); }}catch(_){{}}
      location.href=destino||"/";
      return;
    }}
    err.textContent=d.error||"No se pudo entrar.";
  }}catch(_){{ err.textContent="No hay conexión con el servidor. Probá de nuevo."; }}
  err.style.display="block"; b.disabled=false; b.textContent="Entrar";
}});
</script></body></html>"""

@app.route("/login")
def login():
    if _autorizado():
        return redirect("/")
    destino = request.args.get("next") or "/"
    if not destino.startswith("/") or destino.startswith("//") or destino.startswith("/login"):
        destino = "/"
    return Response(_pagina_login(destino), content_type="text/html; charset=utf-8",
                    headers={"Cache-Control": "no-store"})

@app.post("/api/login")
def api_login():
    ip = ip_cliente()
    datos = request.get_json(silent=True) or request.form or {}
    email = (datos.get("email") or "").strip().lower()
    clave = datos.get("password") or datos.get("clave") or ""
    if _bloqueado(ip):
        registrar(False, email, "/api/login", "bloqueado por intentos")
        return jsonify({"ok": False, "error": "Demasiados intentos. Esperá 10 minutos."}), 429
    correo_ok = hmac.compare_digest(email.encode(), USUARIO.encode())
    clave_ok = _clave_ok(clave)
    if not (correo_ok and clave_ok):
        _fallos.setdefault(ip, deque()).append(time.time())
        motivo = "correo desconocido" if not correo_ok else "contraseña incorrecta"
        registrar(False, email, "/api/login", motivo)
        time.sleep(0.35)  # frena el sondeo automatizado
        return jsonify({"ok": False, "error": "Correo o contraseña incorrectos."}), 401
    tok = _firmar()
    resp = jsonify({"ok": True, "email": USUARIO, "token": tok})
    resp.set_cookie("radar_ses", tok, max_age=SESION_DIAS * 24 * 3600, httponly=True,
                    samesite="Lax", secure=_https())
    _fallos.pop(ip, None)
    registrar(True, email, "/api/login")
    return resp

@app.post("/api/logout")
def api_logout():
    resp = jsonify({"ok": True})
    resp.delete_cookie("radar_ses")
    return resp

@app.get("/api/sesion")
def api_sesion():
    usuario = sesion_valida()
    if usuario:
        return jsonify({"ok": True, "email": usuario})
    _denegado("/api/sesion")  # deja rastro de quien prueba entrar
    return jsonify({"ok": False}), 401

# ---------- panel de accesos ----------
def _leer_accesos(limite=200):
    url, key = _supabase()
    if url and key:
        try:
            q = (f"{url}/rest/v1/radar_estados?app=eq.accesos"
                 f"&select=id,data,updated_at&order=updated_at.desc&limit={limite}")
            req = urllib.request.Request(q, headers={"apikey": key,
                                                     "Authorization": "Bearer " + key})
            with urllib.request.urlopen(req, timeout=8) as r:
                filas = json.loads(r.read().decode())
            return [dict(f.get("data") or {}, ts=(f.get("data") or {}).get("ts") or f.get("updated_at"))
                    for f in filas]
        except Exception:
            pass
    return list(_mem)[:limite]

def _hora(ts):
    try:
        t = datetime.fromisoformat((ts or "").replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return t.astimezone(ZoneInfo("America/Bogota")).strftime("%d/%m %H:%M:%S")
    except Exception:
        return (ts or "")[:16]

def _pagina_accesos():
    filas = _leer_accesos()
    ahora = time.time()
    recientes = [f for f in filas if (_hora_epoch(f.get("ts")) or 0) > ahora - 86400]
    fallos = sum(1 for f in recientes if not f.get("ok"))
    ips = len({f.get("ip") for f in filas if f.get("ip")})
    cuerpo = []
    for f in filas:
        ok = bool(f.get("ok"))
        lugar = ", ".join(x for x in (f.get("ciudad"), f.get("region"), f.get("pais")) if x) or "—"
        cuerpo.append(
            "<tr>"
            f"<td class='mono'>{html.escape(_hora(f.get('ts')))}</td>"
            f"<td><span class='tag {'ok' if ok else 'no'}'>{'entró' if ok else 'rechazado'}</span></td>"
            f"<td class='mono'>{html.escape(f.get('email') or '—')}</td>"
            f"<td class='mono'>{html.escape(f.get('ip') or '—')}</td>"
            f"<td>{html.escape(lugar)}</td>"
            f"<td class='dim'>{html.escape(f.get('isp') or '—')}</td>"
            f"<td>{html.escape(f.get('dispositivo') or '—')}</td>"
            f"<td class='mono dim' title='{html.escape(f.get('ua') or '')}'>"
            f"{html.escape(f.get('ruta') or '')}"
            f"{' · ' + html.escape(f.get('motivo')) if f.get('motivo') else ''}</td>"
            "</tr>")
    if not cuerpo:
        cuerpo.append("<tr><td colspan='8' class='dim'>Sin registros todavía.</td></tr>")
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Accesos · Radar</title>
<style>
:root{{--ink:#ECEDEF;--ink2:#9CA2AD;--ink3:#5E6470;--line:rgba(255,255,255,.09);--amber:#FFB020}}
*{{box-sizing:border-box}}
body{{margin:0;padding:28px clamp(14px,4vw,40px) 60px;background:#05060A;color:var(--ink);
 font-family:"Archivo",system-ui,sans-serif}}
.mono{{font-family:ui-monospace,"SF Mono",Menlo,monospace;font-size:11.5px}}
h1{{font-size:24px;font-weight:900;letter-spacing:-.02em;margin:0}}
header{{display:flex;flex-wrap:wrap;gap:14px;align-items:baseline;justify-content:space-between;
 border-bottom:1px solid var(--line);padding-bottom:14px;margin-bottom:18px}}
a{{color:var(--amber);text-decoration:none;font-size:12px}}
.resumen{{display:flex;flex-wrap:wrap;gap:10px;margin:0 0 18px}}
.chip{{border:1px solid var(--line);border-radius:999px;padding:6px 12px;font-size:11px;
 color:var(--ink2);font-family:ui-monospace,Menlo,monospace}}
.chip b{{color:var(--ink)}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{text-align:left;font-size:9.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--ink3);
 font-weight:600;padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap}}
td{{padding:9px 10px;border-bottom:1px solid rgba(255,255,255,.05);vertical-align:top}}
tr:hover td{{background:rgba(255,255,255,.025)}}
.tag{{font-family:ui-monospace,Menlo,monospace;font-size:10px;padding:2px 7px;border-radius:6px}}
.tag.ok{{background:rgba(57,255,110,.12);color:#6BFF9B}}
.tag.no{{background:rgba(255,51,85,.12);color:#FF8FA3}}
.dim{{color:var(--ink3)}}
</style></head><body>
<header><div><h1>Registro de accesos</h1>
<div class="mono dim">últimos {len(filas)} intentos · hora de Bogotá</div></div>
<div><a href="/">← Radar</a> &nbsp; <a href="/api/logout" onclick="fetch('/api/logout',{{method:'POST'}}).then(()=>location.href='/login');return false">Salir</a></div>
</header>
<div class="resumen">
 <span class="chip">24 h: <b>{len(recientes)}</b></span>
 <span class="chip">rechazados 24 h: <b>{fallos}</b></span>
 <span class="chip">IPs distintas: <b>{ips}</b></span>
 <span class="chip">guardado en: <b>{'Supabase' if _supabase()[0] else 'memoria'}</b></span>
</div>
<table><thead><tr><th>Hora</th><th>Resultado</th><th>Correo</th><th>IP</th><th>Ubicación</th>
<th>Operador</th><th>Dispositivo</th><th>Ruta / motivo</th></tr></thead>
<tbody>{''.join(cuerpo)}</tbody></table>
<p class="mono dim" style="margin-top:22px">Si no reconocés un intento, cambiá la contraseña:
RADAR_PASS_HASH en Render (generar con <b>python3 server.py --hash</b>).</p>
</body></html>"""

def _hora_epoch(ts):
    try:
        t = datetime.fromisoformat((ts or "").replace("Z", "+00:00"))
        return t.replace(tzinfo=t.tzinfo or timezone.utc).timestamp()
    except Exception:
        return 0

@app.route("/accesos")
def accesos():
    return Response(_pagina_accesos(), content_type="text/html; charset=utf-8",
                    headers={"Cache-Control": "no-store"})

# ---------- rutas ----------
@app.route("/")
def raiz():
    return send_from_directory(BASE, "index.html", max_age=0)

@app.route("/<pagina>")
def paginas(pagina):
    if pagina not in PAGINAS:                  # lista blanca: nada más se sirve
        abort(404)
    return send_from_directory(BASE, pagina, max_age=0)

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

@app.route("/robots.txt")
def robots():
    return Response("User-agent: *\nDisallow: /\n", content_type="text/plain; charset=utf-8")

@app.route("/healthz")
def healthz():
    ruta = os.path.join(BASE, "data", "zonas", "index.json")
    idx = json.load(open(ruta)) if os.path.exists(ruta) else {}
    return {"ok": True, "zonas": len(idx), "negocios": sum(v.get("n", 0) for v in idx.values())}

if __name__ == "__main__":
    import getpass, sys
    if "--hash" in sys.argv:
        clave = getpass.getpass("Nueva contraseña: ")
        if clave != getpass.getpass("Repetir: "):
            raise SystemExit("No coinciden.")
        salt = os.urandom(16)
        h = hashlib.scrypt(clave.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
        print(f"scrypt$16384$8$1${salt.hex()}${h.hex()}")
        raise SystemExit
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 8765)))
