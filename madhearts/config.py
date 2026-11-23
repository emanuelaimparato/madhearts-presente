"""Caricamento della configurazione (config.toml) con ricarica a caldo.

Nessun parametro artistico o tecnico deve essere scritto nel codice:
tutto passa da config.toml.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.toml"


def load_config(path: str | Path | None = None) -> dict:
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(path, "rb") as f:
        return tomllib.load(f)


class ConfigWatcher:
    """Ricarica config.toml quando il file viene salvato.

    Permette di regolare colori, intensità, ecc. mentre l'app gira:
    si salva il file e la modifica diventa visibile in un istante.
    Se il file contiene un errore di sintassi si mantiene l'ultima
    configurazione valida (l'esperienza non si interrompe).
    """

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else DEFAULT_CONFIG_PATH
        self.config = load_config(self.path)
        self._mtime = self.path.stat().st_mtime
        self.last_error: str | None = None

    def poll(self) -> bool:
        """Da chiamare periodicamente. Ritorna True se la config è cambiata."""
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return False
        if mtime == self._mtime:
            return False
        self._mtime = mtime
        try:
            self.config = load_config(self.path)
            self.last_error = None
            return True
        except (tomllib.TOMLDecodeError, OSError) as e:
            self.last_error = str(e)
            return False
