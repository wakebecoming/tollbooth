"""Live test: POST /brief/order on Base Sepolia testnet (spends test-USDC).

Proves, with real money-test:
  1. 402 with PAYMENT-REQUIRED (no payment) for a well-formed order body.
  2. 402 -> sign (EIP-3009, fixed nonce == body nonce) -> 200 with the
     spec-v1 brief JSON + inline receipt (echo matches the request nonce).
  3. Replay of the identical PAYMENT-SIGNATURE -> 409 "nonce already settled"
     with the byte-identical stored brief; no new charge (balance unchanged).

The buyer key is read from wallets/test-buyer.json and NEVER printed.

Run (server first):  .venv/bin/uvicorn app:app --port 8000
Then:                 .venv/bin/python test_live_brief.py --url http://localhost:8000 --topic bounties
"""

from __future__ import annotations

import envfix  # noqa: F401
import argparse
import asyncio
import json
import os
import sys

import httpx
from eth_account import Account

from x402 import x402Client
from x402.http.utils import (
    decode_payment_required_header,
    encode_payment_signature_header,
)
from x402.mechanisms.evm.exact import register_exact_evm_client
from x402.mechanisms.evm.signers import EthAccountSigner
import x402.mechanisms.evm.exact.client as exact_client_mod

NETWORK = "eip155:84532"
USDC = "0x036cbd53842c5426634e7929541ec2318f3dcf7e"
RPC = "https://sepolia.base.org"


async def usdc_balance(http: httpx.AsyncClient, address: str) -> float:
    # balanceOf(address): 4-byte selector + address left-padded to 32 bytes
    data = "0x70a08231" + address[2:].lower().zfill(64)
    r = await http.post(
        RPC,
        json={"jsonrpc": "2.0", "id": 1, "method": "eth_call",
              "params": [{"to": USDC, "data": data}, "latest"]},
        timeout=30.0,
    )
    r.raise_for_status()
    return int(r.json()["result"], 16) / 1e6


async def await_balance(http: httpx.AsyncClient, address: str, want: float,
                       timeout_s: float = 150.0) -> float:
    """Poll until the on-chain balance reaches `want` (chain lags the 200)."""
    import time
    deadline = time.time() + timeout_s
    while True:
        bal = await usdc_balance(http, address)
        if abs(bal - want) < 0.005 or time.time() > deadline:
            return bal
        await asyncio.sleep(5)


async def main(url: str, topic: str) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "wallets", "test-buyer.json")) as f:
        buyer_key = json.load(f)["private_key"]
    account = Account.from_key(buyer_key)
    buyer = account.address
    print(f"buyer: {buyer}")

    # Fixed nonce so the EIP-3009 nonce == the order body's nonce (echo matching).
    nonce = "0x" + os.urandom(32).hex()
    exact_client_mod.create_nonce = lambda: nonce
    body = {"topic": topic, "nonce": nonce}

    signer = EthAccountSigner(account)
    client = x402Client()
    client.set_spend_controls({"max_amount_per_payment": "$10.00", "allowed_assets": True})
    register_exact_evm_client(client, signer, networks=[NETWORK])

    async with httpx.AsyncClient(timeout=30.0) as http:
        bal0 = await usdc_balance(http, buyer)
        print(f"balance before: {bal0:.2f} test-USDC")

        # 1. no payment -> 402
        r1 = await http.post(f"{url}/brief/order", json=body)
        assert r1.status_code == 402, f"expected 402, got {r1.status_code}"
        assert "payment-required" in {k.lower() for k in r1.headers}
        pr = decode_payment_required_header(r1.headers["payment-required"])
        print("1. 402 with PAYMENT-REQUIRED: OK")

        # 2. sign with the fixed nonce, pay
        payload = await client.create_payment_payload(pr)
        sig = encode_payment_signature_header(payload)
        r2 = await http.post(
            f"{url}/brief/order", json=body,
            headers={"PAYMENT-SIGNATURE": sig}, timeout=120.0,
        )
        assert r2.status_code == 200, f"expected 200, got {r2.status_code}: {r2.text[:300]}"
        brief = r2.json()
        rc = brief["receipt"]
        assert brief["id"] == "brief-" + nonce[:8], brief["id"]
        assert brief["topic"] == topic and brief["nonce"] == nonce
        assert isinstance(brief["content"], str) and "v1 demo brief" in brief["content"]
        assert rc["payment_nonce"] == nonce, "echo-to-request mismatch"
        assert rc["amountUsdc"] == "2.00" and rc["network"] == "eip155:84532"
        assert rc["asset"].lower() == USDC and rc["payer"].lower() == buyer.lower()
        assert rc["settleTx"].startswith("0x") and len(rc["settleTx"]) == 66
        assert rc["verifiedAt"] and brief["createdAt"]
        prh = r2.headers.get("payment-response") or r2.headers.get("PAYMENT-RESPONSE")
        assert prh, "missing PAYMENT-RESPONSE header"
        print(f"2. 200 paid brief: OK  id={brief['id']}  settleTx={rc['settleTx']}")
        first_bytes = json.dumps(brief, sort_keys=True, separators=(",", ":")).encode()

        bal1 = await await_balance(http, buyer, bal0 - 2.00)
        print(f"   balance after purchase: {bal1:.2f} (delta {bal0 - bal1:.2f})")
        assert abs((bal0 - bal1) - 2.00) < 0.01, "expected exactly $2.00 charged"

        # 3. replay identical signature -> 409 + identical brief, no new charge
        r3 = await http.post(
            f"{url}/brief/order", json=body,
            headers={"PAYMENT-SIGNATURE": sig}, timeout=60.0,
        )
        assert r3.status_code == 409, f"expected 409, got {r3.status_code}: {r3.text[:300]}"
        dup = r3.json()
        assert dup.get("error") == "nonce already settled", dup.get("error")
        dup_brief = {k: v for k, v in dup.items() if k != "error"}
        dup_bytes = json.dumps(dup_brief, sort_keys=True, separators=(",", ":")).encode()
        assert dup_bytes == first_bytes, "re-served brief not byte-identical"
        assert dup_brief["receipt"]["settleTx"] == rc["settleTx"], "receipt not re-served"
        print("3. 409 replay: OK  byte-identical brief re-served, original receipt intact")

        bal2 = await usdc_balance(http, buyer)
        # give the chain a beat to prove the replay moved nothing
        await asyncio.sleep(10)
        bal2 = await usdc_balance(http, buyer)
        assert abs(bal2 - bal1) < 1e-9, f"replay moved funds: {bal1} -> {bal2}"
        print(f"   balance after replay: {bal2:.2f} (unchanged — no new charge)")

    print("\nLIVE TEST PASSED")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--topic", default="bounties")
    sys.exit(asyncio.run(main(ap.parse_args().url, ap.parse_args().topic)))
