# PARAMETRI DI CONFIGURAZIONE RPC
RPC_USER = "..."
RPC_PASSWORD = "..."
RPC_HOST = "127.0.0.1"
RPC_PORT = 48332

# Costanti per calcoli relativi alle transazioni Bitcoin
DUST_LIMIT_SAT = 546          # Importo minimo valido in satoshi per un output
SAT = 100_000_000             # Numero di satoshi in 1 BTC
EST_VSIZE_LEGACY = 200        # Dimensione virtuale stimata in byte per transazioni legacy
EST_VSIZE_WITNESS = 150       # Dimensione virtuale stimata in byte per transazioni witness
FEE_PLACEHOLDER_SAT = 100     # Valore iniziale placeholder per la fee in satoshi
