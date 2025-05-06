from bitcoinrpc.authproxy import AuthServiceProxy, JSONRPCException
from decimal import Decimal, InvalidOperation
from typing import Set, Tuple, List
import sys
import json

# ===============================
#   PARAMETRI DI CONFIGURAZIONE RPC
# ===============================

RPC_USER     = "..."             # Username RPC configurato nel file bitcoin.conf
RPC_PASSWORD = "..."             # Password RPC configurata nel file bitcoin.conf
RPC_HOST     = "..."             # Indirizzo IP del nodo Bitcoin (localhost se in esecuzione locale)
RPC_PORT     = 8332              # Porta RPC (default: 8332 per mainnet, 18332 per testnet)

# Costanti per calcoli relativi alle transazioni Bitcoin
DUST_LIMIT_SAT = 546             # Limite minimo (in satoshi) per un output valido (546 sat = 0.00000546 BTC)
SAT = 100_000_000                # Numero di satoshi in 1 BTC (100 milioni)
EST_VSIZE_LEGACY = 250           # Dimensione virtuale stimata (in byte) per transazioni legacy
EST_VSIZE_WITNESS = 200          # Dimensione virtuale stimata (in byte) per transazioni witness (SegWit)
FEE_PLACEHOLDER_SAT = 500        # Valore placeholder per fee iniziale durante la stima

# ===============================
#   CONNESSIONE AL NODO BITCOIN
# ===============================
def connect_rpc() -> AuthServiceProxy:
    """Stabilisce una connessione RPC con il nodo Bitcoin utilizzando i parametri di configurazione.
    
    Returns:
        AuthServiceProxy: Un oggetto proxy che permette di chiamare i metodi RPC del nodo Bitcoin.
        
    Esempio:
        rpc = connect_rpc()
        block_count = rpc.getblockcount()  # Chiamata al metodo RPC 'getblockcount'
    """
    return AuthServiceProxy(f"http://{RPC_USER}:{RPC_PASSWORD}@{RPC_HOST}:{RPC_PORT}")

# ===============================
#   TIPO INDIRIZZO
# ===============================
def tipo_indirizzo(addr: str) -> str:
    """Determina il tipo di indirizzo Bitcoin in base al suo prefisso.
    
    Args:
        addr (str): L'indirizzo Bitcoin da analizzare.
        
    Returns:
        str: Il tipo di indirizzo identificato:
            - 'legacy': Indirizzi P2PKH (iniziano con 1, m, n)
            - 'p2sh': Indirizzi P2SH (iniziano con 3, 2)
            - 'witness': Indirizzi SegWit (iniziano con bc1, tb1, bcrt1)
            - 'unknown': Formato non riconosciuto
    """
    if addr.startswith(("1", "m", "n")):
        return "legacy"      # Indirizzi P2PKH (Pay to Public Key Hash)
    elif addr.startswith(("3", "2")):
        return "p2sh"        # Indirizzi P2SH (Pay to Script Hash)
    elif addr.startswith(("bc1", "tb1", "bcrt1")):
        return "witness"     # Indirizzi SegWit (Segregated Witness)
    else:
        return "unknown"     # Formato non riconosciuto

# ===============================
#   GESTIONE UTXO E SALDO (Legacy)
# ===============================
def fetch_utxos_legacy(rpc, address: str) -> List[dict]:
    """Recupera tutti gli UTXO (Unspent Transaction Outputs) disponibili per un indirizzo legacy.
    
    Questa funzione esegue le seguenti operazioni:
    1. Verifica la validità dell'indirizzo
    2. Ottiene lo scriptPubKey associato all'indirizzo
    3. Esegue una scansione dell'UTXO set per trovare tutti gli output non spesi
    4. Controlla anche il mempool per trovare UTXO non ancora confermati
    5. Esclude gli UTXO che sono già stati spesi in transazioni presenti nel mempool
    
    Args:
        rpc: Connessione RPC al nodo Bitcoin
        address (str): Indirizzo Bitcoin legacy (formato P2PKH)
        
    Returns:
        List[dict]: Lista di UTXO disponibili, ciascuno con i campi:
            - txid: ID della transazione
            - vout: Indice dell'output nella transazione
            - amount_sat: Importo in satoshi
            - scriptPubKey: Script di blocco in formato esadecimale
            
    Raises:
        RuntimeError: Se l'indirizzo non è valido
    """
    # Verifica la validità dell'indirizzo
    info = rpc.validateaddress(address)
    if not info.get("isvalid", False):
        raise RuntimeError("Indirizzo non valido")
    
    # Ottiene lo scriptPubKey associato all'indirizzo
    script_hex = info["scriptPubKey"]
    utxos: List[dict] = []
    
    # Scansiona l'UTXO set per trovare tutti gli output non spesi
    scan = rpc.scantxoutset("start", [{"desc": f"raw({script_hex})"}])
    for u in scan.get("unspents", []):
        utxos.append({
            "txid": u["txid"],
            "vout": u["vout"],
            "amount_sat": int(Decimal(u["amount"]) * SAT),  # Converte BTC in satoshi
            "scriptPubKey": u["scriptPubKey"],
        })
    
    # Identifica gli UTXO già spesi in transazioni presenti nel mempool
    spent_in_mempool: Set[Tuple[str, int]] = set()
    mempool_txids = rpc.getrawmempool()
    for txid in mempool_txids:
        raw = rpc.getrawtransaction(txid, True)
        for vin in raw["vin"]:
            spent_in_mempool.add((vin["txid"], vin["vout"]))
    
    # Controlla il mempool per trovare UTXO non ancora confermati
    for txid in mempool_txids:
        raw = rpc.getrawtransaction(txid, True)
        for idx, vout in enumerate(raw["vout"]):
            # Verifica che l'output appartenga all'indirizzo richiesto
            if vout["scriptPubKey"]["hex"] != script_hex:
                continue
            # Verifica che l'output non sia già stato speso
            if (txid, idx) in spent_in_mempool:
                continue
            utxos.append({
                "txid": txid,
                "vout": idx,
                "amount_sat": int(Decimal(vout["value"]) * SAT),  # Converte BTC in satoshi
                "scriptPubKey": script_hex,
            })
    return utxos

def sign_tx_legacy(rpc, raw_hex: str, utxos, wif_key: str) -> str:
    """Firma una transazione grezza utilizzando la chiave privata WIF per indirizzi legacy.
    
    Per firmare una transazione Bitcoin è necessario fornire:
    1. La transazione grezza in formato esadecimale
    2. La chiave privata in formato WIF
    3. Le informazioni sulle transazioni precedenti (prevtxs)
    
    Args:
        rpc: Connessione RPC al nodo Bitcoin
        raw_hex (str): Transazione grezza in formato esadecimale
        utxos (List[dict]): Lista degli UTXO utilizzati come input
        wif_key (str): Chiave privata in formato WIF (Wallet Import Format)
        
    Returns:
        str: Transazione firmata in formato esadecimale
        
    Raises:
        RuntimeError: Se la firma non è completa (chiave WIF errata o incompatibile)
    """
    # Prepara le informazioni sulle transazioni precedenti (prevtxs)
    # Queste informazioni sono necessarie per verificare la proprietà degli UTXO
    prevtxs = [{
        "txid": u["txid"],
        "vout": u["vout"],
        "scriptPubKey": u["scriptPubKey"],
    } for u in utxos]
    
    # Firma la transazione con la chiave privata
    signed = rpc.signrawtransactionwithkey(raw_hex, [wif_key], prevtxs)
    
    # Verifica che la firma sia completa
    if not signed.get("complete", False):
        raise RuntimeError("Firma incompleta: controlla la chiave WIF.")
    
    # Restituisce la transazione firmata in formato esadecimale
    return signed["hex"]

# ===============================
#   GESTIONE UTXO E SALDO (Witness)
# ===============================
def fetch_utxos_witness(rpc, address: str) -> List[dict]:
    """Recupera tutti gli UTXO (Unspent Transaction Outputs) disponibili per un indirizzo witness (SegWit).
    
    Questa funzione è simile a fetch_utxos_legacy, ma adattata per gli indirizzi SegWit (bc1...).
    La differenza principale è nella gestione del descriptor, che per gli indirizzi SegWit
    può essere di tipo wpkh (Witness Public Key Hash) invece di raw.
    
    Args:
        rpc: Connessione RPC al nodo Bitcoin
        address (str): Indirizzo Bitcoin witness (formato SegWit)
        
    Returns:
        List[dict]: Lista di UTXO disponibili, ciascuno con i campi:
            - txid: ID della transazione
            - vout: Indice dell'output nella transazione
            - amount_sat: Importo in satoshi
            - scriptPubKey: Script di blocco in formato esadecimale
            
    Raises:
        RuntimeError: Se l'indirizzo non è valido
    """
    # Verifica la validità dell'indirizzo
    info = rpc.validateaddress(address)
    if not info.get("isvalid", False):
        raise RuntimeError("Indirizzo non valido")
    
    # Ottiene il descriptor per l'indirizzo SegWit
    # Il descriptor è un formato che descrive come generare lo script di blocco
    desc = info.get("desc")
    if not desc:
        # Se il descriptor non è disponibile, lo costruiamo in base alle informazioni disponibili
        if "pubkey" in info:
            # Per indirizzi SegWit nativi, usiamo wpkh (Witness Public Key Hash)
            desc = f"wpkh({info['pubkey']})"
        else:
            # Fallback: usiamo lo scriptPubKey direttamente
            desc = f"raw({info['scriptPubKey']})"
    
    # Scansiona l'UTXO set per trovare tutti gli output non spesi
    utxos: List[dict] = []
    scan = rpc.scantxoutset("start", [{"desc": desc}])
    for u in scan.get("unspents", []):
        utxos.append({
            "txid": u["txid"],
            "vout": u["vout"],
            "amount_sat": int(Decimal(u["amount"]) * SAT),  # Converte BTC in satoshi
            "scriptPubKey": u["scriptPubKey"],
        })
    
    # Identifica gli UTXO già spesi in transazioni presenti nel mempool
    spent: Set[Tuple[str, int]] = set()
    mempool = rpc.getrawmempool()
    for tx in mempool:
        raw = rpc.getrawtransaction(tx, True)
        for vin in raw["vin"]:
            spent.add((vin["txid"], vin["vout"]))
    
    # Controlla il mempool per trovare UTXO non ancora confermati
    for tx in mempool:
        raw = rpc.getrawtransaction(tx, True)
        for idx, vout in enumerate(raw["vout"]):
            # Verifica che l'output appartenga all'indirizzo richiesto
            if vout["scriptPubKey"]["hex"] != info["scriptPubKey"]:
                continue
            # Verifica che l'output non sia già stato speso
            if (tx, idx) in spent:
                continue
            utxos.append({
                "txid": tx,
                "vout": idx,
                "amount_sat": int(Decimal(vout["value"]) * SAT),  # Converte BTC in satoshi
                "scriptPubKey": info["scriptPubKey"],
            })
    return utxos

def sign_tx_witness(rpc, raw_hex: str, utxos, wif_key: str) -> str:
    """Firma una transazione grezza utilizzando la chiave privata WIF per indirizzi witness (SegWit).
    
    Questa funzione è simile a sign_tx_legacy, ma con una differenza fondamentale:
    per le transazioni SegWit è necessario specificare anche l'importo di ogni input.
    Questo è parte del protocollo SegWit che migliora la sicurezza delle transazioni.
    
    Args:
        rpc: Connessione RPC al nodo Bitcoin
        raw_hex (str): Transazione grezza in formato esadecimale
        utxos (List[dict]): Lista degli UTXO utilizzati come input
        wif_key (str): Chiave privata in formato WIF (Wallet Import Format)
        
    Returns:
        str: Transazione firmata in formato esadecimale
        
    Raises:
        RuntimeError: Se la firma non è completa (chiave WIF errata o incompatibile)
    """
    # Prepara le informazioni sulle transazioni precedenti (prevtxs)
    # Per SegWit è OBBLIGATORIO includere anche l'importo di ogni input
    prevtxs = [{
        "txid": u["txid"],
        "vout": u["vout"],
        "scriptPubKey": u["scriptPubKey"],
        "amount": u["amount_sat"] / SAT,  # Converte satoshi in BTC
    } for u in utxos]
    
    # Firma la transazione con la chiave privata
    signed = rpc.signrawtransactionwithkey(raw_hex, [wif_key], prevtxs)
    
    # Verifica che la firma sia completa
    if not signed.get("complete", False):
        raise RuntimeError("Firma incompleta (controlla la chiave WIF)")
    
    # Restituisce la transazione firmata in formato esadecimale
    return signed["hex"]

# ===============================
#   FUNZIONI COMUNI
# ===============================
def get_balance(utxos: List[dict]) -> int:
    """Calcola il saldo totale disponibile sommando il valore di tutti gli UTXO.
    
    Args:
        utxos (List[dict]): Lista di UTXO disponibili
        
    Returns:
        int: Saldo totale in satoshi
    """
    return sum(u["amount_sat"] for u in utxos)

def inputs_in_mempool(rpc) -> Set[Tuple[str, int]]:
    """Identifica gli input già utilizzati in transazioni presenti nel mempool.
    
    Questa funzione è importante per evitare il double-spending, ovvero l'utilizzo
    dello stesso UTXO in più transazioni contemporaneamente.
    
    Args:
        rpc: Connessione RPC al nodo Bitcoin
        
    Returns:
        Set[Tuple[str, int]]: Set di tuple (txid, vout) che rappresentano gli input già spesi
    """
    spent: Set[Tuple[str, int]] = set()
    # Ottiene tutte le transazioni presenti nel mempool (non ancora confermate)
    for txid in rpc.getrawmempool():
        # Ottiene i dettagli della transazione
        raw = rpc.getrawtransaction(txid, True)
        # Per ogni input della transazione, aggiunge l'UTXO speso al set
        for vin in raw["vin"]:
            spent.add((vin["txid"], vin["vout"]))
    return spent

def pick_utxos(rpc, utxos: List[dict], target_sat: int):
    """Seleziona gli UTXO necessari per raggiungere l'importo target.
    
    Questa funzione implementa una strategia di selezione UTXO semplice ma efficace:
    1. Ordina gli UTXO dal più grande al più piccolo
    2. Seleziona gli UTXO in ordine fino a raggiungere o superare l'importo target
    3. Esclude gli UTXO già utilizzati in transazioni presenti nel mempool
    
    Args:
        rpc: Connessione RPC al nodo Bitcoin
        utxos (List[dict]): Lista di tutti gli UTXO disponibili
        target_sat (int): Importo target da raggiungere in satoshi (include l'importo da inviare + fee stimata)
        
    Returns:
        Tuple[List[dict], int]: Tupla contenente:
            - Lista degli UTXO selezionati
            - Importo totale in satoshi degli UTXO selezionati
            
    Raises:
        RuntimeError: Se gli UTXO disponibili non sono sufficienti a raggiungere l'importo target
    """
    # Ottiene la lista degli input già utilizzati in transazioni presenti nel mempool
    forbidden = inputs_in_mempool(rpc)
    
    # Ordina gli UTXO dal più grande al più piccolo (strategia greedy)
    ordered = sorted(utxos, key=lambda u: u["amount_sat"], reverse=True)
    
    chosen, total = [], 0
    for u in ordered:
        # Salta gli UTXO già utilizzati in transazioni pendenti
        if (u["txid"], u["vout"]) in forbidden:
            continue
        chosen.append(u)
        total += u["amount_sat"]
        # Interrompe quando raggiunge o supera l'importo target
        if total >= target_sat:
            break
    
    # Verifica che gli UTXO selezionati siano sufficienti
    if total < target_sat:
        raise RuntimeError("UTXO insufficienti.")
    
    return chosen, total

def build_raw_tx(rpc, utxos, dest_addr, amount_sat, change_addr, fee_sat):
    """Costruisce una transazione Bitcoin grezza (non firmata).
    
    Questa funzione crea una transazione con:
    1. Gli input specificati (UTXO da spendere)
    2. Un output principale per il destinatario
    3. Un output di resto (change) se necessario
    
    Args:
        rpc: Connessione RPC al nodo Bitcoin
        utxos (List[dict]): Lista degli UTXO da utilizzare come input
        dest_addr (str): Indirizzo del destinatario
        amount_sat (int): Importo da inviare in satoshi
        change_addr (str): Indirizzo per il resto (di solito lo stesso del mittente)
        fee_sat (int): Commissione in satoshi
        
    Returns:
        str: Transazione grezza in formato esadecimale
    """
    # Prepara gli input della transazione (UTXO da spendere)
    inputs = [{"txid": u["txid"], "vout": u["vout"]} for u in utxos]
    
    # Calcola il valore totale degli input
    total_in = sum(u["amount_sat"] for u in utxos)
    
    # Calcola il resto (change) sottraendo l'importo da inviare e la commissione
    change_sat = total_in - amount_sat - fee_sat
    
    # Prepara l'output principale per il destinatario (convertendo da satoshi a BTC)
    outputs = {dest_addr: amount_sat / SAT}
    
    # Aggiunge l'output di resto solo se supera il limite di polvere (dust limit)
    # Il dust limit è l'importo minimo che può essere inviato in una transazione
    if change_sat >= DUST_LIMIT_SAT:
        outputs[change_addr] = change_sat / SAT
    
    # Crea la transazione grezza
    # Gestisce le differenze tra versioni di Bitcoin Core (alcune supportano replaceable, altre no)
    try:
        return rpc.createrawtransaction(inputs, outputs, 0, {"replaceable": False})
    except JSONRPCException:
        return rpc.createrawtransaction(inputs, outputs, 0, False)

def read_amount_sat(balance_sat: int) -> int:
    while True:
        raw = input("\nInserisci l'importo da inviare (es. 0.001 oppure 25000sat): ").strip().lower()
        try:
            sat = int(raw[:-3]) if raw.endswith("sat") else int(Decimal(raw) * SAT)
        except (InvalidOperation, ValueError):
            print("Formato non valido"); continue
        if sat <= 0:
            print("Importo deve essere positivo")
        elif sat > balance_sat:
            print("Saldo insufficiente")
        else:
            return sat

def get_suggested_fee_rate(rpc, conf_target: int = 6) -> float:
    """
    Richiama estimatesmartfee(conf_target) e converte il risultato in sat/vB.
    Se non disponibile, ritorna 2.0 sat/vB come fallback.
    """
    try:
        # RPC: stima in BTC per kvB (virtual size)
        res = rpc.estimatesmartfee(conf_target)
        fee_btc_per_kb = res.get("feerate")
        if fee_btc_per_kb is not None:
            # 1 BTC = 1e8 satoshi; 1 kvB = 1000 vB
            return fee_btc_per_kb * 1e8 / 1000
    except JSONRPCException:
        pass
    return 2.0

def read_fee_rate(rpc=None, conf_target: int = 6) -> float:
    """
    Chiede all'utente di inserire il fee-rate e suggerisce un valore dinamico
    basato sulla stima per conf_target blocchi.
    """
    default_rate = 2.0  # fallback
    if rpc is not None:
        est = get_suggested_fee_rate(rpc, conf_target)
        default_rate = est if est is not None else default_rate

    print(f"\nSuggerimento: il fee-rate stimato per conferma in "
          f"{conf_target} blocchi è ~{default_rate:.2f} sat/vB ")
    while True:
        raw = input(f"\nInserisci il Fee-rate desiderato (sat/vB, ≥1) "
                    f"[default: {default_rate:.2f}]: ").strip()
        if not raw:
            return default_rate
        try:
            rate = float(raw.replace(",", "."))
            if rate < 1:
                print("Il network rifiuta fee-rate < 1 sat/vB")
                continue
            if rate > 1000:
                print("Fee-rate > 1000 sat/vB: controlla il valore")
                continue
            return rate
        except ValueError:
            print("Numero non valido, riprova")

def load_sender_from_json(json_path: str):
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        src = data.get("address", "").strip()
        wif = data.get("private_key_wif", "").strip()
        if not src or not wif:
            raise ValueError("Il file JSON deve contenere 'address' e 'wif'.")
        return src, wif
    except Exception as e:
        print(f"Errore nella lettura del file JSON: {e}")
        sys.exit(1)

# ===============================
#   FLUSSO PRINCIPALE UNIFICATO
# ===============================
def main():
    """Funzione principale che gestisce l'intero flusso di creazione e invio di una transazione Bitcoin."""
    try:
        # 1. Caricamento dell'indirizzo e della chiave privata
        json_path = "wallet.json"  # Nome fisso del file JSON nella stessa directory
        src, wif = load_sender_from_json(json_path)
        
        # 2. Identificazione del tipo di indirizzo
        tipo = tipo_indirizzo(src)
        if tipo == "unknown":
            print("Tipo di indirizzo non riconosciuto.")
            return
        
        # Acquisizione dell'indirizzo destinatario
        dest = input("\nInserisci l'indirizzo destinatario: ").strip()
        
        # 3. Connessione RPC (solo dopo aver raccolto i parametri iniziali)
        rpc = connect_rpc()
        print("Connessione RPC OK - blocchi:", rpc.getblockcount())
        
        # 4. Recupero degli UTXO in base al tipo di indirizzo
        if tipo == "legacy":
            utxos = fetch_utxos_legacy(rpc, src)
            est_vsize = EST_VSIZE_LEGACY  # Dimensione stimata per transazioni legacy
            sign_func = sign_tx_legacy    # Funzione di firma per indirizzi legacy
        elif tipo == "witness":
            utxos = fetch_utxos_witness(rpc, src)
            est_vsize = EST_VSIZE_WITNESS  # Dimensione stimata per transazioni witness
            sign_func = sign_tx_witness     # Funzione di firma per indirizzi witness
        else:
            print("Solo indirizzi legacy (1...) o witness (bc1...) supportati.")
            return
        
        # 5. Calcolo del saldo disponibile
        balance = get_balance(utxos)
        print(f"\nSaldo: {balance} sat ({balance/SAT:.8f} BTC)")
        if balance == 0:
            print("Nessuna UTXO disponibile.")
            return
        
        # 6. Acquisizione dei parametri della transazione
        amount = read_amount_sat(balance)  # Importo da inviare
        fee_rate = read_fee_rate(rpc, conf_target=6)  # Fee-rate in sat/vB
        
        # 7. Stima iniziale della fee e selezione degli UTXO
        need_est = amount + int(round(fee_rate * est_vsize))  # Importo + fee stimata
        chosen, _ = pick_utxos(rpc, utxos, need_est)  # Selezione UTXO
        
        # 8. Creazione di una bozza di transazione per stimare la dimensione
        # Inizialmente impostiamo fee_sat=0 per ottenere una bozza
        draft_hex = build_raw_tx(rpc, chosen, dest, amount, src, 0)
        draft_sign = sign_func(rpc, draft_hex, chosen, wif)
        
        # 9. Calcolo preciso della fee basato sulla dimensione effettiva
        vsize = rpc.decoderawtransaction(draft_sign)["vsize"]  # Dimensione virtuale in byte
        fee_sat = int(round(vsize * fee_rate))  # Fee = dimensione * fee-rate
        
        # 10. Creazione della transazione finale con la fee corretta
        final_hex = build_raw_tx(rpc, chosen, dest, amount, src, fee_sat)
        
        # 11. Firma della transazione finale
        signed_hex = sign_func(rpc, final_hex, chosen, wif)
        
        # Calcolo finale della dimensione e della fee effettiva
        vsize_fin = rpc.decoderawtransaction(signed_hex)["vsize"]
        fee_fin = int(round(vsize_fin * fee_rate))
        total_sat = amount + fee_fin  # Importo totale speso
        
        # 12. Visualizzazione del riepilogo della transazione
        print("\n──── RIEPILOGO ────")
        print(f"Mittente     : {src}")
        print(f"Destinatario : {dest}")
        print(f"Importo      : {amount} sat  ({amount / SAT:.8f} BTC)")
        print(f"Fee-rate     : {fee_rate} sat/vB")
        print(f"vsize        : {vsize_fin} vB")
        print(f"Fee totale   : {fee_fin} sat")
        print(f"Totale spesa : {total_sat} sat  ({total_sat / SAT:.8f} BTC)\n")
        print("Raw TX FIRMATA:\n", signed_hex)
        
        # 13. Invio della transazione (previa conferma dell'utente)
        if input("\nInviare la transazione? [s/N] ").lower().startswith("s"):
            txid = rpc.sendrawtransaction(signed_hex)  # Invia la transazione alla rete
            print("Transazione inviata!  TXID:", txid)
        else:
            print("Transazione NON inviata.")
    
    # Gestione delle eccezioni
    except JSONRPCException as e:
        print("Errore RPC:", e)  # Errori specifici del protocollo RPC
    except Exception as e:
        print("Errore:", e)  # Altri errori generici

if __name__ == "__main__":
    main()
