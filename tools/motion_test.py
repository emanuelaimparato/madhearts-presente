"""FASE 3 — Test dell'elaborazione del movimento.

Uso:
    python -m tools.motion_test

Cosa vedi:
  - puntini grigi  = posizione grezza del polso (MediaPipe)
  - cerchio colore = posizione filtrata (quella che userà il motore visivo);
                     la sua opacità è la "presenza" del braccio
  - freccia        = direzione e velocità
  - scia           = percorso filtrato (si interrompe quando il tracking riparte)
  - in basso       = velocità grezza (grigio) e filtrata (colore) degli ultimi 5 s
  - scritte        = eventi: TRATTO, SVOLTA, INCROCIO, INCONTRO, ...

Tasti: Q/ESC esci · I info · B camera on/off (sfondo nero) · R azzera statistiche
config.toml si ricarica a caldo: cambia [motion], salva, e vedi subito l'effetto.

Prova suggerita: in piedi, alla distanza dell'installazione, simula il gesto di
portare un filo da un anello all'altro, lento e poi veloce; incrocia le braccia;
fermati del tutto per qualche secondo; esci dall'inquadratura e rientra.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from collections import Counter, deque

import cv2
import numpy as np

from madhearts.capture import Camera, CameraError
from madhearts.config import ConfigWatcher
from madhearts.motion import HOLDING, LOST, TRACKING, MotionProcessor
from madhearts.tracking import SIDES, Tracker, TrackerThread

WINDOW = "MadHearts - Fase 3 - movimento"
COLORS = {"left": (255, 80, 220), "right": (255, 220, 60)}
EVENT_NAMES = {"stroke": "TRATTO", "turn": "SVOLTA", "cross": "INCROCIO", "uncross": "SCIOLTO",
               "meet": "INCONTRO", "part": "SEPARAZIONE", "appear": "APPARE", "lost": "PERSO",
               "complete": "FILO COMPLETATO"}
GRAPH_SECONDS = 5.0


class Stats:
    def __init__(self):
        self.reset()

    def reset(self):
        self.n = 0
        self.state = {s: Counter() for s in SIDES}
        self.raw_jumps = Counter()
        self.filt_jumps = Counter()
        self.raw_jitter = {s: [] for s in SIDES}
        self.filt_jitter = {s: [] for s in SIDES}
        self.events = Counter()
        self.prev_raw = {s: None for s in SIDES}
        self.prev_filt = {s: None for s in SIDES}
        self.prev_seg = {s: None for s in SIDES}
        self.t0 = time.perf_counter()
        self.base = None

    def add(self, st, sw_norm: float, aspect: float):
        self.n += 1
        for e in st.events:
            self.events[e.kind] += 1
        for s in SIDES:
            a = st.arms[s]
            self.state[s][a.state] += 1
            to_sw = lambda p, q: np.hypot((p[0] - q[0]) * aspect, p[1] - q[1]) / (sw_norm * aspect)
            if a.raw_pos_norm and self.prev_raw[s]:
                d = to_sw(a.raw_pos_norm, self.prev_raw[s])
                self.raw_jumps[s] += d > 0.35
                if a.speed < 0.3:
                    self.raw_jitter[s].append(d)
            if a.state != LOST and self.prev_filt[s] and self.prev_seg[s] == a.segment_id:
                d = to_sw(a.pos_norm, self.prev_filt[s])
                self.filt_jumps[s] += d > 0.35
                if a.speed < 0.3 and a.raw_pos_norm:
                    self.filt_jitter[s].append(d)
            self.prev_raw[s] = a.raw_pos_norm
            self.prev_filt[s] = a.pos_norm if a.state != LOST else None
            self.prev_seg[s] = a.segment_id

    def report(self, proc: MotionProcessor) -> str:
        if self.n < 10:
            return "troppo pochi frame analizzati"
        pct = lambda c, k: f"{100 * c[k] / max(sum(c.values()), 1):5.1f}%"
        jit = lambda v: f"{100 * statistics.mean(v):5.2f}%" if v else "  n/d"
        out = [f"frame analizzati       {self.n}  ({time.perf_counter() - self.t0:.0f} s)"]
        for s, name in (("left", "SX"), ("right", "DX")):
            c = self.state[s]
            arm = proc.arms[s]
            out += [f"--- braccio {name}",
                    f"stato tracking/inerzia/perso  {pct(c, TRACKING)} / {pct(c, HOLDING)} / {pct(c, LOST)}",
                    f"salti grezzi -> filtrati      {self.raw_jumps[s]} -> {self.filt_jumps[s]}",
                    f"tremolio da fermo grezzo -> filtrato  {jit(self.raw_jitter[s])} -> {jit(self.filt_jitter[s])} "
                    f"(della larghezza spalle, per frame)",
                    f"errori scartati               {arm.stats['outliers']}",
                    f"ripartenze traccia            {arm.stats['resets']}"]
        out += [f"--- coppia",
                f"scambi sx<->dx (episodi)     {proc.stats['swaps_corrected']}",
                "eventi                        " + ", ".join(f"{EVENT_NAMES.get(k, k)} {v}" for k, v in sorted(self.events.items()))]
        return "\n".join(out)


def put(img, s, org, scale=0.6, col=(255, 255, 255), th=1):
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), th + 3, cv2.LINE_AA)
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, col, th, cv2.LINE_AA)


def main() -> None:
    ap = argparse.ArgumentParser(description="MadHearts - Fase 3: elaborazione del movimento")
    ap.add_argument("--config")
    args = ap.parse_args()
    watcher = ConfigWatcher(args.config)
    cfg = watcher.config
    mirror = cfg["camera"].get("mirror", True)

    try:
        tracker = Tracker(cfg)
    except FileNotFoundError as e:
        print(e)
        sys.exit(1)
    try:
        cam = Camera.from_config(dict(cfg, camera=dict(cfg["camera"], mirror=False))).start()
    except CameraError as e:
        print(e)
        sys.exit(1)
    worker = TrackerThread(cam, tracker).start()
    proc = MotionProcessor(cfg)
    stats = Stats()

    trails = {s: deque(maxlen=45) for s in SIDES}
    graph = {s: deque() for s in SIDES}            # (t, raw_speed, filt_speed)
    prev_raw = {s: None for s in SIDES}
    banners: deque = deque(maxlen=6)               # (t, text, color, pos)
    show_info, show_cam, last_id = True, True, 0
    last_poll = time.perf_counter()
    sw_norm = 0.2
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)

    try:
        while True:
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("i"):
                show_info = not show_info
            if key == ord("b"):
                show_cam = not show_cam
            if key == ord("r"):
                stats.reset()
            now = time.perf_counter()
            if now - last_poll > 0.5:
                last_poll = now
                if watcher.poll():
                    proc.configure(watcher.config)
                    banners.append((now, "config ricaricata", (120, 255, 120), None))
                elif watcher.last_error:
                    banners.append((now, "errore in config.toml", (80, 80, 255), None))
                    watcher.last_error = None

            item = worker.read()
            if item is None or item[1].frame_id == last_id:
                continue
            frame, obs = item
            last_id = obs.frame_id
            st = proc.update(obs)
            if obs.present and obs.shoulder_width > 0:
                sw_norm = obs.shoulder_width
            stats.add(st, sw_norm, obs.aspect)

            h, w = frame.image.shape[:2]
            if show_cam:
                img = cv2.flip(frame.image, 1) if mirror else frame.image.copy()
                img = (img * 0.45).astype(np.uint8)
            else:
                img = np.zeros_like(frame.image)
            px = lambda p: (int(p[0] * w), int(p[1] * h))

            for e in st.events:
                txt = EVENT_NAMES.get(e.kind, e.kind)
                if e.side:
                    txt += " SX" if e.side == "left" else " DX"
                if e.kind == "complete":
                    txt += f"  ({e.data['reason']}, {e.data['strokes']} gesti)"
                if e.kind == "stroke":
                    txt += f"  {e.data['length']:.1f} sw in {e.data['duration']:.2f} s"
                    cv2.arrowedLine(img, px(e.data["start"]), px(e.data["end"]), (255, 255, 255), 2, cv2.LINE_AA, tipLength=0.08)
                banners.append((now, txt, COLORS.get(e.side, (120, 255, 255)), px(e.pos)))

            for s in SIDES:
                a = st.arms[s]
                col = COLORS[s]
                # velocità grezza per il grafico
                raw_speed = 0.0
                if a.raw_pos_norm and prev_raw[s]:
                    d = np.hypot((a.raw_pos_norm[0] - prev_raw[s][1][0]) * obs.aspect, a.raw_pos_norm[1] - prev_raw[s][1][1])
                    raw_speed = d / (sw_norm * obs.aspect) / max(obs.timestamp - prev_raw[s][0], 1e-3)
                prev_raw[s] = (obs.timestamp, a.raw_pos_norm) if a.raw_pos_norm else None
                graph[s].append((now, raw_speed, a.speed))
                while graph[s] and now - graph[s][0][0] > GRAPH_SECONDS:
                    graph[s].popleft()

                if a.raw_pos_norm:
                    cv2.circle(img, px(a.raw_pos_norm), 4, (150, 150, 150), -1, cv2.LINE_AA)
                if a.state == LOST and a.presence <= 0.01:
                    trails[s].clear()
                    continue
                trails[s].append((a.segment_id, px(a.pos_norm)))
                tr = list(trails[s])
                for i in range(1, len(tr)):
                    if tr[i][0] == tr[i - 1][0]:
                        cv2.line(img, tr[i - 1][1], tr[i][1], col, max(1, i // 8), cv2.LINE_AA)
                c = px(a.pos_norm)
                faded = tuple(int(v * a.presence) for v in col)
                cv2.circle(img, c, int(8 + 22 * a.amplitude), faded, 2 if a.state == TRACKING else 1, cv2.LINE_AA)
                cv2.circle(img, c, 6, faded, -1, cv2.LINE_AA)
                if a.speed > 0.05:
                    end = (int(c[0] + a.vel[0] * sw_norm * w * 0.25), int(c[1] + a.vel[1] * sw_norm * w * 0.25))
                    cv2.arrowedLine(img, c, end, faded, 2, cv2.LINE_AA, tipLength=0.25)

            # grafico velocità
            gh, gy = 110, h - 10
            for k, s in enumerate(SIDES):
                pts_raw, pts_f = [], []
                for t, r, f in graph[s]:
                    x = int(w - (now - t) / GRAPH_SECONDS * w)
                    pts_raw.append((x, int(gy - k * 4 - min(r / 10, 1) * gh)))
                    pts_f.append((x, int(gy - k * 4 - min(f / 10, 1) * gh)))
                if len(pts_raw) > 1:
                    cv2.polylines(img, [np.array(pts_raw, np.int32)], False, (110, 110, 110), 1, cv2.LINE_AA)
                    cv2.polylines(img, [np.array(pts_f, np.int32)], False, COLORS[s], 2, cv2.LINE_AA)
            put(img, "velocita' (0-10 sw/s): grigio grezza, colore filtrata", (14, gy - gh - 8), 0.5)

            for i, (t, txt, col, pos) in enumerate([b for b in banners if now - b[0] < 1.5]):
                put(img, txt, (w - 520, 40 + i * 34), 0.8, col, 2)

            if show_info:
                lines = [f"fps riconoscimento {worker.fps():4.1f}   latenza {(time.perf_counter() - obs.timestamp) * 1000:3.0f} ms   "
                         f"energia {st.energy:.2f}   fermo da {st.still_time:4.1f} s"]
                for s, name in (("left", "SX"), ("right", "DX")):
                    a = st.arms[s]
                    lines.append(f"{name} {a.state:8s} pres {a.presence:.2f} vel {a.speed:4.1f} risp {a.speed_n:.2f} "
                                 f"ampiezza {a.amplitude:.2f} est {a.extension:.2f} elev {a.elevation:+.1f}")
                lines.append(f"intreccio {'IN CORSO' if st.session_active else 'in attesa'}   "
                             f"braccia a riposo da {st.rest_time:4.1f} s   assente da {st.absent_time:4.1f} s")
                lines.append(f"distanza polsi {st.wrist_distance:.2f} sw   vicinanza {st.closeness:.2f}   "
                             f"{'INCROCIATE' if st.crossed else 'non incrociate'}")
                for i, s in enumerate(lines):
                    put(img, s, (14, 28 + i * 26), 0.58)

            cv2.imshow(WINDOW, img)
            if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        worker.stop()
        cam.stop()
        cv2.destroyAllWindows()

    print("\n===== RIEPILOGO FASE 3 (copialo nella risposta) =====")
    print(stats.report(proc))


if __name__ == "__main__":
    main()
