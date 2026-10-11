"""Diagnose settlement failure: build a payment payload and call facilitator /verify directly."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import envfix  # noqa: F401  (repo root; tools/ scripts run from anywhere)
import argparse, asyncio, base64, json
import httpx
from eth_account import Account
from x402.http.utils import decode_payment_required_header
from x402 import x402Client
from x402.mechanisms.evm.exact import register_exact_evm_client
from x402.mechanisms.evm.signers import EthAccountSigner

NETWORK = "eip155:84532"

async def main(url: str, key: str):
    account = Account.from_key(key)
    signer = EthAccountSigner(account)
    client = x402Client()
    client.set_spend_controls({"max_amount_per_payment": "$10.00", "allowed_assets": True})
    register_exact_evm_client(client, signer, networks=[NETWORK])

    async with httpx.AsyncClient(timeout=30.0) as http:
        # 1. Get the 402 requirements
        r = await http.post(f"{url}/v1/brief", json={})
        assert r.status_code == 402, r.status_code
        payment_required = decode_payment_required_header(r.headers["PAYMENT-REQUIRED"])
        req = payment_required.accepts[0]
        print("requirements:", {k: getattr(req, k, None) for k in ("scheme","network","amount","asset","payTo","maxTimeoutSeconds")})

        # 2. Create payment payload
        payload = await client.create_payment_payload(payment_required)
        print("payload:", type(payload).__name__)

        # 3. Call facilitator /verify directly.
        # Pydantic models -> plain dicts for the JSON body.
        def ser(o):
            return o.model_dump(by_alias=True, mode="json") if hasattr(o, "model_dump") else o
        payload_dict = ser(payload)
        async with httpx.AsyncClient(timeout=120.0) as fx:
            vr = await fx.post(
                "https://x402.org/facilitator/verify",
                json={"x402Version": payload_dict.get("x402Version", 2),
                      "paymentPayload": payload_dict,
                      "paymentRequirements": ser(req)},
            )
            print("verify status:", vr.status_code)
            print("verify body:", vr.text[:500])
            sr = await fx.post(
                "https://x402.org/facilitator/settle",
                json={"x402Version": payload_dict.get("x402Version", 2),
                      "paymentPayload": payload_dict,
                      "paymentRequirements": ser(req)},
            )
            print("settle status:", sr.status_code)
            print("settle body:", sr.text[:2000])

ap = argparse.ArgumentParser()
ap.add_argument("--url", default="http://localhost:8000")
ap.add_argument("--key", required=True)
a = ap.parse_args()
asyncio.run(main(a.url, a.key))
