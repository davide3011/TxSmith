from decimal import Decimal, InvalidOperation
from typing import Set, Tuple, List
import sys, json, os

import config
import uxto
from bitcoinrpc.authproxy import JSONRPCException, AuthServiceProxy


def tipo_indirizzo(addr: str) -> str:
    """Determina il tipo di indirizzo Bitcoin in base al suo prefisso."""
    if addr.startswith(("1", "m", "n")): return "legacy"                # P2PKH
    elif addr.startswith(("3", "2")):    return "p2sh"                  # P2SH
    elif addr.startswith(("bc1q","tb1q","bcrt1q")): return "witness"    # SegWit v0
    else: return "unknown"

def get_balance(utxos: List[dict]) -> int:
    """Calcola il saldo totale disponibile sommando il valore di tutti gli UTXO non spesi, escludendo quelli già spesi nel mempool."""
    forbidden = uxto.inputs_in_mempool()  # Modificato per usare input.inputs_in_mempool
    return sum(u["amount_sat"] for u in utxos if (u["txid"], u["vout"]) not in forbidden)

def connect_rpc() -> AuthServiceProxy:
    """Stabilisce una connessione RPC con il nodo Bitcoin."""
    return AuthServiceProxy(f"http://{config.RPC_USER}:{config.RPC_PASSWORD}@{config.RPC_HOST}:{config.RPC_PORT}")

def build_raw_tx(utxos, dest_addr, amount_sat, change_addr, fee_sat):
    rpc_conn = connect_rpc()
    inputs = [{"txid": u["txid"], "vout": u["vout"]} for u in utxos]
    total_in = sum(u["amount_sat"] for u in utxos)
    change_sat = total_in - amount_sat - fee_sat
    
    outputs = {dest_addr: amount_sat / config.SAT}
    if change_sat >= config.DUST_LIMIT_SAT:
        outputs[change_addr] = change_sat / config.SAT
    
    try:
        return rpc_conn.createrawtransaction(inputs, outputs, 0, {"replaceable": False})
    except JSONRPCException:
        return rpc_conn.createrawtransaction(inputs, outputs, 0, False)

def read_amount_sat(balance_sat: int) -> int:
    """Legge l'importo da inviare dall'utente."""
    while True:
        raw = input("\nInserisci l'importo da inviare (es. 0.001 oppure 25000sat): ").strip().lower()
        try:
            sat = int(raw[:-3]) if raw.endswith("sat") else int(Decimal(raw) * config.SAT)
            if sat <= 0: print("Importo deve essere positivo"); continue
            if sat > balance_sat: print("Saldo insufficiente"); continue
            return sat
        except (InvalidOperation, ValueError): print("Formato non valido")

def get_suggested_fee_rate(conf_target: int = 6) -> Decimal:
    """Ottiene il fee-rate suggerito dal nodo."""
    rpc_conn = connect_rpc()
    try:
        res = rpc_conn.estimatesmartfee(conf_target)
        fee_btc_per_kb = res.get("feerate")
        if fee_btc_per_kb is not None:
            return Decimal(fee_btc_per_kb) * Decimal('100000000') / Decimal('1000')
    except JSONRPCException: pass
    return Decimal("2.0")

def read_fee_rate(conf_target: int = 6) -> Decimal:
    default_rate = get_suggested_fee_rate(conf_target)
    print(f"\nSuggerimento: il fee-rate stimato per conferma in {conf_target} blocchi è ~{default_rate:.2f} sat/vB ")
    while True:
        raw = input(f"\nInserisci il Fee-rate desiderato (sat/vB, ≥1) [default: {default_rate:.2f}]: ").strip()
        if not raw: return default_rate
        try:
            rate = Decimal(raw.replace(",", "."))
            if rate < 1: print("Il network rifiuta fee-rate < 1 sat/vB"); continue
            if rate > 1000: print("Fee-rate > 1000 sat/vB: controlla il valore"); continue
            return rate
        except ValueError: print("Numero non valido, riprova")

def load_sender_from_json():
    """Carica indirizzo e chiave privata da file JSON, cercando automaticamente i file .json."""
    json_files = [f for f in os.listdir('.') if f.endswith('.json')]

    if not json_files:
        print("Nessun file wallet .json trovato nella directory corrente.")
        sys.exit(1)

    json_path = ""
    if len(json_files) == 1:
        json_path = json_files[0]
        print(f"Trovato wallet: {json_path}")
    else:
        print("Trovati più file wallet .json:")
        for i, f_name in enumerate(json_files):
            print(f"  {i+1}. {f_name}")
        while True:
            try:
                choice = input(f"Scegli un wallet (1-{len(json_files)}): ")
                choice_idx = int(choice) - 1
                if 0 <= choice_idx < len(json_files):
                    json_path = json_files[choice_idx]
                    break
                else:
                    print("Scelta non valida.")
            except ValueError:
                print("Inserisci un numero.")
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        src, wif = data.get("address", "").strip(), data.get("private_key_wif", "").strip()
        if not src or not wif: raise ValueError("Il file JSON deve contenere 'address' e 'private_key_wif'.")
        return src, wif
    except FileNotFoundError:
        print(f"File wallet '{json_path}' non trovato.")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Errore nel decodificare il file JSON: '{json_path}'. Assicurati che sia formattato correttamente.")
        sys.exit(1)
    except ValueError as e:
        print(f"Errore nel contenuto del file JSON '{json_path}': {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Errore imprevisto durante il caricamento del wallet '{json_path}': {e}"); sys.exit(1)