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
2) C'è una piccola mappa con il percorso che mostra le stelle principali: è abbastanza importante individuare un punto di sincronizzazione della montatura vicino alla partenza in modo di aver certezza e precisione almeno nella partenza dell'inseguimento. Quindi se non fosse possibile fare il plate solving magari è comodo capire se ci sono stelle vicine.
   
script SharpCap: 
Prerequisito: Sharpcap con telecamera e montatura collegata GOTO decente. Credo serva la licenza Pro a pagamento per fare il plate solving comunque costa una fesseria e da delle funzionalità eccellenti quindi
compratela.
C'è un problema di fondo da combattere: pur non essendo di per se indispensabile il plate solving ti darebbe la certezza della posizione della montatura che è fondamentale però la ISS in piena notte potrebbe essere oscurata dal cono d'ombra della Terra quindi spesso ci si apposta con cielo non ancora pefettamente scuro. Di più: lavorando con focali lunghe anche avendo telecamere con sensore generoso spesso il plate solving risulta complesso se non impossibile: del resto questa cosa non ha soluzioni semplici quindi: fatevene una ragione.
Tuttavia qualora il plate solving sia possibile lo script offre 2 strumenti: uno è di lanciare il plate solving con sincronizzazione della montatura così che si possa avere una certezza del posizionamento almeno in una posizione di transito. L'altro strumento è dopo lo spostamento nei 3 punti (start culmine stop) si accende un tasto correzione: premendo il tasto correzione corrispondente il programma tenta di risolvere il cielo senza sincronizzare la montatura ma capendo di quanto è sbagliato il posizionamento: così facendo se sono disponibili le 3 correzioni si può disegnare una traiettoria che tenga conto di queste correzioni 
