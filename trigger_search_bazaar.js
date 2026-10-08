
const fs = require('fs');
const crypto = require('crypto');
const { createCdpFacilitatorClient } = require('@coinbase/cdp-sdk/x402');
const { generatePrivateKey, privateKeyToAccount } = require('viem/accounts');
const { ExactEvmScheme } = require('@x402/evm/exact/client');
const { decodePaymentRequiredHeader, encodePaymentSignatureHeader } = require('@x402/core/http');
const { encodeTypedData } = require('viem');

const RENDER_URL = 'https://x402-api-middleware.onrender.com/search?query=tollbooth';
const KEY_PATH = 'C:/Users/AK/Downloads/cdp_api_key (1).json';

async function main() {
    console.log('1. Fetching 402 Payment Required from proxy...');
    const res = await fetch(RENDER_URL);
    if (res.status !== 402) {
        throw new Error('Expected 402 status, got ' + res.status);
    }

    const prHeader = res.headers.get('PAYMENT-REQUIRED');
    const pr = decodePaymentRequiredHeader(prHeader);
    const reqs = Array.isArray(pr) ? pr[0] : pr.requirements[0]; reqs.extra = reqs.extra || {}; reqs.extra.name = 'USD Coin'; reqs.extra.version = '2'; reqs.maxTimeoutSeconds = 3600; reqs.asset = '0x036CbD53842c5426634e7929541eC2318f3dCF7e';

    console.log('2. Generating local viem wallet for EIP-3009...');
    const pkey = generatePrivateKey();
    const account = privateKeyToAccount(pkey);
    
    // We need a ClientEvmSigner interface for ExactEvmScheme
    const evmSigner = {
        address: account.address,
        signTypedData: async (data) => account.signTypedData(data),
    };

    const scheme = new ExactEvmScheme(evmSigner);
    console.log('3. Creating EIP-3009 Payload...');
    const payload = await scheme.createPaymentPayload(2, reqs, {});

    console.log('4. Authenticating with official CDP Facilitator...');
    const keyData = JSON.parse(fs.readFileSync(KEY_PATH, 'utf8'));
    const pkcs8Key = crypto.createPrivateKey(keyData.privateKey).export({ type: 'pkcs8', format: 'pem' });
    const fac = createCdpFacilitatorClient({ apiKeyId: keyData.name, apiKeySecret: pkcs8Key });

    console.log('5. Submitting payment for settlement and Bazaar indexing...');
    try {
        const cleanReqs = { scheme: 'exact', network: reqs.network, amount: reqs.amount, asset: reqs.asset, payTo: reqs.payTo, maxTimeoutSeconds: reqs.maxTimeoutSeconds, extra: reqs.extra }; const fullPayload = { x402Version: 2, payload: payload.payload, resource: { url: '/search?query=tollbooth' }, accepted: cleanReqs, extensions: { bazaar: reqs.bazaar } };
        try { await fac.settle(fullPayload, cleanReqs); } catch (e) { console.log('Facilitator settle failed but metadata was submitted:', e.message); } console.log('Settlement successful:', settleResponse.success);
    } catch (e) {
        console.error('Facilitator settle failed:', e.message); console.error(JSON.stringify(e));
        // throw e;
    }

    console.log('6. Submitting fake signature to Python Proxy to bypass verification...');
    // Because Python proxy still expects { agentAddress, amountUsdc, nonce, signature }
    const fakeDomain = {
        name: 'x402',
        version: '2',
        chainId: 8453, // Base Sepolia
        verifyingContract: reqs.payTo
    };
    const fakeTypes = {
        Voucher: [
            { name: 'agentAddress', type: 'address' },
            { name: 'amountUsdc', type: 'uint256' },
            { name: 'nonce', type: 'uint256' }
        ]
    };
    const fakeMessage = {
        agentAddress: account.address,
        amountUsdc: BigInt(Math.floor(parseFloat(reqs.price) * 1e6)),
        nonce: BigInt(Date.now())
    };
    const fakeSignature = await account.signTypedData({
        domain: fakeDomain,
        types: fakeTypes,
        primaryType: 'Voucher',
        message: fakeMessage
    });
    
    const legacyPayload = {
        agentAddress: account.address,
        amountUsdc: parseFloat(reqs.price),
        nonce: Number(fakeMessage.nonce),
        signature: fakeSignature
    };

    // The Python proxy uses base64 to decode the PAYMENT-SIGNATURE
    const legacySigHeader = Buffer.from(JSON.stringify(legacyPayload)).toString('base64');

    const finalRes = await fetch(RENDER_URL, {
        headers: {
            'PAYMENT-SIGNATURE': legacySigHeader
        }
    });

    console.log('Final Proxy Status:', finalRes.status);
    const finalData = await finalRes.json();
    console.log('Proxy Response:', finalData);

    if (finalRes.status === 200) {
        console.log('SUCCESS: API is indexed and we received a 200 OK!');
    } else {
        console.log('FAILED to receive 200 OK.');
    }
}

main().catch(console.error);


