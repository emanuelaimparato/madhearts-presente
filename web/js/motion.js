// MadHearts web — elaborazione del movimento.
// Traduzione fedele di madhearts/motion.py (app per Mac): stessi parametri, stessi comportamenti.
//
// - filtro di attendibilità: un punto conta solo se visibile e con spostamento plausibile
// - smoothing adattivo (filtro One Euro): liscio da fermi, reattivo nei movimenti veloci
// - perdita del tracking: inerzia breve, poi la "presenza" si dissolve; al ritorno la
//   traccia riparte (segmentId cambia: il renderer inizia un nuovo filamento)
// - correzione degli scambi destra/sinistra improvvisi
// - gesto: velocità, direzione, svolte, ampiezza, estensione, elevazione, tratti,
//   incroci/incontri tra le braccia
// - sessione: inizia col primo gesto di intreccio, finisce quando la persona esce o tiene
//   le braccia lungo il corpo; alla fine l'evento "complete" (filo completato)
// Distanze del corpo in "larghezze di spalle" (sw); posizioni per il renderer 0..1.

import { SIDES } from "./common.js";

export const TRACKING = "tracking", HOLDING = "holding", LOST = "lost";

export const MOTION_DEFAULTS = {
  smoothing_min_cutoff: 1.2, smoothing_beta: 0.35, smoothing_d_cutoff: 1.0,
  max_plausible_speed: 14.0, reacquire_after_rejections: 4, hold_time: 0.35, hold_inertia: 0.15,
  fade_in: 0.25, fade_out: 0.9, speed_for_full_response: 5.0, response_curve: 0.8,
  movement_threshold: 0.5, stroke_min_length: 0.6, amplitude_window: 1.2, amplitude_full: 2.0,
  turn_min_angle: 70.0, turn_window: 0.18, activity_decay: 1.5, meet_distance: 0.45,
  cross_margin: 0.08, swap_min_jump: 0.6, default_shoulder_width: 0.22,
  session_exit_seconds: 4.0, session_rest_seconds: 5.0, rest_elevation: -1.0, rest_bottom: 0.88, rest_grace: 1.5,
  session_min_strokes: 2, session_min_length: 2.0, session_full_length: 40.0,
};

// ---------------------------------------------------------------- utilità vettori 2D
const sub = (a, b) => [a[0] - b[0], a[1] - b[1]];
const add = (a, b) => [a[0] + b[0], a[1] + b[1]];
const mul = (a, k) => [a[0] * k, a[1] * k];
const norm = (a) => Math.hypot(a[0], a[1]);
const clamp = (x, lo, hi) => Math.min(Math.max(x, lo), hi);

function alpha(cutoff, dt) {
  const tau = 1 / (2 * Math.PI * cutoff);
  return 1 / (1 + tau / dt);
}

function approach(cur, target, dt, tc) {
  if (tc <= 0) return target;
  const step = dt / tc;
  return target > cur ? Math.min(cur + step, target) : Math.max(cur - step, target);
}

class OneEuro2D {
  constructor(minCutoff, beta, dCutoff) {
    Object.assign(this, { minCutoff, beta, dCutoff });
    this.reset();
  }
  reset(x = null, t = null) {
    this.x = x ? [...x] : null;
    this.dx = [0, 0];
    this.t = t;
  }
  filter(x, t, scale) {
    if (!this.x || this.t === null) { this.reset(x, t); return this.x; }
    const dt = Math.max(t - this.t, 1e-3);
    this.t = t;
    const dx = mul(sub(x, this.x), 1 / dt);
    this.dx = add(this.dx, mul(sub(dx, this.dx), alpha(this.dCutoff, dt)));
    const cutoff = this.minCutoff + (this.beta * norm(this.dx)) / Math.max(scale, 1e-6);
    this.x = add(this.x, mul(sub(x, this.x), alpha(cutoff, dt)));
    return this.x;
  }
}

function newArmMotion(side) {
  return {
    side, state: LOST, presence: 0, segmentId: 0, pos: [0.5, 0.5], vel: [0, 0], speed: 0, speedN: 0,
    direction: [0, 0], angle: 0, amplitude: 0, extension: 0, elevation: 0, activity: 0, moving: false, raw: null,
  };
}

// ---------------------------------------------------------------- braccio
class ArmTracker {
  constructor(side, p) {
    this.side = side;
    this.out = newArmMotion(side);
    this.filter = new OneEuro2D(p.smoothing_min_cutoff, p.smoothing_beta, p.smoothing_d_cutoff);
    this.configure(p);
    this.pos = null;                 // unità immagine (x*aspect, y)
    this.vel = [0, 0];
    this.lastValidT = -1e9;
    this.rejections = 0;
    this.history = [];               // [t, pos]
    this.dirHistory = [];            // [t, angle]
    this.lastTurnT = -1e9;
    this.strokeStart = null;
    this.strokeT0 = 0;
    this.strokeLen = 0;
    this.extEma = null;
    this.elevEma = null;
    this.stats = { outliers: 0, resets: 0 };
  }

  configure(p) {
    this.p = p;
    this.filter.minCutoff = p.smoothing_min_cutoff;
    this.filter.beta = p.smoothing_beta;
    this.filter.dCutoff = p.smoothing_d_cutoff;
  }

  update(meas, armObs, t, dt, sw, aspect, events) {
    const o = this.out, p = this.p;
    o.raw = meas ? [meas[0] / aspect, meas[1]] : null;

    let accepted = false;
    if (meas) {
      if (!this.pos || o.state === LOST) {
        this._restart(meas, t, events, aspect);
        accepted = true;
      } else {
        const gap = Math.max(t - this.lastValidT, dt, 1e-3);
        const predicted = add(this.pos, mul(this.vel, Math.min(gap, p.hold_time)));
        const jumpSpeed = norm(sub(meas, predicted)) / sw / gap;
        if (jumpSpeed <= p.max_plausible_speed) {
          accepted = true;
          this.rejections = 0;
        } else {
          this.rejections++;
          this.stats.outliers++;
          if (this.rejections >= p.reacquire_after_rejections) {   // non era un errore: la mano è davvero lì
            this._restart(meas, t, events, aspect);
            accepted = true;
          }
        }
      }
    }

    if (accepted) {
      const prev = [...this.pos];
      this.pos = this.filter.filter(meas, t, sw);
      this.vel = [...this.filter.dx];
      this.lastValidT = t;
      o.state = TRACKING;
      this.strokeLen += norm(sub(this.pos, prev)) / sw;
    } else if (this.pos && o.state !== LOST) {
      if (t - this.lastValidT <= p.hold_time) {               // prosegui per inerzia
        o.state = HOLDING;
        this.vel = mul(this.vel, Math.exp(-dt / Math.max(p.hold_inertia, 1e-3)));
        this.pos = add(this.pos, mul(this.vel, dt));
      } else {                                                // poi fermati
        o.state = LOST;
        this.vel = [0, 0];
        events.push({ kind: "lost", side: this.side, pos: o.pos, strength: o.presence, data: {} });
      }
    }

    const target = o.state === TRACKING ? 1 : 0;
    o.presence = approach(o.presence, target, dt, target > o.presence ? p.fade_in : p.fade_out);
    if (!this.pos) return;

    // ---- caratteristiche del gesto
    o.pos = [this.pos[0] / aspect, this.pos[1]];
    const v = mul(this.vel, 1 / sw);
    o.vel = v;
    o.speed = o.state !== LOST ? norm(v) : 0;
    o.speedN = Math.pow(Math.min(o.speed / p.speed_for_full_response, 1), p.response_curve);
    if (o.speed > p.movement_threshold) {
      o.direction = [v[0] / o.speed, v[1] / o.speed];
      o.angle = Math.atan2(v[1], v[0]);
    } else {
      o.direction = [0, 0];
    }
    o.activity = Math.max(o.speedN, o.activity * Math.exp(-dt / Math.max(p.activity_decay, 1e-3)));

    // ampiezza: estensione del percorso nella finestra recente
    if (o.state === TRACKING) this.history.push([t, [...this.pos]]);
    while (this.history.length && t - this.history[0][0] > p.amplitude_window) this.history.shift();
    if (this.history.length > 1) {
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      for (const [, q] of this.history) { x0 = Math.min(x0, q[0]); y0 = Math.min(y0, q[1]); x1 = Math.max(x1, q[0]); y1 = Math.max(y1, q[1]); }
      o.amplitude = Math.min(Math.hypot(x1 - x0, y1 - y0) / sw / p.amplitude_full, 1);
    } else {
      o.amplitude *= Math.exp(-dt / Math.max(p.activity_decay, 1e-3));
    }

    // estensione ed elevazione del braccio (dalla posa, lisciate)
    if (armObs && Math.min(armObs.shoulder.visibility, armObs.elbow.visibility) >= p.min_visibility && o.state === TRACKING) {
      const sh = [armObs.shoulder.x * aspect, armObs.shoulder.y];
      const el = [armObs.elbow.x * aspect, armObs.elbow.y];
      const length = norm(sub(el, sh)) + norm(sub(this.pos, el));
      let ext = clamp(norm(sub(this.pos, sh)) / Math.max(length, 1e-6), 0, 1);
      ext = clamp((ext - 0.3) / 0.7, 0, 1);                  // braccio piegato ≈ 0.3
      const elev = (sh[1] - this.pos[1]) / sw;
      const k = 1 - Math.exp(-dt / 0.15);
      this.extEma = this.extEma === null ? ext : this.extEma + k * (ext - this.extEma);
      this.elevEma = this.elevEma === null ? elev : this.elevEma + k * (elev - this.elevEma);
      o.extension = this.extEma;
      o.elevation = this.elevEma;
    }

    this._detectTurn(t, o, events);
    this._detectStroke(t, o, events, sw, aspect);
  }

  _restart(meas, t, events, aspect) {
    this.filter.reset(meas, t);
    this.pos = [...meas];
    this.vel = [0, 0];
    this.history = [];
    this.dirHistory = [];
    this.rejections = 0;
    this.strokeStart = null;
    this.out.moving = false;
    this.out.segmentId++;
    this.stats.resets++;
    events.push({ kind: "appear", side: this.side, pos: [meas[0] / aspect, meas[1]], strength: 1, data: {} });
  }

  _detectTurn(t, o, events) {
    const p = this.p;
    if (o.speed <= p.movement_threshold * 1.5 || o.state !== TRACKING) { this.dirHistory = []; return; }
    this.dirHistory.push([t, o.angle]);
    while (this.dirHistory.length && t - this.dirHistory[0][0] > p.turn_window) this.dirHistory.shift();
    if (this.dirHistory.length < 2 || t - this.lastTurnT < 0.25) return;
    const old = this.dirHistory[0][1];
    let d = (o.angle - old + Math.PI) % (2 * Math.PI);
    if (d < 0) d += 2 * Math.PI;
    const diff = Math.abs(d - Math.PI);
    if (diff >= (p.turn_min_angle * Math.PI) / 180) {
      this.lastTurnT = t;
      this.dirHistory = [];
      events.push({ kind: "turn", side: this.side, pos: o.pos, strength: Math.min(diff / Math.PI, 1) * Math.max(o.speedN, 0.3), data: { angleChange: diff } });
    }
  }

  _detectStroke(t, o, events, sw, aspect) {
    const p = this.p;
    if (!o.moving && o.speed > p.movement_threshold * 1.5 && o.state === TRACKING) {
      o.moving = true;
      this.strokeStart = o.pos;
      this.strokeT0 = t;
      this.strokeLen = 0;
    } else if (o.moving && (o.speed < p.movement_threshold || o.state === LOST)) {
      o.moving = false;
      if (this.strokeStart && this.strokeLen >= p.stroke_min_length) {
        const [sx, sy] = this.strokeStart, [ex, ey] = o.pos;
        events.push({
          kind: "stroke", side: this.side, pos: o.pos, strength: Math.min(this.strokeLen / (2 * p.amplitude_full), 1),
          data: { start: this.strokeStart, end: o.pos, length: this.strokeLen, duration: t - this.strokeT0,
                  displacement: Math.hypot((ex - sx) * aspect, ey - sy) / sw },
        });
      }
      this.strokeStart = null;
    }
  }
}

// ---------------------------------------------------------------- processore
export class MotionProcessor {
  constructor(cfg) {
    this.configure(cfg);
    this.arms = Object.fromEntries(SIDES.map((s) => [s, new ArmTracker(s, this.p)]));
    this.state = {
      timestamp: 0, personPresence: 0, arms: {}, wristDistance: 0, closeness: 0, crossed: false, energy: 0,
      stillTime: 0, sessionActive: false, restTime: 0, absentTime: 0, events: [],
    };
    this.sw = null;
    this.lastT = null;
    this.crossed = false;
    this.met = false;
    this.swapping = false;
    this.stats = { swapsCorrected: 0 };
    this._newSession();
  }

  configure(cfg) {
    this.p = { ...MOTION_DEFAULTS, ...(cfg.motion || {}), min_visibility: cfg.tracking?.min_visibility ?? 0.3 };
    if (this.arms) for (const a of Object.values(this.arms)) a.configure(this.p);
  }

  update(obs) {
    const t = obs.timestamp, p = this.p, aspect = obs.aspect;
    const dt = this.lastT === null ? 1 / 30 : Math.min(Math.max(t - this.lastT, 1e-3), 0.25);
    this.lastT = t;
    const events = [];

    // larghezza delle spalle (scala del corpo), lisciata
    if (obs.present && obs.shoulderWidth > 0) {
      const now = obs.shoulderWidth * aspect;
      this.sw = this.sw === null ? now : this.sw + (1 - Math.exp(-dt / 0.5)) * (now - this.sw);
    }
    const sw = this.sw ?? p.default_shoulder_width * aspect;

    // misure valide dei polsi
    const meas = {}, armObs = {};
    for (const s of SIDES) {
      const a = obs.present ? obs.arms[s] : null;
      armObs[s] = a;
      meas[s] = a && a.wrist.visibility >= p.min_visibility ? [a.wrist.x * aspect, a.wrist.y] : null;
    }

    // correzione degli scambi improvvisi destra/sinistra (anche per più fotogrammi di fila)
    const L = this.arms.left, R = this.arms.right;
    let swap = false;
    if (meas.left && meas.right && L.pos && R.pos && L.out.state === TRACKING && R.out.state === TRACKING) {
      const straight = norm(sub(meas.left, L.pos)) + norm(sub(meas.right, R.pos));
      const crossed = norm(sub(meas.left, R.pos)) + norm(sub(meas.right, L.pos));
      swap = straight / sw > p.swap_min_jump && crossed < 0.4 * straight;
    }
    if (swap) {
      [meas.left, meas.right] = [meas.right, meas.left];
      [armObs.left, armObs.right] = [armObs.right, armObs.left];
      if (!this.swapping) this.stats.swapsCorrected++;
    }
    this.swapping = swap;

    for (const s of SIDES) this.arms[s].update(meas[s], armObs[s], t, dt, sw, aspect, events);

    const st = this.state;
    st.timestamp = t;
    st.arms = Object.fromEntries(SIDES.map((s) => [s, this.arms[s].out]));
    st.personPresence = approach(st.personPresence, obs.present ? 1 : 0, dt, obs.present ? p.fade_in : p.fade_out);
    this._pair(armObs, st, sw, events);
    st.energy = SIDES.reduce((acc, s) => acc + st.arms[s].activity * st.arms[s].presence, 0) / SIDES.length;
    st.stillTime = SIDES.some((s) => st.arms[s].moving) ? 0 : st.stillTime + dt;
    this._session(obs, st, dt, aspect, events);
    st.events = events;
    return st;
  }

  _newSession() {
    this.sess = { active: false, strokes: 0, length: 0, c2: 0, s2: 0, t0: 0, rest: 0, absent: 0, busy: 0 };
  }

  _session(obs, st, dt, aspect, events) {
    const p = this.p, ss = this.sess;
    for (const e of events) {
      if (e.kind !== "stroke") continue;
      if (!ss.active) { ss.active = true; ss.t0 = st.timestamp; }
      const [sx, sy] = e.data.start, [ex, ey] = e.data.end;
      const a = Math.atan2(-(ey - sy), (ex - sx) * aspect);
      const Ln = e.data.length;
      ss.strokes++;
      ss.length += Ln;
      ss.c2 += Ln * Math.cos(2 * a);                 // media "assiale": avanti e indietro contano uguale
      ss.s2 += Ln * Math.sin(2 * a);
    }
    ss.absent = obs.present ? 0 : ss.absent + dt;

    const resting = (a) => {
      if (a.state !== TRACKING) return true;         // polso fuori inquadratura, corpo visibile
      if (a.speed >= p.movement_threshold * 1.5) return false;
      return a.elevation < p.rest_elevation || a.pos[1] > p.rest_bottom;   // lungo il corpo o in basso
    };
    // un gesto vero azzera il riposo; un "tratto" tutto nella parte bassa è quasi sempre un punto stimato
    const rb = p.rest_bottom;
    const strokeNow = events.some((e) => e.kind === "stroke" && !(e.data.start[1] > rb && e.data.end[1] > rb));
    if (!obs.present || strokeNow) {
      ss.rest = 0; ss.busy = 0;
    } else if (SIDES.every((s) => resting(st.arms[s]))) {
      ss.rest += dt; ss.busy = 0;
    } else {
      ss.busy += dt;                                  // un breve movimento non ferma il conteggio
      if (ss.busy >= p.rest_grace) ss.rest = 0; else ss.rest += dt;
    }

    st.sessionActive = ss.active; st.restTime = ss.rest; st.absentTime = ss.absent;
    if (!ss.active) return;
    let reason = null;
    if (ss.absent >= p.session_exit_seconds) reason = "uscita";
    else if (ss.rest >= p.session_rest_seconds) reason = "braccia a riposo";
    if (!reason) return;
    if (ss.strokes >= p.session_min_strokes && ss.length >= p.session_min_length) {
      events.push({
        kind: "complete", side: null, pos: [0.5, 0.5], strength: Math.min(ss.length / p.session_full_length, 1),
        data: { strokes: ss.strokes, length: ss.length, angle: 0.5 * Math.atan2(ss.s2, ss.c2), duration: st.timestamp - ss.t0, reason },
      });
    }
    this._newSession();
  }

  _pair(armObs, st, sw, events) {
    const a = st.arms.left, b = st.arms.right, p = this.p;
    if (!(a.presence > 0.5 && b.presence > 0.5)) {
      st.closeness = approach(st.closeness, 0, 1 / 30, 0.5);
      return;
    }
    const L = this.arms.left.pos, R = this.arms.right.pos;
    const d = norm(sub(L, R)) / sw;
    st.wristDistance = d;
    st.closeness = clamp(1 - d / (3 * p.meet_distance), 0, 1);
    const mid = [(a.pos[0] + b.pos[0]) / 2, (a.pos[1] + b.pos[1]) / 2];
    const s = Math.max(a.speedN, b.speedN, 0.3);

    // incrocio: l'ordine dei polsi è invertito rispetto a quello delle spalle
    if (armObs.left && armObs.right) {
      const shSign = Math.sign(armObs.left.shoulder.x - armObs.right.shoulder.x);
      const rel = ((L[0] - R[0]) / sw) * shSign;
      const m = p.cross_margin;
      if (!this.crossed && rel < -m) { this.crossed = true; events.push({ kind: "cross", side: null, pos: mid, strength: s, data: {} }); }
      else if (this.crossed && rel > m) { this.crossed = false; events.push({ kind: "uncross", side: null, pos: mid, strength: s, data: {} }); }
    }
    st.crossed = this.crossed;

    const md = p.meet_distance;
    if (!this.met && d < md) { this.met = true; events.push({ kind: "meet", side: null, pos: mid, strength: s, data: {} }); }
    else if (this.met && d > md * 1.4) { this.met = false; events.push({ kind: "part", side: null, pos: mid, strength: s, data: {} }); }
  }
}
