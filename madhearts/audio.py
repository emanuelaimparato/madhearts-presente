"""Audio dell'esperienza.

Quattro voci, ognuna con il proprio volume:
- MUSICA: la vostra traccia (mp3/ogg/wav) in loop, come sottofondo.
- TAPPETO: un accordo morbido e lento generato dal programma; si alza piano
  quando qualcuno è presente e si abbassa quando l'esperienza è vuota.
- SCIA: un fruscio di pennello (rumore filtrato con lievi armonici) che suona
  solo mentre la mano si muove; il volume segue la velocità del gesto e il
  suono si sposta a sinistra/destra con la mano.
- RINTOCCO: una campana dolce quando un nuovo anello entra nella sfera.

Tutti i suoni generati sono calcolati una volta all'avvio (pochi secondi) e
girano in loop senza giunture. Se il Mac non ha un'uscita audio, l'app funziona
lo stesso, in silenzio.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

SR = 44100
LOOP = 24.0                       # secondi: tutte le frequenze sono multipli di 1/LOOP → loop perfetto
PENTA = [293.66, 329.63, 369.99, 440.00, 493.88, 587.33, 659.25]   # Re maggiore pentatonica


def _q(f: float) -> float:
    """Arrotonda la frequenza a un multiplo di 1/LOOP (loop senza scatti)."""
    return round(f * LOOP) / LOOP


def _stereo(left: np.ndarray, right: np.ndarray, peak: float = 0.9) -> np.ndarray:
    m = max(np.abs(left).max(), np.abs(right).max(), 1e-9)
    out = np.stack([left, right], 1) / m * peak
    return (out * 32767).astype(np.int16)


def _periodic_noise(n: int, lo: float, hi: float, rng) -> np.ndarray:
    """Rumore filtrato in banda, periodico per costruzione (sintesi in frequenza)."""
    spec = np.zeros(n // 2 + 1, complex)
    f = np.fft.rfftfreq(n, 1 / SR)
    band = (f >= lo) & (f <= hi)
    shape = np.exp(-((np.log(f[band] + 1e-9) - math.log(math.sqrt(lo * hi))) ** 2) / 0.6)
    spec[band] = shape * np.exp(1j * rng.uniform(0, 2 * math.pi, band.sum()))
    x = np.fft.irfft(spec, n)
    return x / (np.abs(x).max() + 1e-9)


def make_pad() -> np.ndarray:
    n = int(SR * LOOP)
    t = np.arange(n) / SR
    L, R = np.zeros(n), np.zeros(n)
    notes = [146.83, 220.00, 293.66, 329.63, 440.00, 554.37]       # Re, La, Re, Mi, La, Do#: aperto e luminoso
    gains = [1.0, 0.8, 0.55, 0.4, 0.3, 0.18]
    for i, (fr, g) in enumerate(zip(notes, gains)):
        lfo = 0.55 + 0.45 * np.sin(2 * math.pi * (i % 3 + 1) / LOOP * t + i * 1.3)   # respiro lentissimo
        for det, pan in ((-0.25, 0.3), (0.25, 0.7)):                                 # leggero coro
            f = _q(fr + det)
            tone = np.sin(2 * math.pi * f * t) + 0.12 * np.sin(2 * math.pi * 2 * f * t)
            L += g * lfo * tone * (1 - pan)
            R += g * lfo * tone * pan
    rng = np.random.default_rng(1)
    air = _periodic_noise(n, 300, 2500, rng) * 0.05
    return _stereo(L + air, R + np.roll(air, SR // 3), 0.6)


def make_brush() -> np.ndarray:
    n = int(SR * LOOP / 3)        # 8 s
    t = np.arange(n) / SR
    rng = np.random.default_rng(2)
    loop_len = n / SR
    grain = _periodic_noise(n, 900, 5000, rng)
    swell = 0.6 + 0.4 * np.sin(2 * math.pi * 3 / loop_len * t)             # setole che "respirano"
    shimmer = sum(0.08 * np.sin(2 * math.pi * round(f * loop_len) / loop_len * t + k)
                  for k, f in enumerate([1174.66, 1479.98, 1760.0]))
    sig = grain * swell + shimmer
    return _stereo(sig, np.roll(sig, SR // 7), 0.7)


def make_bell(freq: float) -> np.ndarray:
    dur = 7.0
    n = int(SR * dur)
    t = np.arange(n) / SR
    sig = np.zeros(n)
    for ratio, amp, decay in ((1.0, 1.0, 2.8), (2.0, 0.45, 1.8), (2.76, 0.3, 1.2), (5.4, 0.12, 0.6), (8.93, 0.06, 0.35)):
        sig += amp * np.exp(-t / decay) * np.sin(2 * math.pi * freq * ratio * t)
    sig *= np.minimum(t / 0.01, 1.0)                                          # attacco morbido
    L, R = sig.copy(), np.zeros(n)
    for delay, g in ((0.031, 0.5), (0.057, 0.35), (0.113, 0.25), (0.19, 0.15)):   # piccola eco spaziale
        d = int(SR * delay)
        R[d:] += g * sig[:-d] * 1.6
        L[d * 2:] += g * 0.6 * sig[:-d * 2]
    return _stereo(L, R, 0.5)


class Audio:
    def __init__(self, cfg: dict, project_root: Path, log=print):
        self.log = log
        self.ok = False
        self.music_loaded = False
        self.music_name = ""
        self.vol = {}
        self.muted = False
        self.configure(cfg)
        self.root = project_root
        a = cfg.get("audio", {})
        if not a.get("enabled", True):
            return
        try:
            import pygame
            if not pygame.mixer.get_init():
                pygame.mixer.init(SR, -16, 2, 1024)
            pygame.mixer.set_num_channels(16)
            self.pg = pygame
        except Exception as e:                       # nessuna uscita audio: si prosegue in silenzio
            self.log(f"audio non disponibile ({e}): l'esperienza prosegue senza suono")
            return
        mk = pygame.sndarray.make_sound
        self.pad = mk(make_pad())
        self.brush = mk(make_brush())
        self.bells = [mk(make_bell(f)) for f in PENTA]
        self.ch_pad = pygame.mixer.Channel(0)
        self.ch_brush = {"left": pygame.mixer.Channel(1), "right": pygame.mixer.Channel(2)}
        self.ch_pad.play(self.pad, loops=-1)
        for i, ch in enumerate(self.ch_brush.values()):
            ch.play(self.brush, loops=-1)
            ch.set_volume(0.0, 0.0)
        self.pad_level = 0.0
        self.brush_level = {"left": 0.0, "right": 0.0}
        self.music_loaded = False
        self.ok = True
        self.load_music(a.get("music_file", ""))

    # -------------------------------------------------------------- volumi
    def configure(self, cfg: dict) -> None:
        a = cfg.get("audio", {})
        self.vol = {k: float(a.get(k, d)) for k, d in (
            ("master_volume", 0.8), ("music_volume", 0.5), ("ambient_volume", 0.5),
            ("trail_volume", 0.6), ("chime_volume", 0.6), ("ambient_idle", 0.35))}

    def load_music(self, name: str) -> None:
        if not self.ok or not name:
            return
        path = Path(name)
        if not path.is_absolute():
            path = self.root / path
        if not path.exists():
            self.log(f"musica: file {path.name} non trovato in {path.parent.name}/ (prosegue senza musica)")
            return
        try:
            self.pg.mixer.music.load(str(path))
            self.pg.mixer.music.play(loops=-1, fade_ms=3000)
            self.music_loaded = True
            self.music_name = path.name
            self.log(f"musica: {path.name}")
        except Exception as e:
            self.log(f"musica: impossibile leggere {path.name} ({e})")

    def _m(self, key: str) -> float:
        return 0.0 if self.muted else self.vol["master_volume"] * self.vol[key]

    # -------------------------------------------------------------- aggiornamento
    def update(self, state, dt: float, playing: bool) -> None:
        if not self.ok:
            return
        k = 1 - math.exp(-dt / 0.6)
        presence = state.person_presence if (state is not None and playing) else 0.0
        target_pad = self.vol["ambient_idle"] + (1 - self.vol["ambient_idle"]) * presence
        self.pad_level += k * (target_pad - self.pad_level)
        self.ch_pad.set_volume(self._m("ambient_volume") * self.pad_level)
        if self.music_loaded:
            self.pg.mixer.music.set_volume(self._m("music_volume"))
        kb = 1 - math.exp(-dt / 0.25)
        for side, ch in self.ch_brush.items():
            target = 0.0
            x = 0.5
            if state is not None and playing:
                a = state.arms[side]
                target = a.presence * min(max(a.speed_n - 0.08, 0.0) / 0.7, 1.0)
                x = min(max(a.pos_norm[0], 0.0), 1.0)
            self.brush_level[side] += kb * (target - self.brush_level[side])
            v = self._m("trail_volume") * self.brush_level[side]
            ch.set_volume(v * math.cos(x * math.pi / 2), v * math.sin(x * math.pi / 2))   # panning a potenza costante

    def chime(self, index: int) -> None:
        if not self.ok:
            return
        ch = self.pg.mixer.find_channel()
        if ch is not None:
            v = self._m("chime_volume")
            ch.play(self.bells[index % len(self.bells)])
            ch.set_volume(v, v)

    def close(self) -> None:
        if self.ok:
            self.pg.mixer.music.fadeout(800)
            self.pg.mixer.fadeout(800)
