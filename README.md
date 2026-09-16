# trading-report

## Repo pubblico: i dati sensibili vivono nei GitHub Secrets, mai nei file

Questo repo è **pubblico** (serve a GitHub Pages sul piano Free). Dossier
XLS, mappa ISIN, regole di posizione e watchlist sono dati personali:
vanno impostati come **Settings → Secrets and variables → Actions**, mai
committati come file. I file in `data/` restano template vuoti — se li
trovi non vuoti, è un errore da correggere subito, non un dato da lasciare lì.

| Secret | Sostituisce | Formato |
|---|---|---|
| `MOVIMENTI_XLSX_B64` | `data/movimenti_dossier.xlsx` | il file XLS in base64 (`base64 -i movimenti.xlsx \| pbcopy`) |
| `ISIN_MAP_JSON` | `data/isin_map.json` | il JSON come stringa |
| `REGOLE_POSIZIONI_YAML` | `data/regole_posizioni.yaml` | il YAML come stringa |
| `WATCHLIST_YAML` | `data/watchlist.yaml` | il YAML come stringa (facoltativo) |
| `STORICO_SALT` | — | una stringa a caso, lunga, generata una volta (es. `openssl rand -hex 32`) |

`STORICO_SALT` è quello che rende innocuo lo storico persistente
committato ogni giorno (sotto): senza, il repo pubblico mostrerebbe i
tuoi ISIN/ticker reali in chiaro in `data/storico_indicatori.csv`. **Se
manca, il workflow lo segnala nei log ma non si ferma** — non lasciarlo
senza per più di un run.

Il vecchio secret `PORTFOLIO_JSON` resta come ripiego se non hai ancora
impostato `MOVIMENTI_XLSX_B64`: stesso principio, mai un file committato.

## Sincronizzazione posizioni (conto B)

Le posizioni aperte non si aggiornano più a mano. Il modo più semplice è
dalla pagina del report stesso ("📂 Sincronizza dati personali": carica il
file, compila ticker/stop/target/tesi nella tabella che appare, salva) —
i punti sotto spiegano cosa succede dietro le quinte.

**Due formati di export sono riconosciuti automaticamente**, in .xlsx o
.xls (vecchio formato Excel binario — capita spesso con i broker italiani,
gestito con `xlrd` oltre a `openpyxl`):

- **"Movimenti Dossier Titoli"** (storico: Operazione, Data valuta,
  Descrizione, Titolo, ISIN, Segno A/V, Quantità, Divisa, Prezzo, Cambio,
  Controvalore) — ricostruisce le posizioni in FIFO. Unico formato che dà
  la data di apertura reale, quindi i giorni di detenzione.
- **"Portafoglio di sintesi"** (snapshot attuale: Titolo, ISIN, Simbolo,
  Mercato, Strumento, Valuta, Quantità, P.zo medio di carico...) — ogni
  riga è già una posizione aperta, quantità e prezzo medio già calcolati
  dal broker. Non contiene una data di apertura: i giorni di detenzione
  restano n.d. per queste posizioni, non un numero inventato.

Il file va nel secret `MOVIMENTI_XLSX_B64` (base64), **mai committato**.

**Il ticker TradingView non è più del tutto manuale**: se il formato è
"Portafoglio di sintesi", la colonna Simbolo (es. `ISP.MI`) genera un
suggerimento (`MIL:ISP`) che pre-compila l'editor sulla pagina — resta un
suggerimento da verificare, non un dato certo, perché il suffisso del
broker non sempre corrisponde 1:1 all'exchange TradingView (es. `1SMCI.MI`
non diventa automaticamente il ticker giusto). Confermalo o correggilo,
poi resta salvato in `ISIN_MAP_JSON`.

Ogni run rilegge il dossier e ricalcola le posizioni aperte: quelle chiuse
(o assenti dal nuovo export) spariscono automaticamente.

## Regole di posizione e calendario

Stop, target, data di revisione, tesi, eventi per titolo: nel secret
`REGOLE_POSIZIONI_YAML` (schema nei commenti di `data/regole_posizioni.yaml`,
che resta il template vuoto). `data/eventi_macro.yaml` (riunioni BCE/Fed)
invece resta un file committato normale: sono date ufficiali pubbliche, non
dati tuoi. Il report confronta lo stato attuale con le regole scritte, non
genera giudizi propri.

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

Questo file **è committato ogni giorno dal workflow**, in un repo pubblico.
Con il secret `STORICO_SALT` impostato, ISIN e symbol vengono pseudonimizzati
(hash HMAC-SHA256, chiave = il secret) prima di scrivere: chi guarda il repo
vede hash, non i tuoi ISIN/ticker reali — solo chi conosce il secret può
farli corrispondere di nuovo. **Senza `STORICO_SALT`, questo file contiene
ISIN e ticker reali in chiaro**, visibili a chiunque: impostalo prima del
primo run, non dopo.

Cresce di poche decine di righe al giorno (qualche MB all'anno): non è
previsto un meccanismo di pulizia perché non ne ha bisogno nel breve-medio
termine.

## Segnali di medio periodo (Sezione 4)

Su candele **settimanali**, orizzonte 3-12 mesi: doppio massimo/minimo (con
distanza tra i picchi e livello di conferma), divergenze RSI-prezzo, rotture
dei massimi/minimi a 52 settimane, golden/death cross EMA50-EMA200 (con la
durata reale, non stimata). Il volume anomalo resta invece su base
**giornaliera** (media a 50 giorni), per richiesta esplicita.

Calcolati solo sulle posizioni aperte e sulla watchlist scritta a mano nel
secret `WATCHLIST_YAML` (schema nei commenti di `data/watchlist.yaml`) —
non su tutto il mercato. Un pattern non pulito (picchi troppo distanti in
livello, nessun ritracciamento vero) non viene forzato: niente segnale è
meglio di un falso segnale.

Questo repo contiene dati finanziari personali (quantità, prezzi, ISIN) ed è
pensato per restare **privato**.
