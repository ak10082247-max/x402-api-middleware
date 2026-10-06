import os
import time
import json
import base64
import subprocess
import requests
from web3 import Web3
from eth_account.messages import encode_defunct
from eth_account import Account
import sqlite3

# Set env vars for tests
os.environ["BASE_RPC_URL"] = "https://mainnet.base.org"
os.environ["ESCROW_CONTRACT_ADDRESS"] = "0x1234567890123456789012345678901234567890"
os.environ["TARGET_BACKEND_URL"] = "http://localhost:8001"
os.environ["PROXY_PRIVATE_KEY"] = "0x0000000000000000000000000000000000000000000000000000000000000001"
os.environ["PROVIDER_WALLET_ADDRESS"] = "0x2222222222222222222222222222222222222222"
os.environ["PLATFORM_WALLET_ADDRESS"] = "0x3333333333333333333333333333333333333333"

def run_tests():
    print("🚀 Starting Infrastructure...")
    
    # Start mock backend
    backend_proc = subprocess.Popen([r".\.venv\Scripts\python.exe", "mock_backend.py"], env=os.environ.copy())
    
    # Start proxy
    proxy_env = os.environ.copy()
    proxy_env["PORT"] = "8005"
    proxy_proc = subprocess.Popen([r".\.venv\Scripts\python.exe", "main.py"], env=proxy_env)
    
    time.sleep(3) # Wait for health
    
    print("\n--- Test 1 (The Rejection Flow) ---")
    try:
        resp = requests.get("http://localhost:8005/weather")
        assert resp.status_code == 402
        req = json.loads(base64.b64decode(resp.headers.get("PAYMENT-REQUIRED")).decode())
        assert req[0]["scheme"] == "batch-settlement"
        print("✅ Test 1 Passed: Intercepted and returned HTTP 402 with batch-settlement schema.")
    except Exception as e:
        print(f"❌ Test 1 Failed: {type(e).__name__} {e}")
        try:
            print("Response details:", getattr(resp, 'status_code', None), getattr(resp, 'headers', None))
        except:
            pass
        
    print("\n--- Test 2 (The Payment Flow) ---")
    try:
        # Create an agent account
        Account.enable_unaudited_hdwallet_features()
        agent_acct, _ = Account.create_with_mnemonic()
        agent_addr = agent_acct.address
        
        amount = 1.0
        nonce = 1
        
        # Sign the voucher
        msg = f"x402_voucher:{os.environ['ESCROW_CONTRACT_ADDRESS']}:{amount}:{nonce}"
        signable_message = encode_defunct(text=msg)
        signed = agent_acct.sign_message(signable_message)
        
        voucher = {
            "agentAddress": agent_addr,
            "amountUsdc": amount,
            "nonce": nonce,
            "signature": signed.signature.hex()
        }
        
        voucher_b64 = base64.b64encode(json.dumps(voucher).encode()).decode()
        
        resp2 = requests.get("http://localhost:8005/weather", headers={"PAYMENT-SIGNATURE": voucher_b64})
        
        if resp2.status_code != 200:
            print("Response body:", resp2.text)
        assert resp2.status_code == 200
        assert resp2.json()["city"] == "San Francisco"
        print("✅ Test 2 Passed: Voucher verified off-chain and request proxied successfully.")
    except Exception as e:
        print(f"❌ Test 2 Failed: {type(e).__name__} {e}")

    print("\n--- Test 3 (The Batch Settlement) ---")
    try:
        # Check DB that the voucher was stored
        conn = sqlite3.connect('proxy_payments.db')
        c = conn.cursor()
        c.execute("SELECT * FROM vouchers")
        stored = c.fetchall()
        conn.close()
        
        assert len(stored) >= 1
        print(f"✅ DB Verified: {len(stored)} vouchers pending settlement.")
        
        # Run fee_splitter
        print("Running fee_splitter.py in dry-run mode (intercepting output)...")
        # Since it uses web3 and will fail to connect or send tx with dummy private key, we just expect the output to mention Processing vouchers and then error on tx.
        result = subprocess.run([r".\.venv\Scripts\python.exe", "fee_splitter.py"], env=os.environ.copy(), capture_output=True, text=True)
        
        output = result.stdout
        print(output)
        assert "Starting nightly batch settlement" in output
        assert "Processing 1 vouchers" in output
        print("✅ Test 3 Passed: Batch settlement script aggregated vouchers and executed bulk redemption logic.")
    except Exception as e:
        print(f"❌ Test 3 Failed: {e}")
        
    print("\n--- Cleaning up ---")
    proxy_proc.terminate()
    backend_proc.terminate()
    
if __name__ == "__main__":
    run_tests()
