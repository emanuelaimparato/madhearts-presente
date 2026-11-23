"""Modulo di riconoscimento del corpo (FASE 2).

Base: MediaPipe PoseLandmarker (spalle, gomiti, polsi, e i punti mano grezzi
che la posa fornisce: indice, mignolo, pollice).
Dettaglio opzionale: MediaPipe HandLandmarker (21 punti per mano).

Scelte per l'intreccio dei fili:
- I lati "left"/"right" sono ANATOMICI (braccio sinistro/destro della persona)
  e vengono dalla posa, che sa a quale braccio appartiene ogni polso anche
  quando le mani si incrociano.
- Le mani rilevate da HandLandmarker NON vengono assegnate usando la sua
  etichetta destra/sinistra (che si scambia facilmente negli incroci), ma
  associandole al polso della posa più vicino.
- Il riconoscimento gira sull'immagine NON specchiata (come vista dalla camera);
  lo specchio viene applicato solo alle coordinate in uscita. Così il modello
  non confonde destra e sinistra.

Coordinate in uscita: normalizzate 0..1 rispetto all'immagine (x verso destra,
y verso il basso), già specchiate se camera.mirror = true.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

from .capture import Camera, Frame
from .config import PROJECT_ROOT

SIDES = ("left", "right")
# indici dei punti della posa MediaPipe (33 punti): (sinistra, destra)
POSE_IDX = {
    "shoulder": (11, 12),
    "elbow": (13, 14),
    "wrist": (15, 16),
    "pinky": (17, 18),
    "index": (19, 20),
    "thumb": (21, 22),
    "hip": (23, 24),
}
NOSE = 0


@dataclass
class Point:
    x: float
    y: float
    z: float = 0.0
    visibility: float = 1.0


@dataclass
class Arm:
    side: str
    shoulder: Point | None = None
    elbow: Point | None = None
    wrist: Point | None = None
    index: Point | None = None
    pinky: Point | None = None
    thumb: Point | None = None
    hand: list[Point] | None = None      # 21 punti da HandLandmarker, se associati

    def hand_center(self, min_vis: float) -> Point | None:
        """Centro della mano: dai 21 punti se disponibili, altrimenti dai punti mano della posa."""
        if self.hand:
            xs = [p.x for p in self.hand]
            ys = [p.y for p in self.hand]
            return Point(float(np.mean(xs)), float(np.mean(ys)), 0.0, 1.0)
        pts = [p for p in (self.wrist, self.index, self.pinky, self.thumb)
               if p is not None and p.visibility >= min_vis]
        if not pts:
            return None
        return Point(float(np.mean([p.x for p in pts])), float(np.mean([p.y for p in pts])),
                     0.0, float(min(p.visibility for p in pts)))


@dataclass
class BodyObservation:
    frame_id: int
    timestamp: float                     # istante di acquisizione del frame
    present: bool = False
    arms: dict[str, Arm] = field(default_factory=dict)
    nose: Point | None = None
    hips: tuple[Point, Point] | None = None
    shoulder_width: float = 0.0          # in unità normalizzate di x
    aspect: float = 16 / 9               # larghezza/altezza dell'immagine
    pose_ms: float = 0.0
    hands_ms: float = 0.0
    hands_detected: int = 0


# ---------------------------------------------------------------- preprocessing
class Preprocessor:
    """Miglioramento del contrasto per luce scarsa (CLAHE sulla luminanza)."""

    def __init__(self, cfg: dict):
        self.update(cfg)

    def update(self, cfg: dict) -> None:
        p = cfg.get("preprocess", {})
        self.enabled = p.get("clahe_enabled", True)
        g = int(p.get("clahe_tile_grid", 8))
        self._clahe = cv2.createCLAHE(clipLimit=float(p.get("clahe_clip_limit", 2.0)),
                                      tileGridSize=(g, g))

    def __call__(self, bgr: np.ndarray) -> np.ndarray:
        if not self.enabled:
            return bgr
        lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        lab = cv2.merge((self._clahe.apply(l), a, b))
        return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


# ---------------------------------------------------------------- tracker
def _model_path(name: str) -> str:
    path = PROJECT_ROOT / "models" / name
    if not path.exists():
        raise FileNotFoundError(f"Modello mancante: {path}\n"
                                "Esegui una volta:  python -m tools.download_models")
    return str(path)


def _base_options(model: str, delegate: str) -> BaseOptions:
    d = BaseOptions.Delegate.GPU if delegate == "gpu" else BaseOptions.Delegate.CPU
    return BaseOptions(model_asset_path=_model_path(model), delegate=d)


class Tracker:
    def __init__(self, cfg: dict):
        t = cfg.get("tracking", {})
        self.mirror = cfg.get("camera", {}).get("mirror", True)
        self.min_vis = float(t.get("min_visibility", 0.5))
        self.hands_enabled = bool(t.get("hands_enabled", True))
        self.hands_every = max(1, int(t.get("hands_every_n_frames", 1)))
        self.hand_match_max = float(t.get("hand_match_max_distance", 0.6))
        self.inference_width = int(t.get("inference_width", 0))
        self.pose_model = t.get("pose_model", "full")
        self.preprocess = Preprocessor(cfg)
        requested = t.get("delegate", "cpu")

        conf = dict(min_tracking_confidence=float(t.get("min_tracking_confidence", 0.5)))
        det = float(t.get("min_detection_confidence", 0.5))
        pres = float(t.get("min_presence_confidence", 0.5))

        def build(delegate: str):
            pose = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
                base_options=_base_options(f"pose_landmarker_{self.pose_model}.task", delegate),
                running_mode=vision.RunningMode.VIDEO, num_poses=1,
                min_pose_detection_confidence=det, min_pose_presence_confidence=pres, **conf))
            hands = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
                base_options=_base_options("hand_landmarker.task", delegate),
                running_mode=vision.RunningMode.VIDEO, num_hands=2,
                min_hand_detection_confidence=det, min_hand_presence_confidence=pres, **conf))
            return pose, hands

        try:
            self._pose, self._hands = build(requested)
            self.delegate = requested
        except Exception as e:
            if requested == "cpu":
                raise
            print(f"[tracking] delegate '{requested}' non disponibile ({e}); uso la CPU.")
            self._pose, self._hands = build("cpu")
            self.delegate = "cpu"

        self._last_ts_ms = 0
        self._count = 0
        self._last_hands: list[list[Point]] = []

    def _ts(self, frame: Frame) -> int:
        ts = int(frame.timestamp * 1000)
        if ts <= self._last_ts_ms:            # VIDEO mode richiede timestamp crescenti
            ts = self._last_ts_ms + 1
        self._last_ts_ms = ts
        return ts

    def _pt(self, lm) -> Point:
        x = 1.0 - lm.x if self.mirror else lm.x
        vis = lm.visibility if lm.visibility is not None else 1.0
        # MediaPipe "indovina" anche i punti fuori dall'inquadratura, a volte con visibilità
        # alta: la "presence" dice invece se il punto è davvero dentro l'immagine.
        pres = getattr(lm, "presence", None)
        if pres is not None:
            vis = min(vis, pres)
        if not (-0.02 <= lm.x <= 1.02 and -0.02 <= lm.y <= 1.02):
            vis = 0.0
        return Point(float(x), float(lm.y), float(lm.z or 0.0), float(vis))

    def process(self, frame: Frame) -> BodyObservation:
        img = frame.image
        h, w = img.shape[:2]
        if self.inference_width and w > self.inference_width:
            s = self.inference_width / w
            img = cv2.resize(img, (self.inference_width, int(h * s)), interpolation=cv2.INTER_AREA)
        img = self.preprocess(img)
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        ts = self._ts(frame)
        obs = BodyObservation(frame.frame_id, frame.timestamp, aspect=w / h)

        t0 = time.perf_counter()
        pose_res = self._pose.detect_for_video(mp_img, ts)
        obs.pose_ms = (time.perf_counter() - t0) * 1000

        self._count += 1
        if self.hands_enabled:
            if self._count % self.hands_every == 0:
                t0 = time.perf_counter()
                hand_res = self._hands.detect_for_video(mp_img, ts)
                obs.hands_ms = (time.perf_counter() - t0) * 1000
                self._last_hands = [[self._pt(lm) for lm in hand] for hand in hand_res.hand_landmarks]
            obs.hands_detected = len(self._last_hands)
        else:
            self._last_hands = []

        if not pose_res.pose_landmarks:
            return obs
        lms = pose_res.pose_landmarks[0]
        obs.present = True
        obs.nose = self._pt(lms[NOSE])
        obs.hips = (self._pt(lms[POSE_IDX["hip"][0]]), self._pt(lms[POSE_IDX["hip"][1]]))
        for i, side in enumerate(SIDES):
            arm = Arm(side)
            for part in ("shoulder", "elbow", "wrist", "pinky", "index", "thumb"):
                setattr(arm, part, self._pt(lms[POSE_IDX[part][i]]))
            obs.arms[side] = arm
        ls, rs = obs.arms["left"].shoulder, obs.arms["right"].shoulder
        obs.shoulder_width = float(np.hypot((ls.x - rs.x) * obs.aspect, ls.y - rs.y)) / obs.aspect

        self._match_hands(obs)
        return obs

    def _match_hands(self, obs: BodyObservation) -> None:
        """Associa ogni mano rilevata al polso della posa più vicino (non all'etichetta dx/sx)."""
        hands = self._last_hands
        if not hands or obs.shoulder_width <= 0:
            return
        max_d = self.hand_match_max * obs.shoulder_width
        wrists = {s: obs.arms[s].wrist for s in SIDES}

        def d(hand, side):
            wr = wrists[side]
            return float(np.hypot((hand[0].x - wr.x) * obs.aspect, hand[0].y - wr.y)) / obs.aspect

        best: dict[str, list[Point]] = {}
        if len(hands) >= 2:
            a, b = hands[0], hands[1]
            straight = d(a, "left") + d(b, "right")
            crossed = d(a, "right") + d(b, "left")
            pairs = [(a, "left"), (b, "right")] if straight <= crossed else [(a, "right"), (b, "left")]
        else:
            h0 = hands[0]
            pairs = [(h0, min(SIDES, key=lambda s: d(h0, s)))]
        for hand, side in pairs:
            if d(hand, side) <= max_d:
                best[side] = hand
        for side, hand in best.items():
            obs.arms[side].hand = hand

    def close(self) -> None:
        self._pose.close()
        self._hands.close()


class TrackerThread:
    """Legge sempre l'ultimo frame dalla camera e pubblica l'ultima osservazione.
    Se il riconoscimento è più lento della camera, i frame intermedi vengono
    saltati (meglio saltare che accumulare ritardo)."""

    def __init__(self, camera: Camera, tracker: Tracker):
        self.camera, self.tracker = camera, tracker
        self._lock = threading.Lock()
        self._latest: tuple[Frame, BodyObservation] | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._stamps: list[float] = []
        self.error: Exception | None = None

    def start(self) -> "TrackerThread":
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="tracker", daemon=True)
        self._thread.start()
        return self

    def _loop(self) -> None:
        last_id = 0
        while self._running:
            f = self.camera.read()
            if f is None or f.frame_id == last_id:
                time.sleep(0.002)
                continue
            last_id = f.frame_id
            try:
                obs = self.tracker.process(f)
            except Exception as e:           # non bloccare l'esperienza per un frame difettoso
                self.error = e
                continue
            now = time.perf_counter()
            with self._lock:
                self._latest = (f, obs)
                self._stamps = [t for t in self._stamps if now - t < 2.0] + [now]

    def read(self) -> tuple[Frame, BodyObservation] | None:
        with self._lock:
            return self._latest

    def fps(self) -> float:
        with self._lock:
            s = list(self._stamps)
        return (len(s) - 1) / (s[-1] - s[0]) if len(s) > 1 and s[-1] > s[0] else 0.0

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        self.tracker.close()
