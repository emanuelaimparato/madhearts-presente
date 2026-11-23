"""FASE 2 — Test del riconoscimento di spalle, gomiti, polsi e mani.

Uso:
    python -m tools.tracking_test
    python -m tools.tracking_test --model lite     # confronta i modelli: lite / full / heavy

Tasti:  Q / ESC esci  ·  I info  ·  C contrasto per luce scarsa (CLAHE) on/off
        H riconoscimento mani on/off  ·  R azzera le statistiche

Prova suggerita (circa 1 minuto per ciascuna):
  1. braccia lungo i fianchi, poi alzale lentamente
  2. gesti da intreccio: mani davanti al petto che si incrociano e si sovrappongono
  3. movimenti veloci e ampi
  4. ripeti con la luce della stanza dell'installazione, con C attivo e disattivo

Nessuna immagine viene salvata.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from collections import defaultdict, deque

import cv2
import numpy as np

from madhearts.capture import Camera, CameraError
from madhearts.config import load_config
from madhearts.tracking import SIDES, BodyObservation, Tracker, TrackerThread

WINDOW = "MadHearts - Fase 2 - riconoscimento"
COLORS = {"left": (255, 80, 220), "right": (255, 220, 60)}   # BGR: magenta / ciano
HAND_EDGES = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10),
              (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (0, 17),
              (17, 18), (18, 19), (19, 20)]


class Stats:
    """Statistiche separate per stato del CLAHE (per confrontare on/off)."""

    def __init__(self, jump_threshold: float = 0.35):
        self.jump_threshold = jump_threshold     # in multipli di larghezza spalle
        self.reset()

    def reset(self) -> None:
        self.d = defaultdict(lambda: defaultdict(list))
        self.prev: BodyObservation | None = None

    def add(self, obs: BodyObservation, key: str, min_vis: float) -> None:
        s = self.d[key]
        s["present"].append(obs.present)
        s["pose_ms"].append(obs.pose_ms)
        if obs.hands_ms:
            s["hands_ms"].append(obs.hands_ms)
        s["latency_ms"].append((time.perf_counter() - obs.timestamp) * 1000)
        for side in SIDES:
            arm = obs.arms.get(side)
            vis = bool(arm and arm.wrist.visibility >= min_vis)
            s[f"wrist_{side}"].append(vis)
            s[f"hand_{side}"].append(bool(arm and arm.hand))
        p = self.prev
        if p and p.present and obs.present and obs.shoulder_width > 0 and all(
                min(p.arms[k].wrist.visibility, obs.arms[k].wrist.visibility) >= min_vis for k in SIDES):
            sw = obs.shoulder_width
            cur = {k: np.array([obs.arms[k].wrist.x * obs.aspect, obs.arms[k].wrist.y]) for k in SIDES}
            old = {k: np.array([p.arms[k].wrist.x * p.aspect, p.arms[k].wrist.y]) for k in SIDES}
            straight = {k: np.linalg.norm(cur[k] - old[k]) / obs.aspect / sw for k in SIDES}
            for k in SIDES:
                s[f"jump_{k}"].append(straight[k] > self.jump_threshold)
            crossed = (np.linalg.norm(cur["left"] - old["right"]) + np.linalg.norm(cur["right"] - old["left"])) / obs.aspect / sw
            direct = straight["left"] + straight["right"]
            s["swap"].append(direct > self.jump_threshold and crossed < 0.5 * direct)
        self.prev = obs

    def report(self) -> str:
        out = []
        pct = lambda v: f"{100 * sum(v) / len(v):5.1f}%" if v else "   n/d"
        for key, s in self.d.items():
            n = len(s["present"])
            if n < 10:
                continue
            q = lambda v: (f"media {statistics.mean(v):5.1f}  p95 {np.percentile(v, 95):5.1f}" if v else "n/d")
            out += [f"--- {key}  ({n} frame analizzati)",
                    f"persona rilevata      {pct(s['present'])}",
                    f"polso sx / dx visib.  {pct(s['wrist_left'])} / {pct(s['wrist_right'])}",
                    f"mano sx / dx (21 pt)  {pct(s['hand_left'])} / {pct(s['hand_right'])}",
                    f"salti polso sx / dx   {sum(s['jump_left'])} / {sum(s['jump_right'])}",
                    f"scambi sx<->dx        {sum(s['swap'])}",
                    f"posa ms               {q(s['pose_ms'])}",
                    f"mani ms               {q(s['hands_ms'])}",
                    f"latenza totale ms     {q(s['latency_ms'])}"]
        return "\n".join(out)


def to_px(p, w, h):
    return int(p.x * w), int(p.y * h)


def draw(img: np.ndarray, obs: BodyObservation, trails: dict, min_vis: float) -> None:
    h, w = img.shape[:2]
    if not obs.present:
        return
    for side in SIDES:
        arm = obs.arms[side]
        col = COLORS[side]
        chain = [arm.shoulder, arm.elbow, arm.wrist]
        for a, b in zip(chain, chain[1:]):
            if min(a.visibility, b.visibility) >= min_vis:
                cv2.line(img, to_px(a, w, h), to_px(b, w, h), col, 2, cv2.LINE_AA)
        for i, p in enumerate(chain + [arm.index, arm.pinky, arm.thumb]):
            filled = -1 if p.visibility >= min_vis else 1
            cv2.circle(img, to_px(p, w, h), 7 if i < 3 else 4, col, filled, cv2.LINE_AA)
        if arm.hand:
            pts = [to_px(p, w, h) for p in arm.hand]
            for i, j in HAND_EDGES:
                cv2.line(img, pts[i], pts[j], (255, 255, 255), 1, cv2.LINE_AA)
            for pt in pts:
                cv2.circle(img, pt, 3, col, -1, cv2.LINE_AA)
        if arm.wrist.visibility >= min_vis:
            trails[side].append(to_px(arm.wrist, w, h))
        tr = list(trails[side])
        for i in range(1, len(tr)):
            cv2.line(img, tr[i - 1], tr[i], col, max(1, i // 6), cv2.LINE_AA)
        label = "SX" if side == "left" else "DX"
        x, y = to_px(arm.wrist, w, h)
        cv2.putText(img, label, (x + 10, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2, cv2.LINE_AA)


def text(img, lines):
    for i, s in enumerate(lines):
        y = 28 + i * 26
        cv2.putText(img, s, (14, y), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(img, s, (14, y), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 1, cv2.LINE_AA)


def main() -> None:
    ap = argparse.ArgumentParser(description="MadHearts - Fase 2: riconoscimento del corpo")
    ap.add_argument("--config")
    ap.add_argument("--model", choices=["lite", "full", "heavy"])
    args = ap.parse_args()
    cfg = load_config(args.config)
    if args.model:
        cfg["tracking"]["pose_model"] = args.model
    mirror = cfg["camera"].get("mirror", True)
    min_vis = cfg["tracking"].get("min_visibility", 0.5)

    try:
        tracker = Tracker(cfg)
    except FileNotFoundError as e:
        print(e)
        sys.exit(1)
    cam_cfg = dict(cfg, camera=dict(cfg["camera"], mirror=False))  # specchio gestito dal tracker
    try:
        cam = Camera.from_config(cam_cfg).start()
    except CameraError as e:
        print(e)
        sys.exit(1)
    worker = TrackerThread(cam, tracker).start()
    print(f"modello posa: {tracker.pose_model}  delegate: {tracker.delegate}  "
          f"camera {cam.actual_size[0]}x{cam.actual_size[1]}")

    stats = Stats()
    trails = {s: deque(maxlen=24) for s in SIDES}
    show_info, last_id = True, 0
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    try:
        while True:
            item = worker.read()
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("i"):
                show_info = not show_info
            if key == ord("c"):
                tracker.preprocess.enabled = not tracker.preprocess.enabled
            if key == ord("h"):
                tracker.hands_enabled = not tracker.hands_enabled
            if key == ord("r"):
                stats.reset()
            if item is None or item[1].frame_id == last_id:
                continue
            frame, obs = item
            last_id = obs.frame_id
            stats_key = f"CLAHE {'on' if tracker.preprocess.enabled else 'off'}, mani {'on' if tracker.hands_enabled else 'off'}"
            stats.add(obs, stats_key, min_vis)

            img = cv2.flip(frame.image, 1) if mirror else frame.image.copy()
            draw(img, obs, trails, min_vis)
            if show_info:
                lum = float(cv2.cvtColor(cv2.resize(frame.image, (160, 90)), cv2.COLOR_BGR2GRAY).mean())
                wv = {s: (obs.arms[s].wrist.visibility if obs.present else 0) for s in SIDES}
                text(img, [
                    f"modello {tracker.pose_model}   fps riconoscimento {worker.fps():4.1f}   camera {cam.measured_fps():4.1f}",
                    f"posa {obs.pose_ms:4.1f} ms   mani {obs.hands_ms:4.1f} ms   latenza {(time.perf_counter() - obs.timestamp) * 1000:4.0f} ms",
                    f"persona {'SI' if obs.present else 'no'}   polso SX {wv['left']:.2f}  DX {wv['right']:.2f}   mani viste {obs.hands_detected}",
                    f"[C] contrasto {'ON' if tracker.preprocess.enabled else 'off'}   [H] mani {'ON' if tracker.hands_enabled else 'off'}   luminosita' {lum:.0f}",
                ])
            if worker.error:
                print(f"[avviso] errore in un frame: {worker.error}")
                worker.error = None
            cv2.imshow(WINDOW, img)
            if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        worker.stop()
        cam.stop()
        cv2.destroyAllWindows()

    print("\n===== RIEPILOGO FASE 2 (copialo nella risposta) =====")
    print(f"modello {tracker.pose_model}, camera {cam.actual_size[0]}x{cam.actual_size[1]}")
    print(stats.report() or "troppo pochi frame analizzati")


if __name__ == "__main__":
    main()
