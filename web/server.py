"""MadHearts web — server locale del Mac (solo librerie standard di Python, anche 3.9).

Fa due cose:
1. serve la web app (questa cartella) su http://localhost:8000
2. fa da tramite per il telecomando, SENZA servizi esterni:
   - la pagina dell'esperienza (sul Mac, da localhost) invia lo stato e riceve i comandi;
   - il telefono, sulla stessa rete (o sull'hotspot), apre http://<indirizzo-del-Mac>:8000/telecomando.html,
     inserisce il PIN e invia comandi.
   Solo la pagina aperta sul Mac stesso (localhost) può fare da "esperienza": un telefono non
   può spacciarsi per il Mac. Senza PIN corretto il telefono non riceve né invia nulla.
   Nessuna immagine passa dal server.

Uso:  python3 web/server.py   (o bash web/avvia_web.command)
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.abspath(__file__))
LOCK = threading.Lock()
HUB = {"pin": None, "state": None, "state_t": 0.0, "commands": [], "phones": {}}
EXTRA_TYPES = {".mjs": "text/javascript", ".js": "text/javascript", ".wasm": "application/wasm",
               ".task": "application/octet-stream", ".webmanifest": "application/manifest+json"}


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))      # nessun pacchetto viene inviato: serve a scegliere l'interfaccia
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, **EXTRA_TYPES}

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, *a):                # niente righe per ogni richiesta nel Terminale
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    # ------------------------------------------------------------------ utilità
    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", "0") or 0)
        try:
            return json.loads(self.rfile.read(min(n, 200000)) or b"{}")
        except ValueError:
            return {}

    def _from_mac(self):
        return self.client_address[0] in ("127.0.0.1", "::1")

    def _pin_ok(self, pin):
        with LOCK:
            return HUB["pin"] is not None and str(pin) == str(HUB["pin"])

    # ------------------------------------------------------------------ GET
    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/info":
            ip = lan_ip()
            port = self.server.server_address[1]
            with LOCK:
                phones = sum(1 for t in HUB["phones"].values() if time.time() - t < 5)
            return self._json(200, {"server": "madhearts", "lan_url": f"http://{ip}:{port}/" if ip else None, "phones": phones})
        if u.path == "/api/remote/state":
            pin = parse_qs(u.query).get("pin", [""])[0]
            if not self._pin_ok(pin):
                return self._json(401, {"errore": "pin"})
            with LOCK:
                HUB["phones"][self.client_address[0]] = time.time()
                fresh = time.time() - HUB["state_t"] < 5
                state = HUB["state"] if fresh else None
            return self._json(200, {"state": state, "online": fresh})
        return super().do_GET()

    # ------------------------------------------------------------------ POST
    def do_POST(self):
        u = urlparse(self.path)
        msg = self._body()
        if u.path == "/api/host/state":            # solo la pagina aperta sul Mac
            if not self._from_mac():
                return self._json(403, {"errore": "solo dal Mac"})
            with LOCK:
                HUB["pin"] = msg.get("pin")
                HUB["state"] = msg.get("state")
                HUB["state_t"] = time.time()
                cmds, HUB["commands"] = HUB["commands"], []
                phones = sum(1 for t in HUB["phones"].values() if time.time() - t < 5)
            return self._json(200, {"commands": cmds, "phones": phones})
        if u.path == "/api/remote/cmd":
            if not self._pin_ok(msg.get("pin")):
                return self._json(401, {"errore": "pin"})
            cmd = {k: msg[k] for k in ("cmd", "id", "value") if k in msg}
            if cmd.get("cmd") not in ("play", "pause", "mute", "set"):
                return self._json(400, {"errore": "comando"})
            with LOCK:
                HUB["commands"] = (HUB["commands"] + [cmd])[-50:]
                HUB["phones"][self.client_address[0]] = time.time()
            return self._json(200, {"ok": True})
        return self._json(404, {"errore": "non trovato"})


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    for p in range(port, port + 10):
        try:
            srv = ThreadingHTTPServer(("0.0.0.0", p), Handler)
            break
        except OSError:
            continue
    else:
        print("Nessuna porta libera tra", port, "e", port + 9)
        sys.exit(1)
    p = srv.server_address[1]
    ip = lan_ip()
    print(f"MadHearts web: http://localhost:{p}/")
    if ip:
        print(f"telecomando (stessa rete): http://{ip}:{p}/telecomando.html  — il QR è nelle Impostazioni → Telefono")
    print("Per chiudere: Ctrl+C")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
