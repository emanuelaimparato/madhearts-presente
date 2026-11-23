// MadHearts web — telecomando dal telefono, lato computer.
// Il computer apre un collegamento diretto (WebRTC) con il telefono. Per "trovarsi" usa il
// servizio pubblico gratuito di PeerJS (0.peerjs.com): passa solo un identificativo casuale,
// poi i comandi viaggiano direttamente tra i due dispositivi. Nessuna immagine viene inviata.
// Il telefono deve conoscere il PIN mostrato nelle impostazioni.

const ID_KEY = "madhearts.telecomando.id", PIN_KEY = "madhearts.telecomando.pin", ON_KEY = "madhearts.telecomando.attivo";

function loadScript(src) {
  return new Promise((resolve, reject) => {
    if (window.Peer) return resolve();
    const s = document.createElement("script");
    s.src = src; s.onload = resolve; s.onerror = () => reject(new Error("libreria non caricata"));
    document.head.appendChild(s);
  });
}

// solo per le prove: ?peerserver=host:porta usa un server di collegamento diverso da quello pubblico
export function peerServer() {
  const v = new URLSearchParams(location.search).get("peerserver");
  if (!v) return {};
  const [host, port] = v.split(":");
  return { host, port: +port || 9000, path: "/", secure: false };
}

const randomId = () => "madhearts-" + Array.from(crypto.getRandomValues(new Uint8Array(8)), (b) => (b % 36).toString(36)).join("");
const randomPin = () => String(1000 + (crypto.getRandomValues(new Uint16Array(1))[0] % 9000));
const store = (k, v) => { try { v === null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) { /* privato */ } };
const read = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };

export class RemoteHost {
  constructor({ onCommand, onChange }) {
    this.onCommand = onCommand;
    this.onChange = onChange || (() => {});
    this.id = read(ID_KEY) || randomId();
    this.pin = read(PIN_KEY) || randomPin();
    store(ID_KEY, this.id); store(PIN_KEY, this.pin);
    this.peer = null;
    this.conns = new Set();
    this.status = "spento";
  }

  get wanted() { return read(ON_KEY) === "1"; }

  async enable() {
    store(ON_KEY, "1");
    if (this.peer) return;
    this._set("collegamento in corso…");
    try {
      await loadScript("vendor/peerjs/peerjs.min.js");
    } catch (e) {
      this._set("non disponibile");
      return;
    }
    this._open();
  }

  disable() {
    store(ON_KEY, "0");
    for (const c of this.conns) c.close();
    this.conns.clear();
    this.peer?.destroy();
    this.peer = null;
    this._set("spento");
  }

  newPin() {
    this.pin = randomPin();
    store(PIN_KEY, this.pin);
    for (const c of this.conns) c.close();          // i telefoni dovranno inserire il nuovo PIN
    this.conns.clear();
    this._set(this.status);
  }

  _open(retry = 0) {
    const peer = (this.peer = new window.Peer(this.id, { debug: 0, ...peerServer() }));
    peer.on("open", () => this._set("pronto"));
    peer.on("connection", (conn) => this._accept(conn));
    peer.on("disconnected", () => { this._set("riconnessione…"); setTimeout(() => peer.destroyed || peer.reconnect(), 2000); });
    peer.on("error", (err) => {
      if (err.type === "unavailable-id" && retry < 1) {            // identificativo occupato: ne prendo uno nuovo
        peer.destroy();
        this.id = randomId(); store(ID_KEY, this.id);
        this._open(retry + 1);
      } else if (err.type === "network" || err.type === "server-error" || err.type === "socket-error") {
        this._set("serve Internet: riprovo…");
        setTimeout(() => { if (this.peer === peer && !peer.destroyed) peer.reconnect(); }, 5000);
      } else if (err.type !== "peer-unavailable") {
        this._set("errore: " + err.type);
      }
    });
  }

  _accept(conn) {
    let authed = false;
    conn.on("data", (msg) => {
      if (!msg || typeof msg !== "object") return;
      if (!authed) {
        if (msg.type === "hello" && String(msg.pin) === this.pin) {
          authed = true;
          this.conns.add(conn);
          conn.send({ type: "welcome" });
          this._set("pronto");
        } else {
          conn.send({ type: "denied" });
          setTimeout(() => conn.close(), 300);
        }
        return;
      }
      if (msg.type === "cmd") this.onCommand(msg);
    });
    conn.on("close", () => { this.conns.delete(conn); this._set(this.status); });
    conn.on("error", () => { this.conns.delete(conn); this._set(this.status); });
  }

  broadcast(state) {
    for (const c of this.conns) if (c.open) c.send({ type: "state", state });
  }

  _set(status) {
    this.status = status;
    this.onChange(this);
  }

  remoteUrl(base) {
    const q = new URLSearchParams(location.search).get("peerserver");
    return `${base.replace(/\/$/, "")}/telecomando.html${q ? "?peerserver=" + q : ""}#${this.id}`;
  }
}
