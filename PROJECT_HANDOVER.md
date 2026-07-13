# Project Handover: Coyote ISS Tracker

Questo documento riassume lo stato del progetto **Coyote ISS** per consentire un trasferimento rapido sul nuovo computer e permettere a Antigravity (o a qualsiasi altra istanza del modello) di riprendere il lavoro immediatamente.

---

## 📋 Descrizione del Progetto

Il progetto **Coyote ISS** è un sistema di tracciamento attivo per la Stazione Spaziale Internazionale (ISS) composto da due moduli principali:

1. **`Coyote_ISS_Precalc.py` (Offline Precalculator)**
   - Un'applicazione grafica scritta in Python (Tkinter).
   - Calcola i passaggi futuri della ISS basandosi su dati TLE (scaricati da Celestrak o letti in locale).
   - Genera traiettorie e file di puntamento.
   - Sincronizza l'orario di sistema con server NTP per garantire precisione al millisecondo.
   - Dipendenze principali: `skyfield`, `numpy`, `sgp4`.

2. **`SharpISS_Follower.py` (SharpCap Follower)**
   - Script scritto in IronPython progettato per essere eseguito all'interno di **SharpCap**.
   - Importa namespace .NET (`System.Windows.Forms`, `System.Drawing`) per creare un'interfaccia grafica.
   - Si connette alle montature ASCOM e alla telecamera per guidare attivamente l'inseguimento della ISS basandosi sulla traiettoria precalcolata.
   - Permette calibrazioni in tempo reale e controlli rapidi tramite tastiera (esposizione, guadagno, offset di puntamento).

---

## 📁 Struttura dei File del Progetto

La directory principale `Coyote_ISS` contiene:
* **`Coyote_ISS_Precalc.py`**: Interfaccia di pre-calcolo e download TLE.
* **`SharpISS_Follower.py`**: Script di controllo montatura per SharpCap.
* **`config.json`**: File di configurazione contenente le coordinate dell'osservatore (latitudine, longitudine, elevazione) e l'altezza minima di intercettazione.
* **`iss_tle.txt`**: Cache locale dei Two-Line Elements della ISS.
* **`hip_main.dat`**: Catalogo stellare Hipparcos (utilizzato per allineamento/calibrazione).
* **`coyote_iss_icon.png`**: Icona dell'applicazione precalculator.

---

## ⚙️ Dipendenze e Requisiti sul Nuovo PC

Per eseguire correttamente l'ambiente sul nuovo computer, assicurati di installare:
1. **Python 3.x** installato e aggiunto al PATH di sistema.
2. Le librerie esterne necessarie per il precalculator:
   ```bash
   pip install numpy skyfield sgp4 requests
   ```
   *(Nota: `Coyote_ISS_Precalc.py` tenta di auto-installarle al primo avvio se mancanti).*
3. **SharpCap** installato sul PC per far girare lo script `SharpISS_Follower.py` tramite la sua console IronPython.
4. Driver **ASCOM** installati e configurati per la montatura astronomica utilizzata.

---

## 🔄 Come Riprendere la Chat di Antigravity sul Nuovo Computer

Per non perdere la cronologia delle nostre conversazioni e gli artifact su questo progetto:

1. **Trova la cartella della chat sul PC attuale:**
   Vai al percorso:
   ```text
   C:\Users\user\.gemini\antigravity\brain\30e79f8c-7128-4db2-9b60-a5b9ac8d048f
   ```
2. **Copia la cartella sulla chiavetta.**
3. **Incollala sul nuovo computer** sotto la stessa struttura di cartelle del tuo utente:
   ```text
   C:\Users\<TuoNuovoUtente>\.gemini\antigravity\brain\30e79f8c-7128-4db2-9b60-a5b9ac8d048f
   ```
4. All'avvio di Antigravity sul nuovo computer, il sistema rileverà la sessione e potrai continuare la chat senza perdere il contesto storico.
