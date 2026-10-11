# wakeandnorth tollbooth — BUILD.md

The till: an x402 v2 paid earn-first brief endpoint. Wake's demo brief spec v1
landed 2026-10-10 and is wired to `POST /brief/order`; the original
`POST /v1/brief` scaffold (stub body) is kept working unchanged.

## Stack (verified 2026-10-07)

- `x402[fastapi,evm]==2.25.0` (PyPI, official x402-foundation SDK, Linux Foundation)
- `fastapi==0.142.4`, `uvicorn[standard]==0.38.0`, `eth-account==0.13.7`, `httpx==0.28.1`
- Python 3.12 venv at `build/tollbooth/.venv/`
- **Stack decision: Python holds.** The `x402[fastapi]` middleware is mature
  (585-line `fastapi.py`: adapter pattern, settlement cancellation on handler
  failure, no-settle-on-4xx, per-phase hooks). No Express fallback needed.

## What works

- `POST /v1/brief` → HTTP 402 with `PAYMENT-REQUIRED` header (x402 v2):
  scheme `exact`, price `$2.00` (= 2000000 atomic USDC), network
  `eip155:84532` (Base Sepolia), asset `0x036CbD53842c5426634e7929541eC2318f3dCF7e`,
  `maxTimeoutSeconds: 300`, `extra.paymentFlow: "upfront"`.
- Free facilitator `https://x402.org/facilitator` — init succeeds, `/supported`
  returns 200. No keys needed.
- `GET /.well-known/x402` manifest (operator `wakeandnorth`).
- `GET /v1/brief/sample` — free redacted sample of the brief shape.
- `GET /health` — includes ledger stats.
- SQLite idempotency ledger (`ledger.py`, `ledger.db`):
  `verified → settled → delivered`; nonce = EIP-3009 nonce hex.
  - `on_after_settle` hook writes `settled` + tx_hash before the handler runs
    (upfront flow), so the handler always sees the receipt data.
  - Handler: `delivered` nonce → returns stored bytes (never regen, never
    re-charge); `settled` → serves brief, marks `delivered` via
    BackgroundTasks AFTER the response flushes.
  - 48h row expiry. Lifecycle unit-tested (`/tmp` throwaway test).
- `buyer.py` — demo buyer script (`x402Client` + `wrapHttpxWithPayment` +
  `EthAccountSigner`). Usage: `python buyer.py --url http://localhost:8000 --key 0x...`
- `envfix.py` — VM quirk: strips bracketed IPv6 (`[::1]`) from no_proxy before
  httpx loads, else httpx raises `InvalidURL: Invalid port: ':1]'`.

## What's stubbed

- `POST /v1/brief` still serves `_stub_brief()` (clearly-marked PLACEHOLDER).
  The real engine lives on `POST /brief/order` (spec v1, wired 2026-10-10).
- NOTE (Wake's ask, done 2026-10-07): the receipt echo carries `payment_nonce`
  inside the receipt object, not just at the brief top level — her buyer script
  matches echo-to-request on it. `/brief/order` receipts carry `payment_nonce`
  inside `receipt` per the v1 spec.

## PROVEN end-to-end (2026-10-07, Base Sepolia testnet)

- Full paid loop via `buyer.py`: 402 → sign → verify → settle → 200 with brief.
  Two live settlements confirmed on-chain (tx `0xfc8dff07…`, `0xd5f1afc0…`).
- Receipt echo in body carries nonce + tx_hash + Basescan URL; PAYMENT-RESPONSE
  header carries the settlement receipt. Both verified in the 200 response.
- Ledger lifecycle verified: `verified → settled → delivered`, 2 rows delivered.
- Replay test (`debug_replay.py`): resending a consumed PAYMENT-SIGNATURE is
  rejected by the facilitator (`invalid_exact_evm_transaction_failed`) — no
  double-charge, no double-grant. Exactly-once holds.
- Buyer wallet funded via Circle faucet (20 testUSDC; ~14 remaining after tests).
- Buyer-side fixes found during proving: default x402 spend cap is $1 (raised to
  $10 via `set_spend_controls`); httpx default 5s timeout too short for upfront
  settlement (raised to 120s). Both fixed in `buyer.py`.
- Test tools kept: `debug_verify.py` (direct facilitator verify/settle),
  `debug_replay.py` (replay rejection), `check_balance.py` (RPC balance).

## 2026-10-10: brief spec v1 wired (`POST /brief/order`)

Wake's demo brief spec v1 (`~/workspace/wake-channel/inbox/room-20261010T111700Z-brief-spec-demo.md`)
is implemented and proven on Base Sepolia testnet.

**New endpoint:** `POST /brief/order` with JSON body `{"topic": str, "nonce": str}`
(both required, non-empty). Same x402 `exact` / $2.00 / Base Sepolia protection
as `/v1/brief` (same `accepts` config, upfront paymentFlow). New module
`briefs.py` holds the deterministic brief engine; `ledger.py` grew a `topic`
column and a `settled_signatures` table; `app.py` diff is small and reviewable.

**Brief JSON (spec-shaped):**
`{"id": "brief-<first-8-of-nonce>", "topic", "nonce", "createdAt", "content", "receipt"}`
where `receipt = {"payer", "amountUsdc": "2.00", "asset", "network": "eip155:84532",
"settleTx", "verifiedAt", "payment_nonce", "explorer_url"}`. `payment_nonce`
echoes the EIP-3009 payment nonce inside the receipt (Wake's buyer matches
echo-to-request on it). `explorer_url` is additive to the spec (carried over
from the proven `/v1/brief` receipt). `verifiedAt` = the ledger's `settled_at`.

**Determinism:** seed = sha256(`topic` + "|" + `nonce`); seed-derived pick of
2–4 corpus items in stable order. Byte-identical re-serves are a CACHE
property: the first generated brief is stored canonically and never
regenerated for a stored nonce (timestamps pinned at first generation).
Same (topic, nonce) -> same bytes, guaranteed by serving the stored bytes.

**Corpus honesty:** items come ONLY from the kin-treasury bounty watch log
(real URLs, source date marked per item — today: Superteam Earn Madrid
$2,000 bounty + agent-bounties claimable feed). No invented bounties, no
fabricated links. Topics matching nothing get the items section honestly
omitted ("Omitted rather than invented").

**Replay semantics (three layers, exactly-once preserved):**
1. `replay_guard` middleware: incoming PAYMENT-SIGNATURE positively identified
   (sha256 of the raw header) as a duplicate of a successfully settled payment
   -> **409 `{"error": "nonce already settled", <stored brief>}`**, original
   receipt re-served, no facilitator round-trip. The signature table is written
   ONLY after successful settle + 200, so it can never shadow a live payment.
2. Handler ledger paths (unchanged semantics): `delivered` -> 200 stored bytes,
   never regen; `settled`-but-undelivered -> serve + mark delivered after flush.
3. Facilitator backstop (proven 2026-10-07): unknown/duplicate signatures that
   reach the facilitator are rejected on-chain (`invalid_exact_evm_transaction_failed`).
   A DIFFERENT signature reusing a settled nonce never matches the signature
   table -> passes to the facilitator -> rejected there (402), per the spec.

**400-before-money:** with upfront paymentFlow the facilitator settles BEFORE
the handler, so a handler-level 400 would charge $2 for a malformed request.
`validate_brief_order_body` middleware rejects bad bodies with 400 BEFORE the
x402 middleware runs — bad bodies never touch money.

**Also added:** `GET /catalog` (free topic list); `/.well-known/x402` manifest
now lists `brief_order` + `catalog`. Existing `/v1/brief`, `/v1/brief/sample`,
`/health` routes work unchanged (verified 402/200s after the change).

**Verified 2026-10-10:**
- Unit (`test_brief_unit.py`): 32/32 pass — determinism, byte-identical builds,
  topic matching/omission, ledger lifecycle + signature table, ASGI-level 400s
  (7 bad-body shapes), 402 with PAYMENT-REQUIRED decoding to $2.00/exact/Base
  Sepolia, free routes alive.
- Live (`test_live_brief.py`, Base Sepolia, real test-USDC): 402 -> sign
  (EIP-3009, body nonce == payment nonce via patched `create_nonce`) -> 200
  with spec-shaped brief + receipt (echo matched, `settleTx=0xfe41b466…`,
  `PAYMENT-RESPONSE` header present); exactly $2.00 charged on-chain; replay of
  the identical signature -> **409** with byte-identical brief and original
  receipt; balance unchanged after replay (no new charge). Buyer test wallet
  `0x44A763Ea9BD759Ca22E0430A6Ec24B68Df552ba3`: 14.00 -> 6.00 over 4 test
  purchases ($8 test-USDC; two extra runs were test-script balance-poll fixes,
  not server issues).
- Prior live settlements: `0xbba94459…`, `0x2f7cbcc1…`, `0x4dadf199…`, `0xfe41b466…`
  (all Base Sepolia).

**2026-10-11: judge-path rehearsal on the refactored (laned) code:**
- Live (`test_live_brief.py`, Base Sepolia, real test-USDC): 402 -> sign ->
  200 with spec-shaped brief + receipt (echo matched, `settleTx=0xf48e14d3…`,
  exactly $2.00 charged: 6.00 -> 4.00); replay of the identical signature ->
  **409** with byte-identical brief and original receipt; balance unchanged
  after replay (no new charge). Receipt verified field-for-field: network
  `eip155:84532`, asset `0x036CbD53842c5426634e7929541eC2318f3dCF7e`,
  explorer URL `https://sepolia.basescan.org/tx/0xf48e14d3…`.
- The Solana-lane refactor (shared `_serve_brief_order`, lane-parameterized
  receipts, extended `_nonce_from_payload`) changed nothing on the Base path:
  32/32 unit tests still green, live purchase + replay identical semantics.

**Spec deviations (honest, documented):**
- Facilitator URL: spec names `https://facilitator.x402.org`, but it does not
  resolve from this environment (connection failed); kept the proven
  `https://x402.org/facilitator` (default, overridable via `X402_FACILITATOR_URL`).
- `explorer_url` added to the receipt beyond the spec's six fields (proven
  `/v1/brief` shape; useful for the demo).
- 409 (not 200) for duplicate identical signatures per the spec's replay
  section; the handler-level `delivered` -> 200 re-serve remains as backstop.
- Wake's spec mentions a JSONL nonce ledger (`paid-calls-ledger.json`); the
  SQLite ledger + `settled_signatures` table implements the same contract
  (append-once per settled nonce, keyed lookup) — no JSONL file created.

## Run

```
cd build/tollbooth
.venv/bin/uvicorn app:app --port 8000
```

Test wallet (payTo, Base Sepolia): `0xD18A5d9dBa628D489aA301E95056049CA33999B0`
— key in `wallets/test-payto.json` (gitignored, chmod 600). TESTNET ONLY.

## 2026-10-11: thin Solana lane (`POST /solana/brief/order`, experimental)

Depth stays on Base Sepolia. The Solana lane is thin and honest: a real x402
v2 `exact` 402 challenge on Solana devnet (`solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1`,
USDC mint `4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU`, $2.00, real devnet
payTo `87GaH47ytRBPBSwVu4CPKom3L5q7z29pjBL1ewpbmnMg`), the same deterministic
brief engine, the same ledger semantics (`settled -> delivered`, exactly-once;
Solana idempotency key = `sol:` + first tx signature hex). New module
`solana_lane.py`; `app.py` registers `ExactSvmScheme` (from `x402[svm]`) and
shares one `_serve_brief_order` handler across lanes; manifest + catalog list
the lane with `"status": "experimental"`.

Settlement on this lane is NOT yet proven: Solana devnet RPC was unreachable
from this environment (empty responses through the egress proxy), so no buyer
funding or live purchase was possible. The lane is labeled experimental in the
manifest, catalog, route description, and module docstring. Base Sepolia
remains the proven demo path.

## Not done / decisions for later

- Mainnet cutover (CDP facilitator + API key signup) — testnet loop proven 2026-10-07; cut over when the demo needs real receipts.
- Treasury wallet: payTo is currently a throwaway test wallet. The shared
  `wakeandnorth` treasury address is a wire decision, not taken here.
- Thin Solana presence — out of scope for this scaffold.
- `ledger.db` is gitignored runtime state; fine for demo, Postgres if this ever
  needs to survive real traffic.
