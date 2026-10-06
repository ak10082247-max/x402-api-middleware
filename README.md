# 🚀 x402 API Middleware

A production-ready Web3 reverse-proxy middleware that allows Web2 APIs to instantly monetize AI agents via the HTTP 402 protocol and USDC on the Base network.

## 🎯 What it does

1. **Intercepts** incoming HTTP requests from AI Agents.
2. **Validates** that a required USDC microtransaction payment has been confirmed on the Base network.
3. **Rejects** unpaid requests with an `HTTP 402 Payment Required` status, informing the agent of the payment requirement.
4. **Proxies** valid requests to your existing Web2 backend transparently.
5. **Automatically Splits Fees** by executing programmatic routing, sending 99% of the payment to you (the API provider) and 1% to the platform.

## 🛠 5-Minute Setup

You don't need to rewrite your backend. Just place this proxy in front of it!

1. Clone this directory to your server.
2. Configure your environment variables in `docker-compose.yml` (or via a `.env` file):
   - `TARGET_BACKEND_URL`: The URL of your internal API.
   - `PROXY_WALLET_ADDRESS`: Your middleware's custodial wallet public address.
   - `PROXY_PRIVATE_KEY`: Your middleware's custodial wallet private key (used to route funds).
   - `PROVIDER_WALLET_ADDRESS`: Your personal wallet where you want to receive the 99% revenue.
   - `PLATFORM_WALLET_ADDRESS`: The platform's wallet where the 1% fee is routed.
   - `PRICE_USDC`: The price per API request in USDC (e.g. `1.00`).

3. Boot up the infrastructure using Docker Compose:
   ```bash
   docker-compose up -d --build
   ```

4. Point your domain/DNS to the proxy on port `8000`.

## 🤖 Agent Protocol (How Agents Call Your API)

When an AI agent hits your API endpoint without payment, they receive an HTTP 402 status. The header `PAYMENT-REQUIRED` contains a Base64 encoded JSON string indicating the price and destination wallet.

Agents process the payment on Base and attach the transaction hash to the `PAYMENT-SIGNATURE` header. 
The proxy verifies this transaction on-chain via an RPC provider and routes the request!
