#!/bin/bash
# MadHearts web — prova sul Mac durante lo sviluppo.
# Avvia un piccolo server locale (solo su questo Mac) e apre la pagina nel browser.
# Il browser consente la webcam su "localhost". Per chiudere: chiudi questa finestra del Terminale.
cd "$(dirname "$0")"
PAGE="${1:-test-riconoscimento.html}"
PORT=8000
echo "MadHearts web: http://localhost:$PORT/$PAGE"
( sleep 1; open -a "Google Chrome" "http://localhost:$PORT/$PAGE" 2>/dev/null || open "http://localhost:$PORT/$PAGE" ) &
python3 -m http.server $PORT --bind 127.0.0.1
