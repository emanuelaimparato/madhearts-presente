#!/bin/bash
# MadHearts — avvio dell'esperienza (doppio clic dal Finder).
# caffeinate impedisce a Mac e proiettore di andare in stop finché l'app è aperta.
cd "$(dirname "$0")"
source .venv/bin/activate
caffeinate -dis python -m madhearts.app "$@"
