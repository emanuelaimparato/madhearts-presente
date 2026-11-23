"""Pannello di controllo nel browser.

L'app avvia un piccolo server web locale: apri l'indirizzo mostrato nel
Terminale (di solito http://localhost:8765) nel browser del Mac. Con
`lan = true` in [panel] il pannello è raggiungibile anche dal telefono sulla
stessa rete Wi-Fi, protetto da un PIN. Non serve Internet.

Il server non tocca mai la grafica direttamente: mette i comandi in una coda
che l'app esegue nel proprio ciclo, e legge un'istantanea dello stato.
"""
from __future__ import annotations

import json
import queue
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

WEB = Path(__file__).resolve().parent / "web"


class Panel:
    def __init__(self, cfg: dict, root: Path, log=print):
        p = cfg.get("panel", {})
        self.enabled = bool(p.get("enabled", True))
        self.lan = bool(p.get("lan", False))
        self.pin = str(p.get("pin", "")).strip()
        self.port = int(p.get("port", 8765))
        self.root, self.log = root, log
        self.commands: queue.Queue = queue.Queue()
        self._state = {}
        self._lock = threading.Lock()
        self.server = None
        self.urls: list[str] = []

    def start(self) -> None:
        if not self.enabled:
            return
        if self.lan and not self.pin:
            self.log("pannello: lan = true richiede un pin in [panel]; resta visibile solo da questo Mac")
            self.lan = False
        host = "0.0.0.0" if self.lan else "127.0.0.1"
        panel = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):          # niente log rumorosi nel Terminale
                pass

            def _send(self, code, body: bytes, ctype="application/json"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _authorized(self) -> bool:
                if not panel.pin:
                    return True
                q = parse_qs(urlparse(self.path).query)
                return self.headers.get("X-Pin", "") == panel.pin or q.get("pin", [""])[0] == panel.pin

            def do_GET(self):
                path = urlparse(self.path).path
                if path in ("/", "/index.html"):
                    return self._send(200, (WEB / "panel.html").read_bytes(), "text/html; charset=utf-8")
                if path.startswith("/fonts/") and path.endswith(".ttf"):
                    f = panel.root / "assets" / "fonts" / Path(path).name
                    if f.exists():
                        return self._send(200, f.read_bytes(), "font/ttf")
                if path == "/qr.svg":
                    # codice QR dell'indirizzo per il telefono (contiene solo l'indirizzo, non il PIN)
                    if len(panel.urls) < 2:
                        return self._send(404, b"{}")
                    try:
                        import qrcode
                        import qrcode.image.svg
                        img = qrcode.make(panel.urls[1], image_factory=qrcode.image.svg.SvgPathImage, border=2)
                        return self._send(200, img.to_string(), "image/svg+xml")
                    except Exception:
                        return self._send(404, b"{}")
                if path == "/api/state":
                    if not self._authorized():
                        return self._send(401, b'{"errore":"pin"}')
                    with panel._lock:
                        body = json.dumps(panel._state).encode()
                    return self._send(200, body)
                self._send(404, b'{"errore":"non trovato"}')

            def do_POST(self):
                if urlparse(self.path).path != "/api/cmd":
                    return self._send(404, b"{}")
                if not self._authorized():
                    return self._send(401, b'{"errore":"pin"}')
                try:
                    n = int(self.headers.get("Content-Length", "0"))
                    cmd = json.loads(self.rfile.read(min(n, 10000)) or b"{}")
                    if not isinstance(cmd, dict) or "cmd" not in cmd:
                        raise ValueError
                except ValueError:
                    return self._send(400, b'{"errore":"comando non valido"}')
                panel.commands.put(cmd)
                self._send(200, b'{"ok":true}')

        for port in range(self.port, self.port + 10):
            try:
                self.server = ThreadingHTTPServer((host, port), Handler)
                self.port = port
                break
            except OSError:
                continue
        if self.server is None:
            self.log("pannello: nessuna porta libera, pannello non disponibile")
            return
        threading.Thread(target=self.server.serve_forever, name="pannello", daemon=True).start()
        self.urls = [f"http://localhost:{self.port}"]
        if self.lan:
            ip = _lan_ip()
            if ip:
                self.urls.append(f"http://{ip}:{self.port}")
        self.log("pannello di controllo: " + "  oppure  ".join(self.urls) + ("  (PIN richiesto)" if self.pin else ""))

    def refresh_address(self) -> bool:
        """Ricalcola l'indirizzo per il telefono (cambia se il Mac passa a un'altra rete,
        per esempio all'hotspot del telefono). Ritorna True se è cambiato."""
        if not self.lan or self.server is None:
            return False
        ip = _lan_ip()
        new = [f"http://localhost:{self.port}"] + ([f"http://{ip}:{self.port}"] if ip else [])
        if new == self.urls:
            return False
        self.urls = new
        return True

    def publish(self, state: dict) -> None:
        with self._lock:
            self._state = state

    def poll(self) -> list[dict]:
        out = []
        while True:
            try:
                out.append(self.commands.get_nowait())
            except queue.Empty:
                return out

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()


def _lan_ip() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))        # nessun pacchetto viene inviato: serve solo a scegliere l'interfaccia
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return None
