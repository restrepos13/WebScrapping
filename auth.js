/* Puerta de acceso del Radar — corre antes que cualquier otra cosa de la página.

   · Oculta el documento hasta que el servidor confirme la sesión.
   · Si no hay sesión, muestra la pantalla de entrada (correo + contraseña).
   · Guarda el token en localStorage además de la cookie, para que la sesión
     sobreviva aunque el proxy de Vercel no reenvíe las cookies.
   · Expone window.RadarAuth.listo: promesa que solo se resuelve con sesión
     válida. Las páginas hacen RadarAuth.listo.then(arrancar).

   Sin sesión no se arranca nada: los datos del servidor responden 401. */
(function () {
  "use strict";
  var KEY = "radar-sesion";
  var enLogin = /^\/login\/?$/.test(location.pathname);
  var listo, resolver;
  listo = new Promise(function (r) { resolver = r; });

  if (enLogin) { // la pantalla del servidor ya es la puerta
    window.RadarAuth = { listo: new Promise(function () { }), salir: salir };
    return;
  }

  // 1. ocultar el documento mientras se verifica (sin parpadeo de datos)
  var oculto = document.createElement("style");
  oculto.id = "radar-oculto";
  oculto.textContent = "html{visibility:hidden!important}";
  (document.head || document.documentElement).appendChild(oculto);

  // 2. fetch con cabecera de sesión (respaldo de la cookie)
  var _fetch = window.fetch.bind(window);
  function token() { try { return localStorage.getItem(KEY) || ""; } catch (e) { return ""; } }
  window.fetch = function (input, init) {
    var url = typeof input === "string" ? input : (input && input.url) || "";
    try {
      var t = token();
      if (t && url && !/^https?:/i.test(url)) {
        init = init || {};
        var h = new Headers(init.headers || {});
        if (!h.has("X-Radar-Sesion")) h.set("X-Radar-Sesion", t);
        init.headers = h;
      }
    } catch (e) { }
    return _fetch(input, init).then(function (r) {
      // sesión vencida a mitad de uso: volver a la puerta
      if (r.status === 401 && /(^|\/)(data\/|config\.json)/.test(url)) pintar("La sesión venció. Entrá de nuevo.");
      return r;
    });
  };

  // 3. pantalla de entrada
  var ESTILO = ""
    + "#radar-login{position:fixed;inset:0;z-index:2147483647;display:grid;place-items:center;"
    + "padding:24px;background:radial-gradient(700px 340px at 72% 18%,rgba(255,176,32,.07),transparent),"
    + "radial-gradient(520px 320px at 22% 88%,rgba(57,255,110,.05),transparent),#05060A;"
    + "visibility:visible;font-family:'Archivo',system-ui,-apple-system,sans-serif;color:#ECEDEF}"
    + "#radar-login *{box-sizing:border-box}"
    + "#radar-login .caja{width:min(390px,100%)}"
    + "#radar-login .kicker{font-family:ui-monospace,'SF Mono',Menlo,monospace;font-size:10px;"
    + "letter-spacing:.22em;text-transform:uppercase;color:#5E6470;margin:0 0 10px}"
    + "#radar-login h1{font-size:30px;font-weight:900;letter-spacing:-.02em;margin:0 0 6px}"
    + "#radar-login .sub{font-size:13px;color:#9CA2AD;margin:0 0 24px;line-height:1.6}"
    + "#radar-login label{display:block;font-size:10px;letter-spacing:.14em;text-transform:uppercase;"
    + "color:#5E6470;margin:0 0 6px}"
    + "#radar-login input{width:100%;padding:12px 13px;border-radius:10px;border:1px solid rgba(255,255,255,.1);"
    + "background:rgba(255,255,255,.04);color:#ECEDEF;font-size:14px;outline:none;font-family:inherit}"
    + "#radar-login input:focus{border-color:rgba(255,176,32,.6);background:rgba(255,255,255,.06)}"
    + "#radar-login .campo{margin-bottom:14px}"
    + "#radar-login button{width:100%;margin-top:8px;padding:12px;border:0;border-radius:10px;"
    + "background:#FFB020;color:#161006;font-weight:800;font-size:14px;cursor:pointer;font-family:inherit}"
    + "#radar-login button:disabled{opacity:.6;cursor:wait}"
    + "#radar-login .aviso{display:none;margin:0 0 14px;padding:10px 12px;border-radius:9px;font-size:12px;"
    + "border:1px solid rgba(255,255,255,.1);background:rgba(255,255,255,.04);color:#9CA2AD}"
    + "#radar-login .aviso.malo{border-color:rgba(255,51,85,.35);background:rgba(255,51,85,.09);color:#FF8FA3}"
    + "#radar-login .pie{margin-top:18px;font-size:10.5px;color:#5E6470;line-height:1.7;text-align:center}"
    + "#radar-login .pie a{color:#5E6470}";

  var programado = false;
  function pintar(mensaje, malo) {
    if (!document.body) { // el script corre en <head>: esperar el <body>
      if (!programado) {
        programado = true;
        document.addEventListener("DOMContentLoaded", function () {
          programado = false; pintar(mensaje, malo);
        }, { once: true });
      }
      return;
    }
    if (document.getElementById("radar-login")) {
      if (mensaje) aviso(mensaje, malo);
      return;
    }
    var st = document.createElement("style");
    st.textContent = ESTILO;
    document.head.appendChild(st);
    var d = document.createElement("div");
    d.id = "radar-login";
    d.innerHTML = ''
      + '<div class="caja">'
      + '  <p class="kicker">Radar Nocturno</p>'
      + '  <h1>Acceso privado</h1>'
      + '  <p class="sub">Este panel es de uso personal. Entrá con el correo y la contraseña del propietario.</p>'
      + '  <div class="aviso" id="radar-aviso"></div>'
      + '  <form id="radar-form" autocomplete="on">'
      + '    <div class="campo"><label for="radar-email">Correo</label>'
      + '      <input id="radar-email" type="email" autocomplete="username" required></div>'
      + '    <div class="campo"><label for="radar-clave">Contraseña</label>'
      + '      <input id="radar-clave" type="password" autocomplete="current-password" required></div>'
      + '    <button id="radar-b" type="submit">Entrar</button>'
      + '  </form>'
      + '  <p class="pie">Los intentos de acceso quedan registrados con IP y ubicación aproximada.</p>'
      + '</div>';
    (document.body || document.documentElement).appendChild(d);
    if (mensaje) aviso(mensaje, malo);
    var email = d.querySelector("#radar-email");
    try { email.value = localStorage.getItem("radar-email") || ""; } catch (e) { }
    (email.value ? d.querySelector("#radar-clave") : email).focus();
    d.querySelector("#radar-form").addEventListener("submit", entrar);
  }

  function aviso(texto, malo) {
    var a = document.getElementById("radar-aviso");
    if (!a) return;
    a.textContent = texto;
    a.className = "aviso" + (malo ? " malo" : "");
    a.style.display = "block";
  }

  function entrar(ev) {
    ev.preventDefault();
    var b = document.getElementById("radar-b");
    var correo = document.getElementById("radar-email").value.trim();
    b.disabled = true; b.textContent = "Entrando…";
    window.fetch("api/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: correo, password: document.getElementById("radar-clave").value })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (r.ok && d.ok) {
          try { localStorage.setItem(KEY, d.token || ""); localStorage.setItem("radar-email", correo); } catch (e) { }
          location.reload();
          return;
        }
        throw new Error(d.error || "No se pudo entrar.");
      });
    }).catch(function (e) {
      aviso(e && e.message ? e.message : "No hay conexión con el servidor.", true);
      b.disabled = false; b.textContent = "Entrar";
    });
  }

  function revelar() {
    var st = document.getElementById("radar-oculto");
    if (st) st.remove();
    var d = document.getElementById("radar-login");
    if (d) d.remove();
  }

  function salir() {
    try { localStorage.removeItem(KEY); } catch (e) { }
    window.fetch("api/logout", { method: "POST" }).catch(function () { }).then(function () {
      location.href = "/login";
    });
  }

  // 4. verificar sesión (con margen para el arranque en frío de Render)
  var espera = setTimeout(function () { pintar("Verificando acceso…"); }, 350);
  (function verificar() {
    var c = new AbortController();
    var t = setTimeout(function () { c.abort(); }, 75000);
    window.fetch("api/sesion", { cache: "no-store", credentials: "same-origin", signal: c.signal })
      .then(function (r) {
        clearTimeout(t); clearTimeout(espera);
        if (r.ok) { revelar(); resolver(); return; }
        pintar("Escribí tu correo y contraseña para entrar.", false);
      })
      .catch(function () {
        clearTimeout(t); clearTimeout(espera);
        pintar("No se pudo verificar el acceso. El servidor puede estar despertando: probá de nuevo en unos segundos.", true);
        var a = document.getElementById("radar-aviso");
        if (a) {
          a.style.cursor = "pointer";
          a.title = "Reintentar";
          a.addEventListener("click", function () { location.reload(); });
        }
      });
  })();

  window.RadarAuth = { listo: listo, salir: salir };
})();
