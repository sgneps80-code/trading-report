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

## Storico: due fonti diverse, per due scopi diversi

**EMA, incroci, indicatori di medio periodo** (Sezione 1 e i segnali della
Sezione 4) non aspettano che il nostro log si accumuli: ogni run scarica 2
anni di storico reale (`fetch_ohlc_range`, stesso endpoint Yahoo Finance già
usato per le candele a 5 giorni) e calcola EMA e incroci su dati di mercato
veri, disponibili da subito — non su un file che parte vuoto. "Da quanti
giorni" è quindi un numero reale dal primo run, non una stima che cresce nei
mesi. Se Yahoo non risponde per un titolo, il report ricade sul log proprio
(`data/storico_indicatori.csv`, sotto) e poi sullo stato del solo giorno
corrente, senza durata — mai un dato inventato.

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

Questo repo contiene dati finanziari personali (quantità, prezzi, ISIN) ed è
pensato per restare **privato**.
