"""Anteprima del motore visivo senza finestra: simula un visitatore e salva
alcuni fotogrammi della COMPOSIZIONE GRAFICA (mai immagini della camera).

    python -m tools.render_preview --out anteprima --seconds 20 --every 2
    python -m tools.render_preview --video anteprima.mp4 --seconds 20   # video della composizione
"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import moderngl
import numpy as np

from madhearts.config import load_config
from madhearts.motion import MotionProcessor
from madhearts.simulate import SimulatedVisitor
from madhearts.visuals import VisualEngine


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--out", default="anteprima")
    ap.add_argument("--size", default="1280x720")
    ap.add_argument("--seconds", type=float, default=20)
    ap.add_argument("--every", type=float, default=2.0, help="salva un fotogramma ogni N secondi")
    ap.add_argument("--fps", type=float, default=60)
    ap.add_argument("--palette")
    ap.add_argument("--video", help="salva un video .mp4 della composizione (30 fps)")
    ap.add_argument("--egl", action="store_true", help="contesto EGL (Linux senza display)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.palette:
        cfg.setdefault("visuals", {})["palette"] = args.palette
    w, h = map(int, args.size.split("x"))
    ctx = moderngl.create_standalone_context(require=330, **({"backend": "egl"} if args.egl else {}))
    fbo = ctx.simple_framebuffer((w, h))
    engine = VisualEngine(ctx, (w, h), cfg)
    motion = MotionProcessor(cfg)
    visitor = SimulatedVisitor()
    out = Path(args.out)
    out.mkdir(exist_ok=True)

    writer = None
    if args.video:
        writer = cv2.VideoWriter(args.video, cv2.VideoWriter_fourcc(*"mp4v"), 30, (w, h))
    next_video = 0.0
    dt = 1 / args.fps
    track_dt = 1 / 30
    next_track, next_save, state = 0.0, args.every, None
    t = 0.0
    while t < args.seconds:
        if t >= next_track:
            state = motion.update(visitor.observe(t))
            next_track += track_dt
        else:
            state.events = []
        engine.update(state, dt)
        engine.render(fbo, dt)
        t += dt
        if writer is not None and t >= next_video:
            next_video += 1 / 30
            img = np.frombuffer(fbo.read(components=3), dtype=np.uint8).reshape(h, w, 3)[::-1]
            writer.write(cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
        if not args.video and t >= next_save:
            next_save += args.every
            img = np.frombuffer(fbo.read(components=3), dtype=np.uint8).reshape(h, w, 3)[::-1]
            path = out / f"frame_{t:06.2f}.png"
            cv2.imwrite(str(path), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
            print(path)
    if writer is not None:
        writer.release()
        print(args.video)


if __name__ == "__main__":
    main()
