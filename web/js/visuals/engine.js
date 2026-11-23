// MadHearts web — motore visivo (traduzione di madhearts/visuals/engine.py, versione attuale).
// Primo piano: la scia del gesto, una pennellata bianca che si dissolve in pochi secondi.
// Sfondo: la sfera ad anelli, che cresce di un anello per ogni persona che finisce di intrecciare.
// Le luci sovrapposte non si sommano (resta la più luminosa), il colore non vira al bianco.

import { program, setUniforms, fullscreenQuad, target, bindTarget, bindTex } from "./gl.js";
import { strip, interp, normals, FLOATS } from "./geometry.js";
import { brushTexture } from "./brush.js";
import { RingSphere } from "./sphere.js";
import { SIDES } from "../common.js";

export const VISUAL_DEFAULTS = {
  background: "#000000", render_scale: 1.0, response_intensity: 1.0, fade_speed: 1.0,
  input_zoom: 1.3, input_center_x: 0.5, input_center_y: 0.5,
  trail_color: "#FFFFFF", filaments_per_arm: 1, filament_length: 3.0, filament_width: 0.035, filament_brightness: 0.8,
  filament_wave_amplitude: 0.02, filament_wavelength: 0.35, filament_wave_speed: 0.15, filament_spread: 0.03,
  filament_tail_fade: 1.6, trail_duration: 0.1, brush_amount: 1.0, brush_scale: 2.5, brush_dryness: 0.8, calm: 0.35,
  sphere_enabled: true, sphere_x: 0.5, sphere_y: 0.5, sphere_radius: 0.34, sphere_rotation_speed: 0.06, sphere_tilt: 18.0,
  sphere_perspective: 3.5, sphere_depth: 0.7, sphere_white: "#FFFFFF", initial_rings: 1, max_rings: 48, ring_cooldown: 1.0,
  ring_white_time: 6.0, ring_shades: ["#9E1C22", "#C9262C", "#F5383C", "#FF5C5F", "#FF8485", "#FFB0AE", "#FFD6D2"],
  ring_shade_center: 0.4, ring_shade_spread: 0.22, ring_white_every: 0, ring_grow_time: 2.0, ring_fade_out: 6.0,
  ring_width: 0.006, ring_brightness: 0.8, ring_dryness: 0.25, trail_occlusion: 0.7,
  bloom_intensity: 0.35, bloom_threshold: 0.45, exposure: 1.5, vignette: 0.35,
};

export const hexToRgb = (h) => { h = h.replace("#", ""); return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255); };
const lin = (c) => c.map((x) => Math.pow(x, 2.2));        // sRGB -> lineare

// ---------------------------------------------------------------- shader (GLSL ES 3.00)
const QUAD_VS = `#version 300 es
layout(location = 0) in vec2 in_pos;
out vec2 uv;
void main() { uv = in_pos * 0.5 + 0.5; gl_Position = vec4(in_pos, 0.0, 1.0); }`;

const RIBBON_VS = `#version 300 es
layout(location = 0) in vec2 in_pos;
layout(location = 1) in vec3 in_col;
layout(location = 2) in float in_alpha;
layout(location = 3) in float in_v;
layout(location = 4) in float in_u;
layout(location = 5) in float in_dry;
out vec3 col; out float alpha; out float v; out float u; out float dry;
void main() {
  col = in_col; alpha = in_alpha; v = in_v; u = in_u; dry = in_dry;
  gl_Position = vec4(in_pos * 2.0 - 1.0, 0.0, 1.0);
}`;

const RIBBON_FS = `#version 300 es
precision highp float;
uniform sampler2D brush;
uniform float brush_amount;
in vec3 col; in float alpha; in float v; in float u; in float dry;
out vec4 o;
void main() {
  float soft = exp(-v * v * 3.0) * 0.55 + exp(-v * v * 40.0) * 1.2;
  float b = texture(brush, vec2(u, v * 0.5 + 0.5)).r;
  float t0 = dry * 0.55;                              // verso la coda il pennello si "secca"
  b = smoothstep(t0, t0 + 0.3, b);
  float painted = b * (0.85 + 0.25 * exp(-v * v * 6.0));
  o = vec4(col * alpha * mix(soft, painted, brush_amount), 1.0);
}`;

const TRAIL_FS = `#version 300 es
precision highp float;
uniform sampler2D prev; uniform sampler2D light; uniform float decay;
in vec2 uv; out vec4 o;
void main() {
  vec3 c = texture(prev, uv).rgb * decay;
  vec3 l = texture(light, uv).rgb;
  o = vec4(max(c, l), 1.0);                           // la scia è un'eco che si spegne, non si somma
}`;

const COMPOSE_FS = `#version 300 es
precision highp float;
uniform sampler2D trail; uniform sampler2D sphere; uniform float occlusion; uniform vec3 background;
in vec2 uv; out vec4 o;
void main() {
  vec3 front = texture(trail, uv).rgb;
  float L = max(front.r, max(front.g, front.b));
  vec3 back = texture(sphere, uv).rgb * (1.0 - occlusion * clamp(L * 1.5, 0.0, 1.0));
  o = vec4(background + back + front, 1.0);
}`;

const DOWN_FS = `#version 300 es
precision highp float;
uniform sampler2D src; uniform vec2 texel; uniform float threshold;
in vec2 uv; out vec4 o;
void main() {
  vec3 c = (texture(src, uv + texel * vec2(-1, -1)).rgb + texture(src, uv + texel * vec2(1, -1)).rgb
          + texture(src, uv + texel * vec2(-1, 1)).rgb + texture(src, uv + texel * vec2(1, 1)).rgb) * 0.25;
  float l = max(c.r, max(c.g, c.b));
  o = vec4(c * smoothstep(threshold, threshold + 0.4, l), 1.0);
}`;

const BLUR_FS = `#version 300 es
precision highp float;
uniform sampler2D src; uniform vec2 dir;
in vec2 uv; out vec4 o;
void main() {
  vec3 c = texture(src, uv).rgb * 0.227;
  c += (texture(src, uv + dir * 1.385).rgb + texture(src, uv - dir * 1.385).rgb) * 0.316;
  c += (texture(src, uv + dir * 3.231).rgb + texture(src, uv - dir * 3.231).rgb) * 0.070;
  o = vec4(c, 1.0);
}`;

const FINAL_FS = `#version 300 es
precision highp float;
uniform sampler2D scene; uniform sampler2D bloom1; uniform sampler2D bloom2;
uniform float bloom; uniform float exposure; uniform float vignette;
in vec2 uv; out vec4 o;
void main() {
  vec3 c = texture(scene, uv).rgb + (texture(bloom1, uv).rgb * 0.6 + texture(bloom2, uv).rgb * 0.9) * bloom;
  float L = max(c.r, max(c.g, c.b));                  // tone mapping sulla luminosità: il colore resta quello
  c *= (1.0 - exp(-L * exposure)) / max(L, 1e-4);
  vec2 d = uv - 0.5;
  c *= 1.0 - vignette * dot(d, d) * 1.6;
  o = vec4(pow(max(c, 0.0), vec3(1.0 / 2.2)), 1.0);
}`;

// ---------------------------------------------------------------- motore
export class VisualEngine {
  constructor(gl, size, cfg) {
    this.gl = gl;
    this.t = 0;
    this.arms = Object.fromEntries(SIDES.map((s) => [s, { hist: [], seg: -1, pos: null, presence: 0, speedN: 0, speedS: 0, amplitude: 0, dist: 0 }]));
    this.sphere = new RingSphere();
    this.quad = fullscreenQuad(gl);
    this.progs = {
      trail: program(gl, QUAD_VS, TRAIL_FS), compose: program(gl, QUAD_VS, COMPOSE_FS), down: program(gl, QUAD_VS, DOWN_FS),
      blur: program(gl, QUAD_VS, BLUR_FS), final: program(gl, QUAD_VS, FINAL_FS), ribbon: program(gl, RIBBON_VS, RIBBON_FS),
    };
    // buffer dei nastri
    this.vao = gl.createVertexArray();
    this.vbo = gl.createBuffer();
    gl.bindVertexArray(this.vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vbo);
    const stride = FLOATS * 4;
    [[0, 2, 0], [1, 3, 2], [2, 1, 5], [3, 1, 6], [4, 1, 7], [5, 1, 8]].forEach(([loc, n, off]) => {
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, n, gl.FLOAT, false, stride, off * 4);
    });
    gl.bindVertexArray(null);
    // texture del pennello
    const b = brushTexture();
    this.brush = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, this.brush);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.R8, b.w, b.h, 0, gl.RED, gl.UNSIGNED_BYTE, b.data);
    gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    this.configure(cfg);
    this.resize(size);
  }

  configure(cfg) {
    this.p = { ...VISUAL_DEFAULTS, ...(cfg.visuals || {}) };
    this.background = lin(hexToRgb(this.p.background));
    this.white = lin(hexToRgb(this.p.sphere_white));
    this.trailCol = this.p.trail_color ? lin(hexToRgb(this.p.trail_color)) : [1, 1, 1];
    this.shades = this.p.ring_shades.map(hexToRgb);
  }

  // tonalità degli anelli: gradiente tra i colori di ring_shades (0 = primo, 1 = ultimo), in lineare
  shade(x) {
    const c = this.shades;
    if (c.length === 1) return lin(c[0]);
    const f = Math.min(Math.max(x, 0), 1) * (c.length - 1), i = Math.min(Math.floor(f), c.length - 2), k = f - i;
    return lin([0, 1, 2].map((j) => c[i][j] * (1 - k) + c[i + 1][j] * k));
  }

  resize([w, h]) {
    const gl = this.gl;
    this.size = [w, h];
    this.aspect = w / h;
    const s = this.p.render_scale, rw = Math.max(64, Math.round(w * s)), rh = Math.max(64, Math.round(h * s));
    for (const t of this.targets || []) t.release();
    const T = (a, b) => target(gl, a, b);
    this.light = T(rw, rh); this.sphereLayer = T(rw, rh); this.scene = T(rw, rh);
    this.trail = [T(rw, rh), T(rw, rh)];
    this.half = [T(rw >> 1, rh >> 1), T(rw >> 1, rh >> 1)];
    this.quarter = [T(rw >> 2, rh >> 2), T(rw >> 2, rh >> 2)];
    this.targets = [this.light, this.sphereLayer, this.scene, ...this.trail, ...this.half, ...this.quarter];
  }

  _map(p) {
    const P = this.p, z = P.input_zoom;
    return [0.5 + (p[0] - P.input_center_x) * z, 1 - (0.5 + (p[1] - P.input_center_y) * z)];
  }

  // motion: stato del movimento (o null in pausa); restituisce true se è nato un anello
  update(motion, dt) {
    this.t += dt;
    const t = this.t, P = this.p, resp = P.response_intensity;
    let ringAdded = false;
    for (const side of SIDES) {
      const av = this.arms[side], am = motion ? motion.arms[side] : null;
      if (!am || (am.presence <= 0.005 && am.state === "lost")) {
        av.presence = am ? am.presence : av.presence * Math.exp(-dt / 0.5);
        av.speedN *= Math.exp(-dt / 0.3);
        av.speedS *= Math.exp(-dt / Math.max(P.calm, 0.05));
        if (av.hist.length) { const l = av.hist.at(-1); av.hist.push([t, l[1], l[2], av.speedS, 0, av.presence, av.dist]); }
      } else {
        const tg = this._map(am.pos);
        if (am.segmentId !== av.seg || !av.pos) { av.seg = am.segmentId; av.hist = []; av.pos = [...tg]; }
        const prev = [...av.pos], k0 = 1 - Math.exp(-dt / 0.035);
        av.pos = [av.pos[0] + (tg[0] - av.pos[0]) * k0, av.pos[1] + (tg[1] - av.pos[1]) * k0];
        av.dist += Math.hypot((av.pos[0] - prev[0]) * this.aspect, av.pos[1] - prev[1]);
        av.presence = am.presence;
        av.speedN = am.speedN * resp;
        const k = 1 - Math.exp(-dt / Math.max(P.calm, 0.05));
        av.speedS += k * (av.speedN - av.speedS);
        av.amplitude += k * (am.amplitude * resp - av.amplitude);
        av.hist.push([t, av.pos[0], av.pos[1], av.speedS, av.amplitude, av.presence, av.dist]);
      }
      while (av.hist.length && t - av.hist[0][0] > P.filament_length) av.hist.shift();
    }
    if (motion) {
      for (const e of motion.events) {
        if (e.kind === "complete" && P.sphere_enabled) {      // filo completato: un nuovo anello entra nella sfera
          ringAdded = this.sphere.addFromGesture(t, e.data.angle, e.strength, P) || ringAdded;
        }
      }
    }
    if (P.sphere_enabled) this.sphere.update(t, P);
    return ringAdded;
  }

  _filaments(out) {
    const P = this.p, t = this.t, n = P.filaments_per_arm;
    for (const av of Object.values(this.arms)) {
      if (av.hist.length < 4 || av.presence < 0.01) continue;
      const h = [...av.hist].reverse();                       // 0 = mano, poi indietro nel tempo
      const arc = [0];
      for (let i = 1; i < h.length; i++) arc.push(arc[i - 1] + Math.hypot((h[i][1] - h[i - 1][1]) * this.aspect, h[i][2] - h[i - 1][2]));
      const total = arc.at(-1);
      if (total < 0.01) continue;
      const m = 64, col = (c) => h.map((r) => r[c]);
      const cols = [0, 1, 2, 3, 4, 5, 6].map(col);
      const u = Array.from({ length: m }, (_, i) => (total * i) / (m - 1));
      const I = (c) => u.map((x) => interp(x, arc, cols[c]));
      const T0 = I(0), px = I(1), py = I(2), spd = I(3), amp = I(4), pres = I(5), dist = I(6);
      const s = Array.from({ length: m }, (_, i) => i / (m - 1));          // 0 = mano, 1 = coda
      const age = T0.map((x) => Math.min(Math.max((t - x) / Math.max(P.filament_length, 1e-3), 0), 1));
      let base = px.map((x, i) => [x, py[i]]);
      const sm = base.map((q) => [...q]);                                  // leggera levigatura del percorso
      for (let i = 1; i < m - 1; i++) for (let c = 0; c < 2; c++) sm[i][c] = 0.25 * base[i - 1][c] + 0.5 * base[i][c] + 0.25 * base[i + 1][c];
      base = sm;
      const nrm = normals(base, this.aspect);
      for (let j = 0; j < n; j++) {
        const fj = 1 + 0.35 * Math.sin(j * 1.7), phi = j * 2.399;
        const line = [], alpha = [], width = [], dry = [], uu = [];
        for (let i = 0; i < m; i++) {
          const ampS = P.filament_wave_amplitude * (0.25 + amp[i] * 1.2 + spd[i] * 0.8) * Math.pow(s[i], 0.6);
          // ondulazione ancorata alla strada percorsa: scorre piano, non "nuota" con la mano
          let off = ampS * Math.sin(2 * Math.PI * (dist[i] / P.filament_wavelength) * fj - t * P.filament_wave_speed * 2 * Math.PI * fj + phi);
          off += P.filament_spread * (j / Math.max(n - 1, 1) - 0.5) * s[i] * (0.5 + amp[i]);
          line.push([base[i][0] + (nrm[i][0] * off) / this.aspect, base[i][1] + nrm[i][1] * off]);
          const still = Math.min(Math.max((spd[i] - 0.12) / 0.25, 0), 1);   // mano ferma = nessuna traccia
          alpha.push(pres[i] * still * Math.pow(1 - age[i], P.filament_tail_fade) * (0.45 + 0.55 * Math.min(Math.max(spd[i], 0), 1))
            * (0.3 + 0.7 * Math.pow(s[i], 0.4)) * P.filament_brightness);
          width.push(P.filament_width * (0.7 + 0.5 * Math.min(Math.max(spd[i], 0), 1)) * (1 - 0.45 * age[i]));
          dry.push(age[i] * P.brush_dryness);
          uu.push(dist[i] * P.brush_scale + j * 0.37);
        }
        strip(out, line, width, this.trailCol, alpha, this.aspect, { u: uu, dry });
      }
    }
  }

  _drawRibbons(verts) {
    if (!verts.length) return;
    const gl = this.gl, P = this.p, pr = this.progs.ribbon;
    gl.useProgram(pr.p);
    setUniforms(gl, pr, { brush: bindTex(gl, 5, this.brush), brush_amount: P.brush_amount });
    gl.bindVertexArray(this.vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vbo);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(verts), gl.DYNAMIC_DRAW);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE);
    gl.blendEquation(gl.MAX);                                  // sovrapposizioni: resta la più luminosa
    gl.drawArrays(gl.TRIANGLES, 0, verts.length / FLOATS);
    gl.blendEquation(gl.FUNC_ADD);
    gl.disable(gl.BLEND);
    gl.bindVertexArray(null);
  }

  _pass(name, dst, uniforms) {
    const gl = this.gl, pr = this.progs[name];
    bindTarget(gl, dst);
    gl.useProgram(pr.p);
    setUniforms(gl, pr, uniforms);
    this.quad.draw();
  }

  render(dt, screenSize) {
    const gl = this.gl, P = this.p;
    gl.disable(gl.BLEND);
    // 1. scia -> strato luce
    bindTarget(gl, this.light);
    gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
    const v1 = []; this._filaments(v1); this._drawRibbons(v1);
    // 2. sfera -> strato di sfondo
    bindTarget(gl, this.sphereLayer);
    gl.clear(gl.COLOR_BUFFER_BIT);
    if (P.sphere_enabled) { const v2 = []; this.sphere.geometry(v2, this.t, P, this.aspect, (x) => this.shade(x), this.white); this._drawRibbons(v2); }
    // 3. eco della scia
    this._pass("trail", this.trail[1], { prev: bindTex(gl, 0, this.trail[0].tex), light: bindTex(gl, 1, this.light.tex),
      decay: Math.exp((-dt * P.fade_speed) / Math.max(P.trail_duration, 0.02)) });
    this.trail.reverse();
    // 4. composizione: la scia in primo piano copre in parte la sfera
    this._pass("compose", this.scene, { trail: bindTex(gl, 0, this.trail[0].tex), sphere: bindTex(gl, 1, this.sphereLayer.tex),
      occlusion: P.trail_occlusion, background: this.background });
    // 5. bagliore
    const down = (src, dst, th) => this._pass("down", dst, { src: bindTex(gl, 0, src.tex), texel: [0.5 / src.w, 0.5 / src.h], threshold: th });
    const blur = ([a, b]) => {
      this._pass("blur", b, { src: bindTex(gl, 0, a.tex), dir: [1 / a.w, 0] });
      this._pass("blur", a, { src: bindTex(gl, 0, b.tex), dir: [0, 1 / b.h] });
    };
    down(this.scene, this.half[0], P.bloom_threshold); blur(this.half);
    down(this.half[0], this.quarter[0], 0); blur(this.quarter);
    // 6. uscita sullo schermo
    bindTarget(gl, null);
    gl.viewport(0, 0, screenSize[0], screenSize[1]);
    this._pass("final", null, { scene: bindTex(gl, 0, this.scene.tex), bloom1: bindTex(gl, 1, this.half[0].tex),
      bloom2: bindTex(gl, 2, this.quarter[0].tex), bloom: P.bloom_intensity, exposure: P.exposure, vignette: P.vignette });
  }
}

