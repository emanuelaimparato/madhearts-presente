# MadHearts — versione web

Versione per browser dell'esperienza (in sviluppo, per fasi).

- **Web 1** (questa): camera e riconoscimento delle braccia — `test-riconoscimento.html`
- Web 2: elaborazione del movimento · Web 3: grafica · Web 4: audio, sfera salvata,
  pannello, schermo intero, offline · Web 5: pubblicazione online e telefono

## Provare sul Mac

Dal Terminale, nella cartella del progetto:

```bash
bash web/avvia_web.command
```

Si apre il browser (meglio Chrome) su `http://localhost:8000/test-riconoscimento.html`.
Premi **Avvia camera** e consenti la webcam. Se l'app per Mac è aperta, chiudila
prima: la webcam può essere usata da un'app alla volta.

Tutto è incluso nella cartella (libreria MediaPipe 1.2.3 per il web, modelli, font,
logo): non serve Internet. Nessuna immagine viene salvata o inviata.
