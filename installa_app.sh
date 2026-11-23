#!/bin/bash
# MadHearts — crea l'app "MadHearts" su questo Mac (doppio clic, Dock, icona con il logo)
# e toglie il marchio di quarantena di macOS dalla cartella del progetto.
#
# Uso (dal Terminale, nella cartella del progetto):   bash installa_app.sh
#
# Perché funziona: macOS blocca i file scaricati da Internet (Gatekeeper).
# Un'app creata direttamente su questo Mac non è "scaricata", quindi si apre senza avvisi.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$DIR/MadHearts.app"
echo "Cartella del progetto: $DIR"

# 1. Togli il marchio "scaricato da Internet" da tutti i file del progetto
xattr -dr com.apple.quarantine "$DIR" 2>/dev/null || true
chmod +x "$DIR/avvia_madhearts.command"
echo "• marchio di quarantena rimosso"

# 2. Crea l'app: apre il Terminale (dove compaiono i messaggi e l'indirizzo del pannello)
#    e avvia l'esperienza
ESC_DIR=${DIR//\\/\\\\}
ESC_DIR=${ESC_DIR//\"/\\\"}
rm -rf "$APP"
osacompile -o "$APP" \
  -e 'tell application "Terminal"' \
  -e '	activate' \
  -e "	do script \"cd \" & quoted form of \"$ESC_DIR\" & \" && ./avvia_madhearts.command\"" \
  -e 'end tell'
echo "• app creata: $APP"

# 3. Icona con il logo MadHearts
if [ -f "$DIR/assets/icona.png" ]; then
  TMP="$(mktemp -d)"
  ICONSET="$TMP/MadHearts.iconset"
  mkdir -p "$ICONSET"
  for s in 16 32 128 256 512; do
    sips -z $s $s "$DIR/assets/icona.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
    d=$((s * 2))
    sips -z $d $d "$DIR/assets/icona.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/applet.icns"
  rm -rf "$TMP"
  # firma locale (ad hoc) dopo aver cambiato l'icona, così macOS considera l'app integra
  codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || true
  touch "$APP"
  echo "• icona applicata"
fi

echo
echo "Fatto. Apri MadHearts con un doppio clic su MadHearts.app (puoi trascinarla nel Dock)."
echo "La prima volta macOS chiederà il permesso di controllare il Terminale: rispondi OK."
echo "Se sposti o rinomini la cartella del progetto, rilancia: bash installa_app.sh"
