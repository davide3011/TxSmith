from bitcoinrpc.authproxy import JSONRPCException
from decimal import Decimal

import config
import uxto
import signers
import utils # rpc è stato rimosso, le sue funzioni sono in utils


def main():
    """Gestisce il flusso di creazione e invio di una transazione Bitcoin."""
    try:
        # Caricamento wallet e setup iniziale
        src, wif = utils.load_sender_from_json()
        tipo = utils.tipo_indirizzo(src)
        if tipo == "unknown":
            print("Tipo di indirizzo non riconosciuto."); return
        
        dest = __builtins__.input("\nInserisci l'indirizzo destinatario: ").strip()
        rpc_conn = utils.connect_rpc() # Modificato da rpc a utils
        print("Connessione RPC OK - blocchi:", rpc_conn.getblockcount())
        
        # Recupero UTXO e setup parametri in base al tipo di indirizzo
        if tipo == "legacy":
            utxos_list, est_vsize, sign_func = uxto.fetch_utxos_legacy(src), config.EST_VSIZE_LEGACY, signers.sign_tx_legacy
        elif tipo == "witness":
            utxos_list, est_vsize, sign_func = uxto.fetch_utxos_witness(src), config.EST_VSIZE_WITNESS, signers.sign_tx_witness
        else:
            print("Solo indirizzi legacy (1...) o witness (bc1...) supportati."); return
        
        # Verifica saldo e acquisizione parametri transazione
        balance = utils.get_balance(utxos_list)
        print(f"\nSaldo: {balance} sat ({balance/config.SAT:.8f} BTC)")
        if balance == 0: print("Nessuna UTXO disponibile."); return
        
        amount = utils.read_amount_sat(balance)
        fee_rate = utils.read_fee_rate(conf_target=6)
        
        # Creazione e firma transazione
        need_est = amount + int(round(fee_rate * Decimal(est_vsize)))
        chosen, _ = uxto.pick_utxos(utxos_list, need_est)
        
        # Bozza per calcolo dimensione effettiva
        draft_hex = utils.build_raw_tx(chosen, dest, amount, src, 0)
        draft_sign = sign_func(draft_hex, chosen, wif)
        vsize = rpc_conn.decoderawtransaction(draft_sign)["vsize"]
        fee_sat = int(round(Decimal(vsize) * fee_rate))
        
        # Transazione finale
        final_hex = utils.build_raw_tx(chosen, dest, amount, src, fee_sat)
        signed_hex = sign_func(final_hex, chosen, wif)
        vsize_fin = rpc_conn.decoderawtransaction(signed_hex)["vsize"]
        fee_fin = int(round(Decimal(vsize_fin) * fee_rate))
        total_sat = amount + fee_fin
        
        # Riepilogo e invio
        print("\n──── RIEPILOGO ────")
        print(f"Mittente:      {src}")
        print(f"Destinatario:  {dest}")
        print(f"Importo:       {amount:,} sat ({amount/config.SAT:.8f} BTC)")
        print(f"Fee-rate:      {fee_rate} sat/vB")
        print(f"vsize:         {vsize_fin} vB")
        print(f"Fee totale:    {fee_fin:,} sat")
        print(f"Totale spesa:  {total_sat:,} sat ({total_sat/config.SAT:.8f} BTC)\n")
        print("Raw TX FIRMATA:")
        print(signed_hex)
        
        if __builtins__.input("\nInviare la transazione? [s/N] ").lower().startswith("s"):
            txid = rpc_conn.sendrawtransaction(signed_hex)
            print("Transazione inviata! TXID:", txid)
        else:
            print("Transazione NON inviata.")
    
    except JSONRPCException as e: print("Errore RPC:", e)
    except Exception as e: print("Errore:", e)

if __name__ == "__main__":
    main()