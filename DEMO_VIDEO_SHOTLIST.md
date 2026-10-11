# Demo video shotlist (≤3 min, screen recording)

Real wallet, real data, no slides. Recorded against a local server on Base
Sepolia testnet (test-USDC from the Circle faucet — no real money).

## Shot 1 — the challenge (0:00–0:20)

Terminal. Server already running (`uvicorn app:app --port 8000`).

```bash
curl -i -X POST http://localhost:8000/brief/order \
  -H "Content-Type: application/json" \
  -d '{"topic":"bounties","nonce":"demo-001"}'
```

Viewer sees: `HTTP/1.1 402 Payment Required` + `payment-required:` header.
Cut to the decoded challenge: scheme `exact`, amount `2000000` ($2.00 USDC),
network `eip155:84532` (Base Sepolia), `paymentFlow: upfront`.

**Narration beat:** "No account, no API key. The price is the auth."

## Shot 2 — the paid loop (0:20–1:20)

```bash
python buyer.py --url http://localhost:8000 --key 0x<buyer-key>
```

Viewer sees: buyer signs the EIP-3009 authorization → facilitator verifies →
settles on-chain → `200` with the full brief JSON. Scroll to the `receipt`
block: `payer`, `amountUsdc: "2.00"`, `settleTx`, `explorer_url`,
`payment_nonce` echo.

**Narration beat:** "Two dollars of test-USDC, settled on-chain, brief
delivered with the receipt inline so the buyer can verify independently."

## Shot 3 — the chain (1:20–1:50)

Browser: open the `explorer_url` from the receipt on Basescan Sepolia.
Viewer sees the $2.00 USDC transfer, confirmed.

**Narration beat:** "Don't take our word for it — here's the settlement."

## Shot 4 — the replay (1:50–2:30)

Resend the identical `PAYMENT-SIGNATURE` header from Shot 2.

Viewer sees: `409`, the byte-identical brief re-served, original receipt
intact. Show buyer balance before/after: unchanged — no second charge.

**Narration beat:** "Replay the payment and you get the same brief, not a
second charge. Exactly-once, enforced three layers deep."

## Shot 5 — the free surface + honesty (2:30–3:00)

```bash
curl http://localhost:8000/catalog
curl http://localhost:8000/v1/brief/sample
curl http://localhost:8000/health
```

**Narration beat:** "Catalog and samples are free. And every brief item comes
from a real, dated bounty watch log — unmatched topics get items omitted,
never invented."

End card: repo URL, team `wakeandnorth`, "testnet only".

---

## Pitch video (≤2 min) — Dudley's to record

Not scripted — required beats only (per the hackathon guide: founder voice,
not voiceover):

1. **Problem** — agents can't pay for data without accounts/keys/trust.
2. **Solution** — x402 paid brief endpoint; the payment is the auth.
3. **Team** — wakeandnorth: North + Wake building, Dudley the registered founder.
4. **Traction** — live on Base Sepolia testnet: 6 on-chain settlements,
   32/32 tests, replay protection proven, public repo.
