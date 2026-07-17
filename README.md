# Coyote_ISS

*WORK IN PROGRESS*

### Avvertenze importanti
Perché questo software ha come mascotte **Willy il Coyote**? Perché il Coyote non cattura mai Bip Bip e si schianta malamente pressoché sempre. 
Questo dovrebbe essere di monito verso chi vuole usare questo software: se non cattura nulla oppure il telescopio si schianta sul treppiede o da qualche parte, sono cazzi vostri: io vi ho avvisato.

Comunque, se siete anche voi dei temerari Coyote e state attenti al movimento regolando magari le frizioni del telescopio in modo da non far danni: questo è il software che fa per voi.

---

### Architettura del Progetto
Il software è diviso in 2 parti principali:
1. **Programma di precalcolo (`Coyote_ISS_Precalc.py`):** Calcola il percorso del passaggio della ISS e descrive la traiettoria esportando i dati in un file `.json`.
2. **Script SharpCap (`SharpISS_Follower.py`):** Carica la traiettoria generata dal precalcolatore, registra l'immagine dalla telecamera e controlla la montatura automaticamente per inseguire la ISS.

---

### 1. Il Programma di Precalcolo
Il programma di precalcolo è minimale. Ci sono in particolare due aspetti da evidenziare:
* **Sincronizzazione Oraria NTP:** È presente la possibilità di sincronizzare l'ora tramite i server NTP, poiché l'orario del PC (usato poi nello script SharpCap) è di vitale importanza. *Nota: questa sincronizzazione richiede l'esecuzione del programma come amministratore.*
* **Mappa del Percorso Celeste:** Mostra una piccola mappa radar/polare con il percorso della ISS e le stelle principali. È importante individuare un punto di sincronizzazione della montatura vicino alla partenza in modo da avere certezza e precisione all'avvio dell'inseguimento.

---

### 2. Lo Script SharpCap
* **Prerequisiti:** SharpCap installato con telecamera attiva e montatura ASCOM GOTO compatibile. *Nota: è necessaria la licenza Pro a pagamento di SharpCap per abilitare il Plate Solving.*
* **Puntamenti e Allineamento passivo:** Il Plate Solving permette di rilevare passivamente la posizione esatta della montatura per correggere dinamicamente la traiettoria di inseguimento, senza necessità di effettuare il `Sync` ASCOM della montatura (in modo da non corrompere i modelli di allineamento a più stelle impostati sulla pulsantiera o sul driver).
