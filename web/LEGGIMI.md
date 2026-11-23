# MadHearts — versione web

Versione per browser dell'esperienza (in sviluppo, per fasi).

- **Web 1**: camera e riconoscimento delle braccia — `test-riconoscimento.html`
- **Web 2**: elaborazione del movimento, identica all'app per Mac — `test-movimento.html`
- **Web 3**: l'esperienza — `index.html`: scia a pennello, sfera ad anelli (salvata nel
  browser), schermata d'attesa con logo e invito, debug (tasto D)
- **Web 4**: audio, camera spenta in pausa, funzionamento offline
- **Web 5** (questa): interfaccia da app (icone in alto a destra, menu di pausa,
  impostazioni a schede), telecomando dal telefono, pubblicazione su Netlify

## Provare sul Mac

Dal Terminale, nella cartella del progetto:

```bash
bash web/avvia_web.command
```

Si apre il browser predefinito del Mac su `http://localhost:8000/` (l'esperienza).
Pagine di prova: `bash web/avvia_web.command test-movimento.html` (o `test-riconoscimento.html`).

## Comandi

Muovendo il mouse (o toccando lo schermo) compaiono in alto a destra due icone:
- **pausa** — apre il menu di pausa (la camera si spegne): Riprendi, Volume, Musica,
  Effetti sonori, Muto, Schermo intero;
- **ingranaggio** — le impostazioni tecniche, a schede: Esperienza, Rilevamento, Sfera,
  Audio, Attesa, Telefono, Sistema (stato, debug, valori iniziali, azzeramento della sfera).

Ogni regolazione si salva da sola in questo browser.
Tasti: **Spazio** pausa · **F** schermo intero · **+ / −** volume · **M** muto · **D** debug ·
**Esc** chiude le impostazioni · **C** due volte per azzerare la sfera.

## Telecomando dal telefono

Impostazioni → **Telefono** → attiva il telecomando: compaiono un codice QR e un PIN.
Il telefono inquadra il codice, apre la pagina e inserisce il PIN: da lì comanda pausa,
volumi e impostazioni. Il collegamento è diretto tra i due dispositivi; serve Internet solo
per "trovarsi" (servizio gratuito PeerJS). Nessuna immagine viene inviata.
Il codice QR compare quando l'app è aperta dal suo indirizzo online (Netlify).

## Pubblicazione online (Netlify)

Indirizzo: **https://madhearts-presente.netlify.app** — telecomando: `/telecomando.html` (si apre dal QR).


Il file `netlify.toml` (nella cartella principale) dice a Netlify di pubblicare la cartella
`web`. Una volta collegato il repository, ogni modifica su GitHub aggiorna il sito da sola.

## Musica e funzionamento offline

La traccia va in `web/audio/musica.mp3` (non è nel repository). Tappeto sonoro, fruscio
della scia e rintocco sono generati dal browser. Dopo la prima apertura la pagina
funziona anche senza rete: tutti i file, modelli compresi, restano salvati nel browser.
Premi **Avvia camera** e consenti la webcam. Se l'app per Mac è aperta, chiudila
prima: la webcam può essere usata da un'app alla volta.

Tutto è incluso nella cartella (libreria MediaPipe 1.2.3 per il web, modelli, font,
logo): non serve Internet. Nessuna immagine viene salvata o inviata.
