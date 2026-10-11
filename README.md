# tollbooth — x402 paid earn-first brief endpoint

An agent pays **$2.00 USDC** and receives a bounty/opportunity brief with
claim-level citations and an on-chain delivery attestation. Built by
**wakeandnorth** (North + Wake) for the Colosseum Crypto World's Fair 2026.

**Testnet only.** Every payment below moves test-USDC on Base Sepolia. No real
money is involved anywhere in this repo.

## What it is

AI agents need a way to pay for data without accounts, API keys, or trust.
`tollbooth` is a working answer: an [x402](https://www.x402.org/) v2 endpoint
where the payment *is* the auth. A buyer agent hits `POST /brief/order` with a
topic, gets a `402 Payment Required` challenge, signs an EIP-3009 authorization
for exactly $2.00 USDC, a facilitator settles it on-chain, and the server
returns a deterministic brief — with the settlement transaction echoed back in
the receipt so the buyer can verify it independently.

## How it works

```
buyer → POST /brief/order {"topic","nonce"} → 402 + PAYMENT-REQUIRED header
buyer → signs EIP-3009 auth ($2.00 USDC, Base Sepolia) → retries with PAYMENT-SIGNATURE
server → facilitator verifies → settles on-chain → 200 + brief + receipt
replay of a consumed signature → 409, original brief re-served, no new charge
```

- **Scheme:** x402 v2 `exact`, price `$2.00` (= 2,000,000 atomic USDC)
- **Network:** `eip155:84532` (Base Sepolia)
- **Asset:** USDC `0x036CbD53842c5426634e7929541eC2318f3dCF7e`
- **Facilitator:** the free `https://x402.org/facilitator` (no keys needed)
- **Payment flow:** `upfront` — settlement happens before the handler runs, so
  the brief always carries real receipt data

### Exactly-once (three layers)

1. **Replay guard:** a resubmitted `PAYMENT-SIGNATURE` that matches a settled
   payment returns **409** with the original brief — no facilitator round-trip,
   no second charge.
2. **Ledger:** SQLite idempotency ledger (`verified → settled → delivered`);
   delivered nonces re-serve stored bytes, never regenerate, never re-charge.
3. **Facilitator backstop:** unknown or duplicate signatures that reach the
   facilitator are rejected on-chain (`invalid_exact_evm_transaction_failed`).

### 400-before-money

With upfront settlement, a malformed request could cost $2 before the handler
ever sees it. A validation middleware rejects bad bodies with `400` *before*
the x402 middleware runs — malformed requests never touch money.

## Quickstart

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --port 8000
```

In another terminal, buy a brief (buyer wallet needs Base Sepolia test-USDC —
the [Circle faucet](https://faucet.circle.com/) dispenses it free):

```bash
python buyer.py --url http://localhost:8000 --key 0x<buyer-private-key>
```

The buyer script raises the default x402 $1 spend cap to $10 and the HTTP
timeout to 120s (upfront settlement needs both) — see `buyer.py`.

## Endpoints

| Method | Route | Auth | Description |
|---|---|---|---|
| POST | `/brief/order` | **$2.00 USDC** (x402) | Order a brief. Body: `{"topic": str, "nonce": str}`, both required non-empty. Returns the spec-shaped brief + receipt. |
| GET | `/catalog` | free | Topic list for brief orders. |
| GET | `/v1/brief/sample` | free | Redacted sample of the brief shape. |
| GET | `/health` | free | Liveness + ledger stats. |
| GET | `/.well-known/x402` | free | x402 payment manifest (operator `wakeandnorth`). |
| POST | `/v1/brief` | **$2.00 USDC** (x402) | Legacy scaffold; serves a clearly-marked stub body. Kept working. |

### Brief shape

```json
{
  "id": "brief-<first-8-of-nonce>",
  "topic": "bounties",
  "nonce": "0x…",
  "createdAt": "2026-10-10T11:33:14.522454+00:00",
  "content": "# Earn-first brief — bounties\n…",
  "receipt": {
    "payer": "0x…",
    "amountUsdc": "2.00",
    "asset": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
    "network": "eip155:84532",
    "settleTx": "0x…",
    "verifiedAt": "2026-10-10T11:33:14.452083+00:00",
    "payment_nonce": "0x…",
    "explorer_url": "https://sepolia.basescan.org/tx/0x…"
  }
}
```

**Determinism:** seed = `sha256(topic + "|" + nonce)`; the seed picks 2–4
corpus items in stable order. The first generated brief is stored canonically
and never regenerated for a stored nonce — same `(topic, nonce)` always
returns byte-identical output.

## Corpus honesty

Brief items come **only** from the kin-treasury bounty watch log — real,
currently-listed opportunities (Superteam Earn listings, agent-bounties feeds),
each marked with its source and watch date. Nothing is invented; no links are
fabricated. A topic matching no current items gets the items section
**honestly omitted** ("omitted rather than invented").

## Verified on-chain receipts

Live settlements on Base Sepolia (testnet), each independently verifiable:

- [`0xfe41b466894fc5d1d060206d79c67320cd010fbae117e4461ac729aa70bc714c`](https://sepolia.basescan.org/tx/0xfe41b466894fc5d1d060206d79c67320cd010fbae117e4461ac729aa70bc714c) — spec-v1 brief, $2.00
- [`0xbba944597407031e380f4431575e690ced998eca782b24c4d5e890f725a65ced`](https://sepolia.basescan.org/tx/0xbba944597407031e380f4431575e690ced998eca782b24c4d5e890f725a65ced) — spec-v1 brief, $2.00
- [`0x2f7cbcc183fa9e5d46ef521c3fe0b74d12c1263e6478217958b89945a0a41006`](https://sepolia.basescan.org/tx/0x2f7cbcc183fa9e5d46ef521c3fe0b74d12c1263e6478217958b89945a0a41006) — spec-v1 brief, $2.00
- [`0x4dadf199c4a3fa39535ebcd8dc07cf1c3b936576b6e90f728e347bbce2efb2a5`](https://sepolia.basescan.org/tx/0x4dadf199c4a3fa39535ebcd8dc07cf1c3b936576b6e90f728e347bbce2efb2a5) — spec-v1 brief, $2.00
- [`0xfc8dff073173d01c3e76d0667259c9d25c95a79ba1ed602e0241acb2a166dc2b`](https://sepolia.basescan.org/tx/0xfc8dff073173d01c3e76d0667259c9d25c95a79ba1ed602e0241acb2a166dc2b) — scaffold proving run, $2.00
- [`0xd5f1afc00b11155305f5a6a027a4ce32cf576f486de0ab7790ba3e6f31adb3fa`](https://sepolia.basescan.org/tx/0xd5f1afc00b11155305f5a6a027a4ce32cf576f486de0ab7790ba3e6f31adb3fa) — scaffold proving run, $2.00

Replay of a consumed signature returns **409** with the byte-identical brief;
buyer balance is unchanged (no second charge) — verified live.

## Tests

```bash
.venv/bin/python test_brief_unit.py    # 32/32: determinism, ledger lifecycle,
                                       # signature table, 400 shapes, 402
                                       # challenge decoding, free routes
.venv/bin/python test_live_brief.py     # live Base Sepolia: 402 → sign → 200,
                                       # $2.00 charged, replay → 409
                                       # (needs funded test buyer wallet)
```

## Repo layout

```
app.py              FastAPI app, x402 wiring, replay guard, 400-before-money
briefs.py           deterministic brief engine (spec v1)
ledger.py           SQLite idempotency ledger + settled-signature table
buyer.py            demo buyer (x402Client + EthAccountSigner)
envfix.py           VM quirk: sanitize no_proxy before httpx loads
tools/              debug/replay/verify/balance scripts (dev only)
demo/               curl transcripts of the free + 402 flows
test_brief_unit.py  32 unit tests (no chain needed)
test_live_brief.py  live testnet proving script
BUILD.md            full engineering record
DISCLOSURES.md      what this is and isn't
SUBMISSION_COPY.md  Colosseum submission text
```

`wallets/` (test keys), `ledger.db` (runtime state), and `.venv/` are
gitignored and never committed.

## Team

**wakeandnorth** — North and Wake, built for the Colosseum Crypto World's
Fair 2026. Operator field: `wakeandnorth`.
