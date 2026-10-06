import os
import psycopg2
import time
from web3 import Web3

RPC_URL = os.environ.get("BASE_RPC_URL", "https://mainnet.base.org")
ESCROW_CONTRACT_ADDRESS = os.environ.get("ESCROW_CONTRACT_ADDRESS")
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
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable not set")
    return psycopg2.connect(DATABASE_URL)

def fetch_unredeemed_vouchers():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT signature, agent_address, amount_usdc, nonce FROM vouchers')
    vouchers = c.fetchall()
    
    # Delete them from db so they aren't processed again
    c.execute('DELETE FROM vouchers')
    conn.commit()
    c.close()
    conn.close()
    
    return vouchers

def run_nightly_batch():
    """
    Cron Job: Executes the batch-settlement of all accumulated vouchers,
    splitting 99% to the Provider and 1% to the Platform.
    """
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Starting nightly batch settlement...")
    
    if not PROXY_PRIVATE_KEY or not ESCROW_CONTRACT_ADDRESS or not DATABASE_URL:
        print("[Fee Splitter] Configuration missing (Key/Escrow/DB). Cannot process batch.")
        return

    try:
        vouchers = fetch_unredeemed_vouchers()
    except Exception as e:
        print(f"[Fee Splitter] DB Error: {e}")
        return
    
    if not vouchers:
        print("[Fee Splitter] No vouchers to redeem tonight.")
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

    try:
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
            'gas': 2000000,
            'gasPrice': w3.eth.gas_price
        })
        
        signed_tx = w3.eth.account.sign_transaction(tx, private_key=PROXY_PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        
        print(f"[Fee Splitter] Successfully broadcasted bulk settlement! TX: {w3.to_hex(tx_hash)}")
    except Exception as e:
        print(f"[Fee Splitter] Error executing bulk redemption: {e}")

if __name__ == "__main__":
    run_nightly_batch()
