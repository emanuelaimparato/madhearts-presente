#!/bin/bash
# MadHearts web — prova sul Mac durante lo sviluppo.
# Avvia un piccolo server locale (solo su questo Mac) e apre la pagina nel browser.
# Il browser consente la webcam su "localhost".
# Uso:  bash web/avvia_web.command [pagina]     (predefinita: index.html, l'esperienza)
# Per chiudere il server: Ctrl+C in questa finestra del Terminale (o chiudi la finestra).
cd "$(dirname "$0")"
PAGE="${1:-index.html}"
PORT=8000
URL="http://localhost:$PORT/$PAGE"

apri() { open "$1"; }      # browser predefinito del Mac

# Server già acceso (per esempio in un'altra finestra)? Allora apri solo la pagina.
if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Il server è già acceso: apro $URL"
  apri "$URL"
  exit 0
fi

echo "MadHearts web: $URL"
echo "(per chiudere il server: Ctrl+C)"
( sleep 1; apri "$URL" ) &
python3 -m http.server $PORT --bind 127.0.0.1
