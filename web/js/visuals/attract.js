// MadHearts web — strato di attesa (traduzione di madhearts/attract.py): logo piccolo in un angolo,
// invito a partecipare (compare in attesa o quando nessuno è presente da qualche secondo) e
// dissolvenza al nero per avvio e pausa.

import { program, setUniforms, bindTex } from "./gl.js";

export const ATTRACT_DEFAULTS = {
  logo_file: "assets/logo.png", logo_corner: "bottom-right", logo_height: 0.06, logo_opacity: 0.6, logo_margin: 0.03,
  invite_text: "AVVICINATI E INTRECCIA IL TUO FILO", invite_subtext: "ogni gesto diventa parte della sfera",
  invite_size: 0.045, invite_y: 0.92, invite_color: "#FFFFFF", invite_opacity: 0.75, invite_delay: 6.0, invite_fade: 1.5,
};

const VS = `#version 300 es
layout(location = 0) in vec2 in_pos;
uniform vec4 rect;                // x0, y0, x1, y1 in coordinate schermo -1..1
out vec2 uv;
void main() {
  uv = in_pos * 0.5 + 0.5;
  gl_Position = vec4(mix(rect.xy, rect.zw, uv), 0.0, 1.0);
}`;
const FS = `#version 300 es
precision highp float;
uniform sampler2D tex; uniform float alpha; uniform vec4 solid;
in vec2 uv; out vec4 o;
void main() {
  if (solid.a > 0.0) { o = vec4(solid.rgb * solid.a, solid.a); return; }
  vec4 c = texture(tex, vec2(uv.x, 1.0 - uv.y));     // premoltiplicata
  o = c * alpha;
}`;

export class Attract {
  constructor(gl, quad) {
    this.gl = gl;
    this.quad = quad;
    this.prog = program(gl, VS, FS);
    this.tex = {};
    this.inviteAlpha = 0;
    this.emptyTime = 0;
    this.black = 1;                // parte dal nero e si apre in dissolvenza
    this.blackTarget = 0;
    this.t = 0;
    this.key = null;
    this.p = { ...ATTRACT_DEFAULTS };
  }

  async configure(cfg, size) {
    this.p = { ...ATTRACT_DEFAULTS, ...(cfg.attract || {}) };
    this.size = size;
    const p = this.p;
    const key = JSON.stringify([p.logo_file, p.logo_height, p.invite_text, p.invite_subtext, p.invite_size, p.invite_color, size]);
    if (key === this.key) return;
    this.key = key;
    await Promise.all([document.fonts.load('40px "League Gothic"'), document.fonts.load('20px "DM Sans"')]).catch(() => {});
    const H = size[1];
    this.tex.invite = p.invite_text ? this._text(p.invite_text, `${Math.round(H * p.invite_size)}px "League Gothic", sans-serif`, p.invite_color) : null;
    this.tex.sub = p.invite_subtext ? this._text(p.invite_subtext, `${Math.round(H * p.invite_size * 0.42)}px "DM Sans", sans-serif`, p.invite_color) : null;
    this.tex.logo = null;
    if (p.logo_file) {
      try {
        const img = new Image();
        img.src = p.logo_file;
        await img.decode();
        const h = Math.max(Math.round(H * p.logo_height), 8), w = Math.round((img.width * h) / img.height);
        const c = new OffscreenCanvas(w, h), g = c.getContext("2d");
        g.imageSmoothingQuality = "high";
        g.drawImage(img, 0, 0, w, h);
        this.tex.logo = this._upload(c);
      } catch (e) { console.warn("logo non disponibile", e); }
    }
  }

  _text(text, font, color) {
    const m = new OffscreenCanvas(4, 4).getContext("2d");
    m.font = font;
    const mt = m.measureText(text);
    const w = Math.ceil(mt.width) + 8, h = Math.ceil((mt.actualBoundingBoxAscent + mt.actualBoundingBoxDescent) * 1.3) + 8;
    const c = new OffscreenCanvas(w, h), g = c.getContext("2d");
    g.font = font; g.fillStyle = color; g.textBaseline = "middle";
    g.fillText(text, 4, h / 2);
    return this._upload(c);
  }

  _upload(canvas) {
    const gl = this.gl, tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, canvas);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    return { tex, w: canvas.width, h: canvas.height };
  }

  fadeToBlack(on) { this.blackTarget = on ? 1 : 0; }

  update(dt, playing, presence) {
    const p = this.p;
    this.t += dt;
    this.emptyTime = presence < 0.2 ? this.emptyTime + dt : 0;
    const target = !playing || this.emptyTime >= p.invite_delay ? 1 : 0;
    const step = dt / Math.max(p.invite_fade, 0.05);
    this.inviteAlpha = target > this.inviteAlpha ? Math.min(this.inviteAlpha + step, target) : Math.max(this.inviteAlpha - step * 1.5, target);
    const sb = dt / 1.2;
    this.black = this.blackTarget > this.black ? Math.min(this.black + sb, this.blackTarget) : Math.max(this.black - sb, this.blackTarget);
  }

  _quad(t, x, y, a) {            // x, y = angolo in basso a sinistra, in pixel
    const gl = this.gl, [sw, sh] = this.size;
    const x0 = -1 + (2 * x) / sw, y0 = -1 + (2 * y) / sh;
    setUniforms(gl, this.prog, { tex: bindTex(gl, 0, t.tex), alpha: a, solid: [0, 0, 0, 0], rect: [x0, y0, x0 + (2 * t.w) / sw, y0 + (2 * t.h) / sh] });
    this.quad.draw();
  }

  draw() {
    const gl = this.gl, p = this.p, [sw, sh] = this.size;
    gl.useProgram(this.prog.p);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    if (this.tex.logo && p.logo_opacity > 0) {
      const t = this.tex.logo, m = sh * p.logo_margin, c = p.logo_corner;
      this._quad(t, c.includes("left") ? m : sw - t.w - m, c.includes("top") ? sh - t.h - m : m, p.logo_opacity);
    }
    const a = this.inviteAlpha * p.invite_opacity * (0.85 + 0.15 * Math.sin(this.t * 0.8));   // respira piano
    if (a > 0.003) {
      const y = sh * (1 - p.invite_y);
      if (this.tex.invite) this._quad(this.tex.invite, (sw - this.tex.invite.w) / 2, y, a);
      if (this.tex.sub) this._quad(this.tex.sub, (sw - this.tex.sub.w) / 2, y - this.tex.sub.h * 1.2, a * 0.8);
    }
    if (this.black > 0.002) {
      setUniforms(gl, this.prog, { solid: [0, 0, 0, this.black], rect: [-1, -1, 1, 1] });
      this.quad.draw();
    }
    gl.disable(gl.BLEND);
  }
}
