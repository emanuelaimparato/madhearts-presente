"""FASE 1 — Test della videocamera integrata.

Uso:
    python -m tools.camera_test            # flusso video con misure in sovrimpressione
    python -m tools.camera_test --list     # elenca le videocamere disponibili (indici 0-4)
    python -m tools.camera_test --probe    # misura fps reali a diverse risoluzioni

Tasti (finestra video):  Q / ESC esci  ·  M specchio on/off  ·  I info on/off

Nessuna immagine viene salvata: i frame restano solo in memoria.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time

import cv2

from madhearts.capture import Camera, CameraError
from madhearts.config import load_config

WINDOW = "MadHearts - Fase 1 - test videocamera"
PROBE_RESOLUTIONS = [(640, 480), (1280, 720), (1920, 1080)]


def brightness(img) -> float:
    small = cv2.resize(img, (160, 90), interpolation=cv2.INTER_AREA)
    return float(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).mean())


def list_cameras(cfg) -> None:
    print("Ricerca videocamere (indici 0-4)...")
    for i in range(5):
        try:
            cam = Camera(index=i, backend=cfg["camera"].get("backend", "avfoundation")).start()
        except CameraError:
            continue
        time.sleep(1.0)
        print(f"  indice {i}: {cam.actual_size[0]}x{cam.actual_size[1]}  "
              f"fps dichiarati {cam.reported_fps:.0f}, misurati {cam.measured_fps():.1f}")
        cam.stop()
    print("Imposta l'indice della camera integrata in config.toml → [camera] index.")


def probe(cfg) -> None:
    c = cfg["camera"]
    print(f"{'richiesta':>12} {'ottenuta':>12} {'fps dich.':>10} {'fps reali':>10} {'luminosità':>11}")
    for w, h in PROBE_RESOLUTIONS:
        try:
            cam = Camera(index=c.get("index", 0), width=w, height=h, fps=c.get("fps", 30),
                         backend=c.get("backend", "avfoundation")).start()
        except CameraError as e:
            print(f"{w}x{h}: errore — {e}")
            continue
        time.sleep(1.0)                       # assestamento esposizione
        t0 = time.perf_counter()
        lum = []
        while time.perf_counter() - t0 < 3.0:
            f = cam.read()
            if f is not None:
                lum.append(brightness(f.image))
            time.sleep(0.1)
        fps = cam.measured_fps()
        aw, ah = cam.actual_size
        cam.stop()
        print(f"{f'{w}x{h}':>12} {f'{aw}x{ah}':>12} {cam.reported_fps:>10.0f} {fps:>10.1f} "
              f"{statistics.mean(lum) if lum else 0:>11.0f}")


def live(cfg) -> None:
    low_light = cfg.get("debug", {}).get("low_light_threshold", 60)
    try:
        cam = Camera.from_config(cfg).start()
    except CameraError as e:
        print(e)
        sys.exit(1)

    print(f"Camera aperta: richiesta {cam.req_width}x{cam.req_height}@{cam.req_fps}, "
          f"ottenuta {cam.actual_size[0]}x{cam.actual_size[1]}, fps dichiarati {cam.reported_fps:.0f}")
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    show_info = True
    last_id = 0
    disp_stamps: list[float] = []
    fps_log, lum_log, age_log = [], [], []
    t_start = time.perf_counter()
    last_log = t_start

    try:
        while True:
            f = cam.read()
            if f is None or f.frame_id == last_id:
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break
                continue
            last_id = f.frame_id
            now = time.perf_counter()
            disp_stamps = [t for t in disp_stamps if now - t < 2.0] + [now]
            disp_fps = (len(disp_stamps) - 1) / (disp_stamps[-1] - disp_stamps[0]) if len(disp_stamps) > 1 else 0
            cap_fps = cam.measured_fps()
            lum = brightness(f.image)
            age_ms = (now - f.timestamp) * 1000

            if now - last_log > 1.0 and now - t_start > 2.0:   # scarta i primi 2 s
                fps_log.append(cap_fps); lum_log.append(lum); age_log.append(age_ms)
                last_log = now

            img = f.image
            if show_info:
                h, w = img.shape[:2]
                lines = [
                    f"risoluzione {w}x{h}",
                    f"fps camera {cap_fps:5.1f}   (dichiarati {cam.reported_fps:.0f})",
                    f"fps display {disp_fps:5.1f}",
                    f"eta' frame {age_ms:4.1f} ms",
                    f"luminosita' {lum:5.1f}" + ("   LUCE SCARSA" if lum < low_light else ""),
                    f"specchio {'on' if cam.mirror else 'off'}   riconnessioni {cam.reconnections}",
                ]
                for i, s in enumerate(lines):
                    y = 30 + i * 28
                    cv2.putText(img, s, (16, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4, cv2.LINE_AA)
                    cv2.putText(img, s, (16, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1, cv2.LINE_AA)
            cv2.imshow(WINDOW, img)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("m"):
                cam.mirror = not cam.mirror
            if key == ord("i"):
                show_info = not show_info
            if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        cam.stop()
        cv2.destroyAllWindows()

    if fps_log:
        print("\n===== RIEPILOGO (copialo nella risposta) =====")
        print(f"durata            {time.perf_counter() - t_start:.0f} s")
        print(f"risoluzione       {cam.actual_size[0]}x{cam.actual_size[1]}")
        print(f"fps camera        media {statistics.mean(fps_log):.1f}  min {min(fps_log):.1f}  max {max(fps_log):.1f}")
        print(f"eta' frame        media {statistics.mean(age_log):.1f} ms")
        print(f"luminosità        media {statistics.mean(lum_log):.0f}  min {min(lum_log):.0f}")
        print(f"riconnessioni     {cam.reconnections}")


def main() -> None:
    ap = argparse.ArgumentParser(description="MadHearts - Fase 1: test videocamera")
    ap.add_argument("--config", help="percorso di config.toml")
    ap.add_argument("--list", action="store_true", help="elenca le videocamere")
    ap.add_argument("--probe", action="store_true", help="misura fps a varie risoluzioni")
    args = ap.parse_args()
    cfg = load_config(args.config)
    if args.list:
        list_cameras(cfg)
    elif args.probe:
        probe(cfg)
    else:
        live(cfg)


if __name__ == "__main__":
    main()
