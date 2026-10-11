import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import envfix  # noqa: F401  (repo root; tools/ scripts run from anywhere)
import argparse, asyncio, base64, json, sys, traceback
from eth_account import Account
from x402 import x402Client
from x402.http.clients import wrapHttpxWithPayment
from x402.mechanisms.evm.exact import register_exact_evm_client
from x402.mechanisms.evm.signers import EthAccountSigner

NETWORK = "eip155:84532"

async def buy(url: str, key: str):
    account = Account.from_key(key)
    signer = EthAccountSigner(account)
    client = x402Client()
    client.set_spend_controls({"max_amount_per_payment": "$10.00", "allowed_assets": True})
    register_exact_evm_client(client, signer, networks=[NETWORK])
    print(f"buyer: {account.address}", flush=True)
    try:
        async with wrapHttpxWithPayment(client) as http:
            resp = await http.post(f"{url}/v1/brief", json={})
            print(f"status: {resp.status_code}")
            print(resp.text[:500])
    except BaseException as e:
        print("TOP:", type(e).__name__, repr(str(e))[:300])
        cause = e.__cause__
        depth = 0
        while cause is not None and depth < 6:
            print(f"CAUSE[{depth}]:", type(cause).__name__, repr(str(cause))[:300])
            cause = cause.__cause__
            depth += 1
        traceback.print_exc()

ap = argparse.ArgumentParser()
ap.add_argument("--url", default="http://localhost:8000")
ap.add_argument("--key", required=True)
a = ap.parse_args()
asyncio.run(buy(a.url, a.key))
