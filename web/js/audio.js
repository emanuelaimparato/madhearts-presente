// MadHearts web — audio (traduzione di madhearts/audio.py con la Web Audio API, in tempo reale).
// Quattro voci con il proprio volume:
// - MUSICA: la vostra traccia (web/audio/musica.mp3) in loop, se presente
// - TAPPETO: accordo morbido in Re maggiore che respira piano; si alza quando c'è qualcuno
// - SCIA: fruscio di pennello (rumore filtrato + lievi armonici) che suona solo mentre la mano
//   si muove, a sinistra/destra con la mano
// - RINTOCCO: campana dolce quando un nuovo anello entra nella sfera
// L'audio parte dopo un clic (regola dei browser): per questo si avvia col pulsante Avvia.

const PENTA = [293.66, 329.63, 369.99, 440.0, 493.88, 587.33, 659.25];   // Re maggiore pentatonica

export const AUDIO_DEFAULTS = {
  enabled: true, music_file: "audio/musica.mp3",
  master_volume: 0.8, music_volume: 0.5, ambient_volume: 0.5, ambient_idle: 0.35, trail_volume: 0.6, chime_volume: 0.6,
};

export class Audio {
  constructor(cfg, log = console.log) {
    this.log = log;
    this.muted = false;
    this.ok = false;
    this.musicName = "";
    this.configure(cfg);
  }

  configure(cfg) {
    this.v = { ...AUDIO_DEFAULTS, ...(cfg.audio || {}) };
    if (this.ok) this._applyStatic();
  }

  // da chiamare dentro un clic
  async start() {
    if (this.ok || !this.v.enabled) return;
    try {
      const ac = (this.ac = new (window.AudioContext || window.webkitAudioContext)());
      if (ac.state === "suspended") await ac.resume();
      this.master = ac.createGain();
      this.master.connect(ac.destination);
      this._pad();
      this._brush();
      this.chimeBus = ac.createGain();
      this.chimeBus.connect(this.master);
      this.ok = true;
      this.padLevel = this.v.ambient_idle;
      this._applyStatic();
      this._music();
    } catch (e) {
      this.log("audio non disponibile: l'esperienza prosegue senza suono");
    }
  }

  // ---------------------------------------------------------------- voci
  _noiseBuffer(seconds) {
    const ac = this.ac, n = Math.round(ac.sampleRate * seconds), b = ac.createBuffer(1, n, ac.sampleRate), d = b.getChannelData(0);
    for (let i = 0; i < n; i++) d[i] = Math.random() * 2 - 1;
    return b;
  }

  _pad() {
    const ac = this.ac;
    this.padGain = ac.createGain();
    this.padGain.gain.value = 0;
    this.padGain.connect(this.master);
    const notes = [146.83, 220.0, 293.66, 329.63, 440.0, 554.37];        // Re, La, Re, Mi, La, Do#
    const gains = [1.0, 0.8, 0.55, 0.4, 0.3, 0.18];
    const k = 0.6 / 3.6;                                                 // stessa intensità dell'app per Mac
    notes.forEach((fr, i) => {
      // respiro lentissimo: un LFO sul volume di ogni nota
      const voice = ac.createGain();
      voice.gain.value = 0.55 * gains[i] * k;
      const lfo = ac.createOscillator(), lfoAmt = ac.createGain();
      lfo.frequency.value = (i % 3 + 1) / 24;
      lfoAmt.gain.value = 0.45 * gains[i] * k;
      lfo.connect(lfoAmt).connect(voice.gain);
      lfo.start();
      for (const [det, pan] of [[-0.25, -0.4], [0.25, 0.4]]) {           // leggero coro
        const p = ac.createStereoPanner();
        p.pan.value = pan;
        for (const [mult, g] of [[1, 1], [2, 0.12]]) {
          const o = ac.createOscillator(), og = ac.createGain();
          o.frequency.value = (fr + det) * mult;
          og.gain.value = g;
          o.connect(og).connect(p);
          o.start();
        }
        p.connect(voice);
      }
      voice.connect(this.padGain);
    });
    // aria: rumore filtrato molto basso
    const air = ac.createBufferSource(), bp = ac.createBiquadFilter(), ag = ac.createGain();
    air.buffer = this._noiseBuffer(3); air.loop = true;
    bp.type = "bandpass"; bp.frequency.value = 870; bp.Q.value = 0.6;
    ag.gain.value = 0.02;
    air.connect(bp).connect(ag).connect(this.padGain);
    air.start();
  }

  _brush() {
    const ac = this.ac;
    this.brushVoices = {};
    for (const side of ["left", "right"]) {
      const out = ac.createGain(), pan = ac.createStereoPanner();
      out.gain.value = 0;
      out.connect(pan).connect(this.master);
      const src = ac.createBufferSource(), hp = ac.createBiquadFilter(), lp = ac.createBiquadFilter(), swell = ac.createGain();
      src.buffer = this._noiseBuffer(4); src.loop = true;
      hp.type = "highpass"; hp.frequency.value = 900;
      lp.type = "lowpass"; lp.frequency.value = 5000;
      swell.gain.value = 0.42;
      const lfo = ac.createOscillator(), amt = ac.createGain();             // setole che "respirano"
      lfo.frequency.value = 3 / 8; amt.gain.value = 0.28;
      lfo.connect(amt).connect(swell.gain);
      src.connect(hp).connect(lp).connect(swell).connect(out);
      [1174.66, 1479.98, 1760.0].forEach((f) => {                           // lievi armonici luminosi
        const o = ac.createOscillator(), g = ac.createGain();
        o.frequency.value = f; g.gain.value = 0.05;
        o.connect(g).connect(out); o.start();
      });
      src.start(0, side === "left" ? 0 : 1.7);
      lfo.start();
      this.brushVoices[side] = { out, pan, level: 0 };
    }
  }

  async _music() {
    if (!this.v.music_file) return;
    try {
      const head = await fetch(this.v.music_file, { method: "HEAD" });
      if (!head.ok) { this.log(`musica: metti la traccia in web/${this.v.music_file} (per ora nessuna musica)`); return; }
      const el = (this.musicEl = new window.Audio(this.v.music_file));
      el.loop = true;
      el.crossOrigin = "anonymous";
      this.musicGain = this.ac.createGain();
      this.ac.createMediaElementSource(el).connect(this.musicGain).connect(this.master);
      this.musicGain.gain.value = 0;
      await el.play();
      this.musicGain.gain.setTargetAtTime(this.v.music_volume, this.ac.currentTime, 1.0);   // entra in dissolvenza
      this.musicName = this.v.music_file.split("/").pop();
      this.log("musica: " + this.musicName);
    } catch (e) {
      this.log("musica: impossibile leggere il file");
    }
  }

  // ---------------------------------------------------------------- volumi
  _applyStatic() {
    const now = this.ac.currentTime;
    this.master.gain.setTargetAtTime(this.muted ? 0 : this.v.master_volume, now, 0.15);
    if (this.musicGain) this.musicGain.gain.setTargetAtTime(this.v.music_volume, now, 0.2);
    this.chimeBus.gain.setTargetAtTime(this.v.chime_volume, now, 0.1);
  }

  setMuted(m) { this.muted = m; if (this.ok) this._applyStatic(); }

  update(state, dt, playing) {
    if (!this.ok) return;
    const now = this.ac.currentTime, v = this.v;
    const presence = state && playing ? state.personPresence : 0;
    const k = 1 - Math.exp(-dt / 0.6);
    this.padLevel += k * (v.ambient_idle + (1 - v.ambient_idle) * presence - this.padLevel);
    this.padGain.gain.setTargetAtTime(v.ambient_volume * this.padLevel, now, 0.05);
    const kb = 1 - Math.exp(-dt / 0.25);
    for (const [side, b] of Object.entries(this.brushVoices)) {
      let target = 0, x = 0.5;
      if (state && playing) {
        const a = state.arms[side];
        target = a.presence * Math.min(Math.max(a.speedN - 0.08, 0) / 0.7, 1);
        x = Math.min(Math.max(a.pos[0], 0), 1);
      }
      b.level += kb * (target - b.level);
      b.out.gain.setTargetAtTime(v.trail_volume * b.level, now, 0.05);
      b.pan.pan.setTargetAtTime(x * 2 - 1, now, 0.1);
    }
  }

  chime(index) {
    if (!this.ok) return;
    const ac = this.ac, t = ac.currentTime + 0.02, freq = PENTA[index % PENTA.length];
    const dry = ac.createGain(), echoL = ac.createStereoPanner(), echoR = ac.createStereoPanner();
    echoL.pan.value = -0.8; echoR.pan.value = 0.8;
    dry.gain.value = 0.5 / 1.9;
    dry.connect(this.chimeBus);
    for (const [ratio, amp, decay] of [[1, 1, 2.8], [2, 0.45, 1.8], [2.76, 0.3, 1.2], [5.4, 0.12, 0.6], [8.93, 0.06, 0.35]]) {
      const o = ac.createOscillator(), g = ac.createGain();
      o.frequency.value = freq * ratio;
      g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(amp, t + 0.01);              // attacco morbido
      g.gain.setTargetAtTime(0, t + 0.01, decay);
      o.connect(g).connect(dry);
      o.start(t); o.stop(t + 8);
    }
    for (const [delay, g, pan] of [[0.031, 0.5, echoR], [0.057, 0.35, echoR], [0.113, 0.25, echoL], [0.19, 0.15, echoL]]) {   // piccola eco
      const d = ac.createDelay(1), dg = ac.createGain();
      d.delayTime.value = delay; dg.gain.value = g;
      dry.connect(d).connect(dg).connect(pan);
    }
    echoL.connect(this.chimeBus); echoR.connect(this.chimeBus);
  }
}
