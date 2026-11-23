#!/bin/bash
# MadHearts — scarica l'ultima versione dal repository e aggiorna le librerie.
# Uso, nella cartella del progetto:   bash aggiorna.sh
# La sfera, le impostazioni del pannello, config.local.toml e la musica restano come sono.
# Se hai modificato file del progetto (per esempio config.toml), le modifiche vengono
# messe da parte prima dell'aggiornamento e rimesse subito dopo.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

STASHED=0
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "• metto da parte le tue modifiche locali:"
  git diff --name-only | sed 's/^/    /'
  git stash push -q -m "modifiche locali prima di aggiorna.sh"
  STASHED=1
fi

git pull --ff-only

if [ "$STASHED" = "1" ]; then
  if git stash pop -q; then
    echo "• modifiche locali rimesse al loro posto"
  else
    echo
    echo "ATTENZIONE: alcune tue modifiche toccano le stesse righe dell'aggiornamento."
    echo "Sono conservate: 'git stash list' le mostra, 'git checkout -- config.toml && git stash pop'"
    echo "le riapplica. Consiglio: sposta le tue regolazioni in config.local.toml (vedi config.local.esempio.toml)."
    exit 1
  fi
fi

source .venv/bin/activate
pip install --quiet -r requirements.txt
python -m tools.download_models
echo "Aggiornamento completato."
