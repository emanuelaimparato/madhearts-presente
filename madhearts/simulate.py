"""Visitatore simulato: produce osservazioni del corpo come se una persona
portasse dei fili da un anello all'altro, con pause, incroci e momenti di
immobilità. Serve a provare il motore visivo senza camera (e a confrontare
regolazioni sempre sulla stessa "coreografia")."""
from __future__ import annotations

import math
import random

from .tracking import Arm, BodyObservation, Point

# anelli immaginari della struttura, in coordinate immagine (0..1, y in basso)
RINGS = [(0.30, 0.35), (0.42, 0.25), (0.58, 0.28), (0.70, 0.38), (0.33, 0.58),
         (0.50, 0.50), (0.67, 0.60), (0.45, 0.72), (0.60, 0.75)]


def _ease(u: float) -> float:
    return u * u * (3 - 2 * u)


class _ArmPath:
    def __init__(self, rng: random.Random, start: int, side_bias: float):
        self.rng = rng
        self.cur = RINGS[start]
        self.target = self.cur
        self.t0 = 0.0
        self.dur = 0.0
        self.pause_until = 0.5
        self.bend = 0.0
        self.side_bias = side_bias

    def pick(self, t: float, cross: bool, still_until: float) -> None:
        cands = [r for r in RINGS if r != self.cur]
        if cross:
            cands = [r for r in cands if (r[0] - 0.5) * self.side_bias < 0] or cands
        else:
            cands = [r for r in cands if (r[0] - 0.5) * self.side_bias >= -0.05] or cands
        self.target = self.rng.choice(cands)
        self.t0 = max(t, still_until)
        d = math.dist(self.cur, self.target)
        self.dur = self.rng.uniform(0.6, 1.3) * (0.6 + d * 2)
        self.bend = self.rng.uniform(-0.12, 0.12)

    def pos(self, t: float) -> tuple[float, float]:
        if t < self.t0 or self.dur <= 0:
            return self.cur
        u = min((t - self.t0) / self.dur, 1.0)
        e = _ease(u)
        (x0, y0), (x1, y1) = self.cur, self.target
        nx, ny = -(y1 - y0), (x1 - x0)
        b = math.sin(math.pi * e) * self.bend
        p = (x0 + (x1 - x0) * e + nx * b, y0 + (y1 - y0) * e + ny * b)
        if u >= 1.0:
            self.cur = self.target
            self.dur = 0.0
            self.pause_until = t + self.rng.uniform(0.25, 0.9)
        return p


class SimulatedVisitor:
    """Una successione di visitatori: ognuno intreccia per un po', poi finisce
    abbassando le braccia (e restando fermo) oppure uscendo dall'inquadratura."""

    def __init__(self, seed: int = 3, weave=(16.0, 24.0), rest_for: float = 17.0, away_for: float = 6.0):
        self.rng = random.Random(seed)
        self.weave, self.rest_for, self.away_for = weave, rest_for, away_for
        self.frame = 0
        self.ends = ["rest", "away"]
        self.visitor = 0
        self._start_visitor(0.0)

    def _start_visitor(self, t: float) -> None:
        self.arms = {"left": _ArmPath(self.rng, 4, -1), "right": _ArmPath(self.rng, 3, +1)}
        for a in self.arms.values():
            a.pause_until = t + 0.5
        self.weave_until = t + self.rng.uniform(*self.weave)
        self.end = self.ends[self.visitor % 2]
        self.end_until = self.weave_until + (self.rest_for if self.end == "rest" else self.away_for)
        self.visitor += 1

    def observe(self, t: float, aspect: float = 16 / 9) -> BodyObservation:
        self.frame += 1
        if t >= self.end_until:
            self._start_visitor(t)
        obs = BodyObservation(self.frame, t, present=True, aspect=aspect, shoulder_width=0.16)
        if t >= self.weave_until and self.end == "away":
            obs.present = False
            return obs
        for side, path in self.arms.items():
            sx = 0.42 if side == "left" else 0.58
            if t >= self.weave_until:                         # braccia lungo il corpo
                u = min((t - self.weave_until) / 1.2, 1.0)
                x0, y0 = path.cur
                rest = (sx + (0.02 if side == "right" else -0.02), 0.88)
                e = _ease(u)
                x, y = x0 + (rest[0] - x0) * e, y0 + (rest[1] - y0) * e
            else:
                if path.dur == 0.0 and t >= path.pause_until:
                    path.pick(t, cross=self.rng.random() < 0.18, still_until=0.0)
                x, y = path.pos(t)
            x += self.rng.gauss(0, 0.002)
            y += self.rng.gauss(0, 0.002)
            obs.arms[side] = Arm(side, shoulder=Point(sx, 0.40, 0, 0.99),
                                 elbow=Point((sx + x) / 2, (0.40 + y) / 2 + 0.08, 0, 0.95),
                                 wrist=Point(x, y, 0, 0.9))
        return obs
