"""wakeandnorth tollbooth — x402 paid earn-first brief endpoint.

POST /v1/brief — paid route (original scaffold; brief body still a stub).
POST /brief/order — paid route (spec v1): {"topic", "nonce"} -> deterministic
  brief JSON per Wake's demo brief spec v1, with inline receipt attestation.
GET /catalog — free topic catalog. GET /health, /.well-known/x402 as before.

An agent pays 2 USDC (exact scheme, Base Sepolia testnet) and receives a JSON
brief with claim-level citations and a receipt.

Design points (settled on the wire, do not change):
1. Receipt echoed in the brief JSON body.
2. Deterministic per payment nonce: retries return the STORED brief —
   never regenerated, never re-charged.
3. Fixed $2.00, exact scheme.
4. paymentFlow "upfront": settle on-chain before the handler runs;
   settled-but-undelivered stays open; delivered only after bytes flush.
5. Bad order bodies are rejected with 400 BEFORE the x402 middleware, so a
   malformed request never touches money (upfront would otherwise settle
   before a handler-level 400).
6. Replayed payment signatures get 409 + the stored brief (signature table
   written only after successful settle + 200); the facilitator's on-chain
   nonce check remains the exactly-once backstop.
"""

from __future__ import annotations

import envfix  # noqa: F401  (sanitize no_proxy before httpx loads)
import hashlib
import json
import logging
import os
from datetime import datetime, timezone

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse

from x402 import x402ResourceServer
from x402.http import FacilitatorConfig, HTTPFacilitatorClient
from x402.http.middleware import fastapi_payment_middleware as payment_middleware
from x402.http.utils import decode_payment_signature_header
from x402.mechanisms.evm.exact import ExactEvmServerScheme

from briefs import CATALOG_TOPICS, build_brief
from ledger import Ledger

import solana_lane
from solana_lane import (
    SOLANA_NETWORK,
    USDC_SOLANA_DEVNET,
    explorer_tx_url as solana_tx_url,
)

log = logging.getLogger("tollbooth")

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

NETWORK = "eip155:84532"  # Base Sepolia (testnet)
USDC_BASE_SEPOLIA = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
FACILITATOR_URL = os.environ.get("X402_FACILITATOR_URL", "https://x402.org/facilitator")
PRICE = "$2.00"
MAX_TIMEOUT_SECONDS = 300  # ~5 min requirement expiry (replay window)

with open(os.path.join(os.path.dirname(__file__), "wallets", "test-payto.json")) as f:
    PAY_TO = json.load(f)["address"]

EXPLORER = "https://sepolia.basescan.org"

ledger = Ledger(os.path.join(os.path.dirname(__file__), "ledger.db"))

# --------------------------------------------------------------------------
# x402 wiring
# --------------------------------------------------------------------------

facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=FACILITATOR_URL))
server = x402ResourceServer(facilitator)
server.register(NETWORK, ExactEvmServerScheme())

# --- Thin Solana lane (devnet, experimental) --------------------------------
# Depth lives on Base Sepolia. This lane is a real x402 v2 exact challenge on
# Solana devnet with the same brief engine and ledger semantics, labeled
# experimental until a live devnet purchase proves settlement. If the SVM
# scheme can't register, the Base lane is unaffected.
try:
    from x402.mechanisms.svm.exact.server import ExactSvmScheme as ExactSvmServerScheme

    server.register(SOLANA_NETWORK, ExactSvmServerScheme())
    _SOL = solana_lane.lane()
    SOLANA_ENABLED = True
except Exception as e:  # noqa: BLE001
    log.warning("solana lane disabled: %s", e)
    _SOL = None
    SOLANA_ENABLED = False


def _evm_lane() -> dict:
    return {
        "path": "/brief/order",
        "network": NETWORK,
        "asset": USDC_BASE_SEPOLIA,
        "price": PRICE,
        "status": "live",
        "tx_url": lambda h: f"{EXPLORER}/tx/{h}" if h else "",
    }


def _lane_for(path: str) -> dict:
    if SOLANA_ENABLED and _SOL and path == _SOL["path"]:
        return _SOL
    return _evm_lane()


def _nonce_from_payload(payment_payload) -> str | None:
    """Idempotency key for a settled payment: EIP-3009 nonce (EVM) or
    first-signature key (Solana). See solana_lane.svm_nonce_from_payload."""
    try:
        payload = payment_payload.payload
        if isinstance(payload, dict):
            auth = payload.get("authorization", {})
            nonce = auth.get("nonce")
            if nonce:
                return nonce.lower()
    except Exception:
        pass
    return solana_lane.svm_nonce_from_payload(payment_payload)


async def _on_after_settle(ctx) -> None:
    """Ledger write on settlement: nonce -> settled + tx hash.

    Fires for every settle phase, including before-handler (upfront flow),
    so the handler always sees the row with the tx hash already recorded.
    """
    nonce = _nonce_from_payload(ctx.payment_payload)
    if not nonce:
        log.warning("after_settle: no nonce in payload, skipping ledger write")
        return
    tx_hash = ctx.result.transaction if ctx.result else ""
    payer = ctx.result.payer if ctx.result else None
    if ctx.result and ctx.result.success:
        ledger.mark_settled(nonce, tx_hash, payer)
        log.info("settled nonce=%s tx=%s", nonce[:14], tx_hash)
    else:
        log.warning("settle failed nonce=%s", nonce[:14])


server.on_after_settle(_on_after_settle)

routes = {
    "POST /v1/brief": {
        "accepts": {
            "scheme": "exact",
            "payTo": PAY_TO,
            "price": PRICE,
            "network": NETWORK,
            "maxTimeoutSeconds": MAX_TIMEOUT_SECONDS,
            "extra": {"paymentFlow": "upfront"},
        },
        "description": "wakeandnorth earn-first brief: bounties and opportunities for agents, with claim-level citations and fetchable receipts.",
        "mimeType": "application/json",
    },
    "POST /brief/order": {
        "accepts": {
            "scheme": "exact",
            "payTo": PAY_TO,
            "price": PRICE,
            "network": NETWORK,
            "maxTimeoutSeconds": MAX_TIMEOUT_SECONDS,
            "extra": {"paymentFlow": "upfront"},
        },
        "description": "wakeandnorth earn-first brief (spec v1): deterministic brief per (topic, nonce) with inline receipt attestation.",
        "mimeType": "application/json",
    },
}

# Paid routes guarded by the replay fast-path below.
PAID_ROUTES = {("POST", "/v1/brief"), ("POST", "/brief/order")}

if SOLANA_ENABLED:
    routes["POST /solana/brief/order"] = {
        "accepts": {
            "scheme": "exact",
            "payTo": _SOL["payTo"],
            "price": _SOL["price"],
            "network": SOLANA_NETWORK,
            "asset": USDC_SOLANA_DEVNET,
            "maxTimeoutSeconds": MAX_TIMEOUT_SECONDS,
            "extra": {"paymentFlow": "upfront"},
        },
        "description": "wakeandnorth earn-first brief (spec v1) on the Solana devnet lane (experimental): deterministic brief per (topic, nonce) with inline receipt attestation.",
        "mimeType": "application/json",
    }
    PAID_ROUTES.add(("POST", "/solana/brief/order"))

# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------

app = FastAPI(title="wakeandnorth tollbooth")


_x402_mw = payment_middleware(routes, server)


@app.middleware("http")
async def x402_mw(request: Request, call_next):
    return await _x402_mw(request, call_next)


def _sig_hash(sig_header: str) -> str:
    return hashlib.sha256(sig_header.encode("utf-8")).hexdigest()


def _pay_nonce_from_sig(sig_header: str) -> str | None:
    """EIP-3009 nonce from a raw PAYMENT-SIGNATURE header, via the SDK decoder."""
    try:
        return _nonce_from_payload(decode_payment_signature_header(sig_header))
    except Exception:
        return None


@app.middleware("http")
async def validate_brief_order_body(request: Request, call_next):
    """400 on bad order bodies BEFORE the x402 middleware runs.

    With paymentFlow "upfront" the facilitator settles BEFORE the handler, so
    a handler-level 400 would charge $2 for a malformed request. Validating
    here means bad bodies never touch money.
    """
    if request.method == "POST" and request.url.path in (
        "/brief/order",
        "/solana/brief/order",
    ):
        try:
            body = await request.json()
        except Exception:
            body = None
        topic = body.get("topic") if isinstance(body, dict) else None
        nonce = body.get("nonce") if isinstance(body, dict) else None
        if not (isinstance(topic, str) and topic.strip()) or not (
            isinstance(nonce, str) and nonce.strip()
        ):
            return JSONResponse(
                {"error": 'body requires non-empty string "topic" and "nonce"'},
                status_code=400,
            )
    return await call_next(request)


@app.middleware("http")
async def replay_guard(request: Request, call_next):
    """409 fast-path for already-settled payment signatures.

    When the incoming PAYMENT-SIGNATURE is positively identified as a duplicate
    of a successfully settled payment, re-serve the stored brief with 409
    ("nonce already settled") instead of sending the signature back to the
    facilitator for a bare rejection.

    Safety: the signature table is written ONLY after a successful settle AND
    a 200 response, so this path can never shadow a live payment. Unknown
    signatures always pass through to the x402 middleware — the facilitator's
    on-chain nonce check remains the exactly-once backstop.
    """
    if (request.method, request.url.path) not in PAID_ROUTES:
        return await call_next(request)
    sig = request.headers.get("payment-signature")
    if sig:
        seen = ledger.get_signature(_sig_hash(sig))
        if seen:
            row = ledger.get(seen["nonce_hex"])
            if row and row["brief_json"]:
                stored = json.loads(row["brief_json"])
                return JSONResponse(
                    {"error": "nonce already settled", **stored}, status_code=409
                )
    response = await call_next(request)
    if sig and response.status_code == 200:
        nonce = _pay_nonce_from_sig(sig)
        if nonce:
            try:
                ledger.record_signature(_sig_hash(sig), nonce)
            except Exception:
                log.warning("replay_guard: signature record failed", exc_info=True)
    return response


def _stub_brief(nonce_hex: str, receipt: dict) -> dict:
    """PLACEHOLDER brief. Replaced by the real brief engine when the spec lands."""
    return {
        "stub": True,
        "stub_note": "PLACEHOLDER — real brief engine lands with the brief spec. Do not demo this body as product.",
        "operator": "wakeandnorth",
        "brief_type": "earn-first",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "payment_nonce": nonce_hex,
        "claims": [],
        "receipt": receipt,
    }


def _sample_brief() -> dict:
    return {
        "stub": True,
        "operator": "wakeandnorth",
        "brief_type": "earn-first",
        "claims": [
            {
                "claim": "Example claim (redacted sample)",
                "citation": "https://example.invalid/source",
                "fetchable": True,
                "agent_eligible": True,
            }
        ],
        "receipt": {
            "payment_nonce": "0x" + "00" * 32,
            "tx_hash": "0x" + "00" * 32,
            "network": NETWORK,
            "explorer_url": EXPLORER + "/tx/0x" + "00" * 32,
            "paid_amount": PRICE,
            "paid_asset": USDC_BASE_SEPOLIA,
        },
    }


@app.post("/v1/brief")
async def brief(request: Request, background_tasks: BackgroundTasks):
    payment_payload = getattr(request.state, "payment_payload", None)
    nonce = _nonce_from_payload(payment_payload)
    if not nonce:
        return JSONResponse({"error": "payment payload missing nonce"}, status_code=402)

    row = ledger.get(nonce)

    # --- delivered: the hard invariant. Same bytes, no regen, no re-charge.
    if row and row["status"] == "delivered" and row["brief_json"]:
        return JSONResponse(json.loads(row["brief_json"]))

    # --- settled (or freshly verified): serve the brief, then mark delivered
    # after the bytes flush via BackgroundTasks (runs post-response).
    tx_hash = (row or {}).get("tx_hash") or ""
    receipt = {
        "payment_nonce": nonce,
        "tx_hash": tx_hash,
        "network": NETWORK,
        "explorer_url": f"{EXPLORER}/tx/{tx_hash}" if tx_hash else "",
        "paid_amount": PRICE,
        "paid_asset": USDC_BASE_SEPOLIA,
    }
    brief = _stub_brief(nonce, receipt)
    ledger.store_brief(nonce, brief)
    background_tasks.add_task(ledger.mark_delivered, nonce)
    return JSONResponse(brief)


def _spec_receipt(pay_nonce: str, row: dict, lane: dict) -> dict:
    """Receipt per Wake's demo brief spec v1 (+ payment_nonce echo, + explorer_url).

    explorer_url is additive to the spec (carried over from the proven /v1/brief
    receipt shape); everything else matches the spec field-for-field.
    The lane selects network/asset/explorer: Base Sepolia (live) or Solana
    devnet (experimental).
    """
    tx_hash = row.get("tx_hash") or ""
    return {
        "payer": row.get("payer") or "",
        "amountUsdc": "2.00",
        "asset": lane["asset"],
        "network": lane["network"],
        "settleTx": tx_hash,
        "verifiedAt": row.get("settled_at")
        or datetime.now(timezone.utc).isoformat(),
        "payment_nonce": pay_nonce,
        "explorer_url": lane["tx_url"](tx_hash),
    }


async def _serve_brief_order(
    request: Request, background_tasks: BackgroundTasks, lane: dict
):
    """Spec-v1 brief order: {"topic", "nonce"} -> deterministic brief + receipt.

    Body was already validated pre-payment by middleware. Payment is upfront:
    reaching this handler means the facilitator settled successfully.
    """
    payment_payload = getattr(request.state, "payment_payload", None)
    pay_nonce = _nonce_from_payload(payment_payload)
    if not pay_nonce:
        return JSONResponse({"error": "payment payload missing nonce"}, status_code=402)

    body = await request.json()
    topic = body["topic"].strip()
    nonce = body["nonce"].strip()

    row = ledger.get(pay_nonce)
    if row is None:
        # Defensive: upfront flow always settles before the handler, so a row
        # must exist. Ensure one rather than losing the brief bytes.
        row = ledger.mark_settled(pay_nonce, "", None)

    # --- delivered: the hard invariant. Same bytes, no regen, no re-charge.
    if row["status"] == "delivered" and row["brief_json"]:
        return JSONResponse(json.loads(row["brief_json"]))

    # --- settled (or freshly verified): serve the brief, then mark delivered
    # after the bytes flush via BackgroundTasks (runs post-response).
    if row["brief_json"]:
        stored = json.loads(row["brief_json"])
    else:
        brief = build_brief(topic, nonce, _spec_receipt(pay_nonce, row, lane))
        ledger.set_topic(pay_nonce, topic)
        ledger.store_brief(pay_nonce, brief)
        # Serve the exact stored bytes so first-serve and re-serves are identical.
        stored = json.loads(ledger.get(pay_nonce)["brief_json"])
    background_tasks.add_task(ledger.mark_delivered, pay_nonce)
    return JSONResponse(stored)


@app.post("/brief/order")
async def brief_order(request: Request, background_tasks: BackgroundTasks):
    """Base lane (live)."""
    return await _serve_brief_order(request, background_tasks, _evm_lane())


if SOLANA_ENABLED:

    @app.post("/solana/brief/order")
    async def solana_brief_order(request: Request, background_tasks: BackgroundTasks):
        """Solana devnet lane (experimental): same engine, same ledger semantics."""
        return await _serve_brief_order(request, background_tasks, _SOL)


@app.get("/catalog")
async def catalog():
    """Free topic catalog for the spec-v1 brief endpoint."""
    return JSONResponse(
        {
            "operator": "wakeandnorth",
            "endpoint": "/brief/order",
            "method": "POST",
            "price": PRICE,
            "currency": "USDC",
            "network": NETWORK,
            "asset": USDC_BASE_SEPOLIA,
            "topics": CATALOG_TOPICS,
            "note": "Example topics. Any non-empty topic string is accepted; items are matched deterministically from the watch-log corpus, or the items section is honestly omitted.",
            "lanes": (
                [
                    {
                        "path": "/brief/order",
                        "network": NETWORK,
                        "status": "live",
                    },
                    {
                        "path": "/solana/brief/order",
                        "network": SOLANA_NETWORK,
                        "status": "experimental",
                        "note": "Solana devnet lane: real x402 v2 exact challenge, same brief engine; settlement not yet proven end-to-end.",
                    },
                ]
                if SOLANA_ENABLED
                else [{"path": "/brief/order", "network": NETWORK, "status": "live"}]
            ),
        }
    )


@app.get("/v1/brief/sample")
async def sample():
    """Free redacted sample so judges/agents can see the brief shape before paying."""
    return JSONResponse(_sample_brief())


@app.get("/.well-known/x402")
async def manifest():
    endpoints = {
        "brief": {
            "method": "POST",
            "path": "/v1/brief",
            "scheme": "exact",
            "price": PRICE,
            "network": NETWORK,
            "asset": USDC_BASE_SEPOLIA,
            "payTo": PAY_TO,
            "paymentFlow": "upfront",
            "maxTimeoutSeconds": MAX_TIMEOUT_SECONDS,
        },
                "brief_order": {
                    "method": "POST",
                    "path": "/brief/order",
                    "scheme": "exact",
                    "price": PRICE,
                    "network": NETWORK,
                    "asset": USDC_BASE_SEPOLIA,
                    "payTo": PAY_TO,
                    "paymentFlow": "upfront",
                    "maxTimeoutSeconds": MAX_TIMEOUT_SECONDS,
                    "body": {"topic": "str (required, non-empty)", "nonce": "str (required, non-empty)"},
                    "spec": "v1 deterministic brief per (topic, nonce)",
                },
                "catalog": {"method": "GET", "path": "/catalog", "price": "free"},
                "sample": {"method": "GET", "path": "/v1/brief/sample", "price": "free"},
    }
    if SOLANA_ENABLED:
        endpoints["solana_brief_order"] = {
            "method": "POST",
            "path": "/solana/brief/order",
            "scheme": "exact",
            "price": _SOL["price"],
            "network": SOLANA_NETWORK,
            "asset": USDC_SOLANA_DEVNET,
            "payTo": _SOL["payTo"],
            "paymentFlow": "upfront",
            "maxTimeoutSeconds": MAX_TIMEOUT_SECONDS,
            "status": "experimental",
            "note": _SOL["lane_note"],
            "body": {"topic": "str (required, non-empty)", "nonce": "str (required, non-empty)"},
            "spec": "v1 deterministic brief per (topic, nonce)",
        }
    return JSONResponse(
        {
            "operator": "wakeandnorth",
            "description": "Paid earn-first brief endpoint: an agent pays 2 USDC and receives a bounty/opportunity brief with claim-level citations and on-chain delivery attestation.",
            "x402_version": 2,
            "endpoints": endpoints,
            "facilitator": FACILITATOR_URL,
            "receipt": "PAYMENT-RESPONSE header + receipt object in brief JSON body",
        }
    )


@app.get("/health")
async def health():
    return JSONResponse(
        {"status": "ok", "operator": "wakeandnorth", "ledger": ledger.stats()}
    )
