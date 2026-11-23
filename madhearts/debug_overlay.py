"""Pannello di debug, disegnato in un angolo sopra l'esperienza (tasto D).

Mostra la camera con i punti rilevati, la posizione filtrata dei polsi, il
riquadro della zona di camera che corrisponde allo schermo (utile per decidere
dove mettere la camera), lo stato dell'intreccio, gli fps e i parametri live.
L'immagine resta solo in memoria: non viene mai salvata.
"""
from __future__ import annotations

import time

import cv2
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
in vec2 uv;
out vec4 o;
void main() { o = texture(tex, uv); }
"""
PANEL_W = 560
CAM_H = 315
COLORS = {"left": (255, 80, 220), "right": (255, 220, 60)}
CHAIN = ("shoulder", "elbow", "wrist")


_ACCENTS = str.maketrans({"à": "a'", "è": "e'", "é": "e'", "ì": "i'", "ò": "o'", "ù": "u'", "—": "-", "→": "->"})


def _ascii(s: str) -> str:
    """Le scritte di OpenCV non hanno lettere accentate."""
    return s.translate(_ACCENTS).encode("ascii", "replace").decode()


class DebugOverlay:
    def __init__(self, ctx: moderngl.Context, size: tuple[int, int]):
        self.ctx, self.size = ctx, size
        self.prog = ctx.program(vertex_shader=VS, fragment_shader=FS)
        self.vbo = ctx.buffer(reserve=4 * 4 * 4)
        self.vao = ctx.vertex_array(self.prog, [(self.vbo, "2f 2f", "in_pos", "in_uv")])
        self.tex = None

    def _panel(self, frame, obs, state, cfg, info, messages) -> np.ndarray:
        lines = list(info)
        now = time.perf_counter()
        lines += [m for t, m in messages if now - t < 8]
        h = CAM_H + 14 + 22 * len(lines) + 10
        img = np.zeros((h, PANEL_W, 3), np.uint8)
        img[:] = (18, 18, 18)
        cam = img[:CAM_H]
        mirror = cfg.get("camera", {}).get("mirror", True)
        if frame is not None:
            f = cv2.resize(frame.image, (PANEL_W, CAM_H), interpolation=cv2.INTER_AREA)
            cam[:] = cv2.flip(f, 1) if mirror else f
        else:
            cv2.putText(cam, "camera non attiva", (170, CAM_H // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1, cv2.LINE_AA)
        px = lambda p: (int(p.x * PANEL_W), int(p.y * CAM_H))

        # zona di camera che corrisponde allo schermo
        v = cfg.get("visuals", {})
        z = float(v.get("input_zoom", 1.3))
        cx, cy = float(v.get("input_center_x", 0.5)), float(v.get("input_center_y", 0.5))
        x0, x1 = (cx - 0.5 / z) * PANEL_W, (cx + 0.5 / z) * PANEL_W
        y0, y1 = (cy - 0.5 / z) * CAM_H, (cy + 0.5 / z) * CAM_H
        cv2.rectangle(cam, (int(x0), int(y0)), (int(x1), int(y1)), (60, 60, 245), 1, cv2.LINE_AA)
        cv2.putText(cam, "zona schermo", (int(x0) + 4, int(y0) + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (60, 60, 245), 1, cv2.LINE_AA)

        min_vis = float(cfg.get("tracking", {}).get("min_visibility", 0.3))
        if obs is not None and obs.present:
            for side, arm in obs.arms.items():
                col = COLORS[side]
                pts = [getattr(arm, n) for n in CHAIN]
                for a, b in zip(pts, pts[1:]):
                    if min(a.visibility, b.visibility) >= min_vis:
                        cv2.line(cam, px(a), px(b), col, 2, cv2.LINE_AA)
                for p in pts:
                    cv2.circle(cam, px(p), 5, col, -1 if p.visibility >= min_vis else 1, cv2.LINE_AA)
        if state is not None:
            for side, a in state.arms.items():
                if a.presence > 0.05:
                    c = (int(a.pos_norm[0] * PANEL_W), int(a.pos_norm[1] * CAM_H))
                    cv2.circle(cam, c, 9, (255, 255, 255), 2, cv2.LINE_AA)
        lines = [_ascii(s) for s in lines]
        for i, s in enumerate(lines):
            cv2.putText(img, s, (10, CAM_H + 28 + 22 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (235, 235, 235), 1, cv2.LINE_AA)
        return img

    def draw(self, fb, frame, obs, state, cfg, info, messages) -> None:
        img = self._panel(frame, obs, state, cfg, info, messages)
        h, w = img.shape[:2]
        rgb = np.ascontiguousarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)[::-1])
        if self.tex is None or self.tex.size != (w, h):
            if self.tex is not None:
                self.tex.release()
            self.tex = self.ctx.texture((w, h), 3, rgb.tobytes())
        else:
            self.tex.write(rgb.tobytes())
        sw, sh = fb.viewport[2], fb.viewport[3]
        scale = min(1.0, 0.9 * sh / h, 0.6 * sw / w)
        m = 16
        x0, y1 = -1 + 2 * m / sw, 1 - 2 * m / sh
        x1, y0 = x0 + 2 * w * scale / sw, y1 - 2 * h * scale / sh
        self.vbo.write(np.array([x0, y0, 0, 0, x1, y0, 1, 0, x0, y1, 0, 1, x1, y1, 1, 1], dtype="f4").tobytes())
        fb.use()
        self.tex.use(0)
        self.prog["tex"] = 0
        self.vao.render(moderngl.TRIANGLE_STRIP)
