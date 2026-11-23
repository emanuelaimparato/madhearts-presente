#!/bin/bash
# MadHearts web — avvio dal Mac.
# Avvia il server locale (web/server.py: serve l'app e fa da tramite per il telecomando dal
# telefono, senza servizi esterni) e apre l'esperienza nel browser predefinito.
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

( sleep 1; apri "$URL" ) &
python3 server.py $PORT
