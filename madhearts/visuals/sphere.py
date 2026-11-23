"""La sfera ad anelli: la struttura collettiva sullo sfondo.

All'inizio c'è un solo anello che ruota. Ogni filo intrecciato (un "tratto"
del gesto) aggiunge un anello: nasce bianco — il presente — e in pochi
secondi diventa rosso MadHearts, entrando a far parte della struttura comune.
La sfera ruota lentamente; la parte posteriore è più tenue, per dare profondità.

L'inclinazione di ogni nuovo anello segue la direzione del gesto che l'ha
generato; la sequenza "aurea" delle elevazioni distribuisce gli anelli in modo
uniforme, così la sfera si riempie in modo armonioso.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

import numpy as np

GOLDEN = 0.6180339887


@dataclass
class Ring:
    normal: np.ndarray
    born: float
    white: bool
    strength: float
    seed: float
    drift: float
    dying: float | None = None
    shade: float = 0.5       # 0..1: posizione nella gamma delle tonalità (da rosso profondo a quasi bianco)


def _rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _ease(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


class RingSphere:
    def __init__(self, seed: int = 5):
        self.rings: list[Ring] = []
        self.count = 0
        self.rng = random.Random(seed)
        self.last_add = -1e9

    def ensure_initial(self, n: int, t: float) -> None:
        while len(self.rings) < n:
            self._add(t - 1000.0, self.rng.uniform(0, math.pi), 1.0, white_every=0, shade=0.4)

    def _pick_shade(self, P: dict) -> float:
        """Sceglie la tonalità del nuovo anello: per lo più vicina al rosso MadHearts,
        più di rado molto scura o molto chiara (curva a campana regolabile)."""
        center = float(P.get("ring_shade_center", 0.4))
        spread = float(P.get("ring_shade_spread", 0.22))
        return min(max(self.rng.gauss(center, spread), 0.0), 1.0)

    def add_from_gesture(self, t: float, angle: float, strength: float, P: dict) -> bool:
        if t - self.last_add < P["ring_cooldown"]:
            return False
        self.last_add = t
        self._add(t, angle, strength, int(P["ring_white_every"]), self._pick_shade(P))
        alive = [r for r in self.rings if r.dying is None]
        excess = len(alive) - int(P["max_rings"])
        for r in alive[:max(excess, 0)]:
            r.dying = t                       # i più vecchi si dissolvono piano
        return True

    def _add(self, t, angle, strength, white_every, shade=0.4) -> None:
        z = 1.0 - 2.0 * ((self.count * GOLDEN + 0.21) % 1.0)
        z *= 0.85                             # evita anelli perfettamente frontali (linee piatte)
        r = math.sqrt(max(1.0 - z * z, 0.0))
        az = angle + math.pi / 2
        n = np.array([r * math.cos(az), r * math.sin(az), z])
        white = white_every > 0 and self.count > 0 and self.count % white_every == 0
        self.rings.append(Ring(n / np.linalg.norm(n), t, white, strength,
                               self.rng.random() * 6.28, self.rng.uniform(-0.03, 0.03), shade=shade))
        self.count += 1

    def clear(self, t: float, keep: int = 1) -> None:
        self.rings = []
        self.count = 0
        self.ensure_initial(keep, t)

    def update(self, t: float, P: dict) -> None:
        self.rings = [r for r in self.rings if r.dying is None or t - r.dying < P["ring_fade_out"]]
        self.ensure_initial(int(P["initial_rings"]), t)

    def geometry(self, t: float, P: dict, aspect: float, shades, white: np.ndarray, strip) -> list:
        """shades: funzione 0..1 -> colore lineare (la gamma delle tonalità degli anelli)."""
        out = []
        rot = _rot_x(math.radians(P["sphere_tilt"])) @ _rot_y(t * P["sphere_rotation_speed"])
        cx, cy, R = P["sphere_x"], P["sphere_y"], P["sphere_radius"]
        d = P["sphere_perspective"]
        m = 180
        th = np.linspace(0, 2 * math.pi, m)
        for ring in self.rings:
            age = t - ring.born
            grow = _ease(age / max(P["ring_grow_time"], 1e-3))
            a = P["ring_brightness"] * (0.7 + 0.3 * ring.strength) * _ease(age / 1.2)
            if ring.dying is not None:
                a *= 1.0 - _ease((t - ring.dying) / max(P["ring_fade_out"], 1e-3))
            if a < 0.003:
                continue
            n = _rot_y(t * ring.drift) @ ring.normal                     # deriva lentissima di ogni anello
            helper = np.array([0.0, 1.0, 0.0]) if abs(n[1]) < 0.9 else np.array([1.0, 0.0, 0.0])
            ax = np.cross(n, helper)
            ax /= np.linalg.norm(ax)
            bx = np.cross(n, ax)
            pts = (np.outer(np.cos(th + ring.seed), ax) + np.outer(np.sin(th + ring.seed), bx)) * (0.7 + 0.3 * grow)
            q = pts @ rot.T
            f = d / (d - q[:, 2])
            line = np.stack([cx + q[:, 0] * f * R / aspect, cy + q[:, 1] * f * R], 1)
            front = (q[:, 2] + 1) / 2                                  # 1 = verso chi guarda
            depth = P["sphere_depth"]
            alpha = a * (1 - depth + depth * front)
            width = P["ring_width"] * (0.6 + 0.6 * front) * f
            target = white if ring.white else shades(ring.shade)
            k = _ease(age / max(P["ring_white_time"], 1e-3))       # nasce bianco, poi prende la sua tonalità
            col = white * (1 - k) + target * k
            out.append(strip(line, width, np.tile(col, (m, 1)), alpha, aspect,
                             u_offset=ring.seed, u_scale=P["brush_scale"] * 0.6, dry=P["ring_dryness"]))
        return out

    # ------------------------------------------------------------ memoria
    # La sfera è conservata su file: ogni anello con il suo orientamento, colore e
    # istante di nascita (ora reale). Nessun dato sulle persone, nessuna immagine.
    def export(self, now_t: float, now_epoch: float) -> dict:
        return {"versione": 1, "anelli_aggiunti": self.count, "anelli": [
            {"normale": [float(v) for v in r.normal], "nato": now_epoch - (now_t - r.born),
             "bianco": r.white, "tinta": r.shade, "forza": r.strength, "seme": r.seed, "deriva": r.drift}
            for r in self.rings if r.dying is None]}

    def load(self, data: dict, now_t: float, now_epoch: float) -> None:
        rings = []
        for d in data.get("anelli", []):
            # sfere salvate prima delle tonalità: i vecchi anelli "bianchi" diventano quasi bianchi,
            # gli altri ricevono una tonalità stabile ricavata dal loro seme
            shade = d.get("tinta")
            if shade is None:
                shade = 0.95 if d.get("bianco") else (math.sin(float(d["seme"]) * 12.9898) * 0.5 + 0.5) * 0.7 + 0.1
            rings.append(Ring(np.array(d["normale"], dtype=float), now_t - (now_epoch - d["nato"]),
                              False, float(d["forza"]), float(d["seme"]), float(d["deriva"]), shade=float(shade)))
        self.rings = rings
        self.count = int(data.get("anelli_aggiunti", len(self.rings)))

