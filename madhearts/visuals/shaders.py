"""Shader GLSL 330 (compatibili con OpenGL 4.1 core di macOS)."""

FULLSCREEN_VS = """
#version 330
in vec2 in_pos;
out vec2 uv;
void main() { uv = in_pos * 0.5 + 0.5; gl_Position = vec4(in_pos, 0.0, 1.0); }
"""

# --- Simulazione dell'onda (equazione delle onde 2D). R = altezza, G = altezza precedente.
WAVE_STEP_FS = """
#version 330
#define MAX_SRC 24
uniform sampler2D state;
uniform vec2 texel;
uniform float k;          // (c*dt/dx)^2, < 0.5 per stabilità
uniform float damping;
uniform float aspect;
uniform int n_src;
uniform vec4 src[MAX_SRC];   // x, y, raggio, ampiezza
in vec2 uv;
out vec2 o;
void main() {
    vec2 s = texture(state, uv).rg;
    float h = s.r, hp = s.g;
    float lap = texture(state, uv + vec2(texel.x, 0)).r + texture(state, uv - vec2(texel.x, 0)).r
              + texture(state, uv + vec2(0, texel.y)).r + texture(state, uv - vec2(0, texel.y)).r - 4.0 * h;
    // bordi assorbenti: niente riflessioni secche ai margini dello schermo
    vec2 e = min(uv, 1.0 - uv);
    float edge = smoothstep(0.0, 0.06, min(e.x, e.y));
    float hn = (2.0 * h - hp + k * lap) * mix(0.9, damping, edge);
    hn = mix(hn, h + lap * 0.25, 0.015);   // leggera diffusione: niente rumore a scacchiera
    for (int i = 0; i < n_src; i++) {
        vec2 d = (uv - src[i].xy) * vec2(aspect, 1.0);
        hn += src[i].w * exp(-dot(d, d) / (src[i].z * src[i].z));
    }
    o = vec2(clamp(hn, -4.0, 4.0), h);
}
"""

# --- Colore trasportato dalle onde ("tinta"): ogni braccio colora le proprie onde,
#     dove le onde si incontrano i colori si mescolano.
DYE_FS = """
#version 330
#define MAX_SRC 24
uniform sampler2D dye;
uniform sampler2D wave;
uniform vec2 texel;
uniform float decay;
uniform float aspect;
uniform int n_src;
uniform vec4 src[MAX_SRC];     // x, y, raggio, intensità
uniform vec3 src_col[MAX_SRC];
in vec2 uv;
out vec4 o;
void main() {
    // la tinta si allarga lentamente seguendo il fronte d'onda
    float gx = texture(wave, uv + vec2(texel.x, 0)).r - texture(wave, uv - vec2(texel.x, 0)).r;
    float gy = texture(wave, uv + vec2(0, texel.y)).r - texture(wave, uv - vec2(0, texel.y)).r;
    vec2 adv = vec2(gx, gy) * texel * 6.0;
    vec3 c = texture(dye, uv - adv).rgb * 0.6;
    c += (texture(dye, uv + vec2(texel.x, 0)).rgb + texture(dye, uv - vec2(texel.x, 0)).rgb
        + texture(dye, uv + vec2(0, texel.y)).rgb + texture(dye, uv - vec2(0, texel.y)).rgb) * 0.1;
    c *= decay;
    for (int i = 0; i < n_src; i++) {
        vec2 d = (uv - src[i].xy) * vec2(aspect, 1.0);
        float w = exp(-dot(d, d) / (src[i].z * src[i].z)) * src[i].w;
        c = mix(c, src_col[i], clamp(w, 0.0, 1.0));
    }
    o = vec4(c, 1.0);
}
"""

# --- Filamenti: nastri con sezione gaussiana, sommati in modo additivo.
RIBBON_VS = """
#version 330
in vec2 in_pos;      // 0..1, y verso l'alto
in vec3 in_col;
in float in_alpha;
in float in_v;       // -1..1 attraverso il nastro
in float in_u;       // lungo il nastro (ancorato alla strada percorsa)
in float in_dry;     // 0 = pennello carico, 1 = pennello secco
out vec3 col;
out float alpha;
out float v;
out float u;
out float dry;
void main() {
    col = in_col; alpha = in_alpha; v = in_v; u = in_u; dry = in_dry;
    gl_Position = vec4(in_pos * 2.0 - 1.0, 0.0, 1.0);
}
"""
RIBBON_FS = """
#version 330
uniform sampler2D brush;
uniform float brush_amount;
in vec3 col;
in float alpha;
in float v;
in float u;
in float dry;
out vec4 o;
void main() {
    float soft = exp(-v * v * 3.0) * 0.55 + exp(-v * v * 40.0) * 1.2;
    float b = texture(brush, vec2(u, v * 0.5 + 0.5)).r;
    // verso la coda il pennello si "secca": restano solo le setole più cariche
    float t0 = dry * 0.55;
    b = smoothstep(t0, t0 + 0.3, b);
    float painted = b * (0.85 + 0.25 * exp(-v * v * 6.0));
    o = vec4(col * alpha * mix(soft, painted, brush_amount), 1.0);
}
"""

# --- Scie: il fotogramma precedente sfuma e viene leggermente trascinato dalle onde.
TRAIL_FS = """
#version 330
uniform sampler2D prev;
uniform sampler2D light;
uniform sampler2D wave;
uniform vec2 wave_texel;
uniform float decay;
uniform float flow;
uniform float trail_max;
in vec2 uv;
out vec4 o;
void main() {
    float gx = texture(wave, uv + vec2(wave_texel.x, 0)).r - texture(wave, uv - vec2(wave_texel.x, 0)).r;
    float gy = texture(wave, uv + vec2(0, wave_texel.y)).r - texture(wave, uv - vec2(0, wave_texel.y)).r;
    vec2 disp = vec2(gx, gy) * flow * 0.004;
    vec3 c = texture(prev, uv - disp).rgb * decay;
    vec3 l = texture(light, uv).rgb;
    // accumulo "max": la scia è solo un'eco che si spegne, non si somma alla luce nuova
    o = vec4(mix(c + l, max(c, l), trail_max), 1.0);
}
"""

# --- Strato delle onde: creste luminose, lisciate nel tempo.
WAVELAYER_FS = """
#version 330
uniform sampler2D prev;
uniform float blend;
uniform sampler2D wave;
uniform sampler2D dye;
uniform sampler2D palette;
uniform vec2 wave_texel;
uniform float wave_gain;
uniform float phase_step;
uniform float ring_sharpness;
uniform vec3 calm_zone[2];   // x, y, raggio: attorno alle mani le onde non pulsano
uniform float aspect;
uniform float time;
in vec2 uv;
out vec4 o;
void main() {
    vec2 w = texture(wave, uv).rg;
    float h = w.r;
    // inviluppo locale dell'onda (ampiezza indipendente dalla fase)
    float env = sqrt(h * h + pow((w.r - w.g) / phase_step, 2.0));
    float n = h / max(env, 1e-4);                     // -1..1 lungo l'onda
    // solo la cresta diventa una linea di luce sottile; dove l'acqua è calma resta il nero
    float line = pow(0.5 + 0.5 * n, ring_sharpness);
    float strength = smoothstep(0.015, 0.5, env) * min(env * 1.8, 1.4);
    vec3 tint = texture(dye, uv).rgb;
    float tl = length(tint);
    vec3 pal = texture(palette, vec2(fract(0.5 + time * 0.01), 0.5)).rgb;
    vec3 colr = mix(pal * 0.6, tint / max(tl, 1e-3), clamp(tl * 4.0, 0.0, 1.0));
    float quiet = 1.0;
    for (int i = 0; i < 2; i++) {
        vec2 d = (uv - calm_zone[i].xy) * vec2(aspect, 1.0);
        quiet *= mix(0.35, 1.0, smoothstep(0.0, calm_zone[i].z, length(d)));
    }
    vec3 wc = colr * (line * 0.9 + 0.08) * strength * wave_gain * quiet;
    // media nel tempo: gli anelli scorrono morbidi invece di battere
    o = vec4(mix(texture(prev, uv).rgb, wc, blend), 1.0);
}
"""


# --- Composizione: sfondo + scie + onde.
COMPOSE_FS = """
#version 330
uniform sampler2D trail;
uniform sampler2D wavelayer;
uniform sampler2D sphere;
uniform float occlusion;
uniform vec3 background;
in vec2 uv;
out vec4 o;
void main() {
    // primo piano: la scia (e le onde); sfondo: la sfera, che la scia copre in parte
    vec3 front = texture(trail, uv).rgb + texture(wavelayer, uv).rgb;
    float L = max(front.r, max(front.g, front.b));
    vec3 back = texture(sphere, uv).rgb * (1.0 - occlusion * clamp(L * 1.5, 0.0, 1.0));
    o = vec4(background + back + front, 1.0);
}
"""

DOWNSAMPLE_FS = """
#version 330
uniform sampler2D src;
uniform vec2 texel;
uniform float threshold;
in vec2 uv;
out vec4 o;
void main() {
    vec3 c = (texture(src, uv + texel * vec2(-1, -1)).rgb + texture(src, uv + texel * vec2(1, -1)).rgb
            + texture(src, uv + texel * vec2(-1, 1)).rgb + texture(src, uv + texel * vec2(1, 1)).rgb) * 0.25;
    float l = max(c.r, max(c.g, c.b));
    o = vec4(c * smoothstep(threshold, threshold + 0.4, l), 1.0);
}
"""

BLUR_FS = """
#version 330
uniform sampler2D src;
uniform vec2 dir;    // texel * direzione
in vec2 uv;
out vec4 o;
void main() {
    vec3 c = texture(src, uv).rgb * 0.227;
    c += (texture(src, uv + dir * 1.385).rgb + texture(src, uv - dir * 1.385).rgb) * 0.316;
    c += (texture(src, uv + dir * 3.231).rgb + texture(src, uv - dir * 3.231).rgb) * 0.070;
    o = vec4(c, 1.0);
}
"""

FINAL_FS = """
#version 330
uniform sampler2D scene;
uniform sampler2D bloom1;
uniform sampler2D bloom2;
uniform float bloom;
uniform float exposure;
uniform float vignette;
in vec2 uv;
out vec4 o;
void main() {
    vec3 c = texture(scene, uv).rgb + (texture(bloom1, uv).rgb * 0.6 + texture(bloom2, uv).rgb * 0.9) * bloom;
    // tone mapping sulla luminosità: il colore resta quello della palette, non vira al bianco
    float L = max(c.r, max(c.g, c.b));
    c *= (1.0 - exp(-L * exposure)) / max(L, 1e-4);
    vec2 d = uv - 0.5;
    c *= 1.0 - vignette * dot(d, d) * 1.6;
    o = vec4(pow(max(c, 0.0), vec3(1.0 / 2.2)), 1.0);
}
"""
