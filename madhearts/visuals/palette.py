"""Palette cromatiche: liste di colori esadecimali trasformate in un gradiente
continuo (texture 1D) che il motore campiona."""
from __future__ import annotations

import numpy as np

DEFAULT_PALETTES = {
    # Rosso MadHearts (dalla Main Color Palette del brand).
    "madhearts": ["#F5383C"],
    "madhearts_rosa": ["#F5383C", "#FF8485"],
    # Segnaposto: da sostituire con i colori di MadHearts quando disponibili.
    "presente": ["#ff2d95", "#ff7a2d", "#ffd23f", "#00e5ff", "#7b2cff"],
    "oceano": ["#00e5ff", "#2d6bff", "#7b2cff", "#00ffb3"],
    "brace": ["#ff2d55", "#ff7a2d", "#ffd23f", "#ff4fd8"],
    "aurora": ["#00ffb3", "#00e5ff", "#7b2cff", "#ff2d95"],
}


def hex_to_rgb(h: str) -> np.ndarray:
    h = h.strip().lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)], dtype="f4")


def gradient(colors: list[str], n: int = 256, cyclic: bool = True) -> np.ndarray:
    """Restituisce n colori RGB (float32) interpolati; ciclico = l'ultimo torna al primo."""
    cols = [hex_to_rgb(c) for c in colors]
    if cyclic:
        cols.append(cols[0])
    cols = np.array(cols)
    xs = np.linspace(0, 1, len(cols))
    t = np.linspace(0, 1, n)
    out = np.stack([np.interp(t, xs, cols[:, k]) for k in range(3)], axis=1)
    return out.astype("f4")


def resolve(cfg_visuals: dict) -> list[str]:
    name = cfg_visuals.get("palette", "madhearts")
    custom = cfg_visuals.get("palettes", {})
    if isinstance(name, list):
        return name
    return custom.get(name) or DEFAULT_PALETTES.get(name) or DEFAULT_PALETTES["madhearts"]


def names(cfg_visuals: dict) -> list[str]:
    return list(dict.fromkeys(list(cfg_visuals.get("palettes", {}).keys()) + list(DEFAULT_PALETTES.keys())))
