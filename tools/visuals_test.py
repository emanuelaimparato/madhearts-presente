"""FASE 4 — Il motore visivo dal vivo.

Uso:
    python -m tools.visuals_test                 # dai tuoi movimenti (camera)
    python -m tools.visuals_test --source demo   # visitatore simulato (senza camera)
    python -m tools.visuals_test --source mouse  # il mouse muove il braccio destro;
                                                 # il sinistro lo segue a specchio
    aggiungi --fullscreen per lo schermo intero

Tasti:  Q / ESC esci  ·  P palette successiva  ·  C ricomincia (sfera con un solo anello)
config.toml si ricarica a caldo: cambia [visuals] o [motion], salva, e guarda.
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import deque

import moderngl
import pygame

from madhearts.config import ConfigWatcher
from madhearts.motion import MotionProcessor
from madhearts.simulate import SimulatedVisitor
from madhearts.tracking import Arm, BodyObservation, Point
from madhearts.visuals import VisualEngine
from madhearts.visuals import palette as pal


def create_window(fullscreen: bool, size=(1280, 720)):
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 4)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 1)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_FORWARD_COMPATIBLE_FLAG, True)
    flags = pygame.OPENGL | pygame.DOUBLEBUF
    if fullscreen:
        flags |= pygame.FULLSCREEN
        size = (0, 0)
    try:
        pygame.display.set_mode(size, flags, vsync=1)
    except pygame.error:
        pygame.display.set_mode(size, flags)
    ctx = moderngl.create_context()
    fb = ctx.detect_framebuffer()
    return ctx, fb


class MouseSource:
    """Il mouse è il polso destro; il sinistro lo segue a specchio con un po' di ritardo."""

    def __init__(self):
        self.lag = deque(maxlen=12)
        self.frame = 0

    def observe(self, t: float, win_size) -> BodyObservation:
        self.frame += 1
        mx, my = pygame.mouse.get_pos()
        x, y = mx / win_size[0], my / win_size[1]
        self.lag.append((x, y))
        lx, ly = self.lag[0]
        obs = BodyObservation(self.frame, t, present=True, aspect=16 / 9, shoulder_width=0.16)
        for side, (wx, wy), sx in (("right", (x, y), 0.58), ("left", (1 - lx, ly), 0.42)):
            obs.arms[side] = Arm(side, shoulder=Point(sx, 0.4, 0, 1), elbow=Point(sx, 0.55, 0, 1),
                                 wrist=Point(wx, wy, 0, 1))
        return obs


def report_session(st, log: dict) -> None:
    """Stampa nel Terminale lo stato dell'intreccio (solo i cambiamenti)."""
    if st.session_active and not log["active"]:
        print("intreccio iniziato")
    log["active"] = st.session_active
    if st.session_active:
        for key, value, label in (("rest", st.rest_time, "braccia a riposo"), ("absent", st.absent_time, "fuori inquadratura")):
            sec = int(value)
            if sec != log[key] and sec > 0:
                print(f"  {label} da {sec} s")
            log[key] = sec
    for e in st.events:
        if e.kind == "complete":
            print(f"FILO COMPLETATO ({e.data['reason']}, {e.data['strokes']} gesti) -> nuovo anello")


def main() -> None:
    ap = argparse.ArgumentParser(description="MadHearts - Fase 4: motore visivo")
    ap.add_argument("--config")
    ap.add_argument("--source", choices=["camera", "demo", "mouse"], default="camera")
    ap.add_argument("--fullscreen", action="store_true")
    args = ap.parse_args()
    watcher = ConfigWatcher(args.config)
    cfg = watcher.config

    worker = cam = None
    if args.source == "camera":
        from madhearts.capture import Camera, CameraError
        from madhearts.tracking import Tracker, TrackerThread
        try:
            tracker = Tracker(cfg)
            cam = Camera.from_config(dict(cfg, camera=dict(cfg["camera"], mirror=False))).start()
        except (FileNotFoundError, CameraError) as e:
            print(e)
            sys.exit(1)
        worker = TrackerThread(cam, tracker).start()
    demo = SimulatedVisitor() if args.source == "demo" else None
    mouse = MouseSource() if args.source == "mouse" else None

    pygame.init()
    ctx, fb = create_window(args.fullscreen)
    pygame.mouse.set_visible(args.source == "mouse")
    size = fb.viewport[2], fb.viewport[3]
    engine = VisualEngine(ctx, size, cfg)
    motion = MotionProcessor(cfg)
    palettes = pal.names(cfg.get("visuals", {}))
    pal_idx = palettes.index(engine.p["palette"]) if engine.p["palette"] in palettes else 0
    print(f"finestra {size[0]}x{size[1]}  renderer {ctx.info['GL_RENDERER']}")

    sess_log = {"active": False, "rest": 0, "absent": 0}
    clock = pygame.time.Clock()
    t0 = time.perf_counter()
    last = t0
    last_id = 0
    next_sim = 0.0
    state = None
    frames, fps_t = 0, t0
    last_poll = t0
    running = True
    try:
        while running:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    running = False
                elif ev.type == pygame.KEYDOWN:
                    if ev.key in (pygame.K_ESCAPE, pygame.K_q):
                        running = False
                    elif ev.key == pygame.K_p:
                        pal_idx = (pal_idx + 1) % len(palettes)
                        engine.set_palette(palettes[pal_idx])
                        print("palette:", palettes[pal_idx])
                    elif ev.key == pygame.K_c:          # ricomincia: via i fili, sfera con un solo anello
                        engine.threads.clear()
                        engine.sphere.clear(engine.t, int(engine.p["initial_rings"]))
            now = time.perf_counter()
            dt = min(now - last, 0.1)
            last = now
            t = now - t0

            if now - last_poll > 0.5:
                last_poll = now
                if watcher.poll():
                    engine.configure(watcher.config)
                    motion.configure(watcher.config)
                    print("config ricaricata")
                elif watcher.last_error:
                    print("errore in config.toml:", watcher.last_error)
                    watcher.last_error = None

            if worker:
                item = worker.read()
                if item and item[1].frame_id != last_id:
                    last_id = item[1].frame_id
                    state = motion.update(item[1])
            elif t >= next_sim:
                next_sim = t + 1 / 30
                obs = demo.observe(t) if demo else mouse.observe(t, pygame.display.get_window_size())
                state = motion.update(obs)

            if state is not None:
                report_session(state, sess_log)
            engine.update(state, dt)
            if state is not None:
                state.events = []          # ogni evento si usa una sola volta
            engine.render(fb, dt)
            pygame.display.flip()
            clock.tick(120)

            frames += 1
            if now - fps_t > 5:
                msg = f"fps grafica {frames / (now - fps_t):.0f}"
                if worker:
                    msg += f"  fps riconoscimento {worker.fps():.0f}"
                print(msg)
                frames, fps_t = 0, now
    finally:
        if worker:
            worker.stop()
            cam.stop()
        pygame.quit()


if __name__ == "__main__":
    main()
