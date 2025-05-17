"""Tx legacy P2PK → P2PK modulare
=================================================
• Costruisce e (opzionalmente) invia una transazione legacy con input P2PK
  e output P2PK (resto P2PK).
• Tutte le parti riutilizzabili sono raggruppate per sezione.
• Basta sostituire le funzioni nella sezione SCRIPT_TYPES per ottenere
  qualsiasi combinazione legacy → effort minimo in futuro.
"""
# ---------------------------------------------------------------------------
# CONFIG – parametri RPC / costanti globali
# ---------------------------------------------------------------------------

SAT          = 100_000_000          # 1 BTC in satoshi
RPC_USER     = "..."
RPC_PASSWORD = "..."
RPC_HOST     = "127.0.0.1"
RPC_PORT     = 48332
WALLET_JSON  = "wallet.json"        # file con chiave, pubkey, address

# ---------------------------------------------------------------------------
# UTILS – funzioni comuni
# ---------------------------------------------------------------------------

import struct, json, math, sys, base58
import hashlib
from ecdsa import SigningKey, SECP256k1
from bitcoinrpc.authproxy import AuthServiceProxy, JSONRPCException

def sha256d(b: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(b).digest()).digest()

def vi(n: int) -> bytes:                # VarInt encoder
    if n < 0xfd:        return n.to_bytes(1, "little")
    if n <= 0xffff:     return b"\xfd"+n.to_bytes(2,"little")
    if n <= 0xffffffff: return b"\xfe"+n.to_bytes(4,"little")
    return b"\xff"+n.to_bytes(8,"little")

def der_low_s(r: int, s: int) -> bytes: # firma DER normalizzata BIP-62
    n = SECP256k1.order
    if s > n//2: s = n - s
    rb = r.to_bytes((r.bit_length()+7)//8, "big")
    sb = s.to_bytes((s.bit_length()+7)//8, "big")
    if rb[0] & 0x80: rb = b"\x00"+rb
    if sb[0] & 0x80: sb = b"\x00"+sb
    return (b"\x30"+bytes([len(rb)+len(sb)+4]) +
            b"\x02"+bytes([len(rb)])+rb +
            b"\x02"+bytes([len(sb)])+sb)

def little(h: str) -> bytes:           # hex→bytes + LE
    return bytes.fromhex(h)[::-1]

# ---------------------------------------------------------------------------
# RPC / wallet helpers
# ---------------------------------------------------------------------------

rpc = lambda: AuthServiceProxy(f"http://{RPC_USER}:{RPC_PASSWORD}@{RPC_HOST}:{RPC_PORT}")

def load_wallet(path=WALLET_JSON):
    w = json.load(open(path, "r"))
    priv = bytes.fromhex(w["private_key_hex"])
    pub  = bytes.fromhex(w["public_key_hex"])
    
    # Per P2PK non abbiamo bisogno di addr e h160, quindi li impostiamo a None
    addr = None
    h160 = None
    
    sk = SigningKey.from_string(priv, curve=SECP256k1)
    return sk, pub, addr, h160

# ---------------------------------------------------------------------------
# SCRIPT_TYPES – implementazioni di INPUT / OUTPUT legacy
# ---------------------------------------------------------------------------

# Ogni “tipo” espone due funzioni:
#   • build_spk(data)  – bytes scriptPubKey
#   • sign_input(z, sk, pub, spk_prev)  – bytes scriptSig

# ---- P2PKH ---------------------------------------------------------------

def spk_p2pkh(pubkey_hash: bytes) -> bytes:
    return b"\x76\xa9\x14"+pubkey_hash+b"\x88\xac"

def sig_p2pkh(z: bytes, sk, pub: bytes, *_):
    r,s = sk.sign_digest_deterministic(z, sigencode=lambda r,s,_:(r,s))
    sig = der_low_s(r,s)+b"\x01"     # SIGHASH_ALL
    return vi(len(sig))+sig + vi(len(pub))+pub

# ---- P2PK ----------------------------------------------------------------

def spk_p2pk(pubkey_bytes: bytes) -> bytes:
    return bytes([len(pubkey_bytes)]) + pubkey_bytes + b"\xac"

def sig_p2pk(z: bytes, sk, *_):
    r,s = sk.sign_digest_deterministic(z, sigencode=lambda r,s,_:(r,s))
    sig = der_low_s(r,s)+b"\x01"
    return vi(len(sig))+sig           # solo firma

# Mapping comodo
SCRIPT_TYPES = {
    "p2pkh": {"build": spk_p2pkh, "sign": sig_p2pkh},
    "p2pk" : {"build": spk_p2pk,  "sign": sig_p2pk },
}

# ---------------------------------------------------------------------------
# UTXO – scansione, filtro, selezione
# ---------------------------------------------------------------------------

def collect_utxos(node, spk_hex, include_mempool=True, include_unconfirmed=True):
    """
    Ottiene gli UTXO confermati per uno specifico scriptPubKey e opzionalmente controlla il mempool.

    Argomenti:
        node: Istanza RPC di Bitcoin Core (AuthServiceProxy)
        spk_hex: scriptPubKey da filtrare (formato hex)
        include_mempool: Se True:
            - Esclude gli UTXO confermati già spesi nel mempool
            - Se False, restituisce solo UTXO confermati
        include_unconfirmed: Valido solo se include_mempool=True
            - Se True, aggiunge anche output non confermati che pagano a spk_hex
              e che non sono spesi nel mempool

    Restituisce:
        Lista di dizionari con:
        - "txid": ID della transazione
        - "vout": Indice dell'output
        - "amount": Importo in satoshi
    """
    utxos = node.scantxoutset("start", [{"desc": f"raw({spk_hex})"}])["unspents"]
    for u in utxos: u["amount"] = int(u["amount"]*SAT)

    if include_mempool:
        spent=set()
        for txid in node.getrawmempool():                       # tutti i txid in mempool :contentReference[oaicite:1]{index=1}
            tx=node.getrawtransaction(txid, True)
            for vin in tx["vin"]:
                spent.add((vin["txid"],vin["vout"]))
            if include_unconfirmed:                             
                for vout,out in enumerate(tx["vout"]):
                    if out["scriptPubKey"]["hex"]==spk_hex:      # match al tuo script
                        if (txid,vout) not in spent:             # non già speso in mempool
                            utxos.append({
                                "txid":txid,
                                "vout":vout,
                                "amount":int(out["value"]*SAT)
                            })
        utxos=[u for u in utxos if (u["txid"],u["vout"]) not in spent]
    return utxos


def select_utxos(utxos, target_sat, fee_rate, in_weight):
    utxos = sorted(utxos, key=lambda x: x["amount"], reverse=True)
    selected, total = [], 0
    est_fee = lambda n_in, n_out: math.ceil((10+n_in*in_weight+n_out*34)*fee_rate)
    for u in utxos:
        selected.append(u); total += u["amount"]
        if total >= target_sat + est_fee(len(selected), 2):
            return selected
    raise ValueError("Saldo insufficiente")

# ---------------------------------------------------------------------------
# BUILDER – costruzione / firma tx generica
# ---------------------------------------------------------------------------

def build_tx(node, utxos, send_sat, fee_rate, inp_sign, out_build, chg_build, sk, pub, change_data, dest_data):
    version = struct.pack("<I", 1)
    lock    = struct.pack("<I", 0)
    seq     = b"\xff"*4

    # recupera gli scriptPubKey precedenti
    prev=[]
    for u in utxos:
        tx=node.getrawtransaction(u["txid"], True)
        prev.append((u["txid"], u["vout"],
                     bytes.fromhex(tx["vout"][u["vout"]]["scriptPubKey"]["hex"]),
                     u["amount"]))

    fee=200
    best=None
    for _ in range(40):
        total_in=sum(a for *_,a in prev)
        change_sat=total_in-send_sat-fee
        if change_sat<0: raise ValueError("Saldo insufficiente")
        # OUTPUTS
        spk_dest = out_build(dest_data)
        outputs  = struct.pack("<Q", send_sat)+vi(len(spk_dest))+spk_dest
        n_out=1
        if change_sat>=546:
            spk_change=chg_build(change_data)
            outputs += struct.pack("<Q", change_sat)+vi(len(spk_change))+spk_change
            n_out=2
        # FIRME
        sigs=[]
        for txid,vout,spk_prev,_ in prev:
            inputs_pre=b""
            for txid2,vout2,spk_prev2,_ in prev:
                inputs_pre+=little(txid2)+struct.pack("<I",vout2)
                if (txid2,vout2)==(txid,vout):
                    inputs_pre+=vi(len(spk_prev))+spk_prev
                else:
                    inputs_pre+=vi(0)
                inputs_pre+=seq
            preimg=(version+vi(len(prev))+inputs_pre+
                    vi(n_out)+outputs+lock+struct.pack("<I",1))
            z=sha256d(preimg)
            sigs.append(inp_sign(z, sk, pub, spk_prev))
        # assembla txin definitivi
        txin=b""
        for (txid,vout,_,_),scriptSig in zip(prev,sigs):
            txin+=little(txid)+struct.pack("<I",vout)+vi(len(scriptSig))+scriptSig+seq
        raw=version+vi(len(prev))+txin+vi(n_out)+outputs+lock
        vsize=node.decoderawtransaction(raw.hex())["vsize"]
        new_fee=math.ceil(vsize*fee_rate)
        best=(raw,vsize,new_fee,change_sat,len(prev))
        if new_fee==fee: break
        fee=new_fee
    return best

# ---------------------------------------------------------------------------
# CLI / orchestratore
# ---------------------------------------------------------------------------

def main():
    # 1. RPC + wallet
    node        = rpc()
    sk,pub,addr,h160 = load_wallet()
    # Per P2PK, usiamo direttamente lo script P2PK dal wallet
    w = json.load(open(WALLET_JSON, "r"))
    spk_hex     = w.get("p2pk_script", "")  # Ottiene lo script P2PK dal wallet

    # 2. UTXO listing
    utxos = collect_utxos(node, spk_hex, include_mempool=True, include_unconfirmed=True)
    if not utxos:
        sys.exit("Nessun UTXO disponibile")
    print("\n--- UTXO ---")
    for i,u in enumerate(utxos,1):
        print(f"{i}. {u['txid']}:{u['vout']} → {u['amount']} sat")
    print("------------")

    # 3. Prompt utente
    pubkey_hex = input("Pubkey destinatario (hex): ").strip()
    dest_pub   = bytes.fromhex(pubkey_hex)
    send_sat   = int(input("Importo da inviare (satoshi): "))
    fee_rate   = float(input("Fee-rate (sat/vB): "))

    # 4. Selezione UTXO
    in_weight = 114                         # peso di un input P2PK (più leggero di P2PKH)
    selected  = select_utxos(utxos, send_sat, fee_rate, in_weight)

    # 5. Costruzione / firma
    raw,vsize,fee,change_sat,n_in = build_tx(
        node, selected, send_sat, fee_rate,
        inp_sign   = SCRIPT_TYPES["p2pk"]["sign"],    # input  P2PK
        out_build  = SCRIPT_TYPES["p2pk"]["build"],   # output P2PK
        chg_build  = SCRIPT_TYPES["p2pk"]["build"],   # resto  P2PK
        sk=sk, pub=pub,
        change_data=pub,                             # Per P2PK usiamo la pubkey, non l'hash
        dest_data=dest_pub
    )

    # 6. Riepilogo
    print("\n··· RIEPILOGO ···")
    print(f"Input usati   : {n_in}")
    print(f"Fee           : {fee} sat  ({fee/vsize:.2f} sat/vB su {vsize} vB)")
    print(f"Importo out   : {send_sat} sat")
    print(f"Resto         : {change_sat} sat")
    print("Raw hex       :", raw.hex(), "\n")

    # 7. Invio
    if input("Inviare? [s/N] ").lower().startswith("s"):
        try:
            txid=node.sendrawtransaction(raw.hex())
            print("OK! TXID:", txid)
        except JSONRPCException as e:
            print("Errore nodo:", e)

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Errore:", exc)
