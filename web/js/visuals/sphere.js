// MadHearts web — la sfera ad anelli sullo sfondo (traduzione di madhearts/visuals/sphere.py).
// All'inizio un solo anello che ruota; ogni filo intrecciato aggiunge un anello che nasce
// bianco (il presente) e in pochi secondi prende la sua tonalità di rosso. La sfera ruota piano;
// la parte posteriore è più tenue. Il file salvato contiene solo gli anelli: nessuna immagine.

import { strip } from "./geometry.js";

const GOLDEN = 0.6180339887;
const ease = (x) => { x = Math.min(Math.max(x, 0), 1); return x * x * (3 - 2 * x); };
const rotX = (a) => { const c = Math.cos(a), s = Math.sin(a); return [[1, 0, 0], [0, c, -s], [0, s, c]]; };
const rotY = (a) => { const c = Math.cos(a), s = Math.sin(a); return [[c, 0, s], [0, 1, 0], [-s, 0, c]]; };
const mm = (A, B) => A.map((r) => [0, 1, 2].map((j) => r[0] * B[0][j] + r[1] * B[1][j] + r[2] * B[2][j]));
const mv = (A, v) => A.map((r) => r[0] * v[0] + r[1] * v[1] + r[2] * v[2]);
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const unit = (v) => { const l = Math.hypot(...v); return v.map((x) => x / l); };

function rng(seed) {
  let a = seed >>> 0;
  const next = () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  return { random: next, uniform: (lo, hi) => lo + (hi - lo) * next(),
           gauss: (mu, sd) => mu + sd * Math.sqrt(-2 * Math.log(next() + 1e-12)) * Math.cos(2 * Math.PI * next()) };
}

export class RingSphere {
  constructor(seed = Date.now() % 100000) {
    this.rings = [];
    this.count = 0;
    this.r = rng(seed);
    this.lastAdd = -1e9;
  }

  ensureInitial(n, t) {
    while (this.rings.length < n) this._add(t - 1000, this.r.uniform(0, Math.PI), 1, 0, 0.4);
  }

  _pickShade(P) {           // per lo più vicina al rosso MadHearts, più di rado molto scura o chiara
    return Math.min(Math.max(this.r.gauss(P.ring_shade_center, P.ring_shade_spread), 0), 1);
  }

  addFromGesture(t, angle, strength, P) {
    if (t - this.lastAdd < P.ring_cooldown) return false;
    this.lastAdd = t;
    this._add(t, angle, strength, P.ring_white_every, this._pickShade(P));
    const alive = this.rings.filter((r) => r.dying === null);
    const excess = alive.length - P.max_rings;
    for (const r of alive.slice(0, Math.max(excess, 0))) r.dying = t;   // i più vecchi si dissolvono piano
    return true;
  }

  _add(t, angle, strength, whiteEvery, shade = 0.4) {
    let z = 1 - 2 * ((this.count * GOLDEN + 0.21) % 1);
    z *= 0.85;                               // evita anelli perfettamente frontali
    const rr = Math.sqrt(Math.max(1 - z * z, 0)), az = angle + Math.PI / 2;
    const white = whiteEvery > 0 && this.count > 0 && this.count % whiteEvery === 0;
    this.rings.push({ normal: unit([rr * Math.cos(az), rr * Math.sin(az), z]), born: t, white, strength,
                      seed: this.r.random() * 6.28, drift: this.r.uniform(-0.03, 0.03), dying: null, shade });
    this.count++;
  }

  clear(t, keep = 1) {
    this.rings = [];
    this.count = 0;
    this.ensureInitial(keep, t);
  }

  update(t, P) {
    this.rings = this.rings.filter((r) => r.dying === null || t - r.dying < P.ring_fade_out);
    this.ensureInitial(P.initial_rings, t);
  }

  // aggiunge i vertici di tutti gli anelli a "out"; shade(x) -> colore lineare, white colore lineare
  geometry(out, t, P, aspect, shade, white) {
    const rot = mm(rotX((P.sphere_tilt * Math.PI) / 180), rotY(t * P.sphere_rotation_speed));
    const cx = P.sphere_x, cy = P.sphere_y, R = P.sphere_radius, d = P.sphere_perspective, depth = P.sphere_depth;
    const m = 180;
    for (const ring of this.rings) {
      const age = t - ring.born;
      const grow = ease(age / Math.max(P.ring_grow_time, 1e-3));
      let a = P.ring_brightness * (0.7 + 0.3 * ring.strength) * ease(age / 1.2);
      if (ring.dying !== null) a *= 1 - ease((t - ring.dying) / Math.max(P.ring_fade_out, 1e-3));
      if (a < 0.003) continue;
      const n = mv(rotY(t * ring.drift), ring.normal);      // deriva lentissima di ogni anello
      const helper = Math.abs(n[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0];
      const ax = unit(cross(n, helper)), bx = cross(n, ax);
      const line = [], alpha = [], width = [];
      const scale = 0.7 + 0.3 * grow;
      for (let i = 0; i < m; i++) {
        const th = (2 * Math.PI * i) / (m - 1) + ring.seed, c = Math.cos(th), s = Math.sin(th);
        const p = [(c * ax[0] + s * bx[0]) * scale, (c * ax[1] + s * bx[1]) * scale, (c * ax[2] + s * bx[2]) * scale];
        const q = mv(rot, p);
        const f = d / (d - q[2]);
        line.push([cx + (q[0] * f * R) / aspect, cy + q[1] * f * R]);
        const front = (q[2] + 1) / 2;                       // 1 = verso chi guarda
        alpha.push(a * (1 - depth + depth * front));
        width.push(P.ring_width * (0.6 + 0.6 * front) * f);
      }
      const target = ring.white ? white : shade(ring.shade);
      const k = ease(age / Math.max(P.ring_white_time, 1e-3));   // nasce bianco, poi prende la sua tonalità
      const col = [0, 1, 2].map((i) => white[i] * (1 - k) + target[i] * k);
      strip(out, line, width, col, alpha, aspect, { uOffset: ring.seed, uScale: P.brush_scale * 0.6, dry: P.ring_dryness });
    }
  }

  // ---------------------------------------------------------------- memoria (nel browser)
  export(nowT, nowEpoch) {
    return { versione: 1, anelli_aggiunti: this.count, anelli: this.rings.filter((r) => r.dying === null).map((r) => ({
      normale: r.normal, nato: nowEpoch - (nowT - r.born), bianco: r.white, tinta: r.shade, forza: r.strength, seme: r.seed, deriva: r.drift })) };
  }

  load(data, nowT, nowEpoch) {
    this.rings = (data.anelli || []).map((d) => ({
      normal: d.normale, born: nowT - (nowEpoch - d.nato), white: false, strength: d.forza, seed: d.seme, drift: d.deriva, dying: null,
      shade: d.tinta ?? (d.bianco ? 0.95 : (Math.sin(d.seme * 12.9898) * 0.5 + 0.5) * 0.7 + 0.1),
    }));
    this.count = data.anelli_aggiunti ?? this.rings.length;
  }
}
