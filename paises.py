#!/usr/bin/env python3
"""Países y zonas del radar: Colombia (zonas a mano en config.json), España (52
provincias) y Texas (las 12 regiones económicas del Comptroller).

Uso:
  python3 paises.py --sync-config   # escribe las zonas ES/TX en config.json y config.public.json

Colombia sigue definiéndose en config.json (subzonas para Google Places).
España y Texas se generan desde acá para que el pipeline y el mapa usen la misma fuente.
"""
import json, os, sys

BASE = os.path.dirname(os.path.abspath(__file__))

PAISES = {
    "CO": {"nombre": "Colombia", "idioma": "es", "prefijo": "57", "registro": "RUES"},
    "ES": {"nombre": "España", "idioma": "es", "prefijo": "34", "registro": "BORME"},
    "TX": {"nombre": "Texas (EE.UU.)", "idioma": "en", "prefijo": "1", "registro": "Texas Comptroller"},
}

# clave → (nombre, código ISO 3166-2 que usa OSM, título en el BORME, capital [lat, lng])
PROVINCIAS_ES = {
    "es-a-coruna":     ("A Coruña", "ES-C", "A CORUÑA", [43.3623, -8.4115]),
    "es-alava":        ("Álava", "ES-VI", "ARABA/ÁLAVA", [42.8467, -2.6716]),
    "es-albacete":     ("Albacete", "ES-AB", "ALBACETE", [38.9943, -1.8585]),
    "es-alicante":     ("Alicante", "ES-A", "ALICANTE/ALACANT", [38.3452, -0.4810]),
    "es-almeria":      ("Almería", "ES-AL", "ALMERÍA", [36.8340, -2.4637]),
    "es-asturias":     ("Asturias", "ES-O", "ASTURIAS", [43.3614, -5.8494]),
    "es-avila":        ("Ávila", "ES-AV", "ÁVILA", [40.6565, -4.6818]),
    "es-badajoz":      ("Badajoz", "ES-BA", "BADAJOZ", [38.8794, -6.9707]),
    "es-baleares":     ("Illes Balears", "ES-PM", "ILLES BALEARS", [39.5696, 2.6502]),
    "es-barcelona":    ("Barcelona", "ES-B", "BARCELONA", [41.3874, 2.1686]),
    "es-bizkaia":      ("Bizkaia", "ES-BI", "BIZKAIA", [43.2630, -2.9350]),
    "es-burgos":       ("Burgos", "ES-BU", "BURGOS", [42.3439, -3.6969]),
    "es-caceres":      ("Cáceres", "ES-CC", "CÁCERES", [39.4753, -6.3724]),
    "es-cadiz":        ("Cádiz", "ES-CA", "CÁDIZ", [36.5271, -6.2886]),
    "es-cantabria":    ("Cantabria", "ES-S", "CANTABRIA", [43.4623, -3.8100]),
    "es-castellon":    ("Castellón", "ES-CS", "CASTELLÓN/CASTELLÓ", [39.9864, -0.0513]),
    "es-ceuta":        ("Ceuta", "ES-CE", "CEUTA", [35.8894, -5.3213]),
    "es-ciudad-real":  ("Ciudad Real", "ES-CR", "CIUDAD REAL", [38.9848, -3.9274]),
    "es-cordoba":      ("Córdoba", "ES-CO", "CÓRDOBA", [37.8882, -4.7794]),
    "es-cuenca":       ("Cuenca", "ES-CU", "CUENCA", [40.0704, -2.1374]),
    "es-gipuzkoa":     ("Gipuzkoa", "ES-SS", "GIPUZKOA", [43.3183, -1.9812]),
    "es-girona":       ("Girona", "ES-GI", "GIRONA", [41.9794, 2.8214]),
    "es-granada":      ("Granada", "ES-GR", "GRANADA", [37.1773, -3.5986]),
    "es-guadalajara":  ("Guadalajara", "ES-GU", "GUADALAJARA", [40.6329, -3.1669]),
    "es-huelva":       ("Huelva", "ES-H", "HUELVA", [37.2614, -6.9447]),
    "es-huesca":       ("Huesca", "ES-HU", "HUESCA", [42.1401, -0.4089]),
    "es-jaen":         ("Jaén", "ES-J", "JAÉN", [37.7796, -3.7849]),
    "es-la-rioja":     ("La Rioja", "ES-LO", "LA RIOJA", [42.4627, -2.4450]),
    "es-las-palmas":   ("Las Palmas", "ES-GC", "LAS PALMAS", [28.1235, -15.4363]),
    "es-leon":         ("León", "ES-LE", "LEÓN", [42.5987, -5.5671]),
    "es-lleida":       ("Lleida", "ES-L", "LLEIDA", [41.6176, 0.6200]),
    "es-lugo":         ("Lugo", "ES-LU", "LUGO", [43.0097, -7.5568]),
    "es-madrid":       ("Madrid", "ES-M", "MADRID", [40.4168, -3.7038]),
    "es-malaga":       ("Málaga", "ES-MA", "MÁLAGA", [36.7213, -4.4214]),
    "es-melilla":      ("Melilla", "ES-ML", "MELILLA", [35.2923, -2.9381]),
    "es-murcia":       ("Murcia", "ES-MU", "MURCIA", [37.9922, -1.1307]),
    "es-navarra":      ("Navarra", "ES-NA", "NAVARRA", [42.8125, -1.6458]),
    "es-ourense":      ("Ourense", "ES-OR", "OURENSE", [42.3358, -7.8639]),
    "es-palencia":     ("Palencia", "ES-P", "PALENCIA", [42.0095, -4.5288]),
    "es-pontevedra":   ("Pontevedra", "ES-PO", "PONTEVEDRA", [42.2406, -8.7207]),  # centrado en Vigo
    "es-salamanca":    ("Salamanca", "ES-SA", "SALAMANCA", [40.9701, -5.6635]),
    "es-tenerife":     ("Santa Cruz de Tenerife", "ES-TF", "SANTA CRUZ DE TENERIFE", [28.4636, -16.2518]),
    "es-segovia":      ("Segovia", "ES-SG", "SEGOVIA", [40.9429, -4.1088]),
    "es-sevilla":      ("Sevilla", "ES-SE", "SEVILLA", [37.3891, -5.9845]),
    "es-soria":        ("Soria", "ES-SO", "SORIA", [41.7666, -2.4790]),
    "es-tarragona":    ("Tarragona", "ES-T", "TARRAGONA", [41.1189, 1.2445]),
    "es-teruel":       ("Teruel", "ES-TE", "TERUEL", [40.3456, -1.1065]),
    "es-toledo":       ("Toledo", "ES-TO", "TOLEDO", [39.8628, -4.0273]),
    "es-valencia":     ("Valencia", "ES-V", "VALENCIA/VALÈNCIA", [39.4699, -0.3763]),
    "es-valladolid":   ("Valladolid", "ES-VA", "VALLADOLID", [41.6523, -4.7245]),
    "es-zamora":       ("Zamora", "ES-ZA", "ZAMORA", [41.5034, -5.7467]),
    "es-zaragoza":     ("Zaragoza", "ES-Z", "ZARAGOZA", [41.6488, -0.8891]),
}

# Condados de Texas en el orden del Comptroller: el código de condado de sus
# datasets (taxpayer/outlet_county_code) es la posición 1-based en esta lista.
CONDADOS_TX = [
    "Anderson", "Andrews", "Angelina", "Aransas", "Archer", "Armstrong", "Atascosa", "Austin", "Bailey", "Bandera",
    "Bastrop", "Baylor", "Bee", "Bell", "Bexar", "Blanco", "Borden", "Bosque", "Bowie", "Brazoria",
    "Brazos", "Brewster", "Briscoe", "Brooks", "Brown", "Burleson", "Burnet", "Caldwell", "Calhoun", "Callahan",
    "Cameron", "Camp", "Carson", "Cass", "Castro", "Chambers", "Cherokee", "Childress", "Clay", "Cochran",
    "Coke", "Coleman", "Collin", "Collingsworth", "Colorado", "Comal", "Comanche", "Concho", "Cooke", "Coryell",
    "Cottle", "Crane", "Crockett", "Crosby", "Culberson", "Dallam", "Dallas", "Dawson", "Deaf Smith", "Delta",
    "Denton", "DeWitt", "Dickens", "Dimmit", "Donley", "Duval", "Eastland", "Ector", "Edwards", "Ellis",
    "El Paso", "Erath", "Falls", "Fannin", "Fayette", "Fisher", "Floyd", "Foard", "Fort Bend", "Franklin",
    "Freestone", "Frio", "Gaines", "Galveston", "Garza", "Gillespie", "Glasscock", "Goliad", "Gonzales", "Gray",
    "Grayson", "Gregg", "Grimes", "Guadalupe", "Hale", "Hall", "Hamilton", "Hansford", "Hardeman", "Hardin",
    "Harris", "Harrison", "Hartley", "Haskell", "Hays", "Hemphill", "Henderson", "Hidalgo", "Hill", "Hockley",
    "Hood", "Hopkins", "Houston", "Howard", "Hudspeth", "Hunt", "Hutchinson", "Irion", "Jack", "Jackson",
    "Jasper", "Jeff Davis", "Jefferson", "Jim Hogg", "Jim Wells", "Johnson", "Jones", "Karnes", "Kaufman", "Kendall",
    "Kenedy", "Kent", "Kerr", "Kimble", "King", "Kinney", "Kleberg", "Knox", "Lamar", "Lamb",
    "Lampasas", "La Salle", "Lavaca", "Lee", "Leon", "Liberty", "Limestone", "Lipscomb", "Live Oak", "Llano",
    "Loving", "Lubbock", "Lynn", "McCulloch", "McLennan", "McMullen", "Madison", "Marion", "Martin", "Mason",
    "Matagorda", "Maverick", "Medina", "Menard", "Midland", "Milam", "Mills", "Mitchell", "Montague", "Montgomery",
    "Moore", "Morris", "Motley", "Nacogdoches", "Navarro", "Newton", "Nolan", "Nueces", "Ochiltree", "Oldham",
    "Orange", "Palo Pinto", "Panola", "Parker", "Parmer", "Pecos", "Polk", "Potter", "Presidio", "Rains",
    "Randall", "Reagan", "Real", "Red River", "Reeves", "Refugio", "Roberts", "Robertson", "Rockwall", "Runnels",
    "Rusk", "Sabine", "San Augustine", "San Jacinto", "San Patricio", "San Saba", "Schleicher", "Scurry", "Shackelford", "Shelby",
    "Sherman", "Smith", "Somervell", "Starr", "Stephens", "Sterling", "Stonewall", "Sutton", "Swisher", "Tarrant",
    "Taylor", "Terrell", "Terry", "Throckmorton", "Titus", "Tom Green", "Travis", "Trinity", "Tyler", "Upshur",
    "Upton", "Uvalde", "Val Verde", "Van Zandt", "Victoria", "Walker", "Waller", "Ward", "Washington", "Webb",
    "Wharton", "Wheeler", "Wichita", "Wilbarger", "Willacy", "Williamson", "Wilson", "Winkler", "Wise", "Wood",
    "Yoakum", "Young", "Zapata", "Zavala",
]

# Regiones económicas del Texas Comptroller (comptroller.texas.gov/economy/economic-data/regions)
# clave → (nombre, ciudad ancla [lat, lng], zoom, condados)
REGIONES_TX = {
    "tx-gulf-coast": ("Gulf Coast · Houston", [29.7604, -95.3698], 9,
        ["Austin", "Brazoria", "Chambers", "Colorado", "Fort Bend", "Galveston", "Harris", "Liberty", "Matagorda",
         "Montgomery", "Walker", "Waller", "Wharton"]),
    "tx-metroplex": ("Metroplex · Dallas–Fort Worth", [32.8140, -96.9489], 9,
        ["Collin", "Cooke", "Dallas", "Denton", "Ellis", "Erath", "Fannin", "Grayson", "Hood", "Hunt", "Johnson",
         "Kaufman", "Navarro", "Palo Pinto", "Parker", "Rockwall", "Somervell", "Tarrant", "Wise"]),
    "tx-capital": ("Capital · Austin", [30.2672, -97.7431], 10,
        ["Bastrop", "Blanco", "Burnet", "Caldwell", "Fayette", "Hays", "Lee", "Llano", "Travis", "Williamson"]),
    "tx-alamo": ("Alamo · San Antonio", [29.4241, -98.4936], 10,
        ["Atascosa", "Bandera", "Bexar", "Calhoun", "Comal", "DeWitt", "Frio", "Gillespie", "Goliad", "Gonzales",
         "Guadalupe", "Jackson", "Karnes", "Kendall", "Kerr", "Lavaca", "Medina", "Victoria", "Wilson"]),
    "tx-south": ("South Texas · Corpus Christi / RGV", [27.0, -98.2], 7,
        ["Aransas", "Bee", "Brooks", "Cameron", "Dimmit", "Duval", "Edwards", "Hidalgo", "Jim Hogg", "Jim Wells",
         "Kenedy", "Kinney", "Kleberg", "La Salle", "Live Oak", "McMullen", "Maverick", "Nueces", "Real", "Refugio",
         "San Patricio", "Starr", "Uvalde", "Val Verde", "Webb", "Willacy", "Zapata", "Zavala"]),
    "tx-central": ("Central Texas · Waco / Killeen", [31.2, -97.0], 8,
        ["Bell", "Bosque", "Brazos", "Burleson", "Coryell", "Falls", "Freestone", "Grimes", "Hamilton", "Hill",
         "Lampasas", "Leon", "Limestone", "McLennan", "Madison", "Milam", "Mills", "Robertson", "San Saba", "Washington"]),
    "tx-upper-rio-grande": ("Upper Rio Grande · El Paso", [31.7619, -106.4850], 10,
        ["Brewster", "Culberson", "El Paso", "Hudspeth", "Jeff Davis", "Presidio"]),
    "tx-southeast": ("Southeast · Beaumont", [30.6, -94.4], 8,
        ["Angelina", "Hardin", "Houston", "Jasper", "Jefferson", "Nacogdoches", "Newton", "Orange", "Polk", "Sabine",
         "San Augustine", "San Jacinto", "Shelby", "Trinity", "Tyler"]),
    "tx-upper-east": ("Upper East · Tyler", [32.6, -94.9], 8,
        ["Anderson", "Bowie", "Camp", "Cass", "Cherokee", "Delta", "Franklin", "Gregg", "Harrison", "Henderson",
         "Hopkins", "Lamar", "Marion", "Morris", "Panola", "Rains", "Red River", "Rusk", "Smith", "Titus", "Upshur",
         "Van Zandt", "Wood"]),
    "tx-high-plains": ("High Plains · Lubbock / Amarillo", [34.4, -101.8], 7,
        ["Armstrong", "Bailey", "Briscoe", "Carson", "Castro", "Childress", "Cochran", "Collingsworth", "Crosby",
         "Dallam", "Deaf Smith", "Dickens", "Donley", "Floyd", "Garza", "Gray", "Hale", "Hall", "Hansford", "Hartley",
         "Hemphill", "Hockley", "Hutchinson", "King", "Lamb", "Lipscomb", "Lubbock", "Lynn", "Moore", "Motley",
         "Ochiltree", "Oldham", "Parmer", "Potter", "Randall", "Roberts", "Sherman", "Swisher", "Terry", "Wheeler",
         "Yoakum"]),
    "tx-northwest": ("Northwest · Abilene / Wichita Falls", [32.9, -99.3], 7,
        ["Archer", "Baylor", "Brown", "Callahan", "Clay", "Coleman", "Comanche", "Cottle", "Eastland", "Fisher",
         "Foard", "Hardeman", "Haskell", "Jack", "Jones", "Kent", "Knox", "Mitchell", "Montague", "Nolan", "Runnels",
         "Scurry", "Shackelford", "Stephens", "Stonewall", "Taylor", "Throckmorton", "Wichita", "Wilbarger", "Young"]),
    "tx-west": ("West Texas · Midland / Odessa", [31.6, -101.6], 7,
        ["Andrews", "Borden", "Coke", "Concho", "Crane", "Crockett", "Dawson", "Ector", "Gaines", "Glasscock",
         "Howard", "Irion", "Kimble", "Loving", "McCulloch", "Martin", "Mason", "Menard", "Midland", "Pecos",
         "Reagan", "Reeves", "Schleicher", "Sterling", "Sutton", "Terrell", "Tom Green", "Upton", "Ward", "Winkler"]),
}

# Ciudades donde se lanzan las búsquedas de Google Places (cada una × categoría × hasta 3 páginas).
# Provincias sin entrada usan solo su capital.
SUBZONAS = {
    "es-madrid": ["Centro, Madrid", "Salamanca, Madrid", "Chamberí, Madrid", "Chamartín, Madrid", "Retiro, Madrid",
                  "Alcobendas", "Pozuelo de Alarcón", "Getafe", "Alcalá de Henares", "Móstoles"],
    "es-barcelona": ["Eixample, Barcelona", "Gràcia, Barcelona", "Sarrià-Sant Gervasi, Barcelona", "Ciutat Vella, Barcelona",
                     "Sant Martí, Barcelona", "L'Hospitalet de Llobregat", "Badalona", "Sabadell", "Terrassa"],
    "es-valencia": ["Valencia", "Gandia", "Torrent"],
    "es-sevilla": ["Sevilla", "Dos Hermanas"],
    "es-malaga": ["Málaga", "Marbella", "Fuengirola", "Torremolinos", "Estepona"],
    "es-alicante": ["Alicante", "Elche", "Benidorm", "Torrevieja"],
    "es-murcia": ["Murcia", "Cartagena", "Lorca"],
    "es-baleares": ["Palma", "Ibiza", "Manacor"],
    "es-las-palmas": ["Las Palmas de Gran Canaria", "Arrecife", "Puerto del Rosario"],
    "es-tenerife": ["Santa Cruz de Tenerife", "Adeje", "La Laguna"],
    "es-bizkaia": ["Bilbao", "Getxo", "Barakaldo"],
    "es-asturias": ["Oviedo", "Gijón", "Avilés"],
    "es-a-coruna": ["A Coruña", "Santiago de Compostela", "Ferrol"],
    "es-pontevedra": ["Vigo", "Pontevedra"],
    "es-cadiz": ["Cádiz", "Jerez de la Frontera", "Algeciras"],
    "es-zaragoza": ["Zaragoza"],
    "es-granada": ["Granada", "Motril"],
    "es-girona": ["Girona", "Lloret de Mar", "Figueres"],
    "es-tarragona": ["Tarragona", "Reus", "Salou"],
    "es-castellon": ["Castellón de la Plana", "Vila-real", "Benicàssim"],
    "tx-gulf-coast": ["Downtown Houston", "Midtown Houston", "Galleria, Houston", "The Heights, Houston", "Katy",
                      "Sugar Land", "The Woodlands", "Pasadena, TX", "Pearland", "Galveston"],
    "tx-metroplex": ["Downtown Dallas", "Uptown Dallas", "Fort Worth", "Plano", "Arlington, TX", "Irving",
                     "Frisco", "McKinney", "Denton", "Garland"],
    "tx-capital": ["Downtown Austin", "South Congress, Austin", "North Austin", "Round Rock", "Cedar Park", "San Marcos"],
    "tx-alamo": ["Downtown San Antonio", "Stone Oak, San Antonio", "Alamo Heights, San Antonio", "New Braunfels", "Victoria, TX"],
    "tx-south": ["Corpus Christi", "McAllen", "Brownsville", "Laredo", "Harlingen", "Edinburg"],
    "tx-central": ["Waco", "Killeen", "Temple", "College Station", "Bryan"],
    "tx-upper-rio-grande": ["El Paso", "West El Paso"],
    "tx-southeast": ["Beaumont", "Port Arthur", "Lufkin", "Nacogdoches"],
    "tx-upper-east": ["Tyler", "Longview", "Texarkana, TX"],
    "tx-high-plains": ["Lubbock", "Amarillo"],
    "tx-northwest": ["Abilene", "Wichita Falls"],
    "tx-west": ["Midland", "Odessa", "San Angelo"],
}

def subzonas(zona, z):
    """Textos de búsqueda de Google para una zona (Colombia los define en config.json)."""
    if z.get("subzonas"):
        return z["subzonas"]
    pais = z.get("pais", "CO")
    sufijo = ", España" if pais == "ES" else ", Texas" if pais == "TX" else ""
    lista = SUBZONAS.get(zona) or [z["nombre"]]
    return [s + sufijo for s in lista]

REGION_DE_CONDADO = {c: z for z, (_, _, _, cs) in REGIONES_TX.items() for c in cs}
assert len(REGION_DE_CONDADO) == len(CONDADOS_TX) == 254

def condado_por_codigo(codigo):
    """'101' → 'Harris' (códigos del Comptroller)."""
    try:
        i = int(codigo)
    except (TypeError, ValueError):
        return None
    return CONDADOS_TX[i - 1] if 1 <= i <= len(CONDADOS_TX) else None

def zona_por_provincia_borme(titulo):
    t = (titulo or "").strip().upper()
    return next((k for k, v in PROVINCIAS_ES.items() if v[2] == t), None)

def zonas_generadas():
    z = {}
    for k, (nombre, iso, _, centro) in PROVINCIAS_ES.items():
        z[k] = {"nombre": nombre, "pais": "ES", "centro": centro, "zoom": 10, "iso": iso}
    for k, (nombre, centro, zoom, _) in REGIONES_TX.items():
        z[k] = {"nombre": nombre, "pais": "TX", "centro": centro, "zoom": zoom}
    return z

def pais_de_zona(cfg, zona):
    return (cfg.get("zonas", {}).get(zona) or {}).get("pais", "CO")

def sync_config():
    nuevas = zonas_generadas()
    for nombre in ("config.json", "config.public.json"):
        ruta = os.path.join(BASE, nombre)
        if not os.path.exists(ruta):
            continue
        cfg = json.load(open(ruta))
        zonas = {}
        for k, z in cfg.get("zonas", {}).items():
            if k in nuevas:
                continue
            z.setdefault("pais", "CO")
            zonas[k] = z
        zonas.update(nuevas)
        cfg["zonas"] = zonas
        cfg["paises"] = PAISES
        from categorias import CATEGORIAS, etiqueta
        cfg["etiquetas"] = {p: {c: etiqueta(c, p) for c in CATEGORIAS if etiqueta(c, p) != c} for p in ("ES", "TX")}
        json.dump(cfg, open(ruta, "w"), ensure_ascii=False, indent=2)
        print(f"{nombre}: {len(zonas)} zonas ({sum(1 for z in zonas.values() if z['pais']=='CO')} CO · "
              f"{len(PROVINCIAS_ES)} ES · {len(REGIONES_TX)} TX)")

if __name__ == "__main__":
    if "--sync-config" in sys.argv:
        sync_config()
    else:
        print(__doc__)
