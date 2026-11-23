"""Strato di attesa sopra l'esperienza: logo piccolo in un angolo, invito a
partecipare e dissolvenza al nero per avvio, pausa e riavvio.

L'invito compare quando l'esperienza è in attesa o quando nessuno è presente
da qualche secondo, e svanisce dolcemente appena arriva qualcuno.
"""
from __future__ import annotations

import math
from pathlib import Path

import moderngl
import numpy as np

VS = """
#version 330
in vec2 in_pos;
in vec2 in_uv;
out vec2 uv;
void main() { uv = in_uv; gl_Position = vec4(in_pos, 0.0, 1.0); }
"""
FS = """
#version 330
uniform sampler2D tex;
uniform float alpha;
uniform vec4 solid;       // se solid.a > 0: rettangolo di colore pieno (dissolvenza al nero)
in vec2 uv;
out vec4 o;
void main() {
    if (solid.a > 0.0) { o = vec4(solid.rgb, solid.a); return; }
    vec4 c = texture(tex, uv);
    o = vec4(c.rgb, c.a * alpha);
}
"""
DEFAULTS = dict(
    logo_file="assets/logo.png", logo_corner="bottom-right", logo_height=0.06, logo_opacity=0.6,
    logo_margin=0.03, invite_text="AVVICINATI E INTRECCIA IL TUO FILO",
    invite_subtext="ogni gesto diventa parte della sfera", invite_font="assets/fonts/LeagueGothic.ttf",
    invite_subfont="assets/fonts/DMSans.ttf", invite_size=0.045, invite_y=0.92, invite_color="#FFFFFF",
    invite_opacity=0.75, invite_delay=6.0, invite_fade=1.5,
)


def _hex(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


class Attract:
    def __init__(self, ctx: moderngl.Context, size, cfg: dict, root: Path, log=print):
        self.ctx, self.size, self.root, self.log = ctx, size, root, log
        self.prog = ctx.program(vertex_shader=VS, fragment_shader=FS)
        self.vbo = ctx.buffer(reserve=16 * 4)
        self.vao = ctx.vertex_array(self.prog, [(self.vbo, "2f 2f", "in_pos", "in_uv")])
        self.textures: dict[str, tuple] = {}
        self.invite_alpha = 0.0
        self.empty_time = 0.0
        self.black = 1.0                 # parte dal nero e si apre in dissolvenza
        self.black_target = 0.0
        self.t = 0.0
        self.p = {}
        self._key = None
        self.configure(cfg)

    # -------------------------------------------------------------- risorse
    def _path(self, name: str) -> Path:
        p = Path(name)
        return p if p.is_absolute() else self.root / p

    def _upload(self, surface):
        import pygame
        w, h = surface.get_size()
        data = pygame.image.tobytes(surface, "RGBA", True)       # capovolta per OpenGL
        tex = self.ctx.texture((w, h), 4, data)
        tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        return tex, w, h

    def configure(self, cfg: dict) -> None:
        import pygame
        p = dict(DEFAULTS)
        p.update(cfg.get("attract", {}))
        self.p = p
        key = tuple(p[k] for k in ("logo_file", "logo_height", "invite_text", "invite_subtext", "invite_font",
                                   "invite_subfont", "invite_size", "invite_color")) + tuple(self.size)
        if key == self._key:
            return
        self._key = key
        for tex, *_ in self.textures.values():
            tex.release()
        self.textures = {}
        if not pygame.font.get_init():
            pygame.font.init()
        H = self.size[1]
        col = _hex(p["invite_color"])

        def font(name, px):
            path = self._path(name)
            return pygame.font.Font(str(path) if path.exists() else None, max(int(px), 8))

        if p["invite_text"]:
            s = font(p["invite_font"], H * p["invite_size"]).render(p["invite_text"], True, col)
            self.textures["invite"] = self._upload(s)
        if p["invite_subtext"]:
            s = font(p["invite_subfont"], H * p["invite_size"] * 0.42).render(p["invite_subtext"], True, col)
            self.textures["sub"] = self._upload(s)
        logo = self._path(p["logo_file"])
        if logo.exists():
            try:
                img = pygame.image.load(str(logo))
                img = img.convert_alpha() if pygame.display.get_surface() else img
                h = max(int(H * p["logo_height"]), 8)
                w = int(img.get_width() * h / img.get_height())
                self.textures["logo"] = self._upload(pygame.transform.smoothscale(img, (w, h)))
            except Exception as e:
                self.log(f"logo: impossibile leggere {logo.name} ({e})")
        elif p["logo_file"]:
            self.log(f"logo: metti il file del logo in {p['logo_file']} (per ora non viene mostrato)")

    # -------------------------------------------------------------- stato
    def fade_to_black(self, black: bool) -> None:
        self.black_target = 1.0 if black else 0.0

    def update(self, dt: float, playing: bool, presence: float) -> None:
        self.t += dt
        p = self.p
        self.empty_time = self.empty_time + dt if presence < 0.2 else 0.0
        show = (not playing) or self.empty_time >= p["invite_delay"]
        target = 1.0 if show else 0.0
        step = dt / max(p["invite_fade"], 0.05)
        self.invite_alpha = min(self.invite_alpha + step, target) if target > self.invite_alpha \
            else max(self.invite_alpha - step * 1.5, target)
        sb = dt / 1.2
        self.black = min(self.black + sb, self.black_target) if self.black_target > self.black \
            else max(self.black - sb, self.black_target)

    # -------------------------------------------------------------- disegno
    def _quad(self, tex, x, y, w, h, alpha) -> None:
        """x, y = angolo in basso a sinistra in pixel."""
        sw, sh = self.size
        x0, y0 = -1 + 2 * x / sw, -1 + 2 * y / sh
        x1, y1 = x0 + 2 * w / sw, y0 + 2 * h / sh
        self.vbo.write(np.array([x0, y0, 0, 0, x1, y0, 1, 0, x0, y1, 0, 1, x1, y1, 1, 1], dtype="f4").tobytes())
        tex.use(0)
        self.prog["tex"] = 0
        self.prog["alpha"] = alpha
        self.prog["solid"] = (0.0, 0.0, 0.0, 0.0)
        self.vao.render(moderngl.TRIANGLE_STRIP)

    def draw(self, fb) -> None:
        ctx, p = self.ctx, self.p
        sw, sh = self.size
        fb.use()
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        if "logo" in self.textures and p["logo_opacity"] > 0:
            tex, w, h = self.textures["logo"]
            m = sh * p["logo_margin"]
            corner = p["logo_corner"]
            x = m if "left" in corner else sw - w - m
            y = sh - h - m if "top" in corner else m
            self._quad(tex, x, y, w, h, p["logo_opacity"])
        a = self.invite_alpha * p["invite_opacity"] * (0.85 + 0.15 * math.sin(self.t * 0.8))   # respira piano
        if a > 0.003:
            y = sh * (1 - p["invite_y"])
            if "invite" in self.textures:
                tex, w, h = self.textures["invite"]
                self._quad(tex, (sw - w) / 2, y, w, h, a)
            if "sub" in self.textures:
                tex, w2, h2 = self.textures["sub"]
                self._quad(tex, (sw - w2) / 2, y - h2 * 1.4, w2, h2, a * 0.8)
        if self.black > 0.002:
            self.prog["solid"] = (0.0, 0.0, 0.0, float(self.black))
            self.vbo.write(np.array([-1, -1, 0, 0, 1, -1, 1, 0, -1, 1, 0, 1, 1, 1, 1, 1], dtype="f4").tobytes())
            self.vao.render(moderngl.TRIANGLE_STRIP)
        ctx.disable(moderngl.BLEND)
