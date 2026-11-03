#!/usr/bin/env python3
"""Une duplicados que la fusión por nombre no atrapó.

Cuando Google y OSM describen el mismo negocio con nombres distintos
("Pepper Jack" / "Pepper Jack Restaurante", "Varako Steak House" /
"Varako Steak House & Fast Food"), quedan dos luces en el mapa. Acá se
detectan por cercanía + contención de palabras y se funden en el registro de
Google, que es el que trae teléfono y reseñas.

Guardas para no borrar negocios reales:
  · ≤ 45 m de distancia
  · un nombre contiene al otro (sin palabras genéricas) o similitud ≥ 0.88
  · si los dos tienen teléfono y son distintos, NO se funden
  · si los dos tienen web y son dominios distintos, NO se funden

Uso:
  python3 dedupe.py --zona quito            # informe, no escribe
  python3 dedupe.py --zona quito --aplicar
  python3 dedupe.py --pais EC --aplicar
"""
import argparse, re, unicodedata
from comun import cargar_config, cargar_zona, guardar_zona, metros, similitud

GENERICAS = {
    "restaurante", "restaurant", "cafeteria", "café", "bar", "grill", "steak",
    "house", "pizzeria", "pizza", "cevicheria", "marisqueria", "sushi", "food",
    "fast", "comida", "rapida", "the", "and", "de", "del", "la", "el", "los",
    "las", "y", "sa", "sas", "ltda", "cia", "cía", "sac", "eirl", "srl",
    "sac.", "s.a.", "s.a.s.", "&amp;", "&",
    # rubros y palabras de relleno: no identifican por sí solos a un negocio
    "panaderia", "pasteleria", "heladeria", "peluqueria", "barberia", "optica",
    "farmacia", "drogueria", "minimarket", "tienda", "almacen", "supermercado",
    "hotel", "hostal", "hospedaje", "clinica", "dental", "odontologia",
    "veterinaria", "gimnasio", "spa", "salon", "belleza", "estetica", "centro",
    "agencia", "viajes", "inmobiliaria", "ferreteria", "taller", "automotriz",
    "repuestos", "lavanderia", "imprenta", "papeleria", "libreria",
    "floristeria", "joyeria", "zapateria", "boutique", "moda", "licorera",
    "discoteca", "pub", "cantina", "polleria", "picanteria", "sangucheria",
    "jugueria", "fuente", "soda", "chifa", "local", "sucursal", "matriz",
}


def normalizar(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9& ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def palabras(s):
    return {p for p in normalizar(s).split() if len(p) > 1 and p not in GENERICAS}


# las palabras genéricas se comparan sin tildes ("panadería" → "panaderia")
GENERICAS = {normalizar(g) for g in GENERICAS}


def contiene(a, b):
    """El nombre corto está completo dentro del largo (por palabras).

    Si el corto es una sola palabra tiene que ser la marca (la primera palabra
    significativa del largo): así "Arenas" se une a "Panadería Arenas" pero
    "Tripas" no se come "Los Antojitos de la Floresta".
    """
    pa, pb = palabras(a), palabras(b)
    if not pa or not pb:
        return False
    corto, largo = (pa, pb) if len(pa) <= len(pb) else (pb, pa)
    if not corto <= largo:
        return False
    if len(corto) == 1:
        palabra = next(iter(corto))
        if len(palabra) < 4:
            return False
        nombre = a if largo is pa else b
        crudos = [normalizar(t) for t in nombre.replace("|", " ").replace("-", " ").split()]
        primera = next((t for t in crudos if len(t) > 1 and t not in GENERICAS), "")
        return palabra == primera
    return True


def dominio(url):
    return re.sub(r"^https?://(www\.)?", "", (url or "").lower()).split("/")[0]


def fusionar(queda, va):
    """Pasa a `queda` lo que solo traía `va`."""
    for c in ("web", "tel", "wa", "direccion"):
        if not queda.get(c) and va.get(c):
            queda[c] = va[c]
            if c == "web":
                queda["auditado"] = False
                queda.setdefault("senales", {})["sin_web"] = False
    if va.get("emails"):
        queda["emails"] = sorted(set(queda.get("emails", [])) | set(va["emails"]))[:5]
    if va.get("redes"):
        queda["redes"] = {**va["redes"], **queda.get("redes", {})}
    for c in ("rating", "reviews"):
        if queda.get(c) is None and va.get(c) is not None:
            queda[c] = va[c]
    for c in ("subzona",):
        if not queda.get(c) and va.get(c):
            queda[c] = va[c]
    if va.get("auditado"):
        queda["auditado"] = True
        for c in ("senales", "gancho"):
            if c in va and c not in queda:
                queda[c] = va[c]
    fs = list(queda.get("fuentes") or [queda.get("fuente", "")])
    for f in va.get("fuentes") or [va.get("fuente", "")]:
        if f and f not in fs:
            fs.append(f)
    queda["fuentes"] = fs
    alt = list(queda.get("ids_alt") or [])
    for a in [va.get("id")] + list(va.get("ids_alt") or []):
        if a and a != queda.get("id") and a not in alt:
            alt.append(a)
    if alt:
        queda["ids_alt"] = alt


def candidatos(negocios):
    """Pares (a, b) que podrían ser el mismo negocio."""
    rejilla = {}
    for n in negocios:
        if n.get("lat") is None or n.get("aprox"):
            continue
        rejilla.setdefault((int(n["lat"] / 0.001), int(n["lng"] / 0.001)), []).append(n)
    vistos = set()
    for (cy, cx), grupo in rejilla.items():
        vecinos = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                vecinos += rejilla.get((cy + dy, cx + dx), [])
        for a in grupo:
            for b in vecinos:
                if a["id"] >= b["id"]:
                    continue
                par = (a["id"], b["id"])
                if par in vistos:
                    continue
                vistos.add(par)
                if abs(a["lat"] - b["lat"]) > 0.002 or abs(a["lng"] - b["lng"]) > 0.002:
                    continue
                if metros(a["lat"], a["lng"], b["lat"], b["lng"]) > 45:
                    continue
                if not (contiene(a["nombre"], b["nombre"]) or similitud(a["nombre"], b["nombre"]) >= 0.88):
                    continue
                ta, tb = a.get("tel") or "", b.get("tel") or ""
                if ta and tb and re.sub(r"\D", "", ta)[-9:] != re.sub(r"\D", "", tb)[-9:]:
                    continue
                da, db = dominio(a.get("web")), dominio(b.get("web"))
                if da and db and da != db:
                    continue
                yield a, b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zona")
    ap.add_argument("--pais")
    ap.add_argument("--aplicar", action="store_true", help="escribe los cambios (si no, solo informa)")
    ap.add_argument("--max", type=int, default=40, help="cuántos ejemplos imprimir")
    args = ap.parse_args()

    cfg = cargar_config()
    zonas = [k for k, z in cfg["zonas"].items()
             if (not args.zona or k == args.zona) and (not args.pais or z.get("pais", "CO") == args.pais)]
    for z in zonas:
        negocios = cargar_zona(z)
        if not negocios:
            continue
        por_id = {n["id"]: n for n in negocios}
        fuera = set()
        pares = []
        for a, b in candidatos(negocios):
            if a["id"] in fuera or b["id"] in fuera:
                continue
            # el registro de Google manda; si no hay, el de más datos
            if a.get("fuente") == "places" or (b.get("fuente") != "places" and
                                               len(a.get("emails") or []) >= len(b.get("emails") or [])):
                queda, va = a, b
            else:
                queda, va = b, a
            pares.append((queda["nombre"], va["nombre"]))
            fusionar(queda, va)
            fuera.add(va["id"])
        if args.aplicar and fuera:
            guardar_zona(z, [n for n in negocios if n["id"] not in fuera], cfg["zonas"][z].get("pais", "CO"))
        print(f"{z}: {len(pares)} duplicados {'fundidos' if args.aplicar else 'detectados'} · "
              f"{len(negocios)} → {len(negocios) - len(fuera)}")
        for q, v in pares[:args.max]:
            print(f"   · {q}  ⟵  {v}")


if __name__ == "__main__":
    main()
