# MadHearts — "Presente"

Esperienza interattiva: il visitatore intreccia dei fili, la camera del Mac segue
le sue braccia e sul proiettore il gesto diventa una scia bianca a pennello che
svanisce in pochi secondi (il presente). Quando la persona ha finito di intrecciare,
un nuovo anello entra nella **sfera** sullo sfondo: nasce bianco, diventa rosso
MadHearts e resta. La sfera cresce con ogni visitatore ed è conservata tra
un'accensione e l'altra.

## Avvio dell'esperienza

**Doppio clic su `MadHearts.app`** (l'app con il logo, si può tenere nel Dock).
Si crea una volta sola, dal Terminale nella cartella del progetto:

```bash
bash installa_app.sh
```

Lo script toglie il marchio di quarantena che macOS mette ai file scaricati (è quello
che fa comparire l'avviso di sicurezza) e crea l'app sul Mac, che quindi si apre senza
avvisi. Va rilanciato solo se sposti o rinomini la cartella. Per farla partire
all'accensione del Mac: Impostazioni di Sistema → Generali → Elementi login → aggiungi
MadHearts.app (con `autostart = true` in `[app]`).

In alternativa, dal Terminale nella cartella del progetto:

```bash
source .venv/bin/activate
caffeinate -dis python -m madhearts.app
```

`caffeinate` impedisce a Mac e proiettore di andare in stop finché l'app è aperta.

L'app si apre a schermo intero sull'ultimo schermo collegato (il proiettore) **in attesa**:
la sfera ruota, il logo è in un angolo e l'invito "Avvicinati e intreccia il tuo filo"
compare in basso. L'esperienza parte quando premi **Avvia** nel pannello (o SPAZIO).
Per farla partire da sola: `autostart = true` in `[app]`.

### Il pannello di controllo

All'avvio il Terminale mostra l'indirizzo del pannello, di solito
**http://localhost:8765**: aprilo nel browser del Mac.

- **Esperienza**: Avvia / Pausa, Riavvia (ricollega camera e audio, ricarica la
  configurazione — la sfera resta), Debug sul proiettore.
- **Sfera**: anelli totali, anelli da questo avvio, stato dell'intreccio in corso.
- **Audio**: Silenzia, volume generale, musica, tappeto sonoro, scia, rintocco.
- **Regolazioni**: luminosità, intensità, durata della scia, dissolvenza, soglia di rilevamento.
- **Sfera e attesa**: tempo a braccia ferme per completare il filo, rotazione,
  luminosità degli anelli, visibilità di invito e logo.
- **Impostazioni**: "Salva come predefinite" (restano anche ai prossimi avvii, in
  `data/impostazioni.json`) e "Ripristina" (torna a `config.toml`); Azzera sfera e
  Chiudi app, con conferma.

**Dal telefono**: in `[panel]` metti `lan = true` e un `pin`; il Terminale mostra
anche l'indirizzo per il telefono (stessa rete Wi-Fi).

### Audio

- **Musica**: metti la vostra traccia in `audio/musica.mp3` (o cambia `music_file` in `[audio]`).
- **Tappeto sonoro**, **suono della scia** e **rintocco** del nuovo anello sono
  generati dal programma: nessun file necessario.
- Ogni voce ha il suo volume (pannello o `[audio]` in `config.toml`).

### Logo e invito

Metti il logo in `assets/logo.png` (PNG con sfondo trasparente). Posizione, grandezza,
opacità, testi e font dell'invito sono in `[attract]`. I font League Gothic e DM Sans
sono inclusi in `assets/fonts/` (licenza SIL Open Font License).

### Tasti di riserva sul Mac

| Tasto | Azione |
|---|---|
| SPAZIO | avvia / pausa |
| R | riavvia |
| D | debug: camera, punti rilevati, zona usata, stato, fps |
| M | silenzia / riattiva l'audio |
| + / − | volume generale |
| 1 / 2 · 3 / 4 · 5 / 6 · 7 / 8 | intensità · dissolvenza · sensibilità · luminosità |
| 0 | torna ai valori di `config.toml` |
| C C | (due volte entro 2 s) azzera la sfera — la precedente resta in `data/` |
| Q / ESC | esci (la sfera viene salvata) |

### Opzioni

```bash
python -m madhearts.app --windowed          # in finestra, per le prove
python -m madhearts.app --start             # parte subito, senza premere Avvia
python -m madhearts.app --debug             # parte con il debug attivo
python -m madhearts.app --source demo       # visitatori simulati, senza camera
python -m madhearts.app --soak 240          # prova continuativa di 4 ore (registro in logs/)
python -m madhearts.app --verbose           # mostra anche i messaggi tecnici di MediaPipe
```

## Posizionare la camera

Con il debug attivo (D) il pannello mostra la camera, i punti del corpo e un
riquadro rosso **"zona schermo"**: è la parte dell'inquadratura che corrisponde
allo schermo intero. Regolala in `[visuals]`: `input_zoom` (più alto = riquadro più
piccolo, i gesti occupano più schermo), `input_center_x`, `input_center_y`.
Se la camera guarda la persona di spalle o di lato, prova `mirror` in `[camera]`.

## La sfera

- Un anello nasce quando una persona ha finito di intrecciare: esce
  dall'inquadratura (`session_exit_seconds`) o tiene le braccia lungo il corpo
  (`session_rest_seconds`). Chi passa senza intrecciare non aggiunge anelli
  (`session_min_strokes`, `session_min_length`). Tutto in `[motion]`.
- È salvata in `data/sfera.json` a ogni nuovo anello (con copia di sicurezza
  `sfera.bak.json`). Contiene solo gli anelli: nessuna immagine, nessun dato personale.
- Per ricominciare: C due volte, oppure `sphere_reset_on_start = true` in `[app]`.

## Per il team: installazione da GitHub

Serve Python 3.12 (https://www.python.org/downloads/macos/, installer "universal2").
Poi, dal Terminale:

```bash
git clone https://github.com/PROPRIETARIO/REPOSITORY.git madhearts
cd madhearts
bash installa.sh
```

`installa.sh` crea l'ambiente Python, installa le librerie, scarica i modelli e crea
**MadHearts.app** (doppio clic per avviare). Per ricevere gli aggiornamenti:

```bash
bash aggiorna.sh
```

Non sono nel repository, e restano locali su ogni Mac: la sfera (`data/sfera.json`),
le impostazioni salvate dal pannello, i log e la musica (`audio/musica.mp3`, da
condividere a parte). Ogni Mac ha quindi la propria sfera; per partire dalla stessa
basta copiare `data/sfera.json`.

## Installazione manuale (alternativa)

Python 3.12 (python.org), poi nella cartella del progetto:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m tools.download_models
```

Al primo avvio macOS chiede il permesso per la fotocamera (Impostazioni di Sistema →
Privacy e sicurezza → Fotocamera). Dopo il download dei modelli non serve Internet.

## Strumenti di prova (fasi di sviluppo)

```bash
python -m tools.camera_test        # FASE 1 videocamera: risoluzione, fps, luminosità
python -m tools.tracking_test      # FASE 2 punti del corpo
python -m tools.motion_test        # FASE 3 movimento: smoothing, gesti, fine intreccio
python -m tools.visuals_test       # FASE 4 grafica (anche --source demo / mouse)
python -m tools.render_preview --video prova.mp4 --seconds 30   # video della grafica, senza camera
```

## Architettura

```
config.toml                 tutti i parametri (si ricarica a caldo)
avvia_madhearts.command     avvio dal Terminale
installa.sh                 installazione completa su un nuovo Mac
aggiorna.sh                 scarica l'ultima versione dal repository
installa_app.sh             crea MadHearts.app (doppio clic, Dock, icona)
madhearts/
  app.py                    FASE 5  applicazione: stati, comandi, salvataggio sfera e impostazioni
  panel.py, web/            pannello di controllo nel browser
  audio.py                  musica, tappeto sonoro, suono della scia, rintocchi
  attract.py                logo, invito, dissolvenze sul proiettore
  capture.py                FASE 1  camera in un thread, solo l'ultimo frame, riconnessione
  tracking.py               FASE 2  MediaPipe Pose → spalle, gomiti, polsi
  motion.py                 FASE 3  smoothing, gesti, incroci, fine dell'intreccio
  visuals/                  FASE 4  motore GPU: scia (primo piano), sfera (sfondo)
  debug_overlay.py                  pannello di debug
  simulate.py                       visitatori simulati
assets/                     logo (da aggiungere) e font
audio/                      la vostra traccia musicale (da aggiungere)
data/                       la sfera e le impostazioni salvate
logs/                       messaggi tecnici e prove continuative
```

Privacy: nessun modulo salva o trasmette immagini delle persone.
