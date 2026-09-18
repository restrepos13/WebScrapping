#!/usr/bin/env python3
"""Auditoría técnica de las webs de data/negocios.json — genera señales y gancho.

Uso:
  python3 audit.py            # audita solo los no auditados
  python3 audit.py --force    # re-audita todo
  python3 audit.py --max 200  # límite de webs por corrida

Señales detectadas: sin_web, web_rota, sin_chatbot, sin_agendador, sin_ingles,
tiene_wa. Extrae correos y redes de la homepage. No usa dependencias externas.
"""
import json, os, re, ssl, argparse, urllib.request, urllib.error, socket
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data", "negocios.json")

CHATBOTS = ["cliengo", "manychat", "tidio", "tawk.to", "crisp.chat", "intercom",
            "hubspot", "wati.io", "treble.ai", "botmaker", "landbot", "chatfuel",
            "zenvia", "b2chat", "cliengify", "drift.com", "freshchat"]
AGENDADORES = ["calendly", "agendapro", "setmore", "booksy", "reservo",
               "lobbypms", "cloudbeds", "thebookingbutton", "omnibees",
               "direct-book", "simplybook", "agendrix", "koibox", "fresha"]
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"

def fetch(url):
    """Devuelve (html_lower, error). error: '', 'ssl', 'muerta', 'http4xx5xx'."""
    if not url.startswith("http"):
        url = "https://" + url
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "es,en"})
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            return r.read(400_000).decode("utf-8", "ignore").lower(), ""
    except urllib.error.HTTPError as e:
        return "", f"http{e.code}"
    except ssl.SSLError:
        return "", "ssl"
    except (urllib.error.URLError, socket.timeout, ConnectionError, OSError):
        return "", "muerta"
    except Exception:
        return "", "muerta"

def gancho_de(n, s):
    cat = n.get("categoria", "negocio")
    rev = f" con {n['reviews']} reseñas y {n['rating']}★" if n.get("reviews") else ""
    if s.get("sin_web"):
        return f"Sin sitio web{rev}: toda la reputación depende de terceros. Pitch: web + bot de WhatsApp."
    if s.get("web_rota"):
        return f"Su web está caída o con error de seguridad{rev} — dolor visible y urgente. Pitch: web nueva + bot."
    partes = []
    if s.get("sin_chatbot"):
        partes.append("atienden WhatsApp/chat a mano")
    if s.get("sin_agendador"):
        partes.append("sin agendamiento online")
    if s.get("sin_ingles"):
        partes.append("web sin inglés")
    if not partes:
        return f"Presencia digital completa{rev} — prioridad baja, revisar manualmente."
    return f"{cat.capitalize()}{rev}: " + ", ".join(partes) + ". Pitch: bot 24/7" + (" + agendador" if s.get("sin_agendador") else "") + "."

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--max", type=int, default=100000)
    args = ap.parse_args()

    negocios = json.load(open(DATA))
    pendientes = []
    for n in negocios:
        web = (n.get("web") or "").strip()
        if not web:
            n["senales"] = {"sin_web": True, "tiene_wa": bool(n.get("wa"))}
            n["gancho"] = n.get("gancho") or gancho_de(n, n["senales"])
            n["auditado"] = True
        elif (not n.get("auditado")) or args.force:
            pendientes.append(n)
    pendientes = pendientes[:args.max]
    print(f"Auditando {len(pendientes)} webs con 12 hilos…", flush=True)

    def auditar(n):
        html, err = fetch(n["web"].strip())
        if err:
            s = {"sin_web": False, "web_rota": True, "error": err, "tiene_wa": bool(n.get("wa"))}
            return n, s, None, None
        s = {
            "sin_web": False,
            "web_rota": False,
            "sin_chatbot": not any(c in html for c in CHATBOTS),
            "sin_agendador": not any(a in html for a in AGENDADORES),
            "sin_ingles": not ('lang="en"' in html or "/en/" in html or ">english<" in html or "hreflang=\"en" in html),
            "tiene_wa": bool(n.get("wa")) or "wa.me/" in html or "api.whatsapp.com" in html,
        }
        emails = sorted({e for e in re.findall(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", html)
                         if not any(x in e for x in ("example", "sentry", "wixpress", ".png", ".jpg", ".webp", ".svg"))})[:5]
        redes = {}
        for red, pat in [("instagram", r"instagram\.com/([a-z0-9_.]{2,30})"),
                         ("facebook", r"facebook\.com/([a-z0-9_.\-]{2,50})"),
                         ("tiktok", r"tiktok\.com/@([a-z0-9_.]{2,30})")]:
            m = re.search(pat, html)
            if m and m.group(1) not in ("p", "reel", "share", "sharer.php", "plugins"):
                redes[red] = m.group(1)
        return n, s, emails, redes

    hechos = 0
    with ThreadPoolExecutor(max_workers=12) as pool:
        futuros = {pool.submit(auditar, n): n for n in pendientes}
        for fut in as_completed(futuros):
            try:
                n, s, emails, redes = fut.result()
            except Exception:
                continue
            if emails is not None:
                n["emails"] = emails
            if redes is not None:
                n["redes"] = redes
            n["senales"] = s
            n["gancho"] = gancho_de(n, s)
            n["auditado"] = True
            hechos += 1
            if hechos % 100 == 0:
                print(f"  …{hechos}/{len(pendientes)}", flush=True)
                json.dump(negocios, open(DATA, "w"), ensure_ascii=False, indent=1)

    json.dump(negocios, open(DATA, "w"), ensure_ascii=False, indent=1)
    tot = len(negocios)
    aud = sum(1 for n in negocios if n.get("auditado"))
    print(f"\nAuditadas {hechos} webs en esta corrida · {aud}/{tot} negocios con señales · guardado en {DATA}")

if __name__ == "__main__":
    main()
