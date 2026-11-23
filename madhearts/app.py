"""MadHearts — applicazione dell'esperienza.

Avvio:
    python -m madhearts.app                  # esperienza a schermo intero (camera)
    python -m madhearts.app --windowed       # in finestra, per le prove
    python -m madhearts.app --source demo    # visitatori simulati, senza camera
    python -m madhearts.app --list-displays  # elenca gli schermi collegati

Comandi principali dal PANNELLO nel browser (indirizzo mostrato all'avvio).
Tasti di riserva sul Mac:
    SPAZIO      avvia / pausa
    R           riavvia (camera, audio, configurazione; la sfera resta)
    F           schermo intero / finestra
    D           modalità debug on/off
    M           silenzia / riattiva l'audio
    1..8        regolazioni (vedi _KEYS), 0 = valori di config.toml
    C C         (due volte entro 2 s) azzera la sfera — ne resta una copia in data/
    Q / ESC     esci (la sfera viene salvata)

Privacy: nessuna immagine viene salvata. Su disco vanno solo la sfera (anelli)
e le impostazioni del pannello.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path


def _quiet_native_logs(log_path: Path) -> None:
    """Manda i messaggi tecnici di MediaPipe (scritti a basso livello su stderr)
    in un file di log, lasciando nel Terminale solo i messaggi dell'app."""
    log_path.parent.mkdir(exist_ok=True)
    saved = os.dup(2)
    f = open(log_path, "a")
    os.dup2(f.fileno(), 2)
    sys.stderr = os.fdopen(saved, "w", buffering=1)


from .config import PROJECT_ROOT, ConfigWatcher  # noqa: E402

# Parametri regolabili dal pannello: id "sezione.chiave", etichetta, gruppo, min, max, passo, unità, nota
PARAMS = [
    ("audio.master_volume", "Volume generale", "audio", 0, 1, 0.05, "%", ""),
    ("audio.music_volume", "Musica", "audio", 0, 1, 0.05, "%", ""),
    ("audio.ambient_volume", "Tappeto sonoro", "audio", 0, 1, 0.05, "%", ""),
    ("audio.trail_volume", "Suono della scia", "audio", 0, 1, 0.05, "%", ""),
    ("audio.chime_volume", "Rintocco del nuovo anello", "audio", 0, 1, 0.05, "%", ""),
    ("visuals.exposure", "Luminosità", "esperienza", 0.3, 3.0, 0.05, "", ""),
    ("visuals.response_intensity", "Intensità della risposta ai gesti", "esperienza", 0.2, 2.5, 0.05, "", ""),
    ("visuals.filament_length", "Durata della scia", "esperienza", 0.5, 8, 0.1, "s", ""),
    ("visuals.fade_speed", "Velocità di dissolvenza", "esperienza", 0.2, 3, 0.05, "", ""),
    ("tracking.min_visibility", "Soglia di rilevamento", "esperienza", 0.05, 0.9, 0.05, "",
     "più bassa = più sensibile (anche con poca luce), più alta = più selettiva"),
    ("motion.session_rest_seconds", "Braccia a riposo per completare il filo", "sfera", 1, 30, 1, "s", ""),
    ("visuals.sphere_rotation_speed", "Velocità di rotazione della sfera", "sfera", 0, 0.3, 0.005, "", ""),
    ("visuals.ring_brightness", "Luminosità degli anelli", "sfera", 0.1, 1.5, 0.05, "", ""),
    ("visuals.sphere_radius", "Grandezza della sfera", "sfera", 0.1, 0.5, 0.01, "", "frazione dell'altezza dello schermo"),
    ("attract.invite_opacity", "Invito sul proiettore", "attesa", 0, 1, 0.05, "%", "0 = nascosto"),
    ("attract.logo_opacity", "Logo", "attesa", 0, 1, 0.05, "%", "0 = nascosto"),
]
_KEYS = {"1": ("visuals.response_intensity", -1), "2": ("visuals.response_intensity", 1),
         "3": ("visuals.fade_speed", -1), "4": ("visuals.fade_speed", 1),
         "5": ("tracking.min_visibility", 1), "6": ("tracking.min_visibility", -1),
         "7": ("visuals.exposure", -1), "8": ("visuals.exposure", 1),
         "+": ("audio.master_volume", 1), "-": ("audio.master_volume", -1)}
_PARAM = {p[0]: p for p in PARAMS}


class App:
    def __init__(self, args):
        self.args = args
        self.watcher = ConfigWatcher(args.config)
        self.base_cfg = self.watcher.config
        self.settings_file = PROJECT_ROOT / "data" / "impostazioni.json"
        self.overrides: dict[str, float] = self._read_settings()
        self.cfg = self._effective()
        a = self.cfg.get("app", {})
        self.sphere_file = PROJECT_ROOT / a.get("sphere_file", "data/sfera.json")
        self.messages: list[tuple[float, str]] = []
        self.debug = bool(a.get("debug_on_start", False)) or args.debug
        self.playing = bool(a.get("autostart", False)) or args.start
        self.clear_armed = 0.0
        self.tracker = self.cam = self.worker = None
        self.running = True
        self.rings_at_start = 0
        self.settings_dirty = None
        self.autosave = bool(self.cfg.get("panel", {}).get("autosave", True))

    # -------------------------------------------------------------- impostazioni
    def _read_settings(self) -> dict:
        try:
            if self.settings_file.exists():
                data = json.loads(self.settings_file.read_text())
                return {k: float(v) for k, v in data.items() if k in _PARAM}
        except Exception:
            pass
        return {}

    def _effective(self) -> dict:
        cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in self.base_cfg.items()}
        for pid, val in self.overrides.items():
            sec, key = pid.split(".", 1)
            cfg.setdefault(sec, {})[key] = val
        return cfg

    def _apply_cfg(self) -> None:
        self.cfg = self._effective()
        self.engine.configure(self.cfg)
        self.motion.configure(self.cfg)
        self.audio.configure(self.cfg)
        self.attract.configure(self.cfg)

    def value(self, pid: str):
        sec, key = pid.split(".", 1)
        v = self.cfg.get(sec, {}).get(key)
        if v is None:
            defaults = {"visuals": self.engine.p, "attract": self.attract.p, "audio": self.audio.vol,
                        "motion": self.motion.p}
            v = defaults.get(sec, {}).get(key, 0.0)
        return float(v)

    def set_param(self, pid: str, value: float, announce=True) -> None:
        if pid not in _PARAM:
            return
        _, label, _, lo, hi, step, unit, _ = _PARAM[pid]
        value = round(min(max(float(value), lo), hi), 4)
        self.overrides[pid] = value
        self._apply_cfg()
        self.settings_dirty = time.perf_counter()        # salvataggio automatico poco dopo
        if announce:
            shown = f"{round(value * 100)}%" if unit == "%" else f"{value:g}{' s' if unit == 's' else ''}"
            self.say(f"{label}: {shown}", quiet=True)

    def save_settings(self, quiet=False) -> None:
        try:
            self.settings_file.parent.mkdir(exist_ok=True)
            tmp = self.settings_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.overrides, indent=1))
            os.replace(tmp, self.settings_file)
            self.settings_dirty = None
            if not quiet:
                self.say("impostazioni salvate: verranno usate anche ai prossimi avvii")
        except Exception as e:
            self.say(f"ERRORE nel salvare le impostazioni: {e}")

    def reset_settings(self) -> None:
        self.overrides.clear()
        self.settings_dirty = None
        if self.settings_file.exists():
            self.settings_file.unlink()
        self._apply_cfg()
        self.say("tornati ai valori di config.toml")

    def say(self, text: str, quiet=False) -> None:
        if not quiet:
            print(text, file=sys.stderr if text.startswith("ERRORE") else sys.stdout, flush=True)
        self.messages.append((time.perf_counter(), datetime.now().strftime("%H:%M") + "  " + text))
        self.messages = self.messages[-30:]

    # -------------------------------------------------------------- sfera su disco
    def load_sphere(self) -> None:
        if self.cfg.get("app", {}).get("sphere_reset_on_start", False) or not self.sphere_file.exists():
            return
        for f in (self.sphere_file, self.sphere_file.with_suffix(".bak.json")):
            try:
                self.engine.sphere.load(json.loads(f.read_text()), self.engine.t, time.time())
                self.say(f"sfera ripristinata: {len(self.engine.sphere.rings)} anelli")
                return
            except Exception as e:
                self.say(f"ERRORE nel leggere {f.name} ({e})")
        self.say("la sfera riparte da un anello")

    def save_sphere(self) -> None:
        try:
            self.sphere_file.parent.mkdir(parents=True, exist_ok=True)
            data = self.engine.sphere.export(self.engine.t, time.time())
            tmp = self.sphere_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1))
            if self.sphere_file.exists():
                shutil.copy2(self.sphere_file, self.sphere_file.with_suffix(".bak.json"))
            os.replace(tmp, self.sphere_file)                 # scrittura atomica: mai un file a metà
        except Exception as e:
            self.say(f"ERRORE nel salvare la sfera: {e}")

    def clear_sphere(self) -> None:
        if self.sphere_file.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(self.sphere_file, self.sphere_file.with_name(f"sfera-azzerata-{stamp}.json"))
        self.engine.sphere.clear(self.engine.t, int(self.engine.p["initial_rings"]))
        self.ring_count = self.engine.sphere.count
        self.rings_at_start = len(self.engine.sphere.rings)
        self.save_sphere()
        self.say("sfera azzerata (copia della precedente salvata in data/)")

    # -------------------------------------------------------------- camera
    def start_camera(self) -> bool:
        from .capture import Camera, CameraError
        from .tracking import TrackerThread
        try:
            cam_cfg = dict(self.cfg, camera=dict(self.cfg["camera"], mirror=False))
            self.cam = Camera.from_config(cam_cfg).start()
        except CameraError as e:
            self.say("ERRORE camera: " + str(e).splitlines()[0] + " — riprovo tra 5 s")
            self.cam = None
            return False
        self.worker = TrackerThread(self.cam, self.tracker).start()
        self.say(f"camera {self.cam.actual_size[0]}x{self.cam.actual_size[1]} attiva")
        return True

    def stop_camera(self) -> None:
        if self.worker is not None:
            self.worker._running = False
            if self.worker._thread:
                self.worker._thread.join(timeout=2.0)
            self.worker = None
        if self.cam is not None:
            self.cam.stop()
            self.cam = None

    def restart(self) -> None:
        """Riavvio morbido: configurazione, camera, riconoscimento e audio da capo; la sfera resta."""
        from .motion import MotionProcessor
        self.say("riavvio…")
        self.watcher.poll()
        self.base_cfg = self.watcher.config
        self.cfg = self._effective()
        self.motion = MotionProcessor(self.cfg)
        self.state = None
        self._apply_cfg()
        if self.tracker is not None:
            self.stop_camera()
            self.start_camera()
        self.audio.load_music(self.cfg.get("audio", {}).get("music_file", ""))
        self.attract.black = 1.0
        self.attract.fade_to_black(False)
        self.say("riavvio completato")

    # -------------------------------------------------------------- finestra
    def create_window(self):
        import moderngl
        import pygame
        a = self.cfg.get("app", {})
        sizes = pygame.display.get_desktop_sizes()
        disp = self.args.display if self.args.display is not None else a.get("display", "auto")
        idx = (len(sizes) - 1) if disp == "auto" else int(disp)
        idx = max(0, min(idx, len(sizes) - 1))
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 4)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 1)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_FORWARD_COMPATIBLE_FLAG, True)
        flags = pygame.OPENGL | pygame.DOUBLEBUF | pygame.RESIZABLE
        size = tuple(a.get("window_size", [1280, 720]))
        self.fullscreen = not self.args.windowed and a.get("fullscreen", True)
        if self.fullscreen:
            flags |= pygame.FULLSCREEN
            size = (0, 0)
        try:
            pygame.display.set_mode(size, flags, display=idx, vsync=1)
        except pygame.error:
            pygame.display.set_mode(size, flags, display=idx)
        pygame.display.set_caption("MadHearts")
        pygame.mouse.set_visible(self.args.source == "mouse" or not self.fullscreen)
        ctx = moderngl.create_context()
        fb = ctx.detect_framebuffer()
        self.say(f"schermo {idx + 1} di {len(sizes)}: {fb.viewport[2]}x{fb.viewport[3]}  ({ctx.info['GL_RENDERER']})")
        return ctx, fb

    # -------------------------------------------------------------- comandi
    def set_fullscreen(self, on: bool) -> None:
        """Passa da schermo intero a finestra (ridimensionabile) e viceversa, senza riavviare."""
        import pygame
        import warnings
        if on == self.fullscreen:
            return
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                win = pygame.Window.from_display_module()
            if on:
                win.set_fullscreen(desktop=True)
            else:
                win.set_windowed()
                win.size = tuple(self.cfg.get("app", {}).get("window_size", [1280, 720]))
                win.position = pygame.WINDOWPOS_CENTERED
        except Exception:
            try:                                    # riserva: metodo classico di pygame
                pygame.display.toggle_fullscreen()
            except pygame.error as e:
                self.say(f"ERRORE nel cambiare modalità schermo: {e}")
                return
        self.fullscreen = on
        pygame.mouse.set_visible(self.args.source == "mouse" or not on)
        self._resize_pending = True
        self.say("schermo intero" if on else "finestra (trascina i bordi per ridimensionarla; F o il pannello per tornare a schermo intero)")

    def on_resize(self) -> None:
        import pygame
        w, h = pygame.display.get_window_size()
        if (w, h) == tuple(self.size) or w < 64 or h < 64:
            return
        self.size = (w, h)
        self.fb = self.ctx.detect_framebuffer()
        self.fb.viewport = (0, 0, w, h)
        self.engine.resize((w, h))
        self.attract.size = (w, h)
        self.attract.configure(self.cfg)
        self.overlay.size = (w, h)

    def toggle_play(self, play: bool | None = None) -> None:
        self.playing = (not self.playing) if play is None else play
        self.say("esperienza avviata" if self.playing else "esperienza in pausa (in attesa)")

    def command(self, c: dict) -> None:
        name = c.get("cmd")
        if name == "start":
            self.toggle_play(True)
        elif name == "pause":
            self.toggle_play(False)
        elif name == "restart":
            self.restart()
        elif name == "fullscreen":
            self.set_fullscreen(not self.fullscreen)
        elif name == "debug":
            self.debug = not self.debug
        elif name == "mute":
            self.audio.muted = not self.audio.muted
            self.say("audio silenziato" if self.audio.muted else "audio riattivato")
        elif name == "set":
            self.set_param(str(c.get("id", "")), c.get("value", 0))
        elif name == "save_settings":
            self.save_settings()
        elif name == "reset_settings":
            self.reset_settings()
        elif name == "reset_sphere":
            self.clear_sphere()
        elif name == "quit":
            self.say("chiusura dal pannello")
            self.running = False

    def on_key(self, ev) -> None:
        import pygame
        ch = ev.unicode
        if ev.key in (pygame.K_ESCAPE, pygame.K_q):
            self.running = False
        elif ev.key == pygame.K_SPACE:
            self.toggle_play()
        elif ch in ("r", "R"):
            self.restart()
        elif ch in ("f", "F"):
            self.set_fullscreen(not self.fullscreen)
        elif ch in ("d", "D"):
            self.debug = not self.debug
        elif ch in ("m", "M"):
            self.command({"cmd": "mute"})
        elif ch in ("c", "C"):
            now = time.perf_counter()
            if now - self.clear_armed < 2.0:
                self.clear_armed = 0.0
                self.clear_sphere()
            else:
                self.clear_armed = now
                self.say("premi di nuovo C entro 2 s per azzerare la sfera")
        elif ch == "0":
            self.reset_settings()
        elif ch in _KEYS:
            pid, sign = _KEYS[ch]
            self.set_param(pid, self.value(pid) + sign * _PARAM[pid][5])
            self.say(self.messages[-1][1][7:])

    def publish(self, gfx_fps: float) -> None:
        st = self.state
        cam = "simulata" if self.args.source != "camera" else (
            f"attiva {self.cam.actual_size[0]}x{self.cam.actual_size[1]}" if self.cam else "non collegata")
        self.panel.publish({
            "playing": self.playing, "debug": self.debug, "muted": self.audio.muted,
            "fullscreen": self.fullscreen, "screen": f"{self.size[0]}x{self.size[1]}",
            "audio_ok": self.audio.ok, "music": self.audio.music_name if self.audio.music_loaded else "",
            "camera": cam, "person": bool(st and st.person_presence > 0.5),
            "session_active": bool(st and st.session_active), "rest": st.rest_time if st else 0.0,
            "absent": st.absent_time if st else 0.0,
            "rings": len(self.engine.sphere.rings), "rings_session": len(self.engine.sphere.rings) - self.rings_at_start,
            "fps_gfx": gfx_fps, "fps_rec": self.worker.fps() if self.worker else 0.0,
            "settings_saved": self.settings_file.exists(), "autosave": self.autosave,
            "phone_url": self.panel.urls[1] if len(self.panel.urls) > 1 else "",
            "lan": self.panel.lan,
            "messages": [m for _, m in self.messages[-12:]],
            "params": [{"id": p[0], "label": p[1], "group": p[2], "min": p[3], "max": p[4], "step": p[5],
                        "unit": p[6], "hint": p[7], "value": self.value(p[0])} for p in PARAMS],
        })

    # -------------------------------------------------------------- ciclo
    def run(self) -> None:
        import pygame

        from .attract import Attract
        from .audio import Audio
        from .debug_overlay import DebugOverlay
        from .motion import MotionProcessor
        from .panel import Panel
        from .simulate import SimulatedVisitor
        from .visuals import VisualEngine

        if self.args.source == "camera":
            from .tracking import Tracker
            try:
                self.tracker = Tracker(self.cfg)
            except FileNotFoundError as e:
                self.say("ERRORE " + str(e))
                sys.exit(1)

        pygame.init()
        ctx, fb = self.create_window()
        self.ctx, self.fb = ctx, fb
        size = fb.viewport[2], fb.viewport[3]
        self.size = size
        self.engine = VisualEngine(ctx, size, self.cfg)
        self.motion = MotionProcessor(self.cfg)
        self.attract = Attract(ctx, size, self.cfg, PROJECT_ROOT, log=self.say)
        self.audio = Audio(self.cfg, PROJECT_ROOT, log=self.say)
        self.load_sphere()
        self.engine.sphere.ensure_initial(int(self.engine.p["initial_rings"]), self.engine.t)
        self.rings_at_start = len(self.engine.sphere.rings)
        self.panel = Panel(self.cfg, PROJECT_ROOT, log=self.say)
        self.panel.start()
        self.state = None
        self.worker_fps = 0.0
        self.publish(0.0)
        overlay = self.overlay = DebugOverlay(ctx, size)
        self._resize_pending = False
        demo = SimulatedVisitor() if self.args.source == "demo" else None
        if self.overrides:
            self.say("impostazioni del pannello caricate da data/impostazioni.json")
        if self.tracker is not None:
            self.start_camera()
        next_cam_retry = time.perf_counter() + 5
        self.say("esperienza avviata" if self.playing else "in attesa: premi Avvia nel pannello (o SPAZIO)")

        clock = pygame.time.Clock()
        t0 = last = time.perf_counter()
        last_poll = last_pub = last_net = t0
        next_sim = 0.0
        last_id, self.state = 0, None
        self.ring_count = self.engine.sphere.count
        fps_frames, fps_t, gfx_fps = 0, t0, 0.0
        soak = Soak(self.args.soak) if self.args.soak else None
        sess_active = False
        try:
            while self.running:
                for ev in pygame.event.get():
                    if ev.type == pygame.QUIT:
                        self.running = False
                    elif ev.type == pygame.KEYDOWN:
                        self.on_key(ev)
                    elif ev.type in (pygame.VIDEORESIZE, pygame.WINDOWSIZECHANGED):
                        self._resize_pending = True
                for c in self.panel.poll():
                    self.command(c)
                if self._resize_pending:
                    self._resize_pending = False
                    self.on_resize()
                fb = self.fb
                now = time.perf_counter()
                dt = min(now - last, 0.1)
                last = now

                if now - last_poll > 1.0:
                    last_poll = now
                    if self.watcher.poll():
                        self.base_cfg = self.watcher.config
                        self._apply_cfg()
                        self.say("config.toml ricaricato")
                    elif self.watcher.last_error:
                        self.say("ERRORE in config.toml (uso l'ultima versione valida): " + self.watcher.last_error)
                        self.watcher.last_error = None

                # --- dati del movimento (solo a esperienza attiva)
                frame = obs = None
                if self.tracker is not None:
                    if self.cam is None and now > next_cam_retry:
                        next_cam_retry = now + 5
                        self.start_camera()
                    if self.worker is not None:
                        item = self.worker.read()
                        if item:
                            frame, obs = item
                            if self.playing and obs.frame_id != last_id:
                                last_id = obs.frame_id
                                self.state = self.motion.update(obs)
                        if self.worker.error:
                            self.say(f"ERRORE riconoscimento (frame saltato): {self.worker.error}")
                            self.worker.error = None
                elif demo is not None and self.playing and now - t0 >= next_sim:
                    next_sim = now - t0 + 1 / 30
                    obs = demo.observe(now - t0)
                    self.state = self.motion.update(obs)
                if not self.playing:
                    self.state = None

                st = self.state
                if st is not None:
                    if st.session_active and not sess_active:
                        self.say("intreccio iniziato", quiet=True)
                    sess_active = st.session_active
                    for e in st.events:
                        if e.kind == "complete":
                            self.say(f"filo completato ({e.data['reason']}, {e.data['strokes']} gesti)")
                self.engine.update(st, dt)
                self.audio.update(st, dt, self.playing)
                if st is not None:
                    st.events = []
                if self.engine.sphere.count != self.ring_count:
                    self.ring_count = self.engine.sphere.count
                    self.save_sphere()
                    self.audio.chime(self.ring_count)
                    self.say(f"nuovo anello — la sfera ne ha {len(self.engine.sphere.rings)}")

                self.attract.update(dt, self.playing, st.person_presence if st else 0.0)
                self.engine.render(fb, dt)
                self.attract.draw(fb)
                if self.debug:
                    overlay.draw(fb, frame, obs, st, self.cfg, self._debug_lines(gfx_fps), self.messages)
                pygame.display.flip()
                clock.tick(240)

                fps_frames += 1
                if now - fps_t >= 2.0:
                    gfx_fps = fps_frames / (now - fps_t)
                    fps_frames, fps_t = 0, now
                if now - last_pub > 0.25:
                    last_pub = now
                    self.publish(gfx_fps)
                if now - last_net > 5.0:
                    last_net = now
                    if self.panel.refresh_address():
                        url = self.panel.urls[1] if len(self.panel.urls) > 1 else "nessuna rete"
                        self.say(f"rete cambiata: nuovo indirizzo per il telefono {url} (il QR nel pannello è aggiornato)")
                if self.autosave and self.settings_dirty is not None and now - self.settings_dirty > 1.5:
                    self.save_settings(quiet=True)
                if soak is not None and not soak.tick(now, gfx_fps, self):
                    self.running = False
        finally:
            if self.autosave and self.settings_dirty is not None:
                self.save_settings(quiet=True)
            self.save_sphere()
            self.audio.close()
            self.panel.stop()
            self.stop_camera()
            pygame.quit()
            n = len(self.engine.sphere.rings)
            self.say(f"sfera salvata ({n} {'anello' if n == 1 else 'anelli'}). Arrivederci.")

    def _debug_lines(self, gfx_fps: float) -> list[str]:
        st = self.state
        rec = self.worker.fps() if self.worker is not None else 0.0
        lines = [f"{'ATTIVA' if self.playing else 'IN ATTESA'}   grafica {gfx_fps:5.1f} fps   "
                 f"riconoscimento {rec:4.1f} fps   anelli {len(self.engine.sphere.rings)}"]
        if st is not None:
            lines.append(f"intreccio {'IN CORSO' if st.session_active else 'in attesa'}   "
                         f"riposo {st.rest_time:4.1f} s   assente {st.absent_time:4.1f} s")
            lines.append("braccio SX " + st.arms['left'].state + f" {st.arms['left'].speed:4.1f}   "
                         "DX " + st.arms['right'].state + f" {st.arms['right'].speed:4.1f} sw/s")
        if self.panel.urls:
            lines.append("pannello: " + self.panel.urls[-1])
        return lines


class Soak:
    """Prova di funzionamento continuativo: registra fps, anelli e memoria."""

    def __init__(self, minutes: float):
        self.end = time.perf_counter() + minutes * 60
        self.next = time.perf_counter() + 60
        self.path = PROJECT_ROOT / "logs" / f"prova-continua-{datetime.now():%Y%m%d-%H%M}.csv"
        self.path.parent.mkdir(exist_ok=True)
        self.path.write_text("minuto,fps_grafica,anelli,memoria_mb\n")
        self.minute = 0

    def tick(self, now: float, fps: float, app: "App") -> bool:
        if now >= self.next:
            import resource
            self.next += 60
            self.minute += 1
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            mb = rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024   # macOS: byte, Linux: KB
            with open(self.path, "a") as f:
                f.write(f"{self.minute},{fps:.1f},{len(app.engine.sphere.rings)},{mb:.0f}\n")
            print(f"[prova] minuto {self.minute}: {fps:.0f} fps, {len(app.engine.sphere.rings)} anelli, memoria {mb:.0f} MB",
                  flush=True)
        return now < self.end


def main() -> None:
    ap = argparse.ArgumentParser(description="MadHearts — esperienza interattiva")
    ap.add_argument("--config")
    ap.add_argument("--source", choices=["camera", "demo", "mouse"], default="camera")
    ap.add_argument("--windowed", action="store_true", help="in finestra invece che a schermo intero")
    ap.add_argument("--display", help="numero dello schermo (0 = principale), oppure 'auto'")
    ap.add_argument("--start", action="store_true", help="avvia subito l'esperienza (senza premere Avvia)")
    ap.add_argument("--debug", action="store_true", help="parte con la modalità debug attiva")
    ap.add_argument("--soak", type=float, help="prova continuativa: minuti di durata (registra in logs/)")
    ap.add_argument("--list-displays", action="store_true")
    ap.add_argument("--verbose", action="store_true", help="mostra anche i messaggi tecnici di MediaPipe")
    args = ap.parse_args()

    if args.list_displays:
        import pygame
        pygame.display.init()
        for i, s in enumerate(pygame.display.get_desktop_sizes()):
            print(f"schermo {i}: {s[0]}x{s[1]}")
        return
    if args.display not in (None, "auto"):
        args.display = int(args.display)
    if not args.verbose:
        _quiet_native_logs(PROJECT_ROOT / "logs" / "mediapipe.log")
    App(args).run()


if __name__ == "__main__":
    main()
