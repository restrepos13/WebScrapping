# Radar Nocturno — deploy en Render (plan free)

## Arquitectura para el free tier
- **Render solo SIRVE** (server.py + Flask): datos cacheados en memoria, gzip, ETag.
  Con 0.1 CPU y 512MB sobra.
- **El pipeline corre LOCAL** (scan.py → audit.py → enrich_empresas.py). El disco de
  Render es efímero: cualquier cosa escrita allá se borra al dormirse. Los datos
  viajan dentro del repo (`data/zonas/*.json`, un archivo por zona).
- Los estados/notas del mapa y del tracker viven en el navegador de quien lo usa
  (localStorage) — no dependen del servidor.

## Deploy (una vez)
1. Crear repo Git en esta carpeta y subirlo a GitHub (privado):
   ```
   git init && git add . && git commit -m "radar nocturno"
   ```
   `config.json` (con la API key), `.venv/` y los PDFs están en `.gitignore` — no suben.
2. En render.com → New → **Blueprint** → conectar el repo. Render lee `render.yaml`
   y crea el servicio en plan free automáticamente.
3. En el dashboard del servicio → Environment: el acceso ya viene cerrado con el
   correo del propietario y la contraseña por defecto. Para cambiarlos, agregá
   `RADAR_USER` y `RADAR_PASS_HASH` (el hash se genera con `python3 server.py --hash`).
4. Listo: `https://radar-nocturno.onrender.com/` pide correo y contraseña.
   La sesión dura 30 días.

## Acceso privado (login + registro de intentos)
- **Sin registro.** Solo entra el correo de `RADAR_USER` (por defecto
  `restrepos591@gmail.com`) con la contraseña cuyo hash vive en `RADAR_PASS_HASH`
  (o en el valor por defecto de `server.py`). La contraseña nunca se guarda ni viaja.
- **Todo cerrado.** `/`, las páginas, `/config.json` y `/data/*` responden 401 o
  redirigen a `/login` sin sesión. Solo quedan libres `/login`, `/api/*`,
  `/healthz` y los JS sin datos.
- **Registro de intentos.** Cada entrada (buena o rechazada) guarda hora, correo,
  IP, ciudad/país, operador, dispositivo y ruta. Se ve en `/accesos` (también
  protegido) y queda en Supabase en `radar_estados` con `app='accesos'`, así que
  sobrevive a los reinicios de Render. Sin Supabase configurado queda solo en
  memoria y en los logs de Render.
- **Freno a la fuerza bruta:** 10 fallos por IP en 10 minutos → 429.
- **Cambiar la contraseña:**
  ```
  python3 server.py --hash          # pide la nueva y devuelve el hash
  ```
  y pegar el resultado en `RADAR_PASS_HASH` (Render → Environment). Sin eso, la
  forma rápida es editar `CLAVE_HASH` en `server.py`. Al cambiarla, caducan las
  sesiones abiertas.
- **Cerrar sesión:** link "salir" en el pie del inicio o en `/accesos`.
- **Sin SEO:** `robots.txt` con `Disallow: /`, `X-Robots-Tag: noindex` en Render y
  Vercel, y `noindex` en el HTML. No hay sitemap ni enlaces externos.
- **Archivos fuente fuera de Vercel:** `vercel.json` redirige `.py`, `.sh`, `.sql`,
  `.md`, `.pdf` y `requirements.txt` a `/` (el repo es privado, pero el front no
  los sirve).

## Actualizar datos (cada vez que barras/audites)
Los datos viven en `data/zonas/<zona>.json` (una zona = un archivo; el mapa baja
solo la que mira) + `data/zonas/index.json`. `data/registros/` son índices crudos
locales (BORME, geocodificación) y no se suben.

| País | Fuentes | Comando |
|---|---|---|
| Colombia | Google Places (principal) · OSM · RUES | `python3 scan.py --zona medellin` · `python3 osm.py --pais CO` |
| España | Google Places (principal) · OSM · BORME · OpenMercantil | `./barrido_nocturno.sh ES` (de noche: horas) · `python3 scan.py --zona es-madrid` |
| Texas | Google Places (principal) · OSM · Comptroller · TBAE · Census | `python3 texas.py` · `python3 osm.py --pais TX` · `./barrido_texas.sh` |
| Florida (Miami) | Google Places (principal) · OSM | `python3 scan.py --zona fl-miami` · `python3 osm.py --zona fl-miami` |

Después de cualquier barrido:
```
python3 enrich_empresas.py --pais CO   # registros oficiales (RUES / BORME / Comptroller)
python3 audit.py --pais CO             # señales de la web + gancho
git add data/zonas && git commit -m "datos $(date +%F)" && git push
```
- `scan.py` (Google) muestra el costo estimado y pide confirmar; `--max-consultas`
  (default 900 ≈ cupo gratis mensual) es un tope duro.
- Fuentes de pago (Registradores, Texas SOS, Foursquare) no se usan.
- Zonas de España/Texas: `python3 paises.py --sync-config` las regenera en ambos config.
- Verticales nuevos (solo Colombia): energía solar, muebles y cocinas, CDA y talleres,
  ferretería y materiales, agencias de seguros (`categorias.py`).

## Evitar el sleep de 15 min (opcional)
El free tier duerme el servicio tras 15 min sin tráfico (despertar tarda ~50s).
Si molesta: crear un monitor gratuito en cron-job.org o UptimeRobot que haga GET a
`https://<tu-servicio>.onrender.com/healthz` cada 10 minutos. Un solo servicio
24/7 cabe en las 750 horas/mes del plan.

## Front en Vercel (opcional, carga instantánea)
1. vercel.com → Add New → Project → importar `restrepos13/WebScrapping`
   (Framework Preset: **Other**; sin build command; Output: raíz). Deploy.
2. `vercel.json` ya trae el proxy: las páginas salen del CDN de Vercel y
   `/data/*`, `/config.json`, `/api/*`, `/login`, `/accesos` y `/healthz` se
   reenvían al back de Render.
3. Entrar con el correo y la contraseña en la pantalla de acceso; la sesión
   queda guardada 30 días en ese navegador.
   (El primer pedido del día puede tardar ~50s: es Render despertando.)

## Estados compartidos entre personas (Supabase)
1. Crear cuenta/proyecto gratis en supabase.com (region São Paulo es la más cercana).
2. SQL Editor → pegar el contenido de `supabase.sql` → Run.
3. Project Settings → API → copiar **Project URL** y **anon public key**.
4. Pegarlos en `config.json` (local) **y** `config.public.json` (para Render) en los
   campos `supabase_url` y `supabase_anon_key`. Commit + push.
5. Al abrir el mapa o el tracker: lo que ya estaba marcado en ese navegador se
   **migra solo** a la base, y desde entonces ambas personas ven lo mismo
   (se refresca al volver a la pestaña y cada 90 segundos).

Sin esos campos, todo sigue funcionando en modo local (localStorage) como antes.

## Local
```
.venv/bin/python server.py          # backend real en http://localhost:8765
# o el estático de siempre:
python3 -m http.server 8765 --bind 127.0.0.1
```
