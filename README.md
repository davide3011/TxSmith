# Bitcoin Transaction Sender

Questo script Python consente di inviare transazioni Bitcoin dalla riga di comando, interagendo con un nodo Bitcoin Core tramite RPC.

## Prerequisiti

- Python 3.x
- Un nodo Bitcoin Core in esecuzione e configurato per accettare connessioni RPC.
- Un file `wallet.json` (o un nome simile che termina con `.json`) nella stessa directory dello script, contenente l'indirizzo del mittente e la sua chiave privata in formato WIF. Esempio:
  ```json
  {
    "address": "tuo_indirizzo_bitcoin",
    "private_key_wif": "tua_chiave_privata_wif"
  }
  ```

## Installazione delle Dipendenze

Per installare le dipendenze necessarie, esegui:

```bash
pip install -r requirements.txt
```

## Configurazione

Prima di eseguire lo script, assicurati di configurare i parametri di connessione RPC nel file `config.py`:

- `RPC_USER`: Il nome utente per la connessione RPC.
- `RPC_PASSWORD`: La password per la connessione RPC.
- `RPC_HOST`: L'host del tuo nodo Bitcoin (solitamente `127.0.0.1`).
- `RPC_PORT`: La porta RPC del tuo nodo Bitcoin (solitamente `8332` per mainnet, `18332` per testnet).

## Tipi di Transazioni Bitcoin

Bitcoin ha evoluto i formati delle sue transazioni nel tempo per migliorare l'efficienza e introdurre nuove funzionalità. Questo script supporta i due tipi di indirizzi e transazioni più comuni:

### 1. Transazioni Legacy (P2PKH - Pay-to-Public-Key-Hash)

- **Indirizzi:** Iniziano con `1` (su mainnet) o `m`/`n` (su testnet).
- **Caratteristiche:**
    - Sono il tipo di transazione originale di Bitcoin.
    - Lo script di sblocco (scriptSig) contiene la firma e la chiave pubblica, che vengono incluse direttamente nella transazione.
    - Tendono ad avere una dimensione maggiore rispetto alle transazioni SegWit, risultando in fee potenzialmente più alte a parità di complessità.
- **Come funziona lo script:**
    - Quando viene rilevato un indirizzo mittente di tipo legacy, lo script utilizza la funzione `uxto.fetch_utxos_legacy()` per recuperare gli UTXO (Unspent Transaction Outputs) associati a quell'indirizzo.
    - Per la firma, viene utilizzata la funzione `signers.sign_tx_legacy()`, che crea una firma standard per transazioni P2PKH.
    - La dimensione stimata della transazione (`config.EST_VSIZE_LEGACY`) è calibrata per questo tipo di transazione.

### 2. Transazioni SegWit v0 (P2WPKH - Pay-to-Witness-Public-Key-Hash)

- **Indirizzi:** Iniziano con `bc1q` (su mainnet) o `tb1q` (su testnet).
- **Caratteristiche:**
    - Introdotte con l'aggiornamento Segregated Witness (SegWit).
    - I dati di sblocco (la "witness") sono separati dalla struttura principale della transazione. Questo permette una stima più efficiente della dimensione della transazione (vsize) e riduce le fee.
    - Offrono una maggiore efficienza in termini di spazio sul blocco e costi di transazione.
    - Migliorano la malleabilità delle transazioni.
- **Come funziona lo script:**
    - Se l'indirizzo mittente è di tipo witness (SegWit v0 nativo), lo script chiama `uxto.fetch_utxos_witness()` per trovare gli UTXO.
    - La firma avviene tramite `signers.sign_tx_witness()`, specifica per transazioni P2WPKH.
    - La dimensione stimata (`config.EST_VSIZE_WITNESS`) è ottimizzata per le transazioni SegWit, che sono generalmente più piccole.

**Nota:** Lo script attualmente non supporta indirizzi P2SH (Pay-to-Script-Hash, che iniziano con `3` o `2`) o altri formati più recenti come Taproot (P2TR, indirizzi che iniziano con `bc1p`).

## Funzionamento del Programma (`main.py`)

Lo script `main.py` orchestra l'intero processo di creazione e invio di una transazione Bitcoin. Ecco i passaggi principali:

1.  **Caricamento Wallet e Setup Iniziale:**
    *   Viene caricato l'indirizzo del mittente (`src`) e la sua chiave privata (`wif`) dal file `.json` specificato (o rilevato automaticamente) tramite `utils.load_sender_from_json()`.
    *   Viene determinato il tipo di indirizzo del mittente (`legacy` o `witness`) usando `utils.tipo_indirizzo()`.
    *   L'utente inserisce l'indirizzo del destinatario (`dest`).
    *   Viene stabilita una connessione RPC con il nodo Bitcoin tramite `utils.connect_rpc()`.

2.  **Recupero UTXO e Selezione Parametri:**
    *   In base al tipo di indirizzo del mittente:
        *   **Legacy:** Vengono recuperati gli UTXO con `uxto.fetch_utxos_legacy()`, si imposta la dimensione stimata `config.EST_VSIZE_LEGACY` e la funzione di firma `signers.sign_tx_legacy()`.
        *   **Witness:** Vengono recuperati gli UTXO con `uxto.fetch_utxos_witness()`, si imposta la dimensione stimata `config.EST_VSIZE_WITNESS` e la funzione di firma `signers.sign_tx_witness()`.
    *   Se il tipo di indirizzo non è supportato, il programma termina.

3.  **Verifica Saldo e Acquisizione Parametri Transazione:**
    *   Viene calcolato e mostrato il saldo disponibile (`balance`) usando `utils.get_balance()`.
    *   L'utente inserisce l'importo da inviare (`amount`), validato tramite `utils.read_amount_sat()`.
    *   L'utente inserisce il fee-rate desiderato (in satoshi per virtual byte, sat/vB), con un suggerimento basato su `utils.read_fee_rate()`.

4.  **Creazione e Firma della Transazione (Processo in Due Fasi per Accuratezza Fee):**
    *   **Stima Iniziale:**
        *   Viene calcolato un importo stimato necessario (`need_est`) che include l'importo da inviare e una stima della fee basata sulla dimensione virtuale predefinita (`est_vsize`) per il tipo di transazione.
        *   Vengono selezionati gli UTXO sufficienti a coprire `need_est` tramite `uxto.pick_utxos()`.
    *   **Calcolo Fee Preciso (Bozza):**
        *   Viene creata una bozza di transazione (`draft_hex`) usando `utils.build_raw_tx()` con una fee temporaneamente impostata a 0.
        *   Questa bozza viene firmata (`draft_sign`) usando la funzione di firma appropriata (`sign_func`).
        *   La dimensione virtuale effettiva (`vsize`) della transazione firmata viene ottenuta dal nodo RPC (`rpc_conn.decoderawtransaction(draft_sign)["vsize"]`).
        *   La fee effettiva (`fee_sat`) viene calcolata moltiplicando `vsize` per il `fee_rate` scelto dall'utente.
    *   **Transazione Finale:**
        *   Viene costruita la transazione finale (`final_hex`) usando `utils.build_raw_tx()`, questa volta includendo la `fee_sat` calcolata con precisione.
        *   La transazione finale viene firmata (`signed_hex`) con `sign_func`.
        *   Vengono ricalcolati la dimensione virtuale finale (`vsize_fin`) e la fee finale (`fee_fin`) per conferma.

5.  **Riepilogo e Invio:**
    *   Viene mostrato un riepilogo dettagliato della transazione: mittente, destinatario, importo, fee-rate, vsize, fee totale e totale speso.
    *   Viene mostrata la transazione firmata in formato esadecimale (`signed_hex`).
    *   L'utente deve confermare l'invio.
    *   Se confermato, la transazione viene inviata al network Bitcoin tramite `rpc_conn.sendrawtransaction(signed_hex)` e viene stampato il TXID (Transaction ID).
    *   Altrimenti, la transazione non viene inviata.

6.  **Gestione Errori:**
    *   Il programma include blocchi `try-except` per gestire eccezioni comuni, come errori di connessione RPC (`JSONRPCException`) o altri errori generici (`Exception`).

## Struttura del Programma

-   `main.py`: Script principale che gestisce il flusso dell'applicazione.
-   `config.py`: Contiene le costanti di configurazione (parametri RPC, valori predefiniti per le fee, ecc.).
-   `utils.py`: Funzioni di utilità (connessione RPC, gestione indirizzi, calcolo saldo, lettura input utente, costruzione transazione raw).
-   `uxto.py`: Funzioni per recuperare e selezionare gli UTXO (Unspent Transaction Outputs).
-   `signers.py`: Funzioni per firmare i diversi tipi di transazioni.
-   `requirements.txt`: Elenco delle dipendenze Python.
-   `README.md`: Questo file.

## Esecuzione

Per eseguire lo script:

```bash
python main.py
```

Segui le istruzioni a schermo per inserire l'indirizzo del destinatario, l'importo e il fee-rate.

## LICENZA

Questo progetto è rilasciato sotto la Licenza MIT. Consulta il file `LICENSE` per maggiori dettagli.