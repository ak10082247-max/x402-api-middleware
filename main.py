import os
import json
import base64
import httpx
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from web3_validator import init_db, verify_voucher
from fee_splitter import run_nightly_batch

app = FastAPI(
    title="x402 API Middleware",
    description="Web3 reverse-proxy middleware that monetizes AI agents via HTTP 402 and off-chain batch settlement.",
    version="2.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

TARGET_BACKEND_URL = os.environ.get("TARGET_BACKEND_URL", "http://localhost:8001")
ESCROW_CONTRACT_ADDRESS = os.environ.get("ESCROW_CONTRACT_ADDRESS")
PRICE_USDC = float(os.environ.get("PRICE_USDC", "1.00"))

scheduler = AsyncIOScheduler()

@app.on_event("startup")
async def startup_event():
    # Initialize Postgres DB tables
    init_db()
    
    # Schedule the bulk settlement cron job to run at midnight UTC
    scheduler.add_job(run_nightly_batch, 'cron', hour=0, minute=0, timezone=timezone.utc)
    scheduler.start()
    print("In-process APScheduler started for nightly batch settlement.")

@app.get("/health")
async def health_check():
    """Anti-Sleep Health Route for Render / UptimeRobot"""
    return {
        "status": "awake", 
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

def create_402_response():
    requirements = [{
        "scheme": "batch-settlement",
        "network": "base",
        "asset": "USDC",
        "price": f"{PRICE_USDC:.2f}",
        "escrow_address": ESCROW_CONTRACT_ADDRESS,
        "instructions": "Deposit USDC into the escrow contract and provide an off-chain signed voucher in the PAYMENT-SIGNATURE header."
    }]
    req_b64 = base64.b64encode(json.dumps(requirements).encode()).decode()
    return JSONResponse(
        {"error": "Payment Required", "message": "Batch-settlement voucher required."}, 
        status_code=402, 
        headers={"PAYMENT-REQUIRED": req_b64}
    )

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_middleware(request: Request, path: str):
    if request.method == "OPTIONS":
        return Response(status_code=200)

    # Bypass payment check for health route if it accidentally fell through to proxy
    if path == "health":
        return await health_check()

    payment_signature = request.headers.get("PAYMENT-SIGNATURE")
    
    if not payment_signature:
        return create_402_response()

    try:
        voucher_data = json.loads(base64.b64decode(payment_signature).decode())
    except Exception:
        return JSONResponse({"error": "Invalid voucher format"}, status_code=400)

    # Verify off-chain cryptographic voucher
    is_valid = verify_voucher(voucher_data, PRICE_USDC)
    
    if not is_valid:
        return JSONResponse({"error": "Voucher cryptographic verification failed or nonce reused."}, status_code=402)
    
    # Forward the Request
    target_url = f"{TARGET_BACKEND_URL}/{path}"
    
    if request.url.query:
        target_url += f"?{request.url.query}"

    async with httpx.AsyncClient() as client:
        req_body = await request.body()
        
        headers = dict(request.headers)
        headers.pop("host", None)
        headers.pop("payment-signature", None)
        
        try:
            resp = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=req_body,
                timeout=30.0
            )
            
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers=dict(resp.headers)
            )
        except httpx.RequestError as exc:
            return JSONResponse({"error": f"Failed to reach target backend: {exc}"}, status_code=502)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
