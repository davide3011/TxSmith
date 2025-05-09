from decimal import Decimal
from typing import List, Set, Tuple

import config
import utils # Modificato da rpc a utils
from bitcoinrpc.authproxy import JSONRPCException

def fetch_utxos_legacy(address: str) -> List[dict]:
    rpc_conn = utils.connect_rpc() # Modificato da rpc a utils
    info = rpc_conn.validateaddress(address)
    if not info.get("isvalid", False): raise RuntimeError("Indirizzo non valido")
    
    script_hex = info["scriptPubKey"]
    utxos: List[dict] = []
    
    # Scansiona UTXO set per output non spesi
    scan = rpc_conn.scantxoutset("start", [{"desc": f"raw({script_hex})"}])
    for u in scan.get("unspents", []):
        utxos.append({
            "txid": u["txid"], "vout": u["vout"],
            "amount_sat": int(Decimal(u["amount"]) * Decimal(config.SAT)),
            "scriptPubKey": u["scriptPubKey"],
        })
    
    # Identifica UTXO già spesi nel mempool
    spent_in_mempool = set((vin["txid"], vin["vout"]) 
                          for txid in rpc_conn.getrawmempool() 
                          for vin in rpc_conn.getrawtransaction(txid, True)["vin"])
    
    # Controlla UTXO non ancora confermati nel mempool
    # NOTA: rpc_conn è già definito come utils.connect_rpc() sopra
    for txid in rpc_conn.getrawmempool():
        raw = rpc_conn.getrawtransaction(txid, True)
        for idx, vout in enumerate(raw["vout"]):
            if vout["scriptPubKey"]["hex"] != script_hex or (txid, idx) in spent_in_mempool:
                continue
            utxos.append({
                "txid": txid, "vout": idx,
                "amount_sat": int(Decimal(vout["value"]) * Decimal(config.SAT)),
                "scriptPubKey": script_hex,
            })
    return utxos

def fetch_utxos_witness(address: str) -> List[dict]:
    rpc_conn = utils.connect_rpc() # Modificato da rpc a utils
    info = rpc_conn.validateaddress(address)
    if not info.get("isvalid", False): raise RuntimeError("Indirizzo non valido")
    
    # Ottiene il descriptor per l'indirizzo SegWit
    desc = info.get("desc")
    if not desc:
        desc = f"wpkh({info['pubkey']})" if "pubkey" in info else f"raw({info['scriptPubKey']})"
    
    # Scansiona UTXO set per output non spesi
    utxos: List[dict] = []
    scan = rpc_conn.scantxoutset("start", [{"desc": desc}])
    for u in scan.get("unspents", []):
        utxos.append({
            "txid": u["txid"], "vout": u["vout"],
            "amount_sat": int(Decimal(u["amount"]) * Decimal(config.SAT)),
            "scriptPubKey": u["scriptPubKey"],
        })
    
    # Identifica UTXO già spesi nel mempool
    spent = set((vin["txid"], vin["vout"]) 
               for tx in rpc_conn.getrawmempool() 
               for vin in rpc_conn.getrawtransaction(tx, True)["vin"])
    
    # Controlla UTXO non ancora confermati nel mempool
    # NOTA: rpc_conn è già definito come utils.connect_rpc() sopra
    for tx in rpc_conn.getrawmempool():
        raw = rpc_conn.getrawtransaction(tx, True)
        for idx, vout in enumerate(raw["vout"]):
            if vout["scriptPubKey"]["hex"] != info["scriptPubKey"] or (tx, idx) in spent:
                continue
            utxos.append({
                "txid": tx, "vout": idx,
                "amount_sat": int(Decimal(vout["value"]) * Decimal(config.SAT)),
                "scriptPubKey": info["scriptPubKey"],
            })
    return utxos

def inputs_in_mempool() -> Set[Tuple[str, int]]:
    """Identifica gli input già utilizzati in transazioni presenti nel mempool."""
    rpc_conn = utils.connect_rpc() # Modificato da rpc a utils
    spent: Set[Tuple[str, int]] = set()
    for txid in rpc_conn.getrawmempool():
        raw = rpc_conn.getrawtransaction(txid, True)
        for vin in raw["vin"]:
            spent.add((vin["txid"], vin["vout"]))
    return spent

def pick_utxos(utxos: List[dict], target_sat: int):
    """Seleziona gli UTXO necessari per raggiungere l'importo target."""
    forbidden = inputs_in_mempool() # Chiama la funzione locale
    ordered = sorted(utxos, key=lambda u: u["amount_sat"], reverse=True)
    
    chosen, total = [], 0
    for u in ordered:
        if (u["txid"], u["vout"]) in forbidden: continue
        chosen.append(u)
        total += u["amount_sat"]
        if total >= target_sat: break
    
    if total < target_sat: raise RuntimeError("UTXO insufficienti.")
    return chosen, total