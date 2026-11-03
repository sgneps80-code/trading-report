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
dalla pagina del report stesso: carica il file in "📂 Sincronizza dati
personali" (in fondo alla pagina), poi torna su a "Le mie posizioni" — lì,
riga per riga, compaiono già i campi ticker/stop/target/revisione/tesi da
compilare (prefissati se la posizione era già configurata, vuoti se è
nuova) e il bottone "💾 Salva regole e aggiorna report" subito sotto la
tabella: un'unica area, senza dover scendere a un'altra tabella per
salvare. I punti sotto spiegano cosa succede dietro le quinte.

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

## Analisi tecnica per Claude (file .md)

Sezione **🔬 Analisi tecnica per Claude** della pagina, sopra "Sincronizza
dati personali". Con un clic genera un file `.md` con tutti i dati tecnici
di uno strumento (o dell'intero portafoglio), da caricare in una chat con
Claude: indicatori con le stesse formule di TradingView, struttura, livelli,
gap, figure, statistiche storiche, strumenti collegati, eventi, posizione e,
in modalità Titolo, i dati grezzi in CSV. Nessun dato stimato: ciò che
manca è scritto "n.d." con il motivo.

### Come si avvia

1. Apri la pagina del report ed entra con la password.
2. Su ogni PC/browser, la prima volta: in "Sincronizza dati personali" devono
   esserci utente, repository e token GitHub (gli stessi già usati per caricare
   il dossier).
3. **📄 Titolo**: scrivi il simbolo Yahoo (es. `SAN.PA`) e premi Titolo,
   oppure premi 📄 sulla riga della watchlist. File completo con dati grezzi.
4. **📚 Portafoglio**: tutte le righe della watchlist (posizioni comprese),
   solo sintesi, senza dati grezzi.
5. Attendi 1-3 minuti senza chiudere la pagina: il file viene generato su
   GitHub Actions e scaricato in automatico.

### Dove finisce il file

Nella **cartella Download predefinita del browser**, con nome
`analisi_<TICKER>_<AAAA-MM-GG_HHMM>.md` oppure
`analisi_PORTAFOGLIO_<AAAA-MM-GG_HHMM>.md` (ora italiana).

Se il browser chiede ogni volta dove salvare:
- **Chrome**: Impostazioni → Download → disattiva "Chiedi dove salvare ciascun file prima di scaricarlo".
- **Edge**: Impostazioni → Download → disattiva "Chiedi cosa fare con ogni download" / "Chiedi dove salvare ogni file".
- **Firefox**: Impostazioni → Generale → File e applicazioni → Download → scegli "Salva i file in: Download" invece di "Chiedi sempre dove salvare i file".

### Come si aggiunge un titolo

- **＋ Aggiungi strumento** e compila la riga. Il simbolo è quello di Yahoo
  Finance: `ISP.MI` (Borsa Italiana ed Euronext Growth Milan), `SAN.PA`
  (Parigi), `SNY` (USA), `EURUSD=X` (cambio), `GC=F` (oro, future COMEX in USD).
- **Tipo** decide la compensabilità con lo zainetto fiscale (sì per azioni,
  ETC, obbligazioni, certificati; no per le plusvalenze degli ETF UCITS).
- **Principale**: per i titoli quotati su più mercati (es. Sanofi: ordini su
  `1SAN.MI`, mercato principale `SAN.PA`) l'analisi si fa sul principale e il
  listino degli ordini compare tra gli strumenti collegati, con scarto di prezzo,
  volumi e qualità del dato. Vuoto = automatico per i listini `1XXX.MI` con ISIN
  (paese dell'ISIN → borsa: FR `.PA`, DE `.DE`, NL `.AS`, ES `.MC`, US nessun
  suffisso…), usato solo se le chiusure dei due listini coincidono entro il 3%.
- **Benchmark** vuoto = `FTSEMIB.MI` per `.MI`, `^FCHI` per `.PA`, `^GSPC` per gli USA.
- **Collegati**: `SNY adr 0.5 EURUSD=X` (ADR: 2 ADR = 1 azione → 0.5 azioni
  per ADR) oppure `GC=F sottostante - EURUSD=X` (ETC oro). Più voci separate da `;`.
- Quantità, carico, stop, target, uscita: facoltativi. Liquidità del conto in alto a destra.
- Scorciatoie: **Importa da "Le mie posizioni"** (ticker, stop e target già
  nel report), **Importa portafoglio-export.xls** (export Fineco: quantità e
  carico), **Esporta/Importa JSON** per portare la watchlist su un altro PC
  (es. dal PC di casa a quello di lavoro).

### Dove stanno i dati

- Watchlist, posizioni e liquidità restano **solo nel browser**
  (localStorage): non sono nel repo pubblico.
- Al clic vengono passati al workflow `analisi_tecnica.yml` come input
  mascherato nei log, insieme a una **chiave casuale nuova per ogni richiesta**
  creata dalla pagina. Il file prodotto viene **cifrato** con quella chiave
  (AES-256-GCM) e pubblicato sul branch `analisi-output`, che contiene solo i
  file cifrati delle ultime 24 ore. La pagina, che tiene la chiave solo in
  memoria, lo scarica, lo decifra e lo salva. Nessuna password da inserire.

### Fonti e verifiche

- **Qualità del dato**: il file segnala le barre incoerenti (apertura o chiusura
  fuori da minimo–massimo), le stampe anomale (ombre oltre 3 ATR con volume
  basso; per i listini di esecuzione, massimi/minimi fuori dal range del mercato
  principale) e le esclude da swing, livelli ed estremi. Se mancano i metadati
  Yahoo, anagrafica e valuta vengono dalla watchlist e lo stato del mercato
  dall'orario standard della borsa; se a mercato aperto manca la seduta di oggi,
  lo scrive in testa con l'ultimo prezzo intraday e l'orario.
- **Statistiche condizionate** (dopo giorni oltre ±2 ATR, dopo RSI oltre 70/30,
  chiusura dei gap) sempre affiancate dal tasso su tutti i giorni e
  dall'intervallo di confidenza di Wilson al 95%.

- Prezzi: Yahoo Finance via `yfinance` con `auto_adjust=False` (non aggiustati
  per i dividendi; dividendi e split elencati a parte). 30 minuti: Yahoo dà solo
  gli ultimi 60 giorni. Oro spot (`XAUUSD=X`) non esiste su Yahoo: si usa `GC=F`.
- Controllo incrociato: la modalità Titolo confronta 18 valori con lo screener
  TradingView (stesso endpoint della libreria `tradingview-screener`, chiamato
  direttamente: la libreria per default esclude ADR, ETF/ETC, cambi e indici) e riporta gli scarti.
- Test: `python -m pytest tests -q` (indicatori su valori calcolati a mano e
  contro TA-Lib, generazione completa su dati sintetici, cifratura).
- **Qualità del dato per ETF/ETC di Borsa Italiana** (verificato il 2026-11-03):
  per le azioni (ISP, ENI, REY, SOM, OMER, SAN, SNY) i valori calcolati da Yahoo
  coincidono con lo screener TradingView alla 4ª cifra; per alcuni ETP no.
  `XUSE.MI` su Yahoo è quotato in EUR mentre `EURONEXT:XUSE` su TradingView
  vale 1.118 volte tanto (= EURUSD, probabilmente la linea in USD);
  `GBSE.MI` ha la stessa chiusura ma massimi/minimi più ampi (ATR +20%).
  Il file lo segnala da solo in testa ("ATTENZIONE qualità del dato") e in
  ogni blocco del Portafoglio, quindi l'analista sa quando i livelli in ATR
  possono non coincidere con i tuoi grafici.
- `verifica_fonti.py`: diagnostica di Yahoo, TradingView e CORS sui simboli principali.
- KAMA: KAMA(10,2,30) e KAMA(50,2,30) sulla chiusura (formula nel file).
  Se su TradingView usi parametri o uno script diversi, cambiali in
  `KAMA_DEFAULT` in `analisi/report.py` o nel campo `kama` del JSON.

### Uso dal PC di casa, senza GitHub

```
py -m pip install -r requirements-analisi.txt
py genera_analisi.py --modo titolo --simbolo SAN.PA --config watchlist_analisi.json
py genera_analisi.py --modo portafoglio --config watchlist_analisi.json
```
`watchlist_analisi.json` è il file di "Esporta JSON"; il .md finisce in `Download`.
