// MadHearts web — telecomando dal telefono, lato computer. Nessun servizio esterno.
// Il tramite è il server locale del Mac (web/server.py, avviato da avvia_web.command):
// questa pagina gli invia lo stato due volte al secondo e riceve i comandi del telefono.
// Il telefono, sulla stessa rete, apre la pagina del telecomando dal Mac e usa il PIN.
// Dal sito online (senza server locale) il telecomando non è disponibile.

const PIN_KEY = "madhearts.telecomando.pin", ON_KEY = "madhearts.telecomando.attivo";
const randomPin = () => String(1000 + (crypto.getRandomValues(new Uint16Array(1))[0] % 9000));
const store = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* privato */ } };
const read = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };

export class RemoteHost {
  constructor({ onCommand, onChange }) {
    this.onCommand = onCommand;
    this.onChange = onChange || (() => {});
    this.pin = read(PIN_KEY) || randomPin();
    store(PIN_KEY, this.pin);
    this.active = false;
    this.available = null;        // null = non ancora verificato
    this.lanUrl = null;
    this.phones = 0;
    this.status = "spento";
    this.state = null;
    this.timer = 0;
  }

  get wanted() { return read(ON_KEY) === "1"; }

  // c'è il server locale del Mac? (solo aprendo l'esperienza da avvia_web.command)
  async check() {
    const local = ["localhost", "127.0.0.1"].includes(location.hostname);
    if (!local) { this.available = false; return false; }
    try {
      const r = await fetch("api/info", { cache: "no-store" });
      const info = r.ok ? await r.json() : null;
      this.available = !!(info && info.server === "madhearts");
      this.lanUrl = info?.lan_url ?? null;
    } catch (e) {
      this.available = false;
    }
    return this.available;
  }

  async enable() {
    store(ON_KEY, "1");
    if (!(await this.check())) { this._set("non disponibile"); return; }
    this.active = true;
    this._set("pronto");
    clearInterval(this.timer);
    this.timer = setInterval(() => this._tick(), 500);
    this._tick();
  }

  disable() {
    store(ON_KEY, "0");
    this.active = false;
    clearInterval(this.timer);
    this.phones = 0;
    this._set("spento");
  }

  newPin() {
    this.pin = randomPin();
    store(PIN_KEY, this.pin);
    this._set(this.status);
  }

  broadcast(state) { this.state = state; }

  async _tick() {
    if (!this.active) return;
    try {
      const r = await fetch("api/host/state", { method: "POST", headers: { "Content-Type": "application/json" },
                                                body: JSON.stringify({ pin: this.pin, state: this.state }) });
      const res = await r.json();
      for (const c of res.commands || []) this.onCommand(c);
      const changed = res.phones !== this.phones || this.status !== "pronto";
      this.phones = res.phones || 0;
      if (changed) this._set("pronto");
      if (Math.random() < 0.05) {                 // ogni tanto: l'indirizzo cambia se il Mac cambia rete
        const old = this.lanUrl;
        await this.check();
        if (old !== this.lanUrl) this._set("pronto");
      }
    } catch (e) {
      this._set("server del Mac non raggiungibile");
    }
  }

  _set(status) {
    this.status = status;
    this.onChange(this);
  }

  remoteUrl() {
    return this.lanUrl ? `${this.lanUrl}telecomando.html` : null;
  }
}
