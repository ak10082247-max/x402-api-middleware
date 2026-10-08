import os
import json
import base64
import httpx
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import trafilatura

from web3_validator import init_db, verify_voucher
from fee_splitter import run_nightly_batch

app = FastAPI(
    title="x402 Markdown Scraper API",
    description="Zero-cost LLM-ready markdown scraper protected by x402.",
    version="2.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ESCROW_CONTRACT_ADDRESS = os.environ.get("ESCROW_CONTRACT_ADDRESS", "0x73279fa4BadA7CAC888c62CDa4f5c8104765f6f1")
PRICE_USDC = float(os.environ.get("PRICE_USDC", "0.05"))

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
        "scheme": "eip155:exact",
        "network": "eip155:84532",
        "asset": "USDC",
        "price": f"{PRICE_USDC:.2f}",
        "payTo": ESCROW_CONTRACT_ADDRESS,
        "instructions": "Pay using CDP Facilitator",
        "bazaar": {
            "name": "LLM Markdown Scraper",
            "description": "Native Python web scraper. Pass any URL and receive clean, token-efficient Markdown optimized for AI agents and RAG pipelines."
        }
    }]
    req_b64 = base64.b64encode(json.dumps(requirements).encode()).decode()
    return JSONResponse(
        {"error": "Payment Required", "message": "Batch-settlement voucher required."}, 
        status_code=402, 
        headers={"PAYMENT-REQUIRED": req_b64}
    )

@app.api_route("/scrape", methods=["GET", "POST"])
async def scrape_middleware(request: Request, url: str = None):
    if request.method == "OPTIONS":
        return Response(status_code=200)

    payment_signature = request.headers.get("PAYMENT-SIGNATURE")
    
    if not payment_signature:
        return create_402_response()

    if not url:
        return JSONResponse({"error": "Missing 'url' query parameter"}, status_code=400)

    try:
        voucher_data = json.loads(base64.b64decode(payment_signature).decode())
    except Exception:
        return JSONResponse({"error": "Invalid voucher format"}, status_code=400)

    # Verify off-chain cryptographic voucher
    is_valid = verify_voucher(voucher_data, PRICE_USDC)
    
    if not is_valid:
        return JSONResponse({"error": "Voucher cryptographic verification failed or nonce reused."}, status_code=402)
    
    # Execute native Python web-scraper
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded is None:
            return JSONResponse({"error": "Failed to fetch URL"}, status_code=400)
        markdown_content = trafilatura.extract(downloaded, output_format='markdown')
        if markdown_content is None:
            return JSONResponse({"error": "Failed to extract content"}, status_code=400)
        
        return Response(
            content=markdown_content,
            media_type="text/markdown",
            status_code=200
        )
    except Exception as exc:
        return JSONResponse({"error": f"Scraping failed: {exc}"}, status_code=500)

def create_402_search_response():
    requirements = [{
        "scheme": "eip155:exact",
        "network": "eip155:84532",
        "asset": "USDC",
        "price": f"{PRICE_USDC:.2f}",
        "payTo": ESCROW_CONTRACT_ADDRESS,
        "instructions": "Pay using CDP Facilitator",
        "bazaar": {
            "name": "Live Web Search API",
            "description": "High-quality, unrestricted live search results from DuckDuckGo. Pass a query and receive structured JSON tailored for agentic reasoning and data extraction."
        }
    }]
    req_b64 = base64.b64encode(json.dumps(requirements).encode()).decode()
    return JSONResponse(
        {"error": "Payment Required", "message": "Batch-settlement voucher required."}, 
        status_code=402, 
        headers={"PAYMENT-REQUIRED": req_b64}
    )

@app.api_route("/search", methods=["GET", "POST"])
async def search_middleware(request: Request, query: str = None, max_results: int = 5):
    if request.method == "OPTIONS":
        return Response(status_code=200)

    payment_signature = request.headers.get("PAYMENT-SIGNATURE")
    
    if not payment_signature:
        return create_402_search_response()

    if not query:
        return JSONResponse({"error": "Missing 'query' query parameter"}, status_code=400)

    try:
        voucher_data = json.loads(base64.b64decode(payment_signature).decode())
    except Exception:
        return JSONResponse({"error": "Invalid voucher format"}, status_code=400)

    # Verify off-chain cryptographic voucher
    is_valid = verify_voucher(voucher_data, PRICE_USDC)
    
    if not is_valid:
        return JSONResponse({"error": "Voucher cryptographic verification failed or nonce reused."}, status_code=402)
    
    # Execute native Python web search
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append(r)
        
        return JSONResponse({"query": query, "results": results}, status_code=200)
    except Exception as exc:
        return JSONResponse({"error": f"Search failed: {exc}"}, status_code=500)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
