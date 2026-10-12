/*
 * CATEGORIE (uscite)                 DETTAGLI
 *   Casa ........................... Mutuo / finanziamento · Utenze · Manutenzione e condominio
 *   Alimentari ..................... Spesa · Bar e caffè
 *   Tempo libero ................... Ristorazione · Svago e spettacoli · Sport · Viaggi e vacanze
 *   Trasporti ...................... Carburante · Pedaggi e parcheggi · Mezzi pubblici e taxi · Assicurazione e manutenzione auto
 *   Salute ......................... Visita medica · Farmacia e ottica
 *   Famiglia ....................... Bonifici a familiari · Altri bonifici e PayPal · Scuola e libri · Donazioni e associazioni
 *   Shopping ....................... Acquisti online · Abbigliamento e scarpe · Elettronica e casa · Abbonamenti e app · Cura della persona
 *   Banca e tasse .................. Spese bancarie · Tasse su investimenti · Imposte e tributi · Consulenze e professionisti
 *   Contanti ....................... Prelievi
 *   Investimenti ................... Acquisto titoli e cripto
 *   Giroconti ...................... Trasferimenti tra conti propri (esclusi dal grafico di default)
 * CATEGORIE (entrate): Lavoro · Investimenti · Rimborsi · Altre entrate
 */
/*
 * Regole di categorizzazione predefinite.
 *
 * Ogni regola: [ espressione, "Macro area", "Dettaglio", segno ]
 *   - espressione: testo/regex (senza distinzione maiuscole) cercato in
 *     "Descrizione | Descrizione_Completa". Gli spazi sono tollerati: la banca
 *     a volte spezza le parole ("FARM ACIA"), quindi la regola viene provata
 *     anche sul testo senza spazi.
 *   - segno: "in" = solo entrate, "out" = solo uscite, omesso = entrambi.
 *
 * Vince la PRIMA regola che corrisponde: metti le più specifiche in alto.
 * Le regole personali create dalla pagina hanno sempre la precedenza su queste.
 */
// Deve coincidere con la versione attesa da index.html: se la pagina segnala
// "regole.js non aggiornato", questo file nella cartella è quello vecchio.
window.REGOLE_VERSIONE = "2026-10-12";

window.REGOLE_PREDEFINITE = [
  // ───────────── ENTRATE ─────────────
  ["^Stipendio", "Lavoro", "Stipendio", "in"],
  ["PELLEGRINO STEFANO BEN: STEFANO PELLEGRINO", "Giroconti", "Trasferimenti tra conti propri"],
  ["Beneficiario: STEFANO PELLEGRINO", "Giroconti", "Trasferimenti tra conti propri"],
  ["Ord: FENDI", "Lavoro", "Rimborsi spese aziendali", "in"],
  ["FASDAC", "Rimborsi", "Rimborsi sanitari", "in"],
  ["GESTORE DEI SERVIZI ENERGETICI", "Altre entrate", "Incentivi energia (GSE)", "in"],
  ["Stacco Cedole", "Investimenti", "Cedole e vendite titoli", "in"],
  ["Compravendita Titoli", "Investimenti", "Cedole e vendite titoli", "in"],
  ["Storno|Accr\\.su carta", "Rimborsi", "Altri rimborsi", "in"],
  ["Sconto Canone", "Altre entrate", "Varie", "in"],
  ["^Bonifico", "Rimborsi", "Altri rimborsi", "in"],

  // ───────────── BANCA, TASSE, INVESTIMENTI, CONTANTI ─────────────
  ["Compravendita Titoli", "Investimenti", "Acquisto titoli e cripto", "out"],
  ["COINBASE|BINANCE|BITPANDA", "Investimenti", "Acquisto titoli e cripto"],
  ["Canone Mensile", "Banca e tasse", "Spese bancarie"],
  ["Imposta bollo|Imposta di bollo", "Banca e tasse", "Spese bancarie"],
  ["Capit\\.GAIN|Ritenuta|Riten\\.", "Banca e tasse", "Tasse su investimenti"],
  ["^(Commiss|Comm\\.Prel|Spese Sepa|Recupero spese)", "Banca e tasse", "Spese bancarie"],
  ["Prelievo Bancomat|Pr\\.FinecoCard ATM|Prelevamento", "Contanti", "Prelievi"],
  ["STUDIO LEGALE|Consulenza Avv|AVVOCAT|NOTAI|COMMERCIALISTA|STUDIO LICONTI", "Banca e tasse", "Consulenze e professionisti", "out"],
  ["SPID|POSTE ITALIANE|ANAGRAFE|UFFICIO POSTALE", "Banca e tasse", "Imposte e tributi"],
  ["PAGOPA|PAG PUB AMM|UNIONE COMUNAL|CONSORZIO DI B|AGENZIA ENTRATE|F24", "Banca e tasse", "Imposte e tributi"],

  // ───────────── CASA ─────────────
  ["RATA FIN", "Casa", "Mutuo / finanziamento"],
  ["Eni Spa|EDISON|ENEL ENERGIA|\\bA2A\\b|\\bHERA\\b|\\bIREN\\b|\\bESTRA\\b", "Casa", "Utenze"],
  ["PUBLIACQUA|ACQUEDOTTO", "Casa", "Utenze"],
  ["COMUNE DI GREVE|COMUNE DI", "Banca e tasse", "Imposte e tributi"],
  ["Condominio", "Casa", "Manutenzione e condominio"],
  ["TELECOMITALIA|TELECOM ITALIA|ILIAD|VODAFONE|WINDTRE|FASTWEB|\\bTIM\\b", "Casa", "Utenze"],
  ["TECNICA ?CLIMATICA|SPAZZACAMINO|CASAMONTI|IDRAULIC|ELETTRICIST", "Casa", "Manutenzione e condominio"],
  ["\\bOBI\\b|BRICOMAN|LEROY ?MERLIN|SCREWFIX|AGRARIA|PIANTE E FIORI|BRICO|FERRAMENTA", "Casa", "Manutenzione e condominio"],

  // ───────────── FAMIGLIA ─────────────
  ["Ben(eficiario)?: [A-Za-z]+ Gebiola|ANNA PELLEGRINO", "Famiglia", "Bonifici a familiari"],
  ["Visa Direct", "Famiglia", "Altri bonifici e PayPal"],
  ["A I S M|\\bAISM\\b|NUNZIATELLA|SAVECHILDRE|SAVE THE CHILDREN|MANAGERITALIA|EMERGENCY|UNICEF|AIRC", "Famiglia", "Donazioni e associazioni"],

  // ───────────── FAMIGLIA: SCUOLA ─────────────
  ["ISTITU ?TO COMPR|ISTITUTO FANFANI|SCUOLA|CARTOLERIA", "Famiglia", "Scuola e libri"],
  ["FELTRINELLI|EDICOL|LIBRERIA|MONDADORI", "Famiglia", "Scuola e libri"],

  // ───────────── SALUTE ─────────────
  ["FARMACIA|FARM ACIA|PARAFARMACIA", "Salute", "Farmacia e ottica"],
  ["ODONT|DENTIST|STUDIO MEDIC|POLIAMBULATORIO|CENTRO MEDICO", "Salute", "Visita medica"],
  ["OTTICA", "Salute", "Farmacia e ottica"],
  ["SANITA'|SANITA |ASLTC|\\bASL\\b|OSPEDA", "Salute", "Visita medica"],

  // ───────────── TEMPO LIBERO: SPORT ─────────────
  ["F\\.C\\. SCANDICCI|Scandicci Calcio|POLISPORT|SESTESE CALCIO|UNIONE SPORTIVA|GRUPPO SPORTIVO|Sport Rotell|VIRTUS|CALCIO|\\bASD\\b", "Tempo libero", "Sport"],
  ["PISCIN|OLYMPUS CLUB|PALESTRA|FITNESS", "Tempo libero", "Sport"],
  ["DECATHLON|NENCINI SPORT|UNIVERSO SPORT|K-SPORT|FAN SHOP|ROLLERMANIA|PATTINOMANIA|CISALFA|\\bSPORT", "Tempo libero", "Sport"],

  // ───────────── TRASPORTI ─────────────
  ["UNIPOL ?TECH|ASPIT|AUTOSTRAD|FASTPAY|SAT COLLESALVETTI|TELEPASS", "Trasporti", "Pedaggi e parcheggi"],
  ["TAMOIL|TAMO IL|\\bENI\\b|\\bQ8\\b|\\bIP\\b|B FUEL|CARBURANT|DISTR IP|\\bADS\\b|STAZIONE DI SERVIZIO|NUOVA SIDAP|ENI\\d{3,}|PV\\d{3,}|\\bESSO\\b|AGIP", "Trasporti", "Carburante"],
  ["EASYPARK|PARCHEGG|PARKING|GARAGE|PARCOMETR|ANM SPA|\\bPARK\\b|TANA DIREZ", "Trasporti", "Pedaggi e parcheggi"],
  ["TAXI|G7 CLICHY|UBER", "Trasporti", "Mezzi pubblici e taxi"],
  ["A\\.T\\.A\\.C|\\bATAC\\b|AUTOLINEE|TRENITALIA|\\bITALO\\b|ITALOTRENO|STAZIONE|APP TORINO|AV ITALIA|TICKET ATM|METRO", "Trasporti", "Mezzi pubblici e taxi"],
  ["SOS AUTO|COMAUTO|GOMM|OFFICINA|CARROZZ|AUTORICAMBI", "Trasporti", "Assicurazione e manutenzione auto"],
  ["ALLIANZ|UNIPOL|ASSICURA|GENERALI|PRIMA\\.IT", "Trasporti", "Assicurazione e manutenzione auto"],

  // ───────────── VOLI / ABBONAMENTI ─────────────
  ["EASYJET|RYANAIR|LUFTHAVN|AEROPORT|ALITALIA|\\bITA AIRWAYS|VUELING|WIZZ", "Tempo libero", "Viaggi e vacanze"],
  ["NETFLIX|DISNEY|PAYPAL \\*NOW|DAZN|YOUTUBE|SPOTIFY|PRIME VIDEO", "Shopping", "Abbonamenti e app"],
  ["ANTHROPIC|CLAUDE|GOOGLE|CHESS COM|LINKEDIN|APPLE\\.COM|MICROSOFT|OPENAI", "Shopping", "Abbonamenti e app"],

  // ───────────── TEMPO LIBERO: VIAGGI ─────────────
  ["HOTEL|AIRBNB|BOOKING|Pappasole spa|PENSIONE|NHOW|AVISIO PARK|SUAN PARK|BORGO PETRIOLO|RESIDENCE|SOC AGRICOLA|AGRITURISMO", "Tempo libero", "Viaggi e vacanze"],
  ["SKIPASS|OBEREGG|LATEMAR|S\\.I\\.T\\. BELLAMONTE|FUNIVI|SEGGIOVIA", "Tempo libero", "Viaggi e vacanze"],
  ["BICI PAPPASOLE|NOLEGG|CHIANTI BIKE", "Tempo libero", "Viaggi e vacanze"],

  // ───────────── SHOPPING ─────────────
  ["AMAZON|AMZN", "Shopping", "Acquisti online"],
  ["PCCOMPONENT|EPRICE|SMARTBUGS|ZALANDO|SHEIN|TEMU|EBAY", "Shopping", "Acquisti online"],
  ["EURONICS|MEDIAWORLD|UNIEURO|TRONY|EXPERT", "Shopping", "Elettronica e casa"],
  ["PRADA (SPA )?\\d+|VFINTERNATI|BOGGI|TIMBERLAND|TEZENIS|ALCOTT|CALZATURE|UPIM|GUTTERIDGE|MILLEPIEDI|\\bOVS\\b|ZARA|H&M|BENETTON|INTIMISSIMI", "Shopping", "Abbigliamento e scarpe"],
  ["TIGER STORE|ACTION|FLYING TIGER", "Shopping", "Elettronica e casa"],

  // ───────────── SHOPPING: CURA DELLA PERSONA ─────────────
  ["BARBER|PARRUCCH|ESTETIC|PROFUMERIA|SEPHORA|ACQUA ?& ?SAPONE", "Shopping", "Cura della persona"],

  // ───────────── ALIMENTARI ─────────────
  ["UNICOOP|\\bCOOP\\b|CARREFOUR|\\bCRF\\b|ESSELUNGA|CONAD|LIDL|EUROSPIN|\\bPAM\\b|IPER |ECONOMY|MISTER RISPARMIO|PENNY|\\bMD\\b|SUPERMERCATO|DITTA AZZURRO", "Alimentari", "Spesa"],
  ["CASEIFICIO|MACELL|MASTROCICCIAIO|FORNO|PANIFIC|ORTOFRUTT|PESCHERIA|SALUMERIA", "Alimentari", "Spesa"],

  // ───────────── TEMPO LIBERO ─────────────
  ["LEGOLAND|LEGO HOUSE|GARDALAND|STANDI|MIRABILANDIA|ACQUAPARK|AQUAFAN|LUNAPARK", "Tempo libero", "Svago e spettacoli"],
  ["CINEMA|\\bUCI\\b|THE SPACE|TICKETONE|TICKETMASTER|TEATRO|PARIS OPERA|CONCERT", "Tempo libero", "Svago e spettacoli"],
  ["MUSEO|MUSEI|UFFIZI|COLOSSEO|OPERA DELLA PRIMAZIALE|MOSTRA", "Tempo libero", "Svago e spettacoli"],
  ["5 RIONI|ASSOCIAZIONE 5|CASA DEL POPOLO|SAGRA|PRO LOCO", "Tempo libero", "Svago e spettacoli"],
  ["SALA GIOCHI|NEW GAMES|LUDOTECA|BOWLING", "Tempo libero", "Svago e spettacoli"],
  ["GELAT|PASTICCERIA|SFOGLIAT|PANDOLCE|DOLCI|LIEVITATI", "Alimentari", "Bar e caffè"],
  ["MC ?DONALD|MCDONALD|FIVE GUYS|BURGER|KEBAB|KEBAB|ICCHEBAB|ANTICO VINAIO|PIAD|FOOD COURT|FOODTRUCK|AUTOGRILL|EXKI|MERCATO CENTRALE", "Tempo libero", "Ristorazione"],
  ["RISTORA|RISTORANTE|OLD WILD WEST|ROADHOUSE|\\bRIST\\b|FIASCHETTERIA|PIZZ|OSTERIA|TRATTORIA|TAVERNA|SUSHI|SATORI|DA I DOLIO|DA I MAVO|IL MARCHESE|ALFREDO ALLA SCROFA|SOTTO PORTA|LA GIOCONDA|IL VECCHIO E IL MARE|AL FRESCO|MALGA|RIFUGIO|BAITA|FARINA & LUPPOLO|LA CARETTA|OLD STOVE|\\bPUB\\b|LOCANDA|BRACERIA|IL PIPISTRELLO|IL VECCIOLINO|MO-VIOLA|LA CAPRICCIOSA|BIANCO SPINO|BAGNO VENERE|GINESTRA ROSALIA|CASUMARO|OWAP|ECCELLENZE DELLA COSTI|SORBILLO|SERV\\.RIST|RISTORO", "Tempo libero", "Ristorazione"],
  ["\\bBAR\\b|CAFFE|CAFFÈ|\\bCAFE\\b|PEDEVILLA|LOC\\.CAPANNUCCIA|DISTRIB|VENDING|SAMARCANDA|6645 -|SEGAFREDO|COFFEE", "Alimentari", "Bar e caffè"],

  // ───────────── RESIDUI PER TIPO DI OPERAZIONE ─────────────
  ["^SEPA Direct Debit", "Casa", "Utenze"],
  ["^Bonifico", "Famiglia", "Altri bonifici e PayPal", "out"],
  ["Bollettino", "Banca e tasse", "Imposte e tributi"],
];

/*
 * Spese piccole: un'uscita fino a "soglia" euro che è stata classificata a mano
 * (singolo movimento o regola personale) oppure non è riconosciuta da nessuna
 * regola, viene messa in questa categoria. Le tue assegnazioni sopra la soglia
 * restano valide. Per disattivare: window.SPESE_PICCOLE = null;
 */
window.SPESE_PICCOLE = { soglia: 10, macro: "Alimentari", det: "Bar e caffè" };

/*
 * Nomi delle versioni precedenti: le assegnazioni manuali e le regole personali
 * fatte con questi nomi vengono mostrate con il nome nuovo.
 */
window.CATEGORIE_RINOMINATE = {
 "Rimborsi › Fondo sanitario": [
  "Rimborsi",
  "Rimborsi sanitari"
 ],
 "Rimborsi › Storni e accrediti carta": [
  "Rimborsi",
  "Altri rimborsi"
 ],
 "Rimborsi › Bonifici ricevuti da persone": [
  "Rimborsi",
  "Altri rimborsi"
 ],
 "Banca e imposte › Sconti e bonus banca": [
  "Altre entrate",
  "Varie"
 ],
 "Investimenti › Cedole": [
  "Investimenti",
  "Cedole e vendite titoli"
 ],
 "Investimenti › Vendita titoli": [
  "Investimenti",
  "Cedole e vendite titoli"
 ],
 "Investimenti › Acquisto titoli": [
  "Investimenti",
  "Acquisto titoli e cripto"
 ],
 "Investimenti › Criptovalute": [
  "Investimenti",
  "Acquisto titoli e cripto"
 ],
 "Banca e imposte › Canone conto": [
  "Banca e tasse",
  "Spese bancarie"
 ],
 "Banca e imposte › Imposta di bollo": [
  "Banca e tasse",
  "Spese bancarie"
 ],
 "Banca e imposte › Commissioni bancarie": [
  "Banca e tasse",
  "Spese bancarie"
 ],
 "Banca e imposte › Tasse su investimenti": [
  "Banca e tasse",
  "Tasse su investimenti"
 ],
 "Banca e imposte › Poste e servizi PA": [
  "Banca e tasse",
  "Imposte e tributi"
 ],
 "Banca e imposte › Imposte e tributi": [
  "Banca e tasse",
  "Imposte e tributi"
 ],
 "Banca e imposte › Bollettini": [
  "Banca e tasse",
  "Imposte e tributi"
 ],
 "Casa e utenze › Tributi e servizi comunali": [
  "Banca e tasse",
  "Imposte e tributi"
 ],
 "Servizi professionali › Avvocati, notai e consulenti": [
  "Banca e tasse",
  "Consulenze e professionisti"
 ],
 "Contanti › Prelievi bancomat": [
  "Contanti",
  "Prelievi"
 ],
 "Casa e utenze › Rata finanziamento / mutuo": [
  "Casa",
  "Mutuo / finanziamento"
 ],
 "Casa e utenze › Luce e gas": [
  "Casa",
  "Utenze"
 ],
 "Casa e utenze › Acqua": [
  "Casa",
  "Utenze"
 ],
 "Casa e utenze › Telefono e internet": [
  "Casa",
  "Utenze"
 ],
 "Casa e utenze › Altre domiciliazioni": [
  "Casa",
  "Utenze"
 ],
 "Casa e utenze › Condominio": [
  "Casa",
  "Manutenzione e condominio"
 ],
 "Casa e utenze › Manutenzione e impianti": [
  "Casa",
  "Manutenzione e condominio"
 ],
 "Casa e utenze › Bricolage e giardino": [
  "Casa",
  "Manutenzione e condominio"
 ],
 "Famiglia e persone › Bonifici a familiari": [
  "Famiglia",
  "Bonifici a familiari"
 ],
 "Famiglia e persone › Invii PayPal a persone": [
  "Famiglia",
  "Altri bonifici e PayPal"
 ],
 "Famiglia e persone › Altri bonifici inviati": [
  "Famiglia",
  "Altri bonifici e PayPal"
 ],
 "Famiglia e persone › Associazioni e donazioni": [
  "Famiglia",
  "Donazioni e associazioni"
 ],
 "Istruzione › Scuola": [
  "Famiglia",
  "Scuola e libri"
 ],
 "Istruzione › Libri e giornali": [
  "Famiglia",
  "Scuola e libri"
 ],
 "Salute › Farmacia": [
  "Salute",
  "Farmacia e ottica"
 ],
 "Salute › Ottica": [
  "Salute",
  "Farmacia e ottica"
 ],
 "Salute › Dentista e visite": [
  "Salute",
  "Visita medica"
 ],
 "Salute › Ticket sanitari": [
  "Salute",
  "Visita medica"
 ],
 "Sport › Società sportive e iscrizioni": [
  "Tempo libero",
  "Sport"
 ],
 "Sport › Piscina e palestra": [
  "Tempo libero",
  "Sport"
 ],
 "Sport › Abbigliamento e attrezzatura": [
  "Tempo libero",
  "Sport"
 ],
 "Trasporti › Pedaggi autostradali": [
  "Trasporti",
  "Pedaggi e parcheggi"
 ],
 "Trasporti › Parcheggi": [
  "Trasporti",
  "Pedaggi e parcheggi"
 ],
 "Trasporti › Taxi": [
  "Trasporti",
  "Mezzi pubblici e taxi"
 ],
 "Trasporti › Mezzi pubblici e treni": [
  "Trasporti",
  "Mezzi pubblici e taxi"
 ],
 "Trasporti › Manutenzione auto": [
  "Trasporti",
  "Assicurazione e manutenzione auto"
 ],
 "Trasporti › Assicurazione auto": [
  "Trasporti",
  "Assicurazione e manutenzione auto"
 ],
 "Abbonamenti › Streaming TV e musica": [
  "Shopping",
  "Abbonamenti e app"
 ],
 "Abbonamenti › App e software": [
  "Shopping",
  "Abbonamenti e app"
 ],
 "Viaggi e vacanze › Voli e aeroporti": [
  "Tempo libero",
  "Viaggi e vacanze"
 ],
 "Viaggi e vacanze › Alloggi": [
  "Tempo libero",
  "Viaggi e vacanze"
 ],
 "Viaggi e vacanze › Sci e impianti": [
  "Tempo libero",
  "Viaggi e vacanze"
 ],
 "Viaggi e vacanze › Noleggi": [
  "Tempo libero",
  "Viaggi e vacanze"
 ],
 "Shopping › Amazon": [
  "Shopping",
  "Acquisti online"
 ],
 "Shopping › Altri acquisti online": [
  "Shopping",
  "Acquisti online"
 ],
 "Shopping › Elettronica": [
  "Shopping",
  "Elettronica e casa"
 ],
 "Shopping › Casalinghi e varie": [
  "Shopping",
  "Elettronica e casa"
 ],
 "Cura della persona › Barbiere, parrucchiere, cosmetici": [
  "Shopping",
  "Cura della persona"
 ],
 "Alimentari › Supermercato": [
  "Alimentari",
  "Spesa"
 ],
 "Alimentari › Botteghe e specialità": [
  "Alimentari",
  "Spesa"
 ],
 "Tempo libero › Gelaterie e pasticcerie": [
  "Alimentari",
  "Bar e caffè"
 ],
 "Tempo libero › Bar e caffè": [
  "Alimentari",
  "Bar e caffè"
 ],
 "Tempo libero › Fast food e street food": [
  "Tempo libero",
  "Ristorazione"
 ],
 "Tempo libero › Parchi divertimento": [
  "Tempo libero",
  "Svago e spettacoli"
 ],
 "Tempo libero › Cinema e spettacoli": [
  "Tempo libero",
  "Svago e spettacoli"
 ],
 "Tempo libero › Musei e cultura": [
  "Tempo libero",
  "Svago e spettacoli"
 ],
 "Tempo libero › Feste ed eventi": [
  "Tempo libero",
  "Svago e spettacoli"
 ],
 "Tempo libero › Giochi e svago": [
  "Tempo libero",
  "Svago e spettacoli"
 ]
};
