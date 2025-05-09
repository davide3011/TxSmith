from typing import List

import config
import utils 
from bitcoinrpc.authproxy import AuthServiceProxy


def sign_tx_legacy(raw_hex: str, utxos, wif_key: str) -> str:
    rpc_conn = utils.connect_rpc() # Modificato da rpc a utils
    prevtxs = [{
        "txid": u["txid"],
        "vout": u["vout"],
        "scriptPubKey": u["scriptPubKey"],
    } for u in utxos]
    signed = rpc_conn.signrawtransactionwithkey(raw_hex, [wif_key], prevtxs)
    if not signed.get("complete", False):
        raise RuntimeError("Firma incompleta: controlla la chiave WIF.")
    return signed["hex"]

def sign_tx_witness(raw_hex: str, utxos, wif_key: str) -> str:
    rpc_conn = utils.connect_rpc() # Modificato da rpc a utils
    prevtxs = [{
        "txid": u["txid"],
        "vout": u["vout"],
        "scriptPubKey": u["scriptPubKey"],
        "amount": u["amount_sat"] / config.SAT,  # Converte satoshi in BTC
    } for u in utxos]
    
    signed = rpc_conn.signrawtransactionwithkey(raw_hex, [wif_key], prevtxs)
    if not signed.get("complete", False):
        raise RuntimeError("Firma incompleta (controlla la chiave WIF)")
    return signed["hex"]

def sign_tx_taproot(raw_hex: str, utxos: List[dict], wif_key: str) -> str:
    rpc_conn = utils.connect_rpc() # Modificato da rpc a utils
    prevtxs = [{
        "txid":         u["txid"],
        "vout":         u["vout"],
        "scriptPubKey": u["scriptPubKey"],
        "amount":       u["amount_sat"] / config.SAT,
    } for u in utxos]
    signed = rpc_conn.signrawtransactionwithkey(raw_hex, [wif_key], prevtxs)
    if not signed.get("complete", False):
        raise RuntimeError("Firma incompleta P2TR: controlla WIF o versione Core.")
    return signed["hex"]