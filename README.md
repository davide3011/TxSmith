# TxSmith - Invio di Transazioni Bitcoin via RPC

## Descrizione Generale
Questo programma Python consente di inviare transazioni Bitcoin in modo semplice e sicuro tramite connessione RPC a un nodo Bitcoin Core. È pensato per utenti che desiderano comprendere e gestire le proprie transazioni senza affidarsi a wallet esterni, offrendo trasparenza e controllo totale.

## Funzionalità Principali
- Connessione diretta a un nodo Bitcoin tramite RPC
- Supporto per indirizzi legacy (1...) e witness (bc1...)
- Calcolo automatico del saldo e selezione UTXO
- Stima e personalizzazione delle fee
- Firma e invio della transazione
- Interazione guidata tramite terminale

## Dipendenze
- Python 3.7+
- [python-bitcoinrpc](https://github.com/bitcoin/bitcoin/blob/master/doc/JSON-RPC-interface.md) (`pip install python-bitcoinrpc`)

## Configurazione
1. **wallet.json**: Crea un file `wallet.json` nella stessa cartella con il seguente formato:
   ```json
   {
     "address": "<TUO_INDIRIZZO_BITCOIN>",
     "private_key_wif": "<TUA_CHIAVE_PRIVATA_WIF>"
   }
   ```
2. **Parametri RPC**: Modifica le variabili `RPC_USER`, `RPC_PASSWORD`, `RPC_HOST`, `RPC_PORT` all'inizio di `txsmith.py` secondo la configurazione del tuo nodo Bitcoin.

## Come Funziona il Programma
1. **Caricamento Wallet**: Legge indirizzo e chiave privata dal file `wallet.json`.
2. **Riconoscimento Tipo Indirizzo**: Determina se l'indirizzo è legacy o witness.
3. **Connessione RPC**: Si collega al nodo Bitcoin tramite le credenziali fornite.
4. **Recupero UTXO**: Ottiene gli UTXO disponibili per l'indirizzo mittente.
5. **Calcolo Saldo**: Somma il valore di tutti gli UTXO disponibili.
6. **Input Utente**: Chiede l'indirizzo destinatario, l'importo da inviare e il fee-rate desiderato, suggerendo un valore ottimale.
7. **Selezione UTXO**: Sceglie gli UTXO necessari per coprire importo e fee.
8. **Costruzione e Firma**: Crea la transazione grezza, la firma con la chiave privata.
9. **Riepilogo**: Mostra tutti i dettagli della transazione (importo, fee, vsize, totale speso, raw hex).
10. **Invio**: Chiede conferma all’utente prima di inviare la transazione alla rete.

## Esempio di Utilizzo
1. Avvia il programma:
   ```bash
   python txsmith.py
   ```
2. Segui le istruzioni a schermo:
   - Inserisci l’indirizzo destinatario
   - Inserisci l’importo (es. `0.001` o `25000sat`)
   - Inserisci il fee-rate desiderato (o premi invio per usare il suggerito)
   - Conferma l’invio della transazione

## Sicurezza
- **Non condividere mai la tua chiave privata!**
- Il file `wallet.json` deve essere protetto e mai pubblicato.
- Le credenziali RPC danno accesso completo al nodo: usale solo in ambienti sicuri.

## Approfondimento sul Codice
Il file `txsmith.py` è ampiamente commentato per spiegare ogni funzione e passaggio. Le sezioni principali sono:
- **Configurazione**: parametri RPC e costanti
- **Connessione**: funzione per collegarsi al nodo
- **Gestione UTXO**: funzioni per recuperare e filtrare UTXO
- **Costruzione e firma**: creazione della transazione e firma con la chiave privata
- **Interfaccia utente**: input guidati e riepilogo

Per qualsiasi dubbio, consulta i commenti nel codice o chiedi supporto alla community Bitcoin.

## LICENZA

Il codice è rilasciato sotto la licenza MIT. Consulta il file `LICENSE` per maggiori dettagli.