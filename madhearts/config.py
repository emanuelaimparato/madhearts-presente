"""Caricamento della configurazione con ricarica a caldo.

Due file:
- config.toml        i valori del progetto, condivisi dal team (arriva con gli aggiornamenti)
- config.local.toml  le regolazioni di QUESTO Mac (PIN, schermo, sensibilità...):
                     non è nel repository, gli aggiornamenti non lo toccano mai.
                     Contiene solo le righe che vuoi cambiare, nelle stesse sezioni
                     di config.toml, e prevale su di esso.

Nessun parametro artistico o tecnico deve essere scritto nel codice:
tutto passa da questi file.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.toml"


def local_path(path: Path) -> Path:
    return path.with_name(path.stem + ".local" + path.suffix)


def _merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for k, v in extra.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config(path: str | Path | None = None) -> dict:
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    loc = local_path(path)
    if loc.exists():
        with open(loc, "rb") as f:
            cfg = _merge(cfg, tomllib.load(f))
    return cfg


class ConfigWatcher:
    """Ricarica la configurazione quando config.toml o config.local.toml vengono salvati.

    Permette di regolare colori, intensità, ecc. mentre l'app gira:
    si salva il file e la modifica diventa visibile in un istante.
    Se un file contiene un errore di sintassi si mantiene l'ultima
    configurazione valida (l'esperienza non si interrompe).
    """

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else DEFAULT_CONFIG_PATH
        self.config = load_config(self.path)
        self._mtime = self._stamp()
        self.last_error: str | None = None

    def _stamp(self):
        out = []
        for p in (self.path, local_path(self.path)):
            try:
                out.append(p.stat().st_mtime)
            except OSError:
                out.append(None)
        return tuple(out)

    def poll(self) -> bool:
        """Da chiamare periodicamente. Ritorna True se la config è cambiata."""
        stamp = self._stamp()
        if stamp == self._mtime:
            return False
        self._mtime = stamp
        try:
            self.config = load_config(self.path)
            self.last_error = None
            return True
        except (tomllib.TOMLDecodeError, OSError) as e:
            self.last_error = str(e)
            return False
