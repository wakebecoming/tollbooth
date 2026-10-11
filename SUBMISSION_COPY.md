# Colosseum submission copy — tollbooth (wakeandnorth)

## Title (≤40 chars)

tollbooth — x402 paid brief endpoint

## One-liner (≤120 chars)

An agent pays $2.00 USDC and gets a bounty brief with claim-level citations and on-chain delivery attestation. No accounts, no keys.

## Description (3–4 sentences)

AI agents need data they can pay for without accounts, API keys, or trust.
Tollbooth is an x402 v2 endpoint where the payment is the auth: a buyer agent
pays exactly $2.00 USDC on Base, and receives a deterministic bounty/opportunity
brief with claim-level citations and the on-chain settlement receipt echoed
back for independent verification. Replayed payments return the original brief
with no second charge — exactly-once, enforced in three layers. Built by
wakeandnorth (North + Wake) for the Crypto World's Fair; proven live on Base
Sepolia testnet.

## Suggested track

**Payments** — closest fit: the product is a working x402 payment flow
(402 → sign → settle → 200) with facilitator-verified settlement and replay
protection. Confirm against the actual track list on the form.

## What's proven

- Full paid loop live on Base Sepolia: 402 → EIP-3009 sign → facilitator
  settle → 200 with spec-shaped brief + receipt (6 on-chain settlements,
  independently verifiable on Basescan Sepolia — links in README).
- Exactly $2.00 charged per purchase; replay of a consumed signature →
  **409** with byte-identical brief and unchanged buyer balance (no
  double-charge).
- 32/32 unit tests: determinism, byte-identical re-serves, ledger lifecycle,
  signature table, 7 malformed-body shapes rejected with 400 *before* money,
  402 challenge decoding, free routes.
- Corpus honesty: brief items come only from a real dated bounty watch log;
  unmatched topics get items omitted, never invented.
- Free routes live: `/catalog`, `/v1/brief/sample`, `/health`,
  `/.well-known/x402` manifest.

## Links for the form

- Repo: https://github.com/wakebecoming/tollbooth (public)
- Demo video: _to be recorded_ (≤3 min, screen recording, real wallet, real data)
- Pitch video: _Dudley's to record_ (≤2 min, founder voice: problem, solution, team, traction)
- Live demo URL: _undecided_ — local run + video, or a public tunnel; Dudley's call
