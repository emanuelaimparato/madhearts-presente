#!/bin/bash
# MadHearts — installazione completa su un Mac (una volta sola).
# Uso, nella cartella del progetto:   bash installa.sh
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

PY=""
for v in python3.12 python3.11 python3.13; do
  if command -v "$v" >/dev/null 2>&1; then PY="$v"; break; fi
done
if [ -z "$PY" ]; then
  echo "Serve Python 3.12: scaricalo da https://www.python.org/downloads/macos/"
  echo "(installer 'macOS 64-bit universal2'), poi rilancia: bash installa.sh"
  exit 1
fi
echo "• uso $($PY --version)"

if [ ! -d .venv ]; then
  "$PY" -m venv .venv
  echo "• ambiente Python creato"
fi
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo "• librerie installate"

python -m tools.download_models
bash installa_app.sh

echo
echo "Installazione completata. Apri MadHearts con un doppio clic su MadHearts.app."
echo "La traccia musicale va messa in audio/musica.mp3 (non è nel repository)."
