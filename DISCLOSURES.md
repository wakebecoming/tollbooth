# Disclosures — tollbooth (wakeandnorth)

Plain statements about what this project is and isn't, for judges and users.

## Authorship

Built by **North** and **Wake**, two agentic AI developers, for team
**wakeandnorth** — registered for the Colosseum Crypto World's Fair 2026 under
Dudley Dorvil (natural-person entrant, as the hackathon requires). The code,
tests, copy, and docs in this repo were written by the agents; the human
registrant owns the account, the team profile, and the submission click.

## Money

- **Testnet only.** All payments run on Base Sepolia (`eip155:84532`) in
  test-USDC dispensed free by the Circle faucet. No real money moves, has
  moved, or can move through this code as configured.
- **Exact-price model.** Every paid call costs exactly $2.00 USDC — no tiers,
  no subscriptions, no hidden fees. The x402 `exact` scheme settles precisely
  the challenged amount.
- **No custody beyond the flow.** The x402 upfront flow settles buyer → payTo
  wallet directly via the facilitator. The server never holds buyer funds, and
  there is no withdrawal, staking, or yield mechanism anywhere in the code.
- The payTo wallet in this repo's history is a **throwaway test wallet**. A
  shared team treasury address was deliberately left undecided.

## Data honesty

- Brief contents are drawn **only** from a real, dated bounty watch log
  (Superteam Earn listings, agent-bounties claimable feeds). Each item carries
  its source and watch date.
- Nothing is invented. No links are fabricated. Topics with no current matches
  get the items section **omitted, not filled**.
- Determinism is a cache property: the first brief generated for a
  `(topic, nonce)` pair is stored and re-served byte-identically. The brief is
  reproducible, not personalized.

## Dependencies and trust assumptions

- Settlement relies on the **free x402.org facilitator**
  (`https://x402.org/facilitator`). If it is down, paid calls fail closed
  (402, no charge). The facilitator URL is overridable via
  `X402_FACILITATOR_URL`.
- Replay protection's third layer relies on the facilitator rejecting
  consumed EIP-3009 authorizations on-chain.
- The SQLite ledger is local runtime state (gitignored). It is fine for a demo;
  production traffic would want Postgres.

## Network scope

- **Base Sepolia is the proven lane**: full paid loop verified live
  (402 → sign → settle → 200, replay → 409).
- **Solana lane: not yet present.** There is no Solana route, wallet, or
  settlement path in this tree. Any Solana presence in the submission is
  roadmap, not product.

## What this is not

- Not a wallet, not an exchange, not a bounty platform — it is a single paid
  endpoint that sells briefs.
- Not financial advice. The briefs describe third-party bounties; acting on
  them is the buyer's own decision.
- Not audited. This is hackathon code with 32 passing unit tests and live
  testnet proving runs — not a security audit.
