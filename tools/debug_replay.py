"""Replay test: capture a paid PAYMENT-SIGNATURE header, resend it verbatim.
Expected: the replay is rejected (facilitator nonce-used) or returns the
stored brief WITHOUT a new settlement. Either way: no double-charge."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import envfix  # noqa: F401  (repo root; tools/ scripts run from anywhere)
import argparse, asyncio, base64, json
import httpx
from eth_account import Account
from x402 import x402Client
from x402.http.utils import decode_payment_required_header
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
        r = await http.post(f"{url}/v1/brief", json={})
        pr = decode_payment_required_header(r.headers["PAYMENT-REQUIRED"])
        payload = await client.create_payment_payload(pr)
        # Encode the signature header the same way the transport does
        from x402.http.clients.httpx import x402AsyncTransport
        t = x402AsyncTransport(client)
        headers = t._http_client.encode_payment_signature_header(payload)
        sig_header = dict(headers)["PAYMENT-SIGNATURE"]
        print("captured signature header, len:", len(sig_header))

        async with httpx.AsyncClient(timeout=120.0) as h2:
            r1 = await h2.post(f"{url}/v1/brief", json={}, headers={"PAYMENT-SIGNATURE": sig_header})
            print("first send:", r1.status_code)
            b1 = r1.json()
            print("  tx:", b1.get("receipt", {}).get("tx_hash", "")[:18])
            # REPLAY the exact same header
            r2 = await h2.post(f"{url}/v1/brief", json={}, headers={"PAYMENT-SIGNATURE": sig_header})
            print("replay send:", r2.status_code)
            prh = r2.headers.get("payment-response") or r2.headers.get("PAYMENT-RESPONSE")
            if prh:
                print("  payment-response:", prh[:200])
            try:
                b2 = r2.json()
                print("  body receipt tx:", b2.get("receipt", {}).get("tx_hash", "")[:18])
                print("  same tx as first?", b2.get("receipt", {}).get("tx_hash") == b1.get("receipt", {}).get("tx_hash"))
            except Exception as e:
                print("  body not JSON:", r2.text[:200])

ap = argparse.ArgumentParser()
ap.add_argument("--url", default="http://localhost:8000")
ap.add_argument("--key", required=True)
a = ap.parse_args()
asyncio.run(main(a.url, a.key))
