// MadHearts web — visitatore simulato (traduzione di madhearts/simulate.py).
// Una successione di visitatori: ognuno intreccia per un po', poi finisce abbassando le
// braccia oppure uscendo dall'inquadratura. Serve a provare tutto senza camera.

const RINGS = [[0.30, 0.35], [0.42, 0.25], [0.58, 0.28], [0.70, 0.38], [0.33, 0.58],
               [0.50, 0.50], [0.67, 0.60], [0.45, 0.72], [0.60, 0.75]];

function rng(seed) {                         // generatore riproducibile (mulberry32)
  let a = seed >>> 0;
  const next = () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  return {
    random: next,
    uniform: (lo, hi) => lo + (hi - lo) * next(),
    choice: (arr) => arr[Math.floor(next() * arr.length)],
    gauss: (mu, sd) => mu + sd * Math.sqrt(-2 * Math.log(next() + 1e-12)) * Math.cos(2 * Math.PI * next()),
  };
}

const ease = (u) => u * u * (3 - 2 * u);

class ArmPath {
  constructor(r, start, sideBias) {
    Object.assign(this, { r, sideBias, cur: RINGS[start], target: RINGS[start], t0: 0, dur: 0, pauseUntil: 0.5, bend: 0 });
  }
  pick(t, cross) {
    let c = RINGS.filter((q) => q !== this.cur);
    const side = c.filter((q) => (cross ? (q[0] - 0.5) * this.sideBias < 0 : (q[0] - 0.5) * this.sideBias >= -0.05));
    if (side.length) c = side;
    this.target = this.r.choice(c);
    this.t0 = t;
    const d = Math.hypot(this.cur[0] - this.target[0], this.cur[1] - this.target[1]);
    this.dur = this.r.uniform(0.6, 1.3) * (0.6 + d * 2);
    this.bend = this.r.uniform(-0.12, 0.12);
  }
  pos(t) {
    if (t < this.t0 || this.dur <= 0) return this.cur;
    const u = Math.min((t - this.t0) / this.dur, 1), e = ease(u);
    const [x0, y0] = this.cur, [x1, y1] = this.target;
    const b = Math.sin(Math.PI * e) * this.bend;
    const p = [x0 + (x1 - x0) * e - (y1 - y0) * b, y0 + (y1 - y0) * e + (x1 - x0) * b];
    if (u >= 1) { this.cur = this.target; this.dur = 0; this.pauseUntil = t + this.r.uniform(0.25, 0.9); }
    return p;
  }
}

export class SimulatedVisitor {
  constructor({ seed = 3, weave = [16, 24], restFor = 8, awayFor = 6 } = {}) {
    this.r = rng(seed);
    Object.assign(this, { weave, restFor, awayFor, frame: 0, visitor: 0 });
    this._startVisitor(0);
  }
  _startVisitor(t) {
    this.arms = { left: new ArmPath(this.r, 4, -1), right: new ArmPath(this.r, 3, +1) };
    for (const a of Object.values(this.arms)) a.pauseUntil = t + 0.5;
    this.weaveUntil = t + this.r.uniform(...this.weave);
    this.end = this.visitor % 2 === 0 ? "rest" : "away";
    this.endUntil = this.weaveUntil + (this.end === "rest" ? this.restFor : this.awayFor);
    this.visitor++;
  }
  observe(t, aspect = 16 / 9) {
    this.frame++;
    if (t >= this.endUntil) this._startVisitor(t);
    const obs = { frameId: this.frame, timestamp: t, present: true, aspect, shoulderWidth: 0.16, arms: {}, poseMs: 0 };
    if (t >= this.weaveUntil && this.end === "away") { obs.present = false; return obs; }
    for (const [side, path] of Object.entries(this.arms)) {
      const sx = side === "left" ? 0.42 : 0.58;
      let x, y;
      if (t >= this.weaveUntil) {                       // braccia lungo il corpo
        const e = ease(Math.min((t - this.weaveUntil) / 1.2, 1));
        const [x0, y0] = path.cur, rest = [sx + (side === "right" ? 0.02 : -0.02), 0.88];
        x = x0 + (rest[0] - x0) * e; y = y0 + (rest[1] - y0) * e;
      } else {
        if (path.dur === 0 && t >= path.pauseUntil) path.pick(t, this.r.random() < 0.18);
        [x, y] = path.pos(t);
      }
      x += this.r.gauss(0, 0.002); y += this.r.gauss(0, 0.002);
      const P = (px, py, v) => ({ x: px, y: py, z: 0, visibility: v });
      obs.arms[side] = { side, shoulder: P(sx, 0.40, 0.99), elbow: P((sx + x) / 2, (0.40 + y) / 2 + 0.08, 0.95), wrist: P(x, y, 0.9) };
    }
    return obs;
  }
}
