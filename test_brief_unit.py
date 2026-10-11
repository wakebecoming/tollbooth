"""Unit tests for the spec-v1 brief endpoint (no chain, no money).

Covers:
- briefs.py: deterministic selection, byte-identical builds (pinned timestamps),
  topic matching / honest omission.
- ledger.py: topic column, signature table, lifecycle on a temp DB.
- app.py (ASGI, no server): 400 on bad bodies (pre-payment), 402 with
  PAYMENT-REQUIRED and no payment, free routes alive.

Run: .venv/bin/python test_brief_unit.py
"""

from __future__ import annotations

import envfix  # noqa: F401
import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from briefs import brief_seed, build_brief, match_items, select_items
from ledger import Ledger

PASS = []
FAIL = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f" — {detail}" if detail and not cond else ""))


# --- briefs.py determinism -----------------------------------------------

t, n = "bounties", "0x" + "ab" * 32
s1 = select_items(t, n)
s2 = select_items(t, n)
check("select_items deterministic (same seed, same order)",
      [i["id"] for i in s1] == [i["id"] for i in s2] and len(s1) >= 1)
check("select_items returns 2-4 or fewer when corpus smaller",
      1 <= len(s1) <= 4, f"got {len(s1)}")
check("seed format", brief_seed(t, n) == __import__("hashlib").sha256(f"{t}|{n}".encode()).hexdigest())

r = {"payer": "0xabc", "amountUsdc": "2.00"}
b1 = build_brief(t, n, r, created_at="2026-10-10T00:00:00+00:00")
b2 = build_brief(t, n, r, created_at="2026-10-10T00:00:00+00:00")
c1 = json.dumps(b1, sort_keys=True, separators=(",", ":")).encode()
c2 = json.dumps(b2, sort_keys=True, separators=(",", ":")).encode()
check("build_brief byte-identical with pinned created_at", c1 == c2)
check("brief id uses first-8 of nonce", b1["id"] == "brief-" + n[:8], b1["id"])
check("brief has spec keys",
      set(b1) == {"id", "topic", "nonce", "createdAt", "content", "receipt"}, str(set(b1)))
check("content carries honesty line", "v1 demo brief" in b1["content"])
check("content carries seed", brief_seed(t, n) in b1["content"])

check("generic topic matches corpus", len(match_items("bounties")) >= 1)
check("specific topic matches", any(i["id"].startswith("superteam") for i in match_items("superteam")))
d = build_brief("defi", "0x" + "cd" * 32, r, created_at="2026-10-10T00:00:00+00:00")
check("unmatched topic omits items honestly",
      "Omitted rather than invented" in d["content"], d["content"][:200])
check("different nonce -> different seed -> (likely) different selection",
      brief_seed(t, n) != brief_seed(t, "0x" + "ff" * 32))

# --- ledger.py ------------------------------------------------------------

tmp = tempfile.mktemp(suffix=".db")
lg = Ledger(tmp)
nonce = "0x" + "11" * 32
row = lg.mark_settled(nonce, "0xtx", "0xpayer")
check("mark_settled", row["status"] == "settled" and row["tx_hash"] == "0xtx")
lg.set_topic(nonce, "bounties")
check("set_topic", lg.get(nonce)["topic"] == "bounties")
brief = build_brief("bounties", nonce, r, created_at="2026-10-10T00:00:00+00:00")
lg.store_brief(nonce, brief)
g = lg.get(nonce)
check("store_brief round-trips canonical bytes",
      json.loads(g["brief_json"])["id"] == "brief-" + nonce[:8])
lg.mark_delivered(nonce)
check("mark_delivered", lg.get(nonce)["status"] == "delivered")
# delivered rows are never touched
lg.mark_settled(nonce, "0xother", "0xother")
check("delivered row immutable", lg.get(nonce)["tx_hash"] == "0xtx")

sh = "deadbeef" * 8
check("get_signature miss", lg.get_signature(sh) is None)
lg.record_signature(sh, nonce)
got = lg.get_signature(sh)
check("record_signature/get_signature", got and got["nonce_hex"] == nonce)
os.unlink(tmp)

# --- app.py via ASGI (no network beyond import-time facilitator sync) -----

import httpx


async def asgi_tests():
    from app import app  # noqa: F401  (import triggers facilitator sync; proven env)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        # bad bodies -> 400, pre-payment (no PAYMENT-SIGNATURE sent)
        for bad, label in [
            ({}, "empty object"),
            ({"topic": "bounties"}, "missing nonce"),
            ({"nonce": "0x123"}, "missing topic"),
            ({"topic": "", "nonce": "0x123"}, "empty topic"),
            ({"topic": "bounties", "nonce": ""}, "empty nonce"),
            ({"topic": 5, "nonce": "0x123"}, "non-string topic"),
        ]:
            r = await http.post("/brief/order", json=bad)
            check(f"400 on bad body ({label})", r.status_code == 400, f"got {r.status_code}")
        # non-JSON body -> 400
        r = await http.post("/brief/order", content=b"not json", headers={"content-type": "text/plain"})
        check("400 on non-JSON body", r.status_code == 400, f"got {r.status_code}")

        # good body, no payment -> 402 with PAYMENT-REQUIRED
        r = await http.post("/brief/order", json={"topic": "bounties", "nonce": "0x" + "ee" * 32})
        check("402 with PAYMENT-REQUIRED (no payment)",
              r.status_code == 402 and "payment-required" in {k.lower() for k in r.headers},
              f"got {r.status_code}")
        try:
            from x402.http.utils import decode_payment_required_header
            pr = decode_payment_required_header(r.headers["payment-required"])
            req = pr.accepts[0]
            check("402 requirement is $2.00 exact / Base Sepolia",
                  req.amount == "2000000" and req.network == "eip155:84532" and req.scheme == "exact",
                  f"{req.amount} {req.network} {req.scheme}")
        except Exception as e:  # noqa: BLE001
            check("402 requirement decodes", False, str(e))

        # free routes alive
        r = await http.get("/catalog")
        check("GET /catalog 200 with topics",
              r.status_code == 200 and "bounties" in r.json().get("topics", []), f"got {r.status_code}")
        r = await http.get("/health")
        check("GET /health 200", r.status_code == 200, f"got {r.status_code}")
        r = await http.get("/.well-known/x402")
        eps = r.json().get("endpoints", {})
        check("manifest lists brief/order", "brief_order" in eps and "catalog" in eps)
        r = await http.get("/v1/brief/sample")
        check("GET /v1/brief/sample 200", r.status_code == 200, f"got {r.status_code}")


asyncio.run(asgi_tests())

print(f"\n{PASS.__len__()} passed, {FAIL.__len__()} failed")
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
