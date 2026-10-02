# Bilancio personale (pagina locale)

Mettere questi 3 file nella stessa cartella e aprire `index.html` con il browser (Chrome, Edge o Firefox):

| File | Cosa fa |
|---|---|
| `index.html` | La pagina: grafico a torta, tabella, selezione periodo, elenco movimenti |
| `regole.js` | Regole predefinite che assegnano macro area e dettaglio (modificabili con un editor di testo) |
| `xlsx.full.min.js` | Libreria SheetJS 0.18.5 per leggere i file Excel; tutto funziona anche senza internet |

## Uso
- **Carica estratto conto**: scegli (o trascina sulla pagina) l'export `.xlsx` della banca. Puoi ricaricare file che si sovrappongono: i movimenti già presenti vengono ignorati e si aggiungono solo quelli nuovi.
- **Periodo**: clic su mesi singoli, sull'anno (anno intero) o Maiusc+clic per un intervallo. Ci sono anche le scorciatoie rapide.
- **Torta e tabella**: clic su una macro area (es. *Tempo libero*) per vedere il dettaglio (*Ristorazione*, *Bar e caffè*, *Cinema e spettacoli*…), poi clic su un dettaglio per vedere i suoi movimenti.
- **✎ su un movimento**: cambia la categoria solo per quel movimento, oppure crea una regola ("tutti i movimenti che contengono…") valida anche per i file futuri.
- **Solo da classificare**: mostra i movimenti che nessuna regola ha riconosciuto.

## Dove sono salvati i dati
Nel `localStorage` del browser, solo sul tuo PC. Non vengono inviati da nessuna parte.
Se cancelli i dati di navigazione o cambi browser li perdi: usa **Esporta backup** ogni tanto
(file `.json` con movimenti e regole personali) e **Ripristina backup** per ricaricarli.
