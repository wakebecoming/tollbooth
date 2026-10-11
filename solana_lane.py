"""Thin Solana lane for the wakeandnorth tollbooth.

Depth lives on Base Sepolia (proven end-to-end: 402 -> sign -> settle -> 200,
replay -> 409). This lane is thin and honest: a real Solana-devnet payTo
address, a real x402 v2 exact/Solana-devnet 402 challenge, the same
deterministic brief engine and the same ledger semantics (settled ->
delivered, exactly-once). Settlement on this lane is EXPERIMENTAL until a
live devnet purchase proves it; the lane is labeled as such everywhere it
appears.

Network facts (from the x402 Python SDK + the free facilitator's /supported):
- CAIP-2: solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1 (Solana devnet)
- USDC mint (devnet): 4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU
- Facilitator sponsors fees on this network (feePayer in /supported).
"""

import base64
import hashlib
import json
import os

SOLANA_NETWORK = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"
USDC_SOLANA_DEVNET = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"
SOLANA_EXPLORER = "https://explorer.solana.com"
SOLANA_PRICE = "$2.00"
SOLANA_STATUS = "experimental"  # flip to "live" only after a proven devnet purchase

_WALLET_PATH = os.path.join(os.path.dirname(__file__), "wallets", "solana-payto.json")


def load_payto() -> str:
    with open(_WALLET_PATH) as f:
        return json.load(f)["address"]


def explorer_tx_url(signature: str) -> str:
    return f"{SOLANA_EXPLORER}/tx/{signature}?cluster=devnet" if signature else ""


def svm_nonce_from_payload(payment_payload) -> str | None:
    """Idempotency key for a Solana exact payment payload.

    The v2 SVM payload carries a base64-encoded Solana transaction. The key is
    ``sol:`` + the hex of the transaction's first signature (the payer's),
    which is also the value the facilitator will report as the settlement
    transaction. Falls back to a hash of the raw transaction bytes if the
    wire shape is unexpected. Returns None when no transaction is present.
    """
    try:
        payload = getattr(payment_payload, "payload", None)
        if payload is None:
            return None
        tx_b64 = None
        if isinstance(payload, dict):
            tx_b64 = payload.get("transaction")
        else:
            tx_b64 = getattr(payload, "transaction", None)
        if not tx_b64:
            return None
        raw = base64.b64decode(tx_b64)
        # Legacy Solana tx wire format: 1-byte signature count, then 64-byte sigs.
        if len(raw) > 65 and raw[0] == 1:
            return "sol:" + raw[1:65].hex()
        return "sol:" + hashlib.sha256(raw).hexdigest()[:32]
    except Exception:
        return None


def lane() -> dict:
    """Lane constants for the /solana/brief/order route and receipt builder."""
    return {
        "path": "/solana/brief/order",
        "network": SOLANA_NETWORK,
        "asset": USDC_SOLANA_DEVNET,
        "payTo": load_payto(),
        "price": SOLANA_PRICE,
        "status": SOLANA_STATUS,
        "tx_url": explorer_tx_url,
        "lane_note": (
            "Solana devnet lane (experimental): real x402 v2 exact challenge, "
            "same brief engine and ledger semantics as the Base lane. "
            "Settlement not yet proven end-to-end."
        ),
    }
