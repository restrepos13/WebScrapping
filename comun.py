"""Utilidades compartidas del pipeline: almacenamiento por zona, teléfonos por
país, normalización de nombres, HTTP y fusión de registros entre fuentes.

Almacenamiento: data/zonas/<zona>.json (una lista de negocios por zona) +
data/zonas/index.json (país, conteo y fecha por zona). Así el mapa descarga solo
la zona que mira y Render no tiene que cargar España entera en memoria.
"""
import json, math, os, re, time, unicodedata, difflib, urllib.request, urllib.error

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
ZONAS_DIR = os.path.join(DATA_DIR, "zonas")
REG_DIR = os.path.join(DATA_DIR, "registros")   # índices crudos locales (no se despliegan)
INDEX = os.path.join(ZONAS_DIR, "index.json")
CONFIG = os.path.join(BASE, "config.json")

UA = "RadarNocturno/1.0 (+https://github.com/restrepos13/WebScrapping)"

# campos que llenan audit/enrich y que un re-barrido nunca debe pisar
CAMPOS_PIPELINE = ("senales", "gancho", "emails", "redes", "auditado", "registro")

def cargar_config():
    ruta = CONFIG if os.path.exists(CONFIG) else os.path.join(BASE, "config.public.json")
    return json.load(open(ruta))

# ---------------- almacenamiento ----------------
def _ruta(zona):
    return os.path.join(ZONAS_DIR, f"{zona}.json")

def cargar_index():
    return json.load(open(INDEX)) if os.path.exists(INDEX) else {}

def cargar_zona(zona):
    r = _ruta(zona)
    return json.load(open(r)) if os.path.exists(r) else []

def guardar_zona(zona, negocios, pais=None):
    os.makedirs(ZONAS_DIR, exist_ok=True)
    negocios = sorted(negocios, key=lambda n: n["id"])  # orden estable → diffs de git chicos
    tmp = _ruta(zona) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(negocios, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, _ruta(zona))
    with bloqueo_index():  # varios scripts pueden correr a la vez (scan + texas + osm)
        idx = cargar_index()
        previo = idx.get(zona, {})
        idx[zona] = {**previo, "pais": pais or (negocios[0].get("pais") if negocios else previo.get("pais", "CO")),
                     "n": len(negocios), "actualizado": time.strftime("%Y-%m-%d")}
        escribir_index(idx)

def escribir_index(idx):
    tmp = INDEX + ".tmp"
    json.dump(dict(sorted(idx.items())), open(tmp, "w"), ensure_ascii=False, indent=1)
    os.replace(tmp, INDEX)

class bloqueo_index:
    def __enter__(self):
        import fcntl
        os.makedirs(ZONAS_DIR, exist_ok=True)
        self.f = open(INDEX + ".lock", "w")
        fcntl.flock(self.f, fcntl.LOCK_EX)
    def __exit__(self, *a):
        import fcntl
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()

def zonas_con_datos(pais=None, zona=None):
    idx = cargar_index()
    return [z for z, v in idx.items() if (not zona or z == zona) and (not pais or v.get("pais") == pais)]

# ---------------- teléfonos ----------------
def digitos(s):
    return "".join(c for c in (s or "") if c.isdigit())

def wa_de(tel, pais):
    """Número en formato wa.me o '' si no es probable que tenga WhatsApp."""
    d = digitos(tel)
    if not d:
        return ""
    if pais == "CO":
        if not d.startswith("57") and len(d) == 10:
            d = "57" + d
        return d
    if pais == "ES":
        if d.startswith("0034"):
            d = d[4:]
        elif d.startswith("34") and len(d) == 11:
            d = d[2:]
        return "34" + d if len(d) == 9 and d[0] in "67" else ""  # solo móviles
    return ""  # Texas: WhatsApp no es el canal por defecto; se usa tel/SMS/email

def tel_legible(tel, pais):
    d = digitos(tel)
    if pais == "TX":
        if len(d) == 11 and d.startswith("1"):
            d = d[1:]
        if len(d) == 10:
            return f"({d[:3]}) {d[3:6]}-{d[6:]}"
    return (tel or "").strip()

# ---------------- nombres ----------------
STOP = {"DE", "LA", "EL", "LOS", "LAS", "Y", "DEL", "EN", "SAS", "S", "A", "LTDA", "CIA", "DR", "DRA",
        "SL", "SLU", "SA", "SLL", "SLP", "SCOOP", "CB", "LLC", "INC", "LP", "LTD", "CO", "CORP", "PLLC",
        "PC", "THE", "AND", "OF", "DBA"}

def norm(s):
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").upper()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", s)).strip()

def palabras(s):
    return [w for w in norm(s).split() if w not in STOP and len(w) >= 2]

def similitud(a, b):
    na, nb = " ".join(palabras(a)), " ".join(palabras(b))
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()

def metros(lat1, lng1, lat2, lng2):
    x = math.radians(lng2 - lng1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = math.radians(lat2 - lat1)
    return 6371000 * math.hypot(x, y)

# ---------------- HTTP ----------------
def http_json(url, data=None, headers=None, timeout=60, intentos=3, metodo=None):
    h = {"User-Agent": UA, "Accept": "application/json"}
    h.update(headers or {})
    ultimo = None
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, data=data, headers=h, method=metodo)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "ignore"))
        except urllib.error.HTTPError as e:
            ultimo = e
            if e.code in (400, 401, 403, 404):
                raise
        except Exception as e:
            ultimo = e
        time.sleep(2 * (i + 1))
    raise ultimo

# ---------------- fusión entre fuentes ----------------
class Fusion:
    """Mezcla registros nuevos sobre los de una zona.

    - mismo id → actualiza los datos de la fuente y conserva lo que llenó el pipeline
    - id distinto pero mismo negocio (≤ 80 m y nombre parecido) → se funde en el
      existente: completa web/tel/emails/redes vacíos y anota la fuente adicional
    """
    CELDA = 0.001  # ~110 m

    def __init__(self, existentes):
        self.por_id = {n["id"]: n for n in existentes}
        self.alias = {a: n["id"] for n in existentes for a in n.get("ids_alt", [])}
        self.grid = {}
        for n in existentes:
            self._indexar(n)
        self.nuevos = self.fundidos = self.actualizados = 0

    def _celda(self, lat, lng):
        return (int(lat / self.CELDA), int(lng / self.CELDA))

    def _indexar(self, n):
        if n.get("aprox") or n.get("lat") is None:
            return
        self.grid.setdefault(self._celda(n["lat"], n["lng"]), []).append(n["id"])

    def _gemelo(self, r):
        if r.get("aprox") or r.get("lat") is None:
            return None
        cy, cx = self._celda(r["lat"], r["lng"])
        mejor, mejor_s = None, 0.0
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for i in self.grid.get((cy + dy, cx + dx), []):
                    n = self.por_id.get(i)
                    if not n or n["id"] == r["id"]:
                        continue
                    if metros(r["lat"], r["lng"], n["lat"], n["lng"]) > 80:
                        continue
                    s = similitud(r["nombre"], n["nombre"])
                    if s >= 0.8 and s > mejor_s:
                        mejor, mejor_s = n, s
        return mejor

    def agregar(self, r):
        rid = self.alias.get(r["id"], r["id"])
        prev = self.por_id.get(rid)
        if prev is not None and rid == r["id"]:
            for c in CAMPOS_PIPELINE:
                if c in prev:
                    r[c] = prev[c]
            for c in ("ids_alt", "fuentes", "nuevo", "categoria", "subzona"):
                if c in prev:  # la primera categoría manda: una búsqueda vecina no la pisa
                    r[c] = prev[c]
            self.por_id[rid] = r
            self.actualizados += 1
            return r
        destino = prev or self._gemelo(r)
        if destino is not None and r.get("fuente") == "places" and destino.get("fuente") != "places":
            return self._promover(r, destino)  # Google es la fuente principal
        if destino is not None:
            self._completar(destino, r)
            self.fundidos += 1
            return destino
        r.setdefault("fuentes", [r.get("fuente", "")])
        self.por_id[r["id"]] = r
        self._indexar(r)
        self.nuevos += 1
        return r

    def _promover(self, g, viejo):
        """El registro de Google reemplaza al de otra fuente y absorbe lo que este traía."""
        for c in ("registro", "nuevo"):
            if c in viejo:
                g[c] = viejo[c]
        if not g.get("web") or g.get("web") == viejo.get("web"):
            for c in ("senales", "gancho", "auditado"):  # la auditoría vale si la web es la misma
                if c in viejo:
                    g[c] = viejo[c]
        g["fuentes"] = ["places"] + [f for f in viejo.get("fuentes", [viejo.get("fuente", "")]) if f and f != "places"]
        g["ids_alt"] = [viejo["id"]] + viejo.get("ids_alt", [])
        self._completar(g, viejo)
        del self.por_id[viejo["id"]]
        self.por_id[g["id"]] = g
        for a in g["ids_alt"]:
            self.alias[a] = g["id"]
        self._indexar(g)
        self.fundidos += 1
        return g

    def _completar(self, n, r):
        for c in ("web", "tel", "wa", "direccion"):
            if not n.get(c) and r.get(c):
                n[c] = r[c]
                if c == "web":
                    n["auditado"] = False  # apareció una web: hay que auditarla
                    n.setdefault("senales", {})["sin_web"] = False
        if r.get("emails"):
            n["emails"] = sorted(set(n.get("emails", [])) | set(r["emails"]))[:5]
        if r.get("redes"):
            n["redes"] = {**r["redes"], **n.get("redes", {})}
        if n.get("aprox") and not r.get("aprox"):
            n["lat"], n["lng"], n["aprox"] = r["lat"], r["lng"], False
        if r.get("nuevo") and not n.get("nuevo"):
            n["nuevo"] = r["nuevo"]
        fs = n.setdefault("fuentes", [n.get("fuente", "")])
        if r.get("fuente") and r["fuente"] not in fs:
            fs.append(r["fuente"])
        alt = n.setdefault("ids_alt", [])
        if r["id"] not in alt and r["id"] != n["id"]:
            alt.append(r["id"])
            self.alias[r["id"]] = n["id"]

    def lista(self):
        return list(self.por_id.values())

def base_registro(id_, nombre, categoria, zona, pais, lat, lng, fuente, **extra):
    """Esqueleto común de un negocio (mismo esquema que scan.py)."""
    web = extra.pop("web", "") or ""
    tel = extra.pop("tel", "") or ""
    n = {
        "id": id_, "nombre": nombre, "categoria": categoria, "zona": zona, "pais": pais,
        "subzona": extra.pop("subzona", ""), "lat": lat, "lng": lng, "aprox": extra.pop("aprox", False),
        "direccion": extra.pop("direccion", ""), "tel": tel_legible(tel, pais), "wa": wa_de(tel, pais),
        "web": web, "rating": extra.pop("rating", None), "reviews": extra.pop("reviews", None),
        "tipos": extra.pop("tipos", []),
        "senales": {"sin_web": not web}, "gancho": "", "emails": extra.pop("emails", []),
        "redes": extra.pop("redes", {}), "auditado": False, "fuente": fuente,
    }
    n.update(extra)
    return n
