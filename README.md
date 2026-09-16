# trading-report

## Sincronizzazione posizioni (conto B)

Le posizioni aperte non si aggiornano più a mano: vengono ricostruite in FIFO
dall'export del broker.

1. Esporta dal tuo dossier titoli il file "Movimenti Dossier Titoli" (colonne:
   Operazione, Data valuta, Descrizione, Titolo, ISIN, Segno A/V, Quantità,
   Divisa, Prezzo, Cambio, Controvalore) e salvalo come
   `data/movimenti_dossier.xlsx`, committandolo nel repo.
2. Mappa ogni ISIN a un ticker TradingView in `data/isin_map.json`:
   ```json
   {
     "IT0003132476": { "tv_symbol": "MIL:ENI", "name": "Eni", "type": "Azione" }
   }
   ```
   `tv_symbol` è `EXCHANGE:TICKER` (`MIL:` per Borsa Italiana) oppure solo
   `TICKER` per i titoli USA. `type` è `Azione` o `ETF`. Gli ISIN non mappati
   compaiono nei log del workflow con un warning, e il titolo resta nel
   report senza dati tecnici finché non lo mappi.
3. Ogni run del report rilegge il file e ricalcola le posizioni aperte:
   quelle chiuse (quantità residua zero) spariscono automaticamente.

## Regole di posizione e calendario

`data/regole_posizioni.yaml` (stop, target, data di revisione, tesi, eventi
per titolo) e `data/eventi_macro.yaml` (riunioni BCE/Fed) — schema e istruzioni
nei commenti dei due file. Il report confronta lo stato attuale con questi
valori, non genera giudizi propri.

## Il prompt AI descrive, non consiglia

Il modello non genera più raccomandazioni operative (accumula/mantieni/riduci,
punteggi Forte/Moderato): quei campi sono stati rimossi dallo schema. Per le
posizioni aperte produce solo due cose, entrambe visibili nella colonna "Da
notare" di Sezione 1, in un colore diverso dai fatti calcolati in Python:
- **cosa è cambiato rispetto a ieri** (prezzo, RSI, MACD), confrontando con
  `data/storico_indicatori.csv` — i numeri del confronto li calcola Python,
  al modello resta solo il compito di descriverli in una riga;
- **contraddizioni tra la tesi scritta e i fatti attuali**, solo quando c'è
  un conflitto di significato reale (non ripete il confronto numerico
  stop/target, già mostrato in tabella).

Per "Da approfondire" ed ETF il modello resta limitato a descrivere il
possibile catalizzatore del movimento — mai un consiglio operativo, come già
dalla correzione del filtro di liquidità.

## Storico: due fonti diverse, per due scopi diversi

**EMA, incroci, indicatori di medio periodo** (Sezione 1 e i segnali della
Sezione 4) non aspettano che il nostro log si accumuli: ogni run scarica 5
anni di storico reale (`fetch_ohlc_range`, stesso endpoint Yahoo Finance già
usato per le candele a 5 giorni) e calcola EMA e incroci su dati di mercato
veri, disponibili da subito — non su un file che parte vuoto. "Da quanti
giorni" è quindi un numero reale dal primo run, non una stima che cresce nei
mesi. Servono 5 anni (non 2) perché l'EMA200 di Sezione 4 è calcolata su
candele SETTIMANALI: 200 settimane sono ~4 anni. Se Yahoo non risponde per
un titolo, il report ricade sul log proprio (`data/storico_indicatori.csv`,
sotto) e poi sullo stato del solo giorno corrente, senza durata — mai un
dato inventato.

**`data/storico_indicatori.csv`** accumula invece una riga al giorno per
ogni posizione aperta e per ogni titolo uscito in "Da approfondire" (prezzo,
RSI, EMA, MACD, performance). Serve a quello che *non* si può retrodatare:
verificare, col tempo, se i segnali del report si sono confermati o no —
questo richiede davvero che il tempo passi, perché dipende da cosa succede
dopo la segnalazione, non da storico di mercato già esistente. Resta anche
il ripiego di prima istanza se Yahoo non risponde per una posizione.

Cresce di poche decine di righe al giorno (qualche MB all'anno): non è
previsto un meccanismo di pulizia perché non ne ha bisogno nel breve-medio
termine.

## Segnali di medio periodo (Sezione 4)

Su candele **settimanali**, orizzonte 3-12 mesi: doppio massimo/minimo (con
distanza tra i picchi e livello di conferma), divergenze RSI-prezzo, rotture
dei massimi/minimi a 52 settimane, golden/death cross EMA50-EMA200 (con la
durata reale, non stimata). Il volume anomalo resta invece su base
**giornaliera** (media a 50 giorni), per richiesta esplicita.

Calcolati solo sulle posizioni aperte e sulla watchlist scritta a mano in
`data/watchlist.yaml` (schema nei commenti del file) — non su tutto il
mercato. Un pattern non pulito (picchi troppo distanti in livello, nessun
ritracciamento vero) non viene forzato: niente segnale è meglio di un falso
segnale.

Questo repo contiene dati finanziari personali (quantità, prezzi, ISIN) ed è
pensato per restare **privato**.
