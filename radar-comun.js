/* Lógica compartida entre mapa.html y tracker-prospeccion.html para los negocios
   del radar: score de oportunidad, mensajes (1er contacto y toques 2/3) y
   cadencia de seguimiento. Una sola fuente → el mapa y el tracker nunca difieren. */
window.RadarComun = (function () {
  "use strict";
  const ESTADOS = {pend:"Sin contactar",t1:"Toque 1",t2:"Toque 2",t3:"Toque 3",resp:"Respondió",demo:"Demo",neg:"Negociando",cli:"Cliente",desc:"Descartado"};
  const NEXT = {pend:"t1", t1:"t2", t2:"t3"};
  const KEY_EST = "radar-estados-v1", KEY_MARCA = "radar-marca";

  function score(n) {
    const s = n.senales || {}; let sc = 0;
    if (s.sin_web) sc += 30; if (s.web_rota) sc += 25;
    if (s.sin_chatbot) sc += 15; if (s.sin_agendador) sc += 10; if (s.sin_ingles || s.sin_espanol) sc += 8;
    if (n.nuevo) sc += 12;
    if (s.tiene_wa || n.wa) sc += 7;
    sc += Math.min(n.reviews || 0, 200) / 200 * 15;
    if ((n.rating || 0) >= 4.5) sc += 5;
    if (n.registro && n.registro.estado === "ACTIVA") sc += 6;
    if (n.registro && n.registro.ingresos) sc += 10;
    return Math.min(99, Math.round(sc));
  }

  function marcaGuardada() {
    try { return (localStorage.getItem(KEY_MARCA) || "").trim(); } catch (e) { return ""; }
  }

  function mensaje(n, marca) {
    marca = marca || marcaGuardada() || "[MARCA]";
    const s = n.senales || {};
    const gancho = n.gancho ? n.gancho.replace(/\s*Pitch:.*$/, "").trim() : "";
    if (n.pais === "TX") {
      const extras = [];
      if (s.sin_agendador) extras.push("online booking");
      if (s.sin_espanol) extras.push("answers in English and Spanish");
      return `Hi, quick note about ${n.nombre}: ${gancho || "I noticed customer inquiries are handled by hand."} We're ${marca}, a software team that automates customer messaging with AI — instant replies 24/7${extras.length ? ", " + extras.join(" and ") : ""} — as a monthly subscription with flexible terms. Could you pass this to the owner? I can show it working in 10 minutes.`;
    }
    const extras = [];
    if (s.sin_agendador) extras.push("agendamiento automático");
    if (s.sin_ingles) extras.push("respuesta en español e inglés");
    const quien = n.pais === "ES" ? "un equipo de desarrollo" : "desarrolladores colombianos";
    const trato = n.pais === "ES" ? "¿Me pasáis con la persona responsable o le reenviáis este mensaje?" : "¿Me comparte el contacto de la persona dueña o le reenvía este mensaje?";
    return `Hola, les escribo por algo puntual de ${n.nombre}: ${gancho || "vi que la atención por WhatsApp es manual"} Somos ${marca}, ${quien}: automatizamos la atención por WhatsApp con IA — respuesta al instante 24/7${extras.length ? ", " + extras.join(" y ") : ""} — por suscripción mensual con condiciones negociables para ambos. ${trato} En 10 minutos se lo muestro funcionando.`;
  }

  /* toques 2 y 3: cortos, sin repetir el pitch */
  function toque(t, nombre, pais, marca) {
    marca = marca || marcaGuardada() || "[MARCA]";
    if (pais === "TX") return t === "t2"
      ? `Hi again — one quick data point and I won't bother you this week: businesses that answer inquiries within 5 minutes book far more than those that reply hours later, and our assistant answers in seconds, 24/7, in English and Spanish. If you can share the owner's contact, I'll take it from there. Thanks!`
      : `Hi, last message from me — I respect that this line is for other things. We're ${marca}: AI-powered customer messaging on a flexible monthly plan, and the demo takes 10 minutes. If it ever makes the agenda, this number is here. All the best to ${nombre}!`;
    return t === "t2"
      ? `Hola de nuevo — un solo dato y no molesto más por esta semana: el negocio que responde en los primeros 5 minutos cierra muchas más ventas que el que responde horas después, y nuestro asistente responde en segundos, 24/7. Si me comparten el contacto de la persona dueña, el resto lo hago yo. Gracias.`
      : `Hola, último mensaje de mi parte — sé que el canal está para otra cosa y lo respeto. Somos ${marca}: automatizamos la atención por WhatsApp con IA por suscripción mensual negociable, y la demo son 10 minutos. Si en algún momento el tema entra en agenda, este número queda a la orden. Que les vaya muy bien en ${nombre}.`;
  }

  const hoy = () => new Date().toISOString().slice(0, 10);
  const diasDesde = f => Math.floor((Date.now() - new Date(f + "T00:00:00").getTime()) / 864e5);
  function fechaDe(s, e) { const h = (s.h || []).filter(x => x.e === e); return h.length ? h[h.length - 1].f : null; }
  /* próximo toque: 2 a las 72h del primero, 3 al día 7 */
  function proximoToque(s) {
    if (s.e !== "t1" && s.e !== "t2") return null;
    const f1 = fechaDe(s, "t1"); if (!f1) return null;
    const dias = s.e === "t1" ? 3 : 7;
    const vence = new Date(new Date(f1 + "T00:00:00").getTime() + dias * 864e5).toISOString().slice(0, 10);
    return { toque: NEXT[s.e], vence, atraso: diasDesde(vence) };
  }
  /* estado al registrar un movimiento: guarda lo necesario para la agenda entre zonas */
  function mover(prev, n, e) {
    const s = Object.assign({ n: "", h: [] }, prev || {});
    s.e = e; s.h = (s.h || []).concat([{ e, f: hoy() }]);
    s.z = n.zona; s.nm = n.nombre; s.wa = n.wa || ""; s.p = n.pais || "CO";
    return s;
  }
  function normalizar(v) { if (v && v.e === "cont") v.e = "t1"; return v; } // estado viejo del mapa

  return { ESTADOS, NEXT, KEY_EST, KEY_MARCA, score, mensaje, toque, hoy, diasDesde, fechaDe, proximoToque, mover, normalizar };
})();
