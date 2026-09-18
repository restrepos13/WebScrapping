/* Llave de acceso: se toma de ?key= una vez, queda en localStorage y se
   propaga automáticamente en los fetch relativos (config/data) — necesario
   cuando el front (Vercel) llama al back (Render) a través del proxy. */
(function(){
  try{
    const u=new URL(location.href), k=u.searchParams.get("key");
    if(k)localStorage.setItem("radar-key",k);
  }catch(e){}
  const clave=()=>{try{return localStorage.getItem("radar-key")||""}catch(e){return ""}};
  const _f=window.fetch.bind(window);
  window.fetch=(input,init)=>{
    try{
      const url=typeof input==="string"?input:input.url;
      if(clave()&&url&&!/^https?:/i.test(url)){
        const sep=url.includes("?")?"&":"?";
        input=url+sep+"key="+encodeURIComponent(clave());
      }
    }catch(e){}
    return _f(input,init);
  };
})();

/* RadarSync — estados compartidos vía Supabase (REST/PostgREST).
   Sin supabase_url/anon_key en config: modo local silencioso (localStorage, como siempre).
   Con ellos: pull inicial (remoto gana), migración automática de lo local que
   falte en la base, write-through en cada cambio y re-pull al volver el foco. */
window.RadarSync = (function () {
  "use strict";
  const TABLA = "radar_estados";
  let URL = null, KEY = null;

  const h = (extra) => Object.assign({
    "apikey": KEY,
    "Authorization": "Bearer " + KEY,
    "Content-Type": "application/json",
  }, extra || {});

  async function pull(app) {
    const r = await fetch(`${URL}/rest/v1/${TABLA}?select=id,data&app=eq.${encodeURIComponent(app)}&limit=20000`,
      { headers: h() });
    if (!r.ok) throw new Error("pull " + r.status);
    const filas = await r.json();
    const out = {};
    filas.forEach(f => out[f.id] = f.data);
    return out;
  }

  async function upsert(app, entradas) { // entradas: [{id, data}]
    if (!entradas.length) return;
    for (let i = 0; i < entradas.length; i += 200) {
      const lote = entradas.slice(i, i + 200).map(e => ({ app, id: e.id, data: e.data }));
      const r = await fetch(`${URL}/rest/v1/${TABLA}?on_conflict=app,id`, {
        method: "POST",
        headers: h({ "Prefer": "resolution=merge-duplicates,return=minimal" }),
        body: JSON.stringify(lote),
      });
      if (!r.ok) throw new Error("upsert " + r.status);
    }
  }

  /* init(cfg, app, localMap, aplicar):
       aplicar(mapaFusionado) se llama tras el pull inicial y en cada re-pull.
       Devuelve {online, save(id,data), pull()} — o {online:false} sin config. */
  async function init(cfg, app, localMap, aplicar) {
    URL = (cfg && cfg.supabase_url || "").replace(/\/$/, "");
    KEY = cfg && cfg.supabase_anon_key || "";
    if (!URL || !KEY) return { online: false };
    let remoto;
    try { remoto = await pull(app); }
    catch (e) { console.warn("RadarSync sin conexión:", e); return { online: false }; }

    // migración: lo marcado localmente que la base aún no tiene, se sube
    const faltan = Object.keys(localMap || {})
      .filter(id => localMap[id] && !(id in remoto))
      .map(id => ({ id, data: localMap[id] }));
    try { await upsert(app, faltan); } catch (e) { console.warn("migración parcial:", e); }
    faltan.forEach(f => remoto[f.id] = f.data);

    aplicar(Object.assign({}, localMap, remoto)); // remoto gana sobre local

    const api = {
      online: true,
      save: (id, data) => upsert(app, [{ id, data }]),
      saveMany: (entradas) => upsert(app, entradas),
      pull: async () => { try { aplicar(await pull(app)); } catch (e) { } },
    };
    // dos personas: refrescar al volver a la pestaña y cada 90s
    window.addEventListener("focus", api.pull);
    setInterval(api.pull, 90000);
    return api;
  }

  return { init };
})();
