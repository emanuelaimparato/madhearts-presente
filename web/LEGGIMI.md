# MadHearts — versione web

Versione per browser dell'esperienza (in sviluppo, per fasi).

- **Web 1**: camera e riconoscimento delle braccia — `test-riconoscimento.html`
- **Web 2**: elaborazione del movimento, identica all'app per Mac — `test-movimento.html`
- **Web 3** (questa): l'esperienza — `index.html`: scia a pennello, sfera ad anelli
  (salvata nel browser), schermata d'attesa con logo e invito, debug (tasto D)
- Web 4: audio, pannello di controllo, funzionamento offline · Web 5: pubblicazione online e telefono

## Provare sul Mac

Dal Terminale, nella cartella del progetto:

```bash
bash web/avvia_web.command
```

Si apre il browser (meglio Chrome) su `http://localhost:8000/` (l'esperienza).
Pagine di prova: `bash web/avvia_web.command test-movimento.html` (o `test-riconoscimento.html`).

Tasti dell'esperienza: **F** schermo intero · **Spazio** pausa · **D** debug ·
**C** due volte per azzerare la sfera.
Premi **Avvia camera** e consenti la webcam. Se l'app per Mac è aperta, chiudila
prima: la webcam può essere usata da un'app alla volta.

Tutto è incluso nella cartella (libreria MediaPipe 1.2.3 per il web, modelli, font,
logo): non serve Internet. Nessuna immagine viene salvata o inviata.
