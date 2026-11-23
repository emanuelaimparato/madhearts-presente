#!/bin/bash
# MadHearts — scarica l'ultima versione dal repository e aggiorna le librerie.
# Uso, nella cartella del progetto:   bash aggiorna.sh
# La sfera, le impostazioni del pannello e la musica restano come sono.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
git pull --ff-only
source .venv/bin/activate
pip install --quiet -r requirements.txt
python -m tools.download_models
echo "Aggiornamento completato."
