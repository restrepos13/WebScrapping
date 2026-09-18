# Radar Nocturno — deploy en Render (plan free)

## Arquitectura para el free tier
- **Render solo SIRVE** (server.py + Flask): datos cacheados en memoria, gzip, ETag.
  Con 0.1 CPU y 512MB sobra.
- **El pipeline corre LOCAL** (scan.py → audit.py → enrich_empresas.py). El disco de
  Render es efímero: cualquier cosa escrita allá se borra al dormirse. Los datos
  viajan dentro del repo (`data/negocios.json`).
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
3. En el dashboard del servicio → Environment → poner valor a **RADAR_TOKEN**
   (cualquier clave tuya, ej. `radar2026x`). Sin esa variable el sitio queda público.
4. Listo: `https://radar-nocturno.onrender.com/mapa.html?key=TU_TOKEN`
   (la key queda en cookie 90 días; después entrás sin ella).

## Actualizar datos (cada vez que barras/audites)
```
python3 scan.py --zona medellin   # o bucaramanga
python3 audit.py
git add data/ && git commit -m "datos $(date +%F)" && git push
```
Render redespliega solo con el push (~1 min).

## Evitar el sleep de 15 min (opcional)
El free tier duerme el servicio tras 15 min sin tráfico (despertar tarda ~50s).
Si molesta: crear un monitor gratuito en cron-job.org o UptimeRobot que haga GET a
`https://<tu-servicio>.onrender.com/healthz` cada 10 minutos. Un solo servicio
24/7 cabe en las 750 horas/mes del plan.

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
