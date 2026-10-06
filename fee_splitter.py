import os
import psycopg2
import time
from web3 import Web3

RPC_URL = os.environ.get("BASE_RPC_URL", "https://mainnet.base.org")
ESCROW_CONTRACT_ADDRESS = os.environ.get("ESCROW_CONTRACT_ADDRESS")
# Private keys MUST NOT be hardcoded. Always retrieved from os.getenv()
PROXY_PRIVATE_KEY = os.environ.get("PROXY_PRIVATE_KEY")
PROVIDER_WALLET_ADDRESS = os.environ.get("PROVIDER_WALLET_ADDRESS")
PLATFORM_WALLET_ADDRESS = os.environ.get("PLATFORM_WALLET_ADDRESS")
DATABASE_URL = os.environ.get("DATABASE_URL")

w3 = Web3(Web3.HTTPProvider(RPC_URL))

ESCROW_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "agentAddresses", "type": "address[]"},
            {"name": "amounts", "type": "uint256[]"},
            {"name": "nonces", "type": "uint256[]"},
            {"name": "signatures", "type": "bytes[]"},
            {"name": "providerWallet", "type": "address"},
            {"name": "platformWallet", "type": "address"}
        ],
        "name": "bulkRedeemAndSplit",
        "outputs": [],
        "type": "function"
    }
]

escrow_contract = w3.eth.contract(
    address=w3.to_checksum_address(ESCROW_CONTRACT_ADDRESS) if ESCROW_CONTRACT_ADDRESS else None, 
    abi=ESCROW_ABI
)

def get_db_connection():
    """
    Returns a PostgreSQL connection. 
    IMPORTANT: For free cloud hosts like Render, ensure DATABASE_URL uses the Supabase 
    Transaction Pooler connection string (IPv4). This typically uses port 6543 (transaction mode) 
    or port 5432 (session mode) on a pooler.supabase.com host.
    """
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable not set")
    return psycopg2.connect(DATABASE_URL)

def run_nightly_batch():
    """
    Cron Job: Executes the batch-settlement of all accumulated vouchers,
    splitting 99% to the Provider and 1% to the Platform.
    """
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Starting nightly batch settlement...")
    
    if not PROXY_PRIVATE_KEY or not ESCROW_CONTRACT_ADDRESS or not DATABASE_URL:
        print("[Fee Splitter] Configuration missing (Key/Escrow/DB). Cannot process batch.")
        return
        
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        # Double-Spend Lock: Select unpaid vouchers using FOR UPDATE SKIP LOCKED
        # This locks the rows so concurrent cron jobs will simply skip them.
        c.execute('SELECT signature, agent_address, amount_usdc, nonce FROM vouchers FOR UPDATE SKIP LOCKED')
        vouchers = c.fetchall()
        
        if not vouchers:
            print("[Fee Splitter] No vouchers to redeem tonight.")
            conn.rollback()
            return
            
        print(f"[Fee Splitter] Processing {len(vouchers)} vouchers...")

        agent_addresses = []
        amounts_wei = []
        nonces = []
        signatures = []

        for signature, agent_address, amount_usdc, nonce in vouchers:
            agent_addresses.append(w3.to_checksum_address(agent_address))
            amounts_wei.append(int(amount_usdc * 10**6))
            nonces.append(int(nonce))
            signatures.append(w3.to_bytes(hexstr=signature))
            
        # We must prepare the transaction and do a pre-flight gas check
        account = w3.eth.account.from_key(PROXY_PRIVATE_KEY)
        tx_nonce = w3.eth.get_transaction_count(account.address)
        
        tx = escrow_contract.functions.bulkRedeemAndSplit(
            agent_addresses,
            amounts_wei,
            nonces,
            signatures,
            w3.to_checksum_address(PROVIDER_WALLET_ADDRESS),
            w3.to_checksum_address(PLATFORM_WALLET_ADDRESS)
        ).build_transaction({
            'from': account.address,
            'nonce': tx_nonce,
            'gas': 0, # Will be set below
            'gasPrice': w3.eth.gas_price
        })
        
        # Estimate gas
        try:
            estimated_gas = w3.eth.estimate_gas(tx)
            tx['gas'] = int(estimated_gas * 1.2) # Add 20% buffer
        except Exception as estimate_err:
            print(f"[Fee Splitter] Gas estimation failed (may fail on-chain): {estimate_err}")
            tx['gas'] = 2000000

        # Pre-flight Gas Check: Ensure wallet has enough native token
        gas_cost = tx['gas'] * tx['gasPrice']
        balance = w3.eth.get_balance(account.address)
        
        if balance < gas_cost:
            print(f"[CRITICAL WARNING] Wallet {account.address} has insufficient native balance to cover network fees. Have: {balance} wei, Need: {gas_cost} wei.")
            conn.rollback() # Rollback DB transaction to unlock the vouchers for a later attempt
            return
            
        signed_tx = w3.eth.account.sign_transaction(tx, private_key=PROXY_PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        
        print(f"[Fee Splitter] Successfully broadcasted bulk settlement! TX: {w3.to_hex(tx_hash)}")
        
        # Now that it's broadcasted, delete them from DB and commit the transaction
        c.execute('DELETE FROM vouchers WHERE signature = ANY(%s)', ([v[0] for v in vouchers],))
        conn.commit()
        
    except Exception as e:
        print(f"[Fee Splitter] Error executing bulk redemption: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    run_nightly_batch()
