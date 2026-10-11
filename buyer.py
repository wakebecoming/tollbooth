"""Demo buyer for the wakeandnorth tollbooth.

The second agent in the story: an agent pays 2 USDC via x402 and receives
the brief. Run against the local server:

    python buyer.py [--url http://localhost:8000] [--key 0x...]

Needs test USDC on Base Sepolia in the buyer wallet. The buyer NEVER pays
gas — the facilitator settles and pays it; the buyer only signs the
EIP-3009 authorization off-chain.
"""

from __future__ import annotations

import envfix  # noqa: F401  (sanitize no_proxy before httpx loads)
import argparse
import asyncio
import base64
import json
import sys

from eth_account import Account

from x402 import x402Client
from x402.http.clients import wrapHttpxWithPayment
from x402.mechanisms.evm.exact import register_exact_evm_client
from x402.mechanisms.evm.signers import EthAccountSigner

NETWORK = "eip155:84532"


async def buy(url: str, key: str) -> int:
    account = Account.from_key(key)
    signer = EthAccountSigner(account)
    client = x402Client()
    # Demo buyer: allow up to $10 per payment (default cap is $1; our brief is $2).
    client.set_spend_controls({"max_amount_per_payment": "$10.00", "allowed_assets": True})
    register_exact_evm_client(client, signer, networks=[NETWORK])

    print(f"buyer: {account.address}")
    # Generous timeout: upfront settlement (verify -> on-chain settle -> handler)
    # can take 30s+ on testnet; httpx defaults to 5s.
    async with wrapHttpxWithPayment(client, timeout=120.0) as http:
        resp = await http.post(f"{url}/v1/brief", json={})
        print(f"status: {resp.status_code}")

        # PAYMENT-RESPONSE settlement receipt header
        pr = resp.headers.get("payment-response") or resp.headers.get("PAYMENT-RESPONSE")
        if pr:
            receipt = json.loads(base64.b64decode(pr))
            print("settlement receipt (PAYMENT-RESPONSE header):")
            print(json.dumps(receipt, indent=2)[:800])

        body = resp.json()
        print("brief receipt (body):")
        print(json.dumps(body.get("receipt", {}), indent=2))
        if body.get("stub"):
            print("NOTE: brief body is the STUB — real engine lands with the spec.")
        return 0 if resp.status_code == 200 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--key", default=None, help="buyer private key (0x...)")
    args = ap.parse_args()
    if not args.key:
        print("buyer needs --key with a Base Sepolia wallet holding test USDC", file=sys.stderr)
        return 2
    return asyncio.run(buy(args.url, args.key))


if __name__ == "__main__":
    raise SystemExit(main())
