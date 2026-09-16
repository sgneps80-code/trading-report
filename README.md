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

Questo repo contiene dati finanziari personali (quantità, prezzi, ISIN) ed è
pensato per restare **privato**.
