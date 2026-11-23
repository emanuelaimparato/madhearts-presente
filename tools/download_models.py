"""Scarica una sola volta i modelli MediaPipe nella cartella models/.
Dopo il download l'applicazione funziona senza connessione Internet."""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

from madhearts.config import PROJECT_ROOT

BASE = "https://storage.googleapis.com/mediapipe-models"
MODELS = {
    "pose_landmarker_lite.task": f"{BASE}/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task",
    "pose_landmarker_full.task": f"{BASE}/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task",
    "pose_landmarker_heavy.task": f"{BASE}/pose_landmarker/pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task",
    "hand_landmarker.task": f"{BASE}/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task",
}


def main() -> None:
    out = PROJECT_ROOT / "models"
    out.mkdir(exist_ok=True)
    for name, url in MODELS.items():
        dest = out / name
        if dest.exists() and dest.stat().st_size > 0:
            print(f"già presente   {name}")
            continue
        print(f"scarico        {name} ...", flush=True)
        tmp = dest.with_suffix(".part")
        try:
            urllib.request.urlretrieve(url, tmp)
        except Exception as e:
            tmp.unlink(missing_ok=True)
            print(f"ERRORE: {e}")
            if "CERTIFICATE" in str(e).upper():
                print("Esegui 'Install Certificates.command' in /Applications/Python 3.12 e riprova.")
            sys.exit(1)
        tmp.rename(dest)
        print(f"ok             {name} ({dest.stat().st_size / 1e6:.1f} MB)")
    print("Modelli pronti.")


if __name__ == "__main__":
    main()
