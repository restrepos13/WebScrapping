"""Catálogo único de categorías del radar.

La clave canónica es la etiqueta en español que ya usan los datos de Colombia
("clínica estética", "barbería"…): así los rubros y filtros del mapa funcionan
igual en los tres países. Cada categoría sabe cómo se busca en cada fuente:

  q      → texto de búsqueda en Google Places por país (scan.py)
  naics  → códigos NAICS del Texas Comptroller (texas.py)
  cnae   → códigos CNAE del objeto social en constituciones del BORME (borme.py)
  kw     → palabras del objeto social (BORME) cuando no viene el CNAE
"""
import re

CATEGORIAS = {
    "clínica estética": {
        "en": "med spa / aesthetic clinic", "q": {"ES": "clínica de medicina estética", "TX": "med spa"},
        "naics": [], "cnae": [], "kw": ["medicina estetica", "medicina estética"]},
    "clínica odontológica": {
        "en": "dental clinic", "q": {"ES": "clínica dental", "TX": "dental clinic"},
        "naics": ["621210"], "cnae": ["86.23"], "kw": ["odontolog", "clinica dental", "clínica dental"]},
    "dermatólogo": {
        "en": "dermatologist", "q": {"ES": "dermatólogo", "TX": "dermatologist"},
        "naics": [], "cnae": [], "kw": ["dermatolog"]},
    "cirujano plástico": {
        "en": "plastic surgeon", "q": {"ES": "cirujano plástico", "TX": "plastic surgeon"},
        "naics": [], "cnae": [], "kw": ["cirugia plastica", "cirugía plástica"]},
    "spa": {
        "en": "spa", "q": {"ES": "spa", "TX": "day spa"},
        "naics": [], "cnae": ["96.04", "96.23"], "kw": [" spa ", "balneario"]},
    "veterinaria": {
        "en": "veterinary clinic", "q": {"ES": "clínica veterinaria", "TX": "veterinary clinic"},
        "naics": ["541940"], "cnae": ["75.00", "75.0"], "kw": ["veterinari"]},
    "barbería": {
        "en": "barbershop", "q": {"ES": "barbería", "TX": "barbershop"},
        "naics": ["812111"], "cnae": [], "kw": ["barberia", "barbería"]},
    "salón de belleza": {
        "en": "hair salon", "q": {"ES": "peluquería", "TX": "hair salon"},
        "naics": ["812112"], "cnae": ["96.02", "96.21"], "kw": ["peluquer"]},
    "gimnasio": {
        "en": "gym", "q": {"ES": "gimnasio", "TX": "gym"},
        "naics": ["713940"], "cnae": ["93.13"], "kw": ["gimnasio", "fitness", "entrenamiento personal"]},
    "inmobiliaria": {
        "en": "real estate agency", "q": {"ES": "inmobiliaria", "TX": "real estate agency"},
        "naics": ["531210"], "cnae": ["68.31"], "kw": ["intermediacion inmobiliaria", "intermediación inmobiliaria", "agencia inmobiliaria"]},
    "concesionario de motos": {
        "en": "motorcycle dealer", "q": {"ES": "concesionario de motos", "TX": "motorcycle dealer"},
        "naics": ["441228", "441227"], "cnae": ["45.40"], "kw": ["motocicletas"]},
    "concesionario de carros": {
        "en": "car dealer", "q": {"ES": "concesionario de coches", "TX": "car dealership"},
        "naics": ["441110", "441120"], "cnae": ["45.11", "46.71"], "kw": ["venta de vehiculos", "venta de vehículos", "concesionario"]},
    "hotel boutique": {
        "en": "hotel", "q": {"ES": "hotel boutique", "TX": "boutique hotel"},
        "naics": ["721110"], "cnae": ["55.10"], "kw": ["hotel"]},
    "hostal": {
        "en": "hostel / B&B", "q": {"ES": "hostal", "TX": "bed and breakfast"},
        "naics": ["721191"], "cnae": ["55.20"], "kw": ["hostal", "albergue", "alojamiento turistico", "alojamiento turístico"]},
    "academia de idiomas": {
        "en": "language school", "q": {"ES": "academia de idiomas", "TX": "language school"},
        "naics": ["611630"], "cnae": [], "kw": ["idiomas", "ensenanza de lenguas", "enseñanza de lenguas"]},
    "escuela de conducción": {
        "en": "driving school", "q": {"ES": "autoescuela", "TX": "driving school"},
        "naics": ["611692"], "cnae": ["85.53"], "kw": ["autoescuela", "escuela de conduc"]},
    "agencia de viajes": {
        "en": "travel agency", "q": {"ES": "agencia de viajes", "TX": "travel agency"},
        "naics": ["561510"], "cnae": ["79.11", "79.12"], "kw": ["agencia de viajes"]},
    "óptica": {
        "en": "optician", "q": {"ES": "óptica", "TX": "optometrist"},
        "naics": ["446130", "456130"], "cnae": [], "kw": ["optica", "óptica"]},
    "centro de estética": {
        "en": "beauty salon", "q": {"ES": "centro de estética", "TX": "beauty salon"},
        "naics": ["812113", "812199"], "cnae": ["96.22"], "kw": ["estetica", "estética", "depilacion", "depilación", "manicura"]},
    "estudio webcam": {
        "en": "webcam studio", "q": {"ES": "estudio webcam"},
        "naics": [], "cnae": [], "kw": []},
    "agencia de modelos": {
        "en": "model agency", "q": {"ES": "agencia de modelos"},
        "naics": [], "cnae": [], "kw": []},
    "restaurante": {
        "en": "restaurant", "q": {"ES": "restaurante", "TX": "restaurant"},
        "naics": ["722511"], "cnae": ["56.10", "56.11"], "kw": ["restaurante"]},
    # --- verticales nuevos (por ahora solo Colombia): alto volumen de consultas
    #     repetitivas por WhatsApp, venta por cotización y/o clientes recurrentes
    "energía solar": {
        "en": "solar installer", "q": {"CO": ["paneles solares", "energía solar"]}, "solo": ["CO"],
        "naics": [], "cnae": [], "kw": [],
        "pitch": "cotización automática: el bot pide la factura de luz, calcula el ahorro y agenda la visita técnica"},
    "muebles y cocinas": {
        "en": "furniture & kitchens", "q": {"CO": ["fábrica de muebles", "cocinas integrales"]}, "solo": ["CO"],
        "naics": [], "cnae": [], "kw": [],
        "pitch": "catálogo y cotización por WhatsApp: el bot recibe fotos y medidas y agenda la toma de medidas"},
    "CDA y talleres": {
        "en": "vehicle inspection & repair", "q": {"CO": ["centro de diagnóstico automotor", "taller automotriz"]}, "solo": ["CO"],
        "naics": [], "cnae": [], "kw": [],
        "pitch": "agendamiento de revisión y recordatorio automático del vencimiento de la técnico-mecánica"},
    "ferretería y materiales": {
        "en": "hardware & building supplies", "q": {"CO": ["ferretería", "depósito de materiales de construcción"]}, "solo": ["CO"],
        "naics": [], "cnae": [], "kw": [],
        "pitch": "pedidos por WhatsApp con catálogo, precio y stock al instante, y domicilio"},
    "agencia de seguros": {
        "en": "insurance agency", "q": {"CO": ["agencia de seguros"]}, "solo": ["CO"],
        "naics": [], "cnae": [], "kw": [],
        "pitch": "cotizador de SOAT y pólizas 24/7 y recordatorios de renovación"},
    "estudio de arquitectura": {
        "en": "architecture firm", "q": {"ES": "estudio de arquitectura", "TX": "architecture firm"},
        "naics": ["541310"], "cnae": ["71.11"], "kw": ["arquitectura"]},
}

NAICS_A_CAT = {c: k for k, v in CATEGORIAS.items() for c in v["naics"]}

def etiqueta(cat, pais):
    """Nombre a mostrar: en Texas en inglés, en España el término local."""
    v = CATEGORIAS.get(cat, {})
    if pais == "TX":
        return v.get("en", cat)
    if pais == "ES":
        return v.get("q", {}).get("ES", cat)
    return cat

def consultas_google(pais, base_co):
    """Pares (categoría canónica, texto de búsqueda) para scan.py."""
    pares = [(c, c) for c in base_co] if pais == "CO" else []
    for k, v in CATEGORIAS.items():
        q = v.get("q", {}).get(pais)
        if q and k not in base_co:
            pares += [(k, t) for t in (q if isinstance(q, list) else [q])]
    return pares

# ---------------- OpenStreetMap ----------------
# Filtros que se piden a Overpass (unión). La clasificación fina se hace en Python.
OSM_FILTROS = [
    '["amenity"~"^(dentist|veterinary|restaurant|language_school|driving_school|clinic|doctors|spa)$"]',
    '["shop"~"^(hairdresser|beauty|massage|optician|car|motorcycle|travel_agency|estate_agent)$"]',
    '["leisure"~"^(fitness_centre|spa)$"]',
    '["office"~"^(estate_agent|travel_agent|architect)$"]',
    '["tourism"~"^(hotel|hostel|guest_house)$"]',
    '["healthcare"~"^(dentist|clinic|doctor)$"]',
    '["shop"~"^(furniture|kitchen|car_repair|hardware|doityourself|trade|energy|solar)$"]',
    '["craft"~"^(carpenter|electrician|photovoltaic|solar)$"]',
    '["office"="insurance"]',
    '["amenity"="vehicle_inspection"]',
]

_RE_BARBER = re.compile(r"barber|barbería|barberia|barbershop", re.I)
_RE_ESTETICA = re.compile(r"est[eé]tic|aesthetic|med ?spa|botox|l[aá]ser|medicina est", re.I)
_RE_SPA = re.compile(r"\bspa\b|balneario|wellness", re.I)

def clasificar_osm(t, pais="CO"):
    """tags de OSM → categoría canónica, o None si no es un prospecto."""
    cat = _clasificar_osm(t)
    if cat and pais not in CATEGORIAS.get(cat, {}).get("solo", [pais]):
        return None
    return cat

def _clasificar_osm(t):
    if t.get("brand:wikidata") or t.get("brand:wikipedia"):
        return None  # cadenas/franquicias: no deciden localmente, mal prospecto
    nombre = t.get("name", "")
    esp = t.get("healthcare:speciality", "")
    amen, shop, hc = t.get("amenity", ""), t.get("shop", ""), t.get("healthcare", "")
    if "plastic_surgery" in esp:
        return "cirujano plástico"
    if "dermatology" in esp:
        return "dermatólogo"
    if amen == "dentist" or hc == "dentist":
        return "clínica odontológica"
    if amen in ("clinic", "doctors") or hc in ("clinic", "doctor"):
        if re.search(r"cosmetic|aesthetic", esp) or _RE_ESTETICA.search(nombre):
            return "clínica estética"
        return None  # clínicas generales: fuera del foco
    if amen == "veterinary":
        return "veterinaria"
    if shop == "hairdresser":
        if t.get("hairdresser") == "barber" or _RE_BARBER.search(nombre):
            return "barbería"
        return "salón de belleza"
    if shop == "beauty":
        if t.get("beauty") == "spa" or _RE_SPA.search(nombre):
            return "spa"
        return "centro de estética"
    if shop == "massage" or amen == "spa" or t.get("leisure") == "spa":
        return "spa"
    if t.get("leisure") == "fitness_centre":
        return "gimnasio"
    if t.get("office") == "estate_agent" or shop == "estate_agent":
        return "inmobiliaria"
    if shop == "motorcycle":
        return "concesionario de motos"
    if shop == "car":
        return "concesionario de carros"
    tur = t.get("tourism", "")
    if tur == "hotel":
        return "hotel boutique"
    if tur in ("hostel", "guest_house"):
        return "hostal"
    if amen == "language_school":
        return "academia de idiomas"
    if amen == "driving_school":
        return "escuela de conducción"
    if shop == "travel_agency" or t.get("office") == "travel_agent":
        return "agencia de viajes"
    if shop == "optician":
        return "óptica"
    if amen == "restaurant":
        return "restaurante"
    if t.get("office") == "architect":
        return "estudio de arquitectura"
    craft = t.get("craft", "")
    if shop in ("solar", "energy") or craft in ("photovoltaic", "solar") or \
            ((shop or craft or t.get("office")) and re.search(r"solar|fotovolt", nombre, re.I)):
        return "energía solar"
    if shop in ("furniture", "kitchen") or craft == "carpenter":
        return "muebles y cocinas"
    if amen == "vehicle_inspection" or shop == "car_repair":
        return "CDA y talleres"
    if shop in ("hardware", "doityourself", "trade"):
        return "ferretería y materiales"
    if t.get("office") == "insurance":
        return "agencia de seguros"
    return None

# ---------------- BORME ----------------
def clasificar_objeto(cnae, objeto):
    """CNAE + objeto social de una constitución → categoría canónica o None."""
    if cnae:
        for k, v in CATEGORIAS.items():
            if any(cnae == c or cnae.startswith(c + ".") for c in v["cnae"]):
                # la peluquería/estética comparten CNAE 96.02 en la versión 2009
                if k == "salón de belleza" and re.search(r"est[eé]tica|depila|manicura", objeto or "", re.I) \
                        and not re.search(r"peluquer", objeto or "", re.I):
                    return "centro de estética"
                return k
    o = " " + (objeto or "").lower() + " "
    for k, v in CATEGORIAS.items():
        if any(w in o for w in v["kw"]):
            return k
    return None
