"""Modulo di acquisizione video.

La camera viene letta in un thread dedicato che conserva SOLO il frame più
recente: chi consuma i frame (riconoscimento, debug) prende sempre l'ultimo
disponibile, senza code che accumulano ritardo. Questo è il primo
accorgimento per avere bassa latenza tra gesto e immagine.

Privacy: questo modulo non salva, non registra e non trasmette immagini.
I frame vivono solo in memoria e vengono sovrascritti a ogni lettura.
"""
from __future__ import annotations

import sys
import threading
import time
from collections import deque
from dataclasses import dataclass

import cv2
import numpy as np

_BACKENDS = {
    "avfoundation": cv2.CAP_AVFOUNDATION,
    "any": cv2.CAP_ANY,
}


class CameraError(RuntimeError):
    pass


@dataclass
class Frame:
    image: np.ndarray      # BGR, già specchiato se mirror=True
    frame_id: int          # contatore crescente
    timestamp: float       # time.perf_counter() al momento della lettura


class Camera:
    def __init__(self, index: int = 0, width: int = 1280, height: int = 720,
                 fps: int = 30, mirror: bool = True, backend: str = "avfoundation",
                 reconnect_after_failures: int = 30):
        self.index = index
        self.req_width, self.req_height, self.req_fps = width, height, fps
        self.mirror = mirror
        if backend == "avfoundation" and sys.platform != "darwin":
            backend = "any"   # permette di provare il codice anche fuori da macOS
        self.api = _BACKENDS.get(backend, cv2.CAP_ANY)
        self.reconnect_after_failures = reconnect_after_failures

        self._cap: cv2.VideoCapture | None = None
        self._lock = threading.Lock()
        self._latest: Frame | None = None
        self._frame_id = 0
        self._stamps: deque[float] = deque(maxlen=120)
        self._running = False
        self._thread: threading.Thread | None = None

        self.actual_size: tuple[int, int] = (0, 0)
        self.reported_fps: float = 0.0
        self.reconnections = 0

    @classmethod
    def from_config(cls, cfg: dict) -> "Camera":
        c = cfg["camera"]
        return cls(index=c.get("index", 0), width=c.get("width", 1280),
                   height=c.get("height", 720), fps=c.get("fps", 30),
                   mirror=c.get("mirror", True), backend=c.get("backend", "avfoundation"),
                   reconnect_after_failures=c.get("reconnect_after_failures", 30))

    # ------------------------------------------------------------------ apertura
    def _open_device(self) -> None:
        cap = cv2.VideoCapture(self.index, self.api)
        if not cap.isOpened():
            raise CameraError(
                f"Impossibile aprire la videocamera {self.index}.\n"
                "• Controlla Impostazioni di Sistema → Privacy e sicurezza → Fotocamera\n"
                "  e abilita l'app da cui lanci Python (Terminale, iTerm, VS Code...).\n"
                "• Dopo aver concesso il permesso, chiudi e riapri quell'app.\n"
                "• Verifica che nessun'altra app (FaceTime, Zoom, browser) stia usando la camera.")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.req_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.req_height)
        cap.set(cv2.CAP_PROP_FPS, self.req_fps)

        # Il primo frame su macOS può arrivare dopo qualche centinaio di ms.
        deadline = time.perf_counter() + 3.0
        frame = None
        while time.perf_counter() < deadline:
            ok, frame = cap.read()
            if ok and frame is not None:
                break
            time.sleep(0.02)
        else:
            cap.release()
            raise CameraError("La videocamera si apre ma non restituisce frame "
                              "(permesso negato o camera occupata).")
        self.actual_size = (frame.shape[1], frame.shape[0])
        self.reported_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        self._cap = cap

    def start(self) -> "Camera":
        self._open_device()
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="camera", daemon=True)
        self._thread.start()
        return self

    # ------------------------------------------------------------------ thread
    def _loop(self) -> None:
        failures = 0
        while self._running:
            ok, img = self._cap.read()
            if not ok or img is None:
                failures += 1
                if failures >= self.reconnect_after_failures:
                    self._reconnect()
                    failures = 0
                else:
                    time.sleep(0.01)
                continue
            failures = 0
            img = cv2.flip(img, 1) if self.mirror else img.copy()
            now = time.perf_counter()
            with self._lock:
                self._frame_id += 1
                self._latest = Frame(img, self._frame_id, now)
                self._stamps.append(now)

    def _reconnect(self) -> None:
        try:
            self._cap.release()
        except Exception:
            pass
        while self._running:
            try:
                self._open_device()
                self.reconnections += 1
                return
            except CameraError:
                time.sleep(1.0)

    # ------------------------------------------------------------------ API
    def read(self) -> Frame | None:
        """Ultimo frame disponibile (o None se ancora nessuno).
        Il chiamante può disegnarci sopra: il thread non lo modifica più."""
        with self._lock:
            return self._latest

    def measured_fps(self) -> float:
        """Frame rate reale misurato sugli ultimi ~2 secondi."""
        with self._lock:
            stamps = list(self._stamps)
        now = time.perf_counter()
        recent = [t for t in stamps if now - t <= 2.0]
        if len(recent) < 2:
            return 0.0
        return (len(recent) - 1) / (recent[-1] - recent[0])

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
