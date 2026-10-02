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
window.REGOLE_PREDEFINITE = [
  // ───────────── ENTRATE ─────────────
  ["^Stipendio", "Lavoro", "Stipendio", "in"],
  ["PELLEGRINO STEFANO BEN: STEFANO PELLEGRINO", "Giroconti", "Trasferimenti tra conti propri"],
  ["Beneficiario: STEFANO PELLEGRINO", "Giroconti", "Trasferimenti tra conti propri"],
  ["Ord: FENDI", "Lavoro", "Rimborsi spese aziendali", "in"],
  ["FASDAC", "Rimborsi", "Fondo sanitario", "in"],
  ["GESTORE DEI SERVIZI ENERGETICI", "Altre entrate", "Incentivi energia (GSE)", "in"],
  ["Stacco Cedole", "Investimenti", "Cedole", "in"],
  ["Compravendita Titoli", "Investimenti", "Vendita titoli", "in"],
  ["Storno|Accr\\.su carta", "Rimborsi", "Storni e accrediti carta", "in"],
  ["Sconto Canone", "Banca e imposte", "Sconti e bonus banca", "in"],
  ["^Bonifico", "Rimborsi", "Bonifici ricevuti da persone", "in"],

  // ───────────── BANCA, TASSE, INVESTIMENTI ─────────────
  ["Compravendita Titoli", "Investimenti", "Acquisto titoli", "out"],
  ["Canone Mensile", "Banca e imposte", "Canone conto"],
  ["Imposta bollo|Imposta di bollo", "Banca e imposte", "Imposta di bollo"],
  ["Capit\\.GAIN|Ritenuta|Riten\\.", "Banca e imposte", "Tasse su investimenti"],
  ["Commiss|Comm\\.Prel|Spese Sepa|Recupero spese", "Banca e imposte", "Commissioni bancarie"],
  ["Prelievo Bancomat|Pr\\.FinecoCard ATM|Prelevamento", "Contanti", "Prelievi bancomat"],
  ["SPID|POSTE ITALIANE", "Banca e imposte", "Poste e servizi PA"],
  ["PAGOPA|PAG PUB AMM|UNIONE COMUNAL|CONSORZIO DI B|AGENZIA ENTRATE|F24", "Banca e imposte", "Imposte e tributi"],

  // ───────────── CASA E UTENZE ─────────────
  ["RATA FIN", "Casa e utenze", "Rata finanziamento / mutuo"],
  ["Eni Spa|EDISON|ENEL ENERGIA|\\bA2A\\b|\\bHERA\\b|\\bIREN\\b|\\bESTRA\\b", "Casa e utenze", "Luce e gas"],
  ["PUBLIACQUA|ACQUEDOTTO", "Casa e utenze", "Acqua"],
  ["COMUNE DI GREVE|COMUNE DI", "Casa e utenze", "Tributi e servizi comunali"],
  ["Condominio", "Casa e utenze", "Condominio"],
  ["TELECOMITALIA|TELECOM ITALIA|ILIAD|VODAFONE|WINDTRE|FASTWEB|\\bTIM\\b", "Casa e utenze", "Telefono e internet"],
  ["TECNICA ?CLIMATICA|SPAZZACAMINO|CASAMONTI|IDRAULIC|ELETTRICIST", "Casa e utenze", "Manutenzione e impianti"],
  ["\\bOBI\\b|BRICOMAN|LEROY ?MERLIN|SCREWFIX|AGRARIA|PIANTE E FIORI|BRICO|FERRAMENTA", "Casa e utenze", "Bricolage e giardino"],

  // ───────────── FAMIGLIA E PERSONE ─────────────
  ["GEBIOLA|ANNA PELLEGRINO", "Famiglia e persone", "Bonifici a familiari"],
  ["Visa Direct", "Famiglia e persone", "Invii PayPal a persone"],
  ["A I S M|\\bAISM\\b|NUNZIATELLA|SAVECHILDRE|SAVE THE CHILDREN|MANAGERITALIA|EMERGENCY|UNICEF|AIRC", "Famiglia e persone", "Associazioni e donazioni"],

  // ───────────── ISTRUZIONE ─────────────
  ["ISTITU ?TO COMPR|ISTITUTO FANFANI|SCUOLA|CARTOLERIA", "Istruzione", "Scuola"],
  ["FELTRINELLI|EDICOL|LIBRERIA|MONDADORI", "Istruzione", "Libri e giornali"],

  // ───────────── SALUTE ─────────────
  ["FARMACIA|FARM ACIA|PARAFARMACIA", "Salute", "Farmacia"],
  ["ODONT|DENTIST|STUDIO MEDIC|POLIAMBULATORIO|CENTRO MEDICO", "Salute", "Dentista e visite"],
  ["OTTICA", "Salute", "Ottica"],
  ["SANITA'|SANITA |ASLTC|\\bASL\\b|OSPEDA", "Salute", "Ticket sanitari"],

  // ───────────── SPORT (figli e personale) ─────────────
  ["F\\.C\\. SCANDICCI|Scandicci Calcio|POLISPORT|SESTESE CALCIO|UNIONE SPORTIVA|GRUPPO SPORTIVO|Sport Rotell|VIRTUS|CALCIO|\\bASD\\b", "Sport", "Società sportive e iscrizioni"],
  ["PISCIN|OLYMPUS CLUB|PALESTRA|FITNESS", "Sport", "Piscina e palestra"],
  ["DECATHLON|NENCINI SPORT|UNIVERSO SPORT|K-SPORT|FAN SHOP|CISALFA|\\bSPORT", "Sport", "Abbigliamento e attrezzatura"],

  // ───────────── TRASPORTI ─────────────
  ["ASPIT|AUTOSTRAD|FASTPAY|SAT COLLESALVETTI|TELEPASS", "Trasporti", "Pedaggi autostradali"],
  ["TAMOIL|TAMO IL|\\bENI\\b|\\bQ8\\b|\\bIP\\b|B FUEL|CARBURANT|DISTR IP|\\bADS\\b|STAZIONE DI SERVIZIO|NUOVA SIDAP|PV\\d{3,}|\\bESSO\\b|AGIP", "Trasporti", "Carburante"],
  ["EASYPARK|PARCHEGG|PARKING|GARAGE|PARCOMETR|ANM SPA|\\bPARK\\b|TANA DIREZ", "Trasporti", "Parcheggi"],
  ["TAXI|G7 CLICHY", "Trasporti", "Taxi"],
  ["A\\.T\\.A\\.C|\\bATAC\\b|AUTOLINEE|TRENITALIA|\\bITALO\\b|STAZIONE|APP TORINO|AV ITALIA|TICKET ATM|METRO", "Trasporti", "Mezzi pubblici e treni"],
  ["SOS AUTO|GOMM|OFFICINA|CARROZZ|AUTORICAMBI", "Trasporti", "Manutenzione auto"],
  ["ALLIANZ|UNIPOL|ASSICURA|GENERALI|PRIMA\\.IT", "Trasporti", "Assicurazione auto"],

  // ───────────── ABBONAMENTI E DIGITALE ─────────────
  ["NETFLIX|DISNEY|PAYPAL \\*NOW|DAZN|YOUTUBE|SPOTIFY|PRIME VIDEO", "Abbonamenti", "Streaming TV e musica"],
  ["ANTHROPIC|CLAUDE|GOOGLE|CHESS COM|APPLE\\.COM|MICROSOFT|OPENAI", "Abbonamenti", "App e software"],

  // ───────────── VIAGGI E VACANZE ─────────────
  ["HOTEL|AIRBNB|BOOKING|Pappasole spa|PENSIONE|NHOW|AVISIO PARK|SUAN PARK|BORGO PETRIOLO|RESIDENCE|SOC AGRICOLA|AGRITURISMO", "Viaggi e vacanze", "Alloggi"],
  ["SKIPASS|OBEREGG|LATEMAR|S\\.I\\.T\\. BELLAMONTE|FUNIVI|SEGGIOVIA", "Viaggi e vacanze", "Sci e impianti"],
  ["BICI PAPPASOLE|NOLEGG|CHIANTI BIKE", "Viaggi e vacanze", "Noleggi"],

  // ───────────── SHOPPING ─────────────
  ["AMAZON|AMZN", "Shopping", "Amazon"],
  ["PCCOMPONENT|EPRICE|SMARTBUGS|ZALANDO|SHEIN|TEMU|EBAY", "Shopping", "Altri acquisti online"],
  ["EURONICS|MEDIAWORLD|UNIEURO|TRONY|EXPERT", "Shopping", "Elettronica"],
  ["BOGGI|TIMBERLAND|TEZENIS|ALCOTT|CALZATURE|UPIM|GUTTERIDGE|MILLEPIEDI|\\bOVS\\b|ZARA|H&M|BENETTON|INTIMISSIMI", "Shopping", "Abbigliamento e scarpe"],
  ["TIGER STORE|ACTION|FLYING TIGER", "Shopping", "Casalinghi e varie"],

  // ───────────── CURA DELLA PERSONA ─────────────
  ["BARBER|PARRUCCH|ESTETIC|PROFUMERIA|SEPHORA|ACQUA ?& ?SAPONE", "Cura della persona", "Barbiere, parrucchiere, cosmetici"],

  // ───────────── ALIMENTARI ─────────────
  ["UNICOOP|\\bCOOP\\b|CARREFOUR|\\bCRF\\b|ESSELUNGA|CONAD|LIDL|EUROSPIN|\\bPAM\\b|IPER |ECONOMY|MISTER RISPARMIO|PENNY|\\bMD\\b|SUPERMERCATO|DITTA AZZURRO", "Alimentari", "Supermercato"],
  ["CASEIFICIO|MACELL|MASTROCICCIAIO|FORNO|PANIFIC|ORTOFRUTT|PESCHERIA|SALUMERIA", "Alimentari", "Botteghe e specialità"],

  // ───────────── TEMPO LIBERO ─────────────
  ["GARDALAND|STANDI|MIRABILANDIA|ACQUAPARK|AQUAFAN|LUNAPARK", "Tempo libero", "Parchi divertimento"],
  ["CINEMA|\\bUCI\\b|THE SPACE|TICKETONE|TICKETMASTER|TEATRO|PARIS OPERA|CONCERT", "Tempo libero", "Cinema e spettacoli"],
  ["MUSEO|MUSEI|UFFIZI|COLOSSEO|OPERA DELLA PRIMAZIALE|MOSTRA", "Tempo libero", "Musei e cultura"],
  ["5 RIONI|ASSOCIAZIONE 5|CASA DEL POPOLO|SAGRA|PRO LOCO", "Tempo libero", "Feste ed eventi"],
  ["SALA GIOCHI|NEW GAMES|LUDOTECA|BOWLING", "Tempo libero", "Giochi e svago"],
  ["GELAT|PASTICCERIA|SFOGLIAT|PANDOLCE|DOLCI|LIEVITATI", "Tempo libero", "Gelaterie e pasticcerie"],
  ["MC ?DONALD|MCDONALD|FIVE GUYS|BURGER|KEBAB|KEBAB|ICCHEBAB|ANTICO VINAIO|PIAD|FOOD COURT|AUTOGRILL|EXKI|MERCATO CENTRALE", "Tempo libero", "Fast food e street food"],
  ["RISTORA|RISTORANTE|PIZZ|OSTERIA|TRATTORIA|TAVERNA|SUSHI|SATORI|DA I DOLIO|DA I MAVO|IL MARCHESE|ALFREDO ALLA SCROFA|SOTTO PORTA|LA GIOCONDA|IL VECCHIO E IL MARE|AL FRESCO|MALGA|RIFUGIO|BAITA|FARINA & LUPPOLO|LA CARETTA|OLD STOVE|\\bPUB\\b|LOCANDA|BRACERIA|IL PIPISTRELLO|IL VECCIOLINO|MO-VIOLA|LA CAPRICCIOSA|BIANCO SPINO|BAGNO VENERE|GINESTRA ROSALIA|CASUMARO|OWAP|ECCELLENZE DELLA COSTI|SORBILLO|SERV\\.RIST|RISTORO", "Tempo libero", "Ristorazione"],
  ["\\bBAR\\b|CAFFE|CAFFÈ|\\bCAFE\\b|PEDEVILLA|LOC\\.CAPANNUCCIA|DISTRIB|VENDING|SAMARCANDA|6645 -|SEGAFREDO|COFFEE", "Tempo libero", "Bar e caffè"],

  // ───────────── RESIDUI PER TIPO DI OPERAZIONE ─────────────
  ["^SEPA Direct Debit", "Casa e utenze", "Altre domiciliazioni"],
  ["^Bonifico", "Famiglia e persone", "Altri bonifici inviati", "out"],
  ["Bollettino", "Banca e imposte", "Bollettini"],
];
