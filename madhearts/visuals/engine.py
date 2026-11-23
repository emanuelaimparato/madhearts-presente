"""Motore visivo di MadHearts.

Tre strati che reagiscono al gesto, sommati come luce su fondo nero:

1. ONDE — una superficie d'acqua simulata (equazione delle onde su GPU).
   Ogni polso è una sorgente che vibra più forte e più in fretta quanto più
   il braccio è veloce; muovendosi lascia una scia d'onda nella direzione del
   gesto. Le onde delle due braccia si incontrano e interferiscono davvero,
   creando forme nuove. Ogni braccio tinge le proprie onde del suo colore.

2. FILAMENTI — fasci di nastri luminosi che escono dalla mano e seguono il
   percorso del braccio, ondeggiando con un'ampiezza legata all'ampiezza del
   gesto. Le scie sfumano lentamente e vengono trascinate dalle onde.

3. FILI — ogni "tratto" (portare il filo da un anello all'altro) lascia un
   filo di luce sottile, ancorato ai due estremi, che resta sospeso a lungo e
   si dissolve piano: i gesti di ognuno si accumulano in una trama collettiva.
   Quando le braccia si incrociano nasce un nodo di luce.

Quando la persona si ferma, le sorgenti tacciono e tutto si placa e si
dissolve con i propri tempi: nulla si interrompe di colpo.
"""
from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass, field

import moderngl
import numpy as np

from ..motion import MotionState
from ..tracking import SIDES
from . import palette as pal
from . import shaders as sh
from .sphere import RingSphere

MAX_SRC = 24
VBO_BYTES = 8 * 1024 * 1024


@dataclass
class Thread:
    pts: np.ndarray          # (K,2) uv
    color: np.ndarray
    born: float
    strength: float
    seed: float


@dataclass
class Knot:
    x: float
    y: float
    born: float
    strength: float
    colors: tuple
    spin: float


@dataclass
class Pulse:
    x: float
    y: float
    strength: float
    born: float
    color: np.ndarray
    radius: float = 0.02


@dataclass
class ArmVis:
    side: str
    hist: deque = field(default_factory=deque)   # (t, x, y, speed_n, amplitude, presence)
    seg: int = -1
    pos: np.ndarray | None = None
    stroke_path: list = field(default_factory=list)
    hue: float = 0.0
    presence: float = 0.0
    speed_n: float = 0.0
    amplitude: float = 0.0
    phase: float = 0.0
    speed_s: float = 0.0          # velocità lisciata (niente sfarfallii)
    dist: float = 0.0             # strada percorsa: ancora la texture al gesto, come pittura


V = dict(
    palette="presente", background="#000000", render_scale=1.0,
    response_intensity=1.0, fade_speed=1.0,
    input_zoom=1.3, input_center_x=0.5, input_center_y=0.5,
    wave_intensity=1.0, wave_speed=0.45, wave_damping=0.992, wave_resolution=360, wave_brightness=1.6, wave_steps=3, wave_frequency=7.0, ring_sharpness=8.0,
    color_duration=1.8, color_radius=0.09, flow_strength=1.0,
    filaments_per_arm=7, filament_length=1.1, filament_width=0.009, filament_wave_amplitude=0.035,
    filament_wavelength=0.18, filament_wave_speed=0.8, filament_spread=0.05, filament_brightness=1.0,
    trail_duration=0.45,
    threads_enabled=True, thread_lifetime=60.0, max_threads=80, thread_brightness=0.3, thread_width=0.004,
    thread_sway=0.012,
    knot_intensity=1.0, event_wave_intensity=1.0,
    hue_left=0.05, hue_right=0.55, hue_drift=0.01, hue_by_height=0.08,
    bloom_intensity=0.7, bloom_threshold=0.35, exposure=1.2, vignette=0.35,
    waves_enabled=True, trail_color="", sphere_enabled=False, sphere_x=0.5, sphere_y=0.5, sphere_radius=0.36,
    sphere_rotation_speed=0.06, sphere_tilt=18.0, sphere_perspective=3.5, sphere_depth=0.7,
    sphere_white="#FFFFFF", initial_rings=1, max_rings=48, ring_cooldown=1.0,
    ring_white_time=6.0, ring_white_every=0,
    ring_shades=("#9E1C22", "#C9262C", "#F5383C", "#FF5C5F", "#FF8485", "#FFB0AE", "#FFD6D2"),
    ring_shade_center=0.4, ring_shade_spread=0.22, ring_grow_time=2.0, ring_fade_out=6.0, ring_width=0.006,
    ring_brightness=0.8, ring_dryness=0.25, trail_occlusion=0.7,
    light_blend="max", filament_tail_fade=1.4, calm=0.35, calm_zone=0.07, wave_softness=0.12, brush_amount=1.0, brush_scale=2.5, brush_dryness=0.8,
)


def _quad(ctx):
    return ctx.buffer(np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype="f4"))


class VisualEngine:
    def __init__(self, ctx: moderngl.Context, size: tuple[int, int], cfg: dict):
        self.ctx = ctx
        self.p = dict(V)
        self.t = 0.0
        self.arms = {s: ArmVis(s) for s in SIDES}
        self.threads: list[Thread] = []
        self.knots: list[Knot] = []
        self.pulses: list[Pulse] = []
        self.energy = 0.0
        self._rng = random.Random(7)
        self.sphere = RingSphere()

        q = _quad(ctx)
        prog = lambda fs: ctx.program(vertex_shader=sh.FULLSCREEN_VS, fragment_shader=fs)
        self.progs = {n: prog(fs) for n, fs in dict(
            wave=sh.WAVE_STEP_FS, dye=sh.DYE_FS, trail=sh.TRAIL_FS, wavelayer=sh.WAVELAYER_FS, compose=sh.COMPOSE_FS,
            down=sh.DOWNSAMPLE_FS, blur=sh.BLUR_FS, final=sh.FINAL_FS).items()}
        self.vaos = {n: ctx.vertex_array(p, [(q, "2f", "in_pos")]) for n, p in self.progs.items()}
        self.ribbon_prog = ctx.program(vertex_shader=sh.RIBBON_VS, fragment_shader=sh.RIBBON_FS)
        self.vbo = ctx.buffer(reserve=VBO_BYTES, dynamic=True)
        self.ribbon_vao = ctx.vertex_array(self.ribbon_prog, [(self.vbo, "2f 3f 1f 1f 1f 1f", "in_pos", "in_col", "in_alpha", "in_v", "in_u", "in_dry")])
        bt = _brush_texture()
        self.brush_tex = ctx.texture((bt.shape[1], bt.shape[0]), 1, bt.tobytes(), dtype="f4")
        self.brush_tex.repeat_x, self.brush_tex.repeat_y = True, False
        self.brush_tex.build_mipmaps()
        self.brush_tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        self.palette_tex = None
        self.configure(cfg)
        self.resize(size)

    # ------------------------------------------------------------ configurazione
    def configure(self, cfg: dict) -> None:
        p = dict(V)
        p.update(cfg.get("visuals", {}))
        old_res = self.p.get("wave_resolution")
        self.p = p
        colors = pal.resolve(p)
        grad = pal.gradient(colors) ** 2.2          # sRGB -> lineare
        self.grad = grad
        data = grad.astype("f4").tobytes()
        if self.palette_tex is None:
            self.palette_tex = self.ctx.texture((len(grad), 1), 3, data, dtype="f4")
            self.palette_tex.repeat_x = True
        else:
            self.palette_tex.write(data)
        self.background = pal.hex_to_rgb(p["background"]) ** 2.2
        if hasattr(self, "size") and old_res != p["wave_resolution"]:
            self.resize(self.size)

    def _shade(self, x: float) -> np.ndarray:
        """Tonalità degli anelli: gradiente lineare tra i colori di ring_shades (0 = primo, 1 = ultimo)."""
        key = tuple(self.p["ring_shades"])
        if getattr(self, "_shade_key", None) != key:
            self._shade_key = key
            self._shade_cols = np.array([pal.hex_to_rgb(c) for c in key], dtype="f4")
        cols = self._shade_cols
        if len(cols) == 1:
            return cols[0] ** 2.2
        f = min(max(x, 0.0), 1.0) * (len(cols) - 1)
        i = min(int(f), len(cols) - 2)
        c = cols[i] * (1 - (f - i)) + cols[i + 1] * (f - i)
        return c ** 2.2

    def set_palette(self, name: str) -> None:
        cfg = {"visuals": dict(self.p, palette=name)}
        self.configure(cfg)

    def color(self, hue: float) -> np.ndarray:
        g = self.grad
        x = (hue % 1.0) * (len(g) - 1)
        i = int(x)
        f = x - i
        return g[i] * (1 - f) + g[min(i + 1, len(g) - 1)] * f

    # ------------------------------------------------------------ risorse GPU
    def _tex(self, size, comps=4, dtype="f2"):
        t = self.ctx.texture(size, comps, dtype=dtype)
        t.repeat_x = t.repeat_y = False
        t.filter = (moderngl.LINEAR, moderngl.LINEAR)
        return t

    def resize(self, size: tuple[int, int]) -> None:
        self.size = size
        w, h = size
        s = float(self.p["render_scale"])
        rw, rh = max(64, int(w * s)), max(64, int(h * s))
        self.rsize = (rw, rh)
        self.aspect = w / h
        sw = int(self.p["wave_resolution"])
        sh_ = max(32, int(sw / self.aspect))
        self.wsize = (sw, sh_)

        for attr in ("_textures",):
            for t in getattr(self, attr, []):
                t.release()
        self._textures = []

        def T(sz, comps=4, dtype="f2"):
            t = self._tex(sz, comps, dtype)
            self._textures.append(t)
            return t

        self.wave = [T(self.wsize, 2, "f4") for _ in range(2)]
        self.dye = [T(self.wsize, 4, "f2") for _ in range(2)]
        self.trail = [T(self.rsize) for _ in range(2)]
        self.light = T(self.rsize)
        self.sphere_layer = T(self.rsize)
        self.wavelayer = [T(self.rsize) for _ in range(2)]
        self.scene = T(self.rsize)
        self.half = [T((rw // 2, rh // 2)) for _ in range(2)]
        self.quarter = [T((rw // 4, rh // 4)) for _ in range(2)]
        mk = lambda t: self.ctx.framebuffer(color_attachments=[t])
        self.fb = {id(t): mk(t) for t in self._textures}
        for t in self.wave + self.dye + self.trail + self.wavelayer:
            self.fb[id(t)].clear(0, 0, 0, 0)

    def _fbo(self, tex):
        return self.fb[id(tex)]

    # ------------------------------------------------------------ aggiornamento
    def _map(self, p) -> np.ndarray:
        """Coordinate camera normalizzate (y in basso) -> uv schermo (y in alto)."""
        z = self.p["input_zoom"]
        x = 0.5 + (p[0] - self.p["input_center_x"]) * z
        y = 0.5 + (p[1] - self.p["input_center_y"]) * z
        return np.array([x, 1.0 - y], dtype="f4")

    def update(self, motion: MotionState | None, dt: float) -> None:
        self.t += dt
        t = self.t
        P = self.p
        resp = P["response_intensity"]
        self.energy = motion.energy if motion else self.energy * math.exp(-dt / 1.5)

        for side in SIDES:
            av = self.arms[side]
            am = motion.arms[side] if motion else None
            base = P["hue_left"] if side == "left" else P["hue_right"]
            if am is None or (am.presence <= 0.005 and am.state == "lost"):
                av.presence = am.presence if am else av.presence * math.exp(-dt / 0.5)
                av.speed_n *= math.exp(-dt / 0.3)
                av.speed_s *= math.exp(-dt / max(P["calm"], 0.05))
                if av.hist:
                    av.hist.append((t, *av.hist[-1][1:3], av.speed_s, 0.0, av.presence, av.dist))
            else:
                target = self._map(am.pos_norm)
                if am.segment_id != av.seg or av.pos is None:
                    av.seg = am.segment_id
                    av.hist.clear()
                    av.stroke_path = []
                    av.pos = target.copy()
                prev = av.pos.copy()
                av.pos += (target - av.pos) * (1 - math.exp(-dt / 0.035))
                av.dist += float(np.hypot((av.pos[0] - prev[0]) * self.aspect, av.pos[1] - prev[1]))
                av.presence, av.speed_n = am.presence, am.speed_n * resp
                k = 1 - math.exp(-dt / max(P["calm"], 0.05))
                av.speed_s += k * (av.speed_n - av.speed_s)
                av.amplitude += k * (am.amplitude * resp - av.amplitude)
                av.hue = base + am.elevation * P["hue_by_height"] + t * P["hue_drift"]
                av.hist.append((t, float(av.pos[0]), float(av.pos[1]), av.speed_s, av.amplitude, av.presence, av.dist))
                if am.moving:
                    av.stroke_path.append(av.pos.copy())
            av.phase += dt * 2 * math.pi * P["wave_frequency"] * (0.85 + 0.3 * min(av.speed_s, 1.5))
            while av.hist and t - av.hist[0][0] > P["filament_length"]:
                av.hist.popleft()

        if motion:
            for e in motion.events:
                self._event(e, motion)
            for side in SIDES:
                am = motion.arms[side]
                if not am.moving and not any(e.kind == "stroke" and e.side == side for e in motion.events):
                    self.arms[side].stroke_path = []

        life = P["thread_lifetime"] / max(P["fade_speed"], 1e-3)
        self.threads = [th for th in self.threads if t - th.born < life * 4]
        self.knots = [k for k in self.knots if t - k.born < 3.0]
        self.pulses = [p for p in self.pulses if t - p.born < 0.8]
        if P["sphere_enabled"]:
            self.sphere.update(t, P)

    def _event(self, e, motion) -> None:
        P, t = self.p, self.t
        ew = P["event_wave_intensity"] * P["response_intensity"]
        pos = self._map(e.pos)
        if e.kind == "stroke" and e.side:
            av = self.arms[e.side]
            if P["threads_enabled"] and len(av.stroke_path) >= 6:
                pts = np.array(av.stroke_path, dtype="f4")
                self.threads.append(Thread(_resample(pts, 48), self.color(av.hue), t,
                                           0.5 + 0.5 * e.strength, self._rng.random() * 10))
                if len(self.threads) > P["max_threads"]:
                    self.threads.pop(0)
            av.stroke_path = []
            self.pulses.append(Pulse(*pos, 0.5 * ew * (0.4 + e.strength), t, self.color(av.hue)))
        elif e.kind == "complete":
            # filo completato: la persona ha finito, un nuovo anello entra nella sfera
            if P["sphere_enabled"]:
                self.sphere.add_from_gesture(t, e.data["angle"], e.strength, P)
        elif e.kind == "turn" and e.side:
            av = self.arms[e.side]
            self.pulses.append(Pulse(*pos, 0.6 * ew * e.strength, t, self.color(av.hue + 0.1), 0.015))
        elif e.kind in ("cross", "uncross", "meet"):
            cl, cr = self.color(self.arms["left"].hue), self.color(self.arms["right"].hue)
            strength = (1.0 if e.kind == "cross" else 0.6) * P["knot_intensity"] * (0.5 + e.strength)
            if e.kind != "meet":
                self.knots.append(Knot(*pos, t, strength, (cl, cr), 1 if e.kind == "cross" else -1))
            self.pulses.append(Pulse(*pos, 1.1 * ew * (0.5 + e.strength), t, (cl + cr) * 0.5, 0.03))
        elif e.kind == "appear" and e.side:
            self.pulses.append(Pulse(*pos, 0.12 * ew, t, self.color(self.arms[e.side].hue), 0.02))

    # ------------------------------------------------------------ geometria
    def _filaments(self) -> list[np.ndarray]:
        P, t = self.p, self.t
        out = []
        n = int(P["filaments_per_arm"])
        additive = P["light_blend"] != "max"
        for av in self.arms.values():
            if len(av.hist) < 4 or av.presence < 0.01:
                continue
            h = np.array(av.hist, dtype="f4")[::-1]           # 0 = mano, poi indietro nel tempo
            pts = h[:, 1:3]
            q = pts * [self.aspect, 1]
            seg = np.linalg.norm(np.diff(q, axis=0), axis=1)
            arc = np.concatenate([[0], np.cumsum(seg)])
            if arc[-1] < 0.01:
                continue
            m = 64
            u = np.linspace(0, arc[-1], m)
            interp = lambda col: np.interp(u, arc, h[:, col])
            px, py = interp(1), interp(2)
            spd, amp, pres, dist = interp(3), interp(4), interp(5), interp(6)
            age = np.clip((t - interp(0)) / max(P["filament_length"], 1e-3), 0, 1)   # la scia svanisce col tempo
            trail_col = pal.hex_to_rgb(P["trail_color"]) ** 2.2 if P["trail_color"] else None
            s = np.linspace(0, 1, m)                             # 0 = mano, 1 = coda
            base = np.stack([px, py], 1)
            # leggera levigatura del percorso
            k = np.array([0.25, 0.5, 0.25])
            for c in range(2):
                base[1:-1, c] = np.convolve(base[:, c], k, mode="valid")
            nrm = _normals(base, self.aspect)
            for j in range(n):
                fj = 1.0 + 0.35 * math.sin(j * 1.7)
                phi = j * 2.399
                amp_s = P["filament_wave_amplitude"] * (0.25 + amp * 1.2 + spd * 0.8) * np.power(s, 0.6)
                # l'ondulazione è ancorata alla strada percorsa: scorre piano, non "nuota" con la mano
                off = amp_s * np.sin(2 * math.pi * (dist / P["filament_wavelength"]) * fj
                                     - t * P["filament_wave_speed"] * 2 * math.pi * fj + phi)
                off += P["filament_spread"] * (j / max(n - 1, 1) - 0.5) * s * (0.5 + amp)
                line = base + nrm * (off[:, None] * np.array([1 / self.aspect, 1]))
                norm = 1.0 if additive is False else 1.6 / max(n, 1) ** 0.6
                # mano ferma = nessuna traccia: la scia esiste solo mentre il gesto accade
                still = np.clip((spd - 0.12) / 0.25, 0, 1)
                alpha = pres * still * np.power(1 - age, P["filament_tail_fade"]) * (0.45 + 0.55 * np.clip(spd, 0, 1.0)) \
                    * (0.3 + 0.7 * np.power(s, 0.4)) * P["filament_brightness"] * norm
                width = P["filament_width"] * (0.7 + 0.5 * np.clip(spd, 0, 1.0)) * (1 - 0.45 * age)
                if trail_col is not None:
                    cols = np.tile(trail_col, (m, 1))
                else:
                    cols = np.array([self.color(av.hue + 0.035 * j - 0.12 * si) for si in s[::4]])
                    cols = np.repeat(cols, 4, axis=0)[:m]
                out.append(_strip(line, width, cols, alpha, self.aspect,
                                  u=dist * P["brush_scale"] + j * 0.37, dry=age * P["brush_dryness"]))
        return out

    def _threads(self) -> list[np.ndarray]:
        P, t = self.p, self.t
        out = []
        life = P["thread_lifetime"] / max(P["fade_speed"], 1e-3)
        for th in self.threads:
            age = t - th.born
            a = P["thread_brightness"] * th.strength * _smooth(min(age / 1.5, 1.0)) * math.exp(-age / life)
            if a < 0.004:
                continue
            m = len(th.pts)
            s = np.linspace(0, 1, m)
            nrm = _normals(th.pts, self.aspect)
            for j in range(2):
                sway = P["thread_sway"] * np.sin(math.pi * s) * np.sin(t * (0.35 + 0.1 * j) + s * 7 + th.seed + j * 2)
                line = th.pts + nrm * (sway[:, None] * np.array([1 / self.aspect, 1]))
                alpha = a * (0.55 + 0.45 * np.sin(math.pi * s)) * (1.0 if j == 0 else 0.5)
                out.append(_strip(line, np.full(m, P["thread_width"]), np.tile(th.color, (m, 1)), alpha, self.aspect,
                                  u_offset=th.seed + j, u_scale=P["brush_scale"], dry=0.35 * P["brush_dryness"]))
        return out

    def _knots(self) -> list[np.ndarray]:
        t, P = self.t, self.p
        out = []
        for k in self.knots:
            age = t - k.born
            # un anello che si stringe, come un nodo tirato
            a = k.strength * math.exp(-age / 1.0) * _smooth(min(age / 0.4, 1.0))
            r = 0.05 * (0.3 + 0.7 * math.exp(-age * 2.5)) * (0.6 + 0.4 * k.strength)
            m = 120
            th = np.linspace(0, 2 * math.pi, m)
            for j, col in enumerate(k.colors):
                rot = k.spin * age * (0.5 if j == 0 else -0.4) + j * math.pi / 3
                rr = r * (1 + 0.35 * np.sin(3 * th + rot * 2))
                x = k.x + rr * np.cos(th + rot) / self.aspect
                y = k.y + rr * np.sin(th + rot)
                out.append(_strip(np.stack([x, y], 1), np.full(m, 0.005), np.tile(col, (m, 1)),
                                  np.full(m, a * 0.35), self.aspect, u_offset=j * 3.1, u_scale=P["brush_scale"],
                                  dry=0.3 * P["brush_dryness"]))
        return out

    # ------------------------------------------------------------ rendering
    def _sources(self, t: float):
        P = self.p
        src, cols = [], []
        wi = P["wave_intensity"] * P["response_intensity"]
        for av in self.arms.values():
            if av.pos is None or av.presence < 0.01:
                continue
            drive = max(min(av.speed_s, 1.5) - 0.04, 0.0)
            amp = wi * av.presence * 0.5 * drive * math.sin(av.phase)
            src.append((av.pos[0], av.pos[1], 0.008 + 0.006 * av.amplitude, amp))
            cols.append((self.color(av.hue), av.presence * (0.15 + 0.6 * min(av.speed_s, 1.0))))
        for p in self.pulses:
            age = t - p.born
            if age < 0.7:   # vibrazione morbida: anelli che si allargano senza scatti
                env = math.sin(math.pi * age / 0.7) ** 2
                src.append((p.x, p.y, 0.012, p.strength * 0.5 * env * math.sin(2 * math.pi * P["wave_frequency"] * age)))
                cols.append((p.color, min(p.strength, 1.0)))
        return src[:MAX_SRC], cols[:MAX_SRC]

    def render(self, target: moderngl.Framebuffer, dt: float) -> None:
        ctx, P = self.ctx, self.p
        ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST)
        src, cols = self._sources(self.t)
        fade = P["fade_speed"]

        waves = bool(P["waves_enabled"])
        # 1. onde
        wp = self.progs["wave"]
        k = min(P["wave_speed"] * (0.75 + 0.5 * self.energy), 0.49)
        damping = 1.0 - (1.0 - P["wave_damping"]) * fade * (1.0 + 2.0 * (1 - min(self.energy * 3, 1)))
        wp["texel"] = (1 / self.wsize[0], 1 / self.wsize[1])
        wp["k"], wp["damping"], wp["aspect"] = k, damping, self.aspect
        steps = int(P["wave_steps"]) if waves else 0
        for i in range(steps):
            n = len(src) if i == 0 else 0
            wp["n_src"] = n
            if n:
                wp["src"].write(np.array(src + [(0, 0, 1, 0)] * (MAX_SRC - n), dtype="f4").tobytes())
            self.wave[0].use(0)
            wp["state"] = 0
            self._fbo(self.wave[1]).use()
            self.vaos["wave"].render(moderngl.TRIANGLE_STRIP)
            self.wave = self.wave[::-1]

        # 2. tinta delle onde
        dp = self.progs["dye"]
        n = len(src)
        dp["n_src"], dp["aspect"] = n, self.aspect
        dp["texel"] = (1 / self.wsize[0], 1 / self.wsize[1])
        dp["decay"] = math.exp(-dt * fade / max(P["color_duration"], 0.05))
        if n:
            dsrc = [(s[0], s[1], P["color_radius"], c[1] * 0.5) for s, c in zip(src, cols)]
            dp["src"].write(np.array(dsrc + [(0, 0, 1, 0)] * (MAX_SRC - n), dtype="f4").tobytes())
            dp["src_col"].write(np.array([c[0] for c in cols] + [(0, 0, 0)] * (MAX_SRC - n), dtype="f4").tobytes())
        self.dye[0].use(0)
        self.wave[0].use(1)
        dp["dye"], dp["wave"] = 0, 1
        if waves:
            self._fbo(self.dye[1]).use()
            self.vaos["dye"].render(moderngl.TRIANGLE_STRIP)
            self.dye = self.dye[::-1]

        # 3. filamenti, fili, nodi -> strato luce
        lf = self._fbo(self.light)
        lf.use()
        lf.clear(0, 0, 0, 0)
        self._draw_ribbons(self._filaments() + self._threads() + self._knots())

        # 3b. sfera ad anelli -> strato di sfondo (nitido, senza scia)
        sf = self._fbo(self.sphere_layer)
        sf.use()
        sf.clear(0, 0, 0, 0)
        if P["sphere_enabled"]:
            white = pal.hex_to_rgb(P["sphere_white"]) ** 2.2
            self._draw_ribbons(self.sphere.geometry(self.t, P, self.aspect, self._shade, white, _strip))

        # 4. scie
        tp = self.progs["trail"]
        tp["decay"] = math.exp(-dt * fade / max(P["trail_duration"], 0.02))
        tp["flow"] = P["flow_strength"]
        tp["trail_max"] = 1.0 if P["light_blend"] == "max" else 0.0
        tp["wave_texel"] = (1 / self.wsize[0], 1 / self.wsize[1])
        self.trail[0].use(0)
        self.light.use(1)
        self.wave[0].use(2)
        tp["prev"], tp["light"], tp["wave"] = 0, 1, 2
        self._fbo(self.trail[1]).use()
        self.vaos["trail"].render(moderngl.TRIANGLE_STRIP)
        self.trail = self.trail[::-1]

        # 5. strato delle onde (lisciato nel tempo) e composizione
        wl = self.progs["wavelayer"]
        self.wave[0].use(1)
        self.dye[0].use(2)
        self.palette_tex.use(3)
        self.wavelayer[0].use(4)
        wl["wave"], wl["dye"], wl["palette"], wl["prev"] = 1, 2, 3, 4
        wl["blend"] = 1 - math.exp(-dt / max(P["wave_softness"], 1e-3))
        wl["wave_gain"] = P["wave_brightness"] if waves else 0.0
        wl["phase_step"] = 2 * math.pi * P["wave_frequency"] / (60.0 * max(int(P["wave_steps"]), 1))
        wl["ring_sharpness"] = P["ring_sharpness"]
        wl["aspect"] = self.aspect
        wl["time"] = self.t
        zones = []
        for av in self.arms.values():
            if av.pos is not None and av.presence > 0.01:
                zones.append((float(av.pos[0]), float(av.pos[1]), float(P["calm_zone"])))
        zones = (zones + [(-9.0, -9.0, 0.001)] * 2)[:2]
        wl["calm_zone"].write(np.array(zones, dtype="f4").tobytes())
        self._fbo(self.wavelayer[1]).use()
        self.vaos["wavelayer"].render(moderngl.TRIANGLE_STRIP)
        self.wavelayer = self.wavelayer[::-1]

        cp = self.progs["compose"]
        self.trail[0].use(0)
        self.wavelayer[0].use(1)
        self.sphere_layer.use(2)
        cp["trail"], cp["wavelayer"], cp["sphere"] = 0, 1, 2
        cp["occlusion"] = P["trail_occlusion"]
        cp["background"] = tuple(self.background)
        self._fbo(self.scene).use()
        self.vaos["compose"].render(moderngl.TRIANGLE_STRIP)

        # 6. bagliore (bloom)
        self._down(self.scene, self.half[0], P["bloom_threshold"])
        self._blur(self.half)
        self._down(self.half[0], self.quarter[0], 0.0)
        self._blur(self.quarter)

        # 7. uscita
        fp = self.progs["final"]
        self.scene.use(0)
        self.half[0].use(1)
        self.quarter[0].use(2)
        fp["scene"], fp["bloom1"], fp["bloom2"] = 0, 1, 2
        fp["bloom"], fp["exposure"], fp["vignette"] = P["bloom_intensity"], P["exposure"], P["vignette"]
        target.use()
        self.vaos["final"].render(moderngl.TRIANGLE_STRIP)

    def _draw_ribbons(self, geo: list) -> None:
        if not geo:
            return
        ctx, P = self.ctx, self.p
        data = np.concatenate(geo).astype("f4")
        if data.nbytes > VBO_BYTES:
            data = data[: VBO_BYTES // (9 * 4)]
        self.brush_tex.use(5)
        self.ribbon_prog["brush"] = 5
        self.ribbon_prog["brush_amount"] = float(P["brush_amount"])
        self.vbo.orphan(VBO_BYTES)
        self.vbo.write(data.tobytes())
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.ONE, moderngl.ONE
        ctx.blend_equation = moderngl.MAX if P["light_blend"] == "max" else moderngl.FUNC_ADD
        self.ribbon_vao.render(moderngl.TRIANGLES, vertices=len(data))
        ctx.blend_equation = moderngl.FUNC_ADD
        ctx.disable(moderngl.BLEND)

    def _down(self, src, dst, threshold) -> None:
        p = self.progs["down"]
        src.use(0)
        p["src"] = 0
        p["texel"] = (0.5 / src.width, 0.5 / src.height)
        p["threshold"] = threshold
        self._fbo(dst).use()
        self.vaos["down"].render(moderngl.TRIANGLE_STRIP)

    def _blur(self, pair) -> None:
        p = self.progs["blur"]
        a, b = pair
        for d, (s, t) in (((1, 0), (a, b)), ((0, 1), (b, a))):
            s.use(0)
            p["src"] = 0
            p["dir"] = (d[0] / s.width, d[1] / s.height)
            self._fbo(t).use()
            self.vaos["blur"].render(moderngl.TRIANGLE_STRIP)


# ---------------------------------------------------------------- utilità geometria
def _resample(pts: np.ndarray, m: int) -> np.ndarray:
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    arc = np.concatenate([[0], np.cumsum(seg)])
    if arc[-1] <= 1e-6:
        return np.repeat(pts[:1], m, 0)
    u = np.linspace(0, arc[-1], m)
    out = np.stack([np.interp(u, arc, pts[:, 0]), np.interp(u, arc, pts[:, 1])], 1)
    k = np.ones(5) / 5
    for c in range(2):
        out[2:-2, c] = np.convolve(out[:, c], k, mode="valid")
    return out.astype("f4")


def _normals(pts: np.ndarray, aspect: float) -> np.ndarray:
    q = pts * np.array([aspect, 1.0])
    tan = np.gradient(q, axis=0)
    ln = np.linalg.norm(tan, axis=1, keepdims=True)
    tan = np.where(ln > 1e-9, tan / np.maximum(ln, 1e-9), np.array([1.0, 0.0]))
    return np.stack([-tan[:, 1], tan[:, 0]], 1)


def _smooth(x: float) -> float:
    return x * x * (3 - 2 * x)


def _brush_texture(w: int = 1024, h: int = 64, seed: int = 11) -> np.ndarray:
    """Texture di una pennellata, generata una volta: setole lungo il tratto,
    bordi sfrangiati, grana. Ripetibile lungo la lunghezza (u)."""
    rng = np.random.default_rng(seed)

    def pnoise(rows, cutoff):
        x = rng.standard_normal((rows, w))
        f = np.fft.rfft(x, axis=1)
        f[:, cutoff:] = 0
        f[:, 0] = 0
        y = np.fft.irfft(f, n=w, axis=1)
        return y / (y.std(axis=1, keepdims=True) + 1e-9)

    bristle = pnoise(h, 48)
    k = np.array([0.25, 0.5, 0.25])
    for _ in range(2):                                   # setole a ciuffi
        bristle[1:-1] = bristle[:-2] * k[0] + bristle[1:-1] * k[1] + bristle[2:] * k[2]
    bristle /= bristle.std() + 1e-9
    b = 0.5 + 0.5 * np.tanh(bristle * 1.1)
    edge = 0.72 + 0.14 * pnoise(1, 14)[0]                # bordo sfrangiato
    v = np.abs(np.linspace(-1, 1, h))[:, None]
    mask = np.clip((edge + 0.1 - v) / 0.2, 0, 1)
    mask = mask * mask * (3 - 2 * mask)
    grain = 0.8 + 0.2 * rng.random((h, w))
    return (b * mask * grain).astype("f4")


def _strip(line: np.ndarray, width, cols: np.ndarray, alpha, aspect: float,
           u=None, dry=0.0, u_offset: float = 0.0, u_scale: float = 1.0) -> np.ndarray:
    """Nastro di triangoli lungo una polilinea.
    Vertici (N,9): x y r g b a v u dry  (v attraverso il nastro, u lungo il nastro)."""
    m = len(line)
    width = np.broadcast_to(np.asarray(width, dtype="f4"), (m,))
    alpha = np.broadcast_to(np.asarray(alpha, dtype="f4"), (m,))
    dry = np.broadcast_to(np.asarray(dry, dtype="f4"), (m,))
    if u is None:
        q = line * np.array([aspect, 1.0])
        u = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(q, axis=0), axis=1))]) * u_scale + u_offset
    nrm = _normals(line, aspect) * np.array([1 / aspect, 1.0])
    half = (width / 2)[:, None]
    left, right = line + nrm * half, line - nrm * half
    v = np.zeros((m, 2, 9), dtype="f4")
    v[:, 0, :2], v[:, 1, :2] = left, right
    v[:, :, 2:5] = cols[:, None, :]
    v[:, :, 5] = alpha[:, None]
    v[:, 0, 6], v[:, 1, 6] = 1.0, -1.0
    v[:, :, 7] = np.asarray(u, dtype="f4")[:, None]
    v[:, :, 8] = dry[:, None]
    i = np.arange(m - 1)
    idx = np.stack([i * 2, i * 2 + 1, i * 2 + 2, i * 2 + 1, i * 2 + 3, i * 2 + 2], 1).ravel()
    return v.reshape(-1, 9)[idx]
