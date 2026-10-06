import os
import json
import base64
import psycopg2
from web3 import Web3
from eth_account.messages import encode_defunct

RPC_URL = os.environ.get("BASE_RPC_URL", "https://mainnet.base.org")
ESCROW_CONTRACT_ADDRESS = os.environ.get("ESCROW_CONTRACT_ADDRESS")
DATABASE_URL = os.environ.get("DATABASE_URL")

w3 = Web3(Web3.HTTPProvider(RPC_URL))

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

def init_db():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS vouchers (
                signature TEXT PRIMARY KEY,
                agent_address TEXT NOT NULL,
                amount_usdc REAL NOT NULL,
                nonce BIGINT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        c.close()
        conn.close()
        print("Database initialized successfully.")
    except Exception as e:
        print(f"Database initialization error: {e}")

def is_nonce_used(agent_address: str, nonce: int) -> bool:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT nonce FROM vouchers WHERE agent_address=%s AND nonce=%s', (agent_address, nonce))
    used = c.fetchone() is not None
    c.close()
    conn.close()
    return used

def save_voucher(agent_address: str, amount_usdc: float, nonce: int, signature: str):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        'INSERT INTO vouchers (signature, agent_address, amount_usdc, nonce) VALUES (%s, %s, %s, %s)', 
        (signature, agent_address, amount_usdc, nonce)
    )
    conn.commit()
    c.close()
    conn.close()

from eth_account.messages import encode_typed_data

def verify_voucher(voucher_data: dict, expected_amount_usdc: float) -> bool:
    """
    Verifies an off-chain cryptographic voucher using EIP-712.
    """
    try:
        agent_address = voucher_data.get("agentAddress")
        amount = float(voucher_data.get("amountUsdc", 0))
        nonce = int(voucher_data.get("nonce", 0))
        signature = voucher_data.get("signature")

        if not agent_address or not signature:
            return False

        if amount < expected_amount_usdc:
            return False

        if is_nonce_used(agent_address, nonce):
            print(f"Nonce {nonce} already used for agent {agent_address}")
            return False

        domain_data = {
            "name": "x402",
            "version": "2",
            "chainId": w3.eth.chain_id,
            "verifyingContract": ESCROW_CONTRACT_ADDRESS,
        }
        
        message_types = {
            "Voucher": [
                {"name": "agentAddress", "type": "address"},
                {"name": "amountUsdc", "type": "uint256"},
                {"name": "nonce", "type": "uint256"}
            ]
        }
        
        amount_wei = int(amount * 10**6)
        
        message_data = {
            "agentAddress": agent_address,
            "amountUsdc": amount_wei,
            "nonce": nonce
        }
        
        signable_message = encode_typed_data(domain_data, message_types, message_data)
        recovered_address = w3.eth.account.recover_message(signable_message, signature=signature)
        
        if recovered_address.lower() == agent_address.lower():
            save_voucher(agent_address, amount, nonce, signature)
            return True
            
        return False
    except Exception as e:
        print(f"Voucher verification error: {e}")
        return False
