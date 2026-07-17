WORK IN PROGRESS.

Perchè questo software ha come mascotte Willy il Coyote? Perchè il Coyote non cattura mai Bip Bip e si schianta malamente pressochè sempre.
Questo dovrebbe essere di monito verso chi vuole usare questo software: se non cattura nulla oppure il telescopio si schianta sul treppiede o da qualche parte sono cazzi vostri: io vi ho avvisato.

Comunque se siete anche voi dei temerari Coyote e state attenti al movimento regolando magari le frizioni del telescopio in modo da non far danni: questo è il software.

Nell'intenzione questo software è diviso in 2 parti principali: un programma di precalcolo calcola il percorso del passaggio della ISS e descrive la traiettoria in un file .json
Un secondo script pensato per Sharpcap carica la traiettoria, registra l'immagine dalla telecamera e muove la montatura automaticamente per catturare l'immagine della ISS.

Il programma di precalcolo è banale e non merita descrizione se non per l'eventuale installazione/lancio: eventualmente per annoiarvi vedo se l'AI mi scrive qualcosa in merito.
Forse ci sono solo 2 cose particolari:
1) ho inserito la possibilità di sincronizzare l'ora tramite i server ntp perchè l'orario del pc, poi usato nello script Sharpcap è letteralmente vitale. Però questa sincronizzazione richiede 
   di aver lanciato il programma come amministratore.
2) C'è una piccola mappa con il percorso che mostra le stelle principali: è abbastanza importante individuare un punto di sincronizzazione della montatura vicino alla partenza in modo di aver certezza
   e precisione almeno nella partenza dell'inseguimento.
   
script SharpCap: 
Prerequisito: Sharpcap con telecamera e montatura collegata GOTO decente. Credo serva la licenza Pro a pagamento per fare il plate solving comunque costa una fesseria e da delle funzionalità eccellenti quindi
compratela.
C'è un problema di fondo da combattere: pur non essendo di per se indispensabile il plate solving ti darebbe la certezza della posizione della montatura che è fondamentale però la ISS in piena notte potrebbe essere 
oscurata dal cono d'ombra della Terra, inoltre un telescopio per vederla decentemente dovrebbe avere una focale lunga e l'inizio/fine del percorso è spesso basso sull'orizzonte: questo rende il plate solving spesso 
problematico perchè non si vedono stelle, è ancora chiaro, poco campo eccetera. ACME non ci da soluzioni facili a questa cosa.

la prima cosa da fare è caricare il tracciato salvato dal programma di precalcolo. A lato viene fuori una sorta di "Radar" che mostra il percorso ed una barra che vi dirà dove è la montatura.
ci sono dei parametri di esposizione e gain che vengono "forzati" durante l'uso dello script per il plate solving e per la ISS. 
Consiglio di inquadrare tipo Venere/Giove che può avere luminosità paragonabili e fare delle considerazioni.
Pongo l'attenzione su un problema non risolto e che non risolverò perchè non so come fare: la comunicazione continua (verosimilmente via porta seriale) rallenta l'acquisizione della telecamera e siccome
sicuramente avete delle telecamere con sensori larghi potrebbe essere che si riempia il buffer: consiglio di mettere il bin a 2. Parentesi ci impiega una vita a scaricarlo su disco. 

C'è un bottone che fa il plate solve ed il sync alla posizione corrente del telescopio. La mappa del programma di precalcolo avrebbe questo intento: individuare delle zone di cielo prossime alla partenza
e fare li un bel plate solve con il sync alla montatura.
Ci sono però anche 3 tasti che permettono di spostare la montatura alle coordinate di partenza, culmine ed arrivo e sotto, una volta raggiunte queste quote, c'è un tasto relativo di "correzione".
premendo il tasto correzione in tutti e 3 i punti il software fa un plate solve senza il sync: potrebbe essere che il punto di partenza sia buono ma magari il treppiede è un po' storto e quindi 
la traiettoria viene disattesa. Il plate solve sui 3 punti ci dovrebbe permettere di calcolare di quanto è sbagliato il movimento e attuare una correzione della traiettoria.

Sotto ci sono 2 bottoni: ARMA fa partire effettivamente il tutto attendendo l'orario del passaggio. SIMULA fa partire tutto come ARMA ma senza attendere, per fare una prova reale del movimento che andrà a fare la montatura. 
NB: ARMA e SIMULA muovono direttamente il motore della montatura mentre i bottoni dei 3 spostamenti GOTO comandano in effetti un GOTO alle coordinate (RA DEC/ ALT AZ) quindi è la montatura che decide da che parte muoversi in base a considerazioni sul meridian flip, antiattorcigliamenti vari e recuperi dei giochi.


