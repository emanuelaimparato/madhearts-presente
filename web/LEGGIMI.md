# MadHearts — versione web

Versione per browser dell'esperienza (in sviluppo, per fasi).

- **Web 1**: camera e riconoscimento delle braccia — `test-riconoscimento.html`
- **Web 2**: elaborazione del movimento, identica all'app per Mac — `test-movimento.html`
- **Web 3**: l'esperienza — `index.html`: scia a pennello, sfera ad anelli (salvata nel
  browser), schermata d'attesa con logo e invito, debug (tasto D)
- **Web 4** (questa): audio, barra dei comandi sullo schermo, pannello Impostazioni,
  camera spenta in pausa, funzionamento offline
- Web 5: pubblicazione online e comandi dal telefono

## Provare sul Mac

Dal Terminale, nella cartella del progetto:

```bash
bash web/avvia_web.command
```

Si apre il browser predefinito del Mac su `http://localhost:8000/` (l'esperienza).
Pagine di prova: `bash web/avvia_web.command test-movimento.html` (o `test-riconoscimento.html`).

## Comandi

Muovendo il mouse (o toccando lo schermo) compare in basso una barra che sparisce da sola:
**Pausa/Riprendi** (in pausa la camera si spegne), **− volume +**, **Muto**, **Schermo
intero**, **Impostazioni** (volumi, luminosità, intensità, durata della scia, soglia di
rilevamento, sfera, invito, logo, azzeramento della sfera). Le regolazioni si salvano da
sole in questo browser.

Tasti: **Spazio** pausa · **F** schermo intero · **+ / −** volume · **M** muto · **D** debug ·
**C** due volte per azzerare la sfera.

## Musica e funzionamento offline

La traccia va in `web/audio/musica.mp3` (non è nel repository). Tappeto sonoro, fruscio
della scia e rintocco sono generati dal browser. Dopo la prima apertura la pagina
funziona anche senza rete: tutti i file, modelli compresi, restano salvati nel browser.
Premi **Avvia camera** e consenti la webcam. Se l'app per Mac è aperta, chiudila
prima: la webcam può essere usata da un'app alla volta.

Tutto è incluso nella cartella (libreria MediaPipe 1.2.3 per il web, modelli, font,
logo): non serve Internet. Nessuna immagine viene salvata o inviata.
