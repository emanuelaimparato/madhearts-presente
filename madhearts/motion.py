"""Modulo di elaborazione del movimento (FASE 3).

Trasforma le osservazioni grezze del tracking in dati di movimento stabili,
pronti per il motore visivo:

- filtro di attendibilità: un punto conta solo se è visibile e se il suo
  spostamento è fisicamente plausibile; gli errori isolati vengono scartati;
- smoothing adattivo (filtro One Euro, Casiez et al. 2012): liscia molto i
  movimenti lenti (niente tremolio) e poco quelli veloci (niente ritardo);
- perdita del tracking: il braccio prosegue per inerzia per un istante, poi
  si ferma e la sua "presenza" si dissolve dolcemente; al ritorno riparte da
  dove si trova davvero, senza linee che attraversano lo schermo
  (segment_id cambia: il renderer sa che deve iniziare un nuovo filamento);
- correzione degli scambi destra/sinistra improvvisi, per continuità;
- caratteristiche del gesto: velocità, direzione, cambi di direzione,
  ampiezza, estensione ed elevazione del braccio, relazione tra le due braccia;
- "tratti": un tratto è un gesto continuo dall'avvio all'arresto, come portare
  il filo da un anello all'altro. A fine tratto viene emesso un evento con
  punto di partenza, arrivo, lunghezza e durata.

Unità: le distanze del corpo sono in "larghezze di spalle" (sw), così i valori
non dipendono dalla distanza della persona dalla camera. Le posizioni per il
renderer sono normalizzate 0..1 (pos_norm), già specchiate come lo schermo.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from .tracking import SIDES, BodyObservation

TRACKING, HOLDING, LOST = "tracking", "holding", "lost"


# ------------------------------------------------------------------ filtri
def _alpha(cutoff: float, dt: float) -> float:
    tau = 1.0 / (2.0 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / dt)


class OneEuro2D:
    """Filtro One Euro su un punto 2D. La parte adattiva usa la velocità
    espressa in larghezze di spalle al secondo (indipendente dalla distanza)."""

    def __init__(self, min_cutoff: float, beta: float, d_cutoff: float):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.reset()

    def reset(self, x: np.ndarray | None = None, t: float | None = None) -> None:
        self.x = None if x is None else x.copy()
        self.dx = np.zeros(2)
        self.t = t

    def __call__(self, x: np.ndarray, t: float, scale: float) -> np.ndarray:
        if self.x is None or self.t is None:
            self.reset(x, t)
            return self.x
        dt = max(t - self.t, 1e-3)
        self.t = t
        dx = (x - self.x) / dt
        self.dx = self.dx + _alpha(self.d_cutoff, dt) * (dx - self.dx)
        cutoff = self.min_cutoff + self.beta * float(np.linalg.norm(self.dx)) / max(scale, 1e-6)
        self.x = self.x + _alpha(cutoff, dt) * (x - self.x)
        return self.x


def _approach(cur: float, target: float, dt: float, time_const: float) -> float:
    if time_const <= 0:
        return target
    step = dt / time_const
    return min(cur + step, target) if target > cur else max(cur - step, target)


# ------------------------------------------------------------------ output
@dataclass
class Event:
    kind: str                 # "stroke" | "turn" | "cross" | "uncross" | "meet" | "part" | "appear" | "lost" | "complete"
    side: str | None          # "left" / "right" / None per eventi della coppia
    pos: tuple[float, float]  # posizione normalizzata 0..1
    strength: float = 1.0     # 0..1
    data: dict = field(default_factory=dict)


@dataclass
class ArmMotion:
    side: str
    state: str = LOST
    presence: float = 0.0           # 0..1, sale/scende dolcemente: da usare come opacità
    segment_id: int = 0             # cambia quando la traccia riparte da zero
    pos_norm: tuple[float, float] = (0.5, 0.5)
    vel: tuple[float, float] = (0.0, 0.0)   # sw/s (x verso destra, y verso il basso)
    speed: float = 0.0              # sw/s
    speed_n: float = 0.0            # 0..1, dopo la curva di risposta
    direction: tuple[float, float] = (0.0, 0.0)   # versore (0,0 se fermo)
    angle: float = 0.0              # radianti, direzione del movimento
    amplitude: float = 0.0          # 0..1, estensione del gesto nella finestra recente
    extension: float = 0.0          # 0..1, braccio piegato → disteso
    elevation: float = 0.0          # sw: >0 polso sopra la spalla, <0 sotto
    activity: float = 0.0           # 0..1, energia recente (decade lentamente)
    moving: bool = False            # dentro un tratto
    raw_pos_norm: tuple[float, float] | None = None   # misura grezza (debug)


@dataclass
class MotionState:
    timestamp: float = 0.0
    person_presence: float = 0.0
    arms: dict[str, ArmMotion] = field(default_factory=lambda: {s: ArmMotion(s) for s in SIDES})
    wrist_distance: float = 0.0     # sw
    closeness: float = 0.0          # 0..1 (1 = mani vicine)
    crossed: bool = False
    energy: float = 0.0             # 0..1, attività complessiva
    still_time: float = 0.0         # secondi senza movimento significativo
    session_active: bool = False    # la persona sta intrecciando un filo
    rest_time: float = 0.0          # da quanto le braccia sono lungo il corpo (s)
    absent_time: float = 0.0        # da quanto la persona non è nell'inquadratura (s)
    events: list[Event] = field(default_factory=list)


# ------------------------------------------------------------------ braccio
class ArmTracker:
    def __init__(self, side: str, p: dict):
        self.side = side
        self.out = ArmMotion(side)
        self.configure(p)
        self.filter = OneEuro2D(self.min_cutoff, self.beta, self.d_cutoff)
        self.pos = None                    # posizione filtrata, unità immagine (x*aspect, y)
        self.vel = np.zeros(2)             # unità immagine / s
        self.last_valid_t = -1e9
        self.rejections = 0
        self.history: deque = deque()      # (t, pos) per ampiezza
        self.dir_history: deque = deque()  # (t, angle)
        self.last_turn_t = -1e9
        self.stroke_start = None
        self.stroke_t0 = 0.0
        self.stroke_len = 0.0
        self.ext_ema = None
        self.elev_ema = None
        self.stats = {"outliers": 0, "resets": 0}

    def configure(self, p: dict) -> None:
        self.min_vis = p["min_visibility"]
        self.min_cutoff, self.beta, self.d_cutoff = p["smoothing_min_cutoff"], p["smoothing_beta"], p["smoothing_d_cutoff"]
        if hasattr(self, "filter"):
            self.filter.min_cutoff, self.filter.beta, self.filter.d_cutoff = self.min_cutoff, self.beta, self.d_cutoff
        self.max_speed = p["max_plausible_speed"]
        self.reacquire_frames = p["reacquire_after_rejections"]
        self.hold_time, self.inertia = p["hold_time"], p["hold_inertia"]
        self.fade_in, self.fade_out = p["fade_in"], p["fade_out"]
        self.speed_full, self.gamma = p["speed_for_full_response"], p["response_curve"]
        self.move_thr = p["movement_threshold"]
        self.stroke_min = p["stroke_min_length"]
        self.amp_window, self.amp_full = p["amplitude_window"], p["amplitude_full"]
        self.turn_angle = math.radians(p["turn_min_angle"])
        self.turn_window = p["turn_window"]
        self.activity_decay = p["activity_decay"]

    # -------------------------------------------------------------- update
    def update(self, meas: np.ndarray | None, arm_obs, t: float, dt: float, sw_img: float,
               aspect: float, events: list[Event]) -> None:
        o = self.out
        o.raw_pos_norm = None if meas is None else (meas[0] / aspect, meas[1])

        accepted = False
        if meas is not None:
            if self.pos is None or o.state == LOST:
                self._restart(meas, t, events, aspect)
                accepted = True
            else:
                gap = max(t - self.last_valid_t, dt, 1e-3)
                predicted = self.pos + self.vel * min(gap, self.hold_time)
                jump_speed = np.linalg.norm(meas - predicted) / sw_img / gap
                if jump_speed <= self.max_speed:
                    accepted = True
                    self.rejections = 0
                else:
                    self.rejections += 1
                    self.stats["outliers"] += 1
                    if self.rejections >= self.reacquire_frames:   # non era un errore: la mano è davvero lì
                        self._restart(meas, t, events, aspect)
                        accepted = True

        if accepted:
            prev = self.pos.copy()
            self.pos = self.filter(meas, t, sw_img)
            self.vel = self.filter.dx.copy()
            self.last_valid_t = t
            if o.state != TRACKING:
                o.state = TRACKING
            self.stroke_len += float(np.linalg.norm(self.pos - prev)) / sw_img
        elif self.pos is not None and o.state != LOST:
            # nessuna misura valida: prosegui per inerzia, poi fermati
            if t - self.last_valid_t <= self.hold_time:
                o.state = HOLDING
                self.vel *= math.exp(-dt / max(self.inertia, 1e-3))
                self.pos = self.pos + self.vel * dt
            else:
                o.state = LOST
                self.vel[:] = 0
                events.append(Event("lost", self.side, o.pos_norm, o.presence))

        target = 1.0 if o.state == TRACKING else 0.0
        o.presence = _approach(o.presence, target, dt, self.fade_in if target > o.presence else self.fade_out)
        if self.pos is None:
            return

        # ---- caratteristiche del gesto
        o.pos_norm = (float(self.pos[0] / aspect), float(self.pos[1]))
        v = self.vel / sw_img
        o.vel = (float(v[0]), float(v[1]))
        o.speed = float(np.linalg.norm(v)) if o.state != LOST else 0.0
        o.speed_n = float(min(o.speed / self.speed_full, 1.0) ** self.gamma)
        if o.speed > self.move_thr:
            o.direction = (float(v[0] / o.speed), float(v[1] / o.speed))
            o.angle = math.atan2(v[1], v[0])
        else:
            o.direction = (0.0, 0.0)

        o.activity = max(o.speed_n, o.activity * math.exp(-dt / max(self.activity_decay, 1e-3)))

        # ampiezza: estensione del percorso nella finestra recente
        if o.state == TRACKING:
            self.history.append((t, self.pos.copy()))
        while self.history and t - self.history[0][0] > self.amp_window:
            self.history.popleft()
        if len(self.history) > 1:
            pts = np.array([p for _, p in self.history])
            diag = float(np.linalg.norm(pts.max(0) - pts.min(0))) / sw_img
            o.amplitude = min(diag / self.amp_full, 1.0)
        else:
            o.amplitude *= math.exp(-dt / max(self.activity_decay, 1e-3))

        # estensione ed elevazione del braccio (dalla posa, lisciate)
        if arm_obs is not None and min(arm_obs.shoulder.visibility, arm_obs.elbow.visibility) >= self.min_vis \
                and o.state == TRACKING:
            sh = np.array([arm_obs.shoulder.x * aspect, arm_obs.shoulder.y])
            el = np.array([arm_obs.elbow.x * aspect, arm_obs.elbow.y])
            length = np.linalg.norm(el - sh) + np.linalg.norm(self.pos - el)
            ext = float(np.clip(np.linalg.norm(self.pos - sh) / max(length, 1e-6), 0, 1))
            ext = float(np.clip((ext - 0.3) / 0.7, 0, 1))      # braccio piegato ≈ 0.3
            elev = float((sh[1] - self.pos[1]) / sw_img)
            k = 1 - math.exp(-dt / 0.15)
            self.ext_ema = ext if self.ext_ema is None else self.ext_ema + k * (ext - self.ext_ema)
            self.elev_ema = elev if self.elev_ema is None else self.elev_ema + k * (elev - self.elev_ema)
            o.extension, o.elevation = self.ext_ema, self.elev_ema

        self._detect_turn(t, o, events)
        self._detect_stroke(t, o, events, sw_img, aspect)

    def _restart(self, meas, t, events, aspect) -> None:
        self.filter.reset(meas, t)
        self.pos = meas.copy()
        self.vel = np.zeros(2)
        self.history.clear()
        self.dir_history.clear()
        self.rejections = 0
        self.stroke_start = None
        self.out.moving = False
        self.out.segment_id += 1
        self.stats["resets"] += 1
        events.append(Event("appear", self.side, (float(meas[0] / aspect), float(meas[1]))))

    def _detect_turn(self, t, o: ArmMotion, events) -> None:
        if o.speed <= self.move_thr * 1.5 or o.state != TRACKING:
            self.dir_history.clear()
            return
        self.dir_history.append((t, o.angle))
        while self.dir_history and t - self.dir_history[0][0] > self.turn_window:
            self.dir_history.popleft()
        if len(self.dir_history) < 2 or t - self.last_turn_t < 0.25:
            return
        old = self.dir_history[0][1]
        diff = abs((o.angle - old + math.pi) % (2 * math.pi) - math.pi)
        if diff >= self.turn_angle:
            self.last_turn_t = t
            self.dir_history.clear()
            events.append(Event("turn", self.side, o.pos_norm, float(min(diff / math.pi, 1.0)) * max(o.speed_n, 0.3),
                                {"angle_change": diff}))

    def _detect_stroke(self, t, o: ArmMotion, events, sw_img, aspect) -> None:
        if not o.moving and o.speed > self.move_thr * 1.5 and o.state == TRACKING:
            o.moving = True
            self.stroke_start = o.pos_norm
            self.stroke_t0 = t
            self.stroke_len = 0.0
        elif o.moving and (o.speed < self.move_thr or o.state == LOST):
            o.moving = False
            if self.stroke_start and self.stroke_len >= self.stroke_min:
                sx, sy = self.stroke_start
                ex, ey = o.pos_norm
                events.append(Event("stroke", self.side, o.pos_norm, float(min(self.stroke_len / (2 * self.amp_full), 1.0)),
                                    {"start": self.stroke_start, "end": o.pos_norm, "length": self.stroke_len,
                                     "duration": t - self.stroke_t0,
                                     "displacement": float(math.hypot((ex - sx) * aspect, ey - sy) / sw_img)}))
            self.stroke_start = None


# ------------------------------------------------------------------ processore
DEFAULTS = dict(
    min_visibility=0.5, smoothing_min_cutoff=1.2, smoothing_beta=0.35, smoothing_d_cutoff=1.0,
    max_plausible_speed=14.0, reacquire_after_rejections=4, hold_time=0.35, hold_inertia=0.15,
    fade_in=0.25, fade_out=0.9, speed_for_full_response=5.0, response_curve=0.8,
    movement_threshold=0.5, stroke_min_length=0.6, amplitude_window=1.2, amplitude_full=2.0,
    turn_min_angle=70.0, turn_window=0.18, activity_decay=1.5, meet_distance=0.45,
    cross_margin=0.08, swap_min_jump=0.6, default_shoulder_width=0.22,
    session_exit_seconds=4.0, session_rest_seconds=5.0, rest_elevation=-1.0,
    session_min_strokes=2, session_min_length=2.0, session_full_length=40.0,
)


class MotionProcessor:
    def __init__(self, cfg: dict):
        self.p = {}
        self.configure(cfg)
        self.arms = {s: ArmTracker(s, self.p) for s in SIDES}
        self.state = MotionState()
        self.sw = None                 # larghezza spalle lisciata, unità immagine
        self.last_t = None
        self.crossed = False
        self.met = False
        self.stats = {"swaps_corrected": 0}     # episodi (non frame)
        self.swapping = False
        self._new_session()

    def configure(self, cfg: dict) -> None:
        p = dict(DEFAULTS)
        p.update(cfg.get("motion", {}))
        p["min_visibility"] = cfg.get("tracking", {}).get("min_visibility", p["min_visibility"])
        self.p = p
        for arm in getattr(self, "arms", {}).values():
            arm.configure(p)

    def update(self, obs: BodyObservation) -> MotionState:
        t = obs.timestamp
        dt = 1 / 30 if self.last_t is None else min(max(t - self.last_t, 1e-3), 0.25)
        self.last_t = t
        p, aspect = self.p, obs.aspect
        events: list[Event] = []

        # larghezza delle spalle (scala del corpo), lisciata
        if obs.present and obs.shoulder_width > 0:
            sw_now = obs.shoulder_width * aspect
            self.sw = sw_now if self.sw is None else self.sw + (1 - math.exp(-dt / 0.5)) * (sw_now - self.sw)
        sw = self.sw or p["default_shoulder_width"] * aspect

        # misure valide dei polsi
        meas, arm_obs = {}, {}
        for s in SIDES:
            a = obs.arms.get(s) if obs.present else None
            arm_obs[s] = a
            meas[s] = (np.array([a.wrist.x * aspect, a.wrist.y])
                       if a is not None and a.wrist.visibility >= p["min_visibility"] else None)

        # correzione scambi improvvisi destra/sinistra
        # Se MediaPipe inverte il corpo (succede negli incroci), l'inversione può
        # durare più frame: finché la misura invertita è più coerente con la
        # traiettoria, si continua a correggere. Si scambia l'intero braccio
        # (spalla, gomito, polso) così anche il calcolo dell'incrocio resta coerente.
        L, R = self.arms["left"], self.arms["right"]
        swap = False
        if meas["left"] is not None and meas["right"] is not None and L.pos is not None and R.pos is not None \
                and L.out.state == TRACKING and R.out.state == TRACKING:
            straight = np.linalg.norm(meas["left"] - L.pos) + np.linalg.norm(meas["right"] - R.pos)
            crossed = np.linalg.norm(meas["left"] - R.pos) + np.linalg.norm(meas["right"] - L.pos)
            swap = straight / sw > p["swap_min_jump"] and crossed < 0.4 * straight
        if swap:
            meas["left"], meas["right"] = meas["right"], meas["left"]
            arm_obs["left"], arm_obs["right"] = arm_obs["right"], arm_obs["left"]
            if not self.swapping:
                self.stats["swaps_corrected"] += 1
        self.swapping = swap

        for s in SIDES:
            self.arms[s].update(meas[s], arm_obs[s], t, dt, sw, aspect, events)

        st = self.state
        st.timestamp = t
        st.arms = {s: self.arms[s].out for s in SIDES}
        st.person_presence = _approach(st.person_presence, 1.0 if obs.present else 0.0, dt,
                                       p["fade_in"] if obs.present else p["fade_out"])
        self._pair(arm_obs, st, sw, aspect, events)
        st.energy = float(np.mean([a.activity * a.presence for a in st.arms.values()]))
        st.still_time = 0.0 if any(a.moving for a in st.arms.values()) else st.still_time + dt
        self._session(obs, st, dt, aspect, events)
        st.events = events
        return st

    # -------------------------------------------------------------- sessione
    # Una sessione è il lavoro di una persona su un filo: inizia con il primo
    # gesto di intreccio e finisce quando la persona esce dall'inquadratura o
    # tiene le braccia lungo il corpo per session_rest_seconds. Alla fine viene
    # emesso l'evento "complete" (filo completato).
    def _new_session(self) -> None:
        self.sess = dict(active=False, strokes=0, length=0.0, c2=0.0, s2=0.0, t0=0.0, rest=0.0, absent=0.0)

    def _session(self, obs, st: MotionState, dt: float, aspect: float, events: list) -> None:
        p, ss = self.p, self.sess
        for e in events:
            if e.kind == "stroke":
                if not ss["active"]:
                    ss.update(active=True, t0=st.timestamp)
                (sx, sy), (ex, ey) = e.data["start"], e.data["end"]
                a = math.atan2(-(ey - sy), (ex - sx) * aspect)
                L = e.data["length"]
                ss["strokes"] += 1
                ss["length"] += L
                ss["c2"] += L * math.cos(2 * a)     # media "assiale": avanti e indietro contano uguale
                ss["s2"] += L * math.sin(2 * a)

        ss["absent"] = 0.0 if obs.present else ss["absent"] + dt

        def resting(a: ArmMotion) -> bool:
            if a.state == LOST:                     # polso fuori dal bordo inferiore, corpo visibile
                return True
            return a.elevation < p["rest_elevation"] and a.speed < p["movement_threshold"] * 1.5
        if obs.present and all(resting(a) for a in st.arms.values()):
            ss["rest"] += dt
        else:
            ss["rest"] = 0.0

        st.session_active, st.rest_time, st.absent_time = ss["active"], ss["rest"], ss["absent"]
        if not ss["active"]:
            return
        reason = None
        if ss["absent"] >= p["session_exit_seconds"]:
            reason = "uscita"
        elif ss["rest"] >= p["session_rest_seconds"]:
            reason = "braccia a riposo"
        if reason is None:
            return
        if ss["strokes"] >= p["session_min_strokes"] and ss["length"] >= p["session_min_length"]:
            events.append(Event("complete", None, (0.5, 0.5),
                                float(min(ss["length"] / p["session_full_length"], 1.0)),
                                {"strokes": ss["strokes"], "length": ss["length"],
                                 "angle": 0.5 * math.atan2(ss["s2"], ss["c2"]),
                                 "duration": st.timestamp - ss["t0"], "reason": reason}))
        self._new_session()

    def _pair(self, arm_obs, st: MotionState, sw, aspect, events) -> None:
        a, b = st.arms["left"], st.arms["right"]
        both = a.presence > 0.5 and b.presence > 0.5
        if not both:
            st.closeness = _approach(st.closeness, 0.0, 1 / 30, 0.5)
            return
        L, R = self.arms["left"].pos, self.arms["right"].pos
        d = float(np.linalg.norm(L - R)) / sw
        st.wrist_distance = d
        st.closeness = float(np.clip(1.0 - d / (3 * self.p["meet_distance"]), 0, 1))
        mid = ((a.pos_norm[0] + b.pos_norm[0]) / 2, (a.pos_norm[1] + b.pos_norm[1]) / 2)

        # incrocio: l'ordine dei polsi è invertito rispetto a quello delle spalle
        if arm_obs["left"] is not None and arm_obs["right"] is not None:
            sh_sign = np.sign(arm_obs["left"].shoulder.x - arm_obs["right"].shoulder.x)
            rel = (L[0] - R[0]) / sw * sh_sign          # >0 ordine normale, <0 incrociati
            m = self.p["cross_margin"]
            if not self.crossed and rel < -m:
                self.crossed = True
                events.append(Event("cross", None, mid, float(max(a.speed_n, b.speed_n, 0.3))))
            elif self.crossed and rel > m:
                self.crossed = False
                events.append(Event("uncross", None, mid, float(max(a.speed_n, b.speed_n, 0.3))))
        st.crossed = self.crossed

        md = self.p["meet_distance"]
        if not self.met and d < md:
            self.met = True
            events.append(Event("meet", None, mid, float(max(a.speed_n, b.speed_n, 0.3))))
        elif self.met and d > md * 1.4:
            self.met = False
            events.append(Event("part", None, mid, float(max(a.speed_n, b.speed_n, 0.3))))
