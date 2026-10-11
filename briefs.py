"""Deterministic earn-first brief engine (v1 demo) for the wakeandnorth tollbooth.

Builds the brief JSON per Wake's demo brief spec v1:

- Deterministic per (topic, nonce): seed = sha256(topic + "|" + nonce).
  Same seed -> same items in the same order (pure selection; no network).
- Corpus drawn ONLY from the kin-treasury bounty watch log: real findings,
  real URLs, source date marked per item. Nothing invented, no links
  fabricated. If no corpus items fit the topic, the items section is omitted
  with an honesty line instead of inventing listings.
- Byte-identical re-serves are a CACHE property, not a generation property:
  the ledger stores the first generated brief and never regenerates for a
  stored nonce (timestamps are pinned at first generation).

Source of the corpus:
  ~/workspace/goals/kin-treasury-earn-first-bootstrap/hidden_files/watch-log.md
"""

from __future__ import annotations

import hashlib
import random
import re
from datetime import datetime, timezone

SPEC_VERSION = "v1"

# --------------------------------------------------------------------------
# Corpus — real watch-log findings only.
# --------------------------------------------------------------------------

CORPUS: list[dict] = [
    {
        "id": "superteam-encuentro-madrid-2026",
        "kind": "bounty",
        "title": "Crea Contenido para Promocionar El Encuentro 2026 en Madrid",
        "reward": "$2,000 USDG (fixed)",
        "source": "Superteam Earn",
        "url": "https://earn.superteam.fun/listings/bounties/crea-contenido-para-promocionar-el-encuentro-2026/",
        "source_date": "2026-10-10",
        "status": (
            "OPEN, agent-eligible (AGENT_ALLOWED), verified sponsor La Familia; "
            "Spanish-language content creation (not code); 100+ submissions as of "
            "2026-10-09; deadline 2026-10-24T22:59:59Z"
        ),
        "tags": ["superteam", "content", "marketing", "solana", "bounty", "earn", "gig"],
    },
    {
        "id": "bountybook-open-board-2026-10-11",
        "kind": "board",
        "title": "BountyBook open board — 50 funded code jobs",
        "reward": "$2.00–$5.00 USDC per job",
        "source": "BountyBook",
        "url": "https://api.bountybook.ai",
        "source_date": "2026-10-11",
        "status": (
            "OPEN, agent-claimable. Board read via API 2026-10-11: 50 open jobs "
            "with real budget_usdc ($2.00–$5.00 code jobs: EventBus TS, "
            "dict-flatten, Trie, merge_csv, etc.). Claim write-path verified "
            "working 2026-10-10 and re-confirmed 2026-10-11 (claim persisted "
            "to wallet, 24h TTL). No solution submitted — board state only."
        ),
        "tags": ["bountybook", "code", "bounty", "earn", "gig"],
    },
    {
        "id": "agentbounties-claimable-feed",
        "kind": "feed",
        "title": "Agent Bounties claimable feed (Base)",
        "reward": "varies by listing",
        "source": "agent-bounties",
        "url": "https://api.agentbounties.app/v1/base/autonomous-bounties/feed?network=base-mainnet&claimable_only=true",
        "source_date": "2026-10-11",
        "status": (
            "0 live claimable items on 2026-10-11 (both feeds empty); lanes "
            "reappear periodically (7-8 funded items in late Sep 2026) — "
            "re-poll before acting"
        ),
        "tags": ["agent-bounties", "agents", "feed", "base", "bounty", "earn"],
    },
]

CATALOG_TOPICS = ["bounties", "agent-earn", "superteam", "content", "defi"]

# Topics in this set match the whole corpus (the demo's standing watch lanes).
GENERIC_TOKENS = {
    "bounty",
    "bounties",
    "earn",
    "earning",
    "earnings",
    "opportunity",
    "opportunities",
    "gig",
    "gigs",
    "work",
    "job",
    "jobs",
    "agent",
    "agents",
}


def brief_seed(topic: str, nonce: str) -> str:
    """Deterministic seed hex for (topic, nonce)."""
    return hashlib.sha256(f"{topic}|{nonce}".encode("utf-8")).hexdigest()


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def match_items(topic: str) -> list[dict]:
    """Corpus items whose tags/title match the topic (generic topics match all)."""
    tt = _tokens(topic)
    if tt & GENERIC_TOKENS:
        return list(CORPUS)
    out = []
    for item in CORPUS:
        if tt & set(item["tags"]) or tt & _tokens(item["title"]):
            out.append(item)
    return out


def select_items(topic: str, nonce: str) -> list[dict]:
    """Seed-derived deterministic selection: 2-4 items, stable order."""
    seed = brief_seed(topic, nonce)
    pool = match_items(topic)
    rng = random.Random(int(seed, 16))
    order = list(pool)
    rng.shuffle(order)
    k = 2 + (int(seed[:2], 16) % 3)
    return order[: min(k, len(order))]


def render_content(topic: str, nonce: str, created_at: str, seed: str) -> str:
    """Deterministic markdown brief body (timestamps passed in, not generated)."""
    items = select_items(topic, nonce)
    lines = [
        f"# Earn-first brief — {topic}",
        "",
        f"- Brief ID: `brief-{nonce[:8]}`",
        f"- Generated (UTC): {created_at}",
        "- Spec: v1 demo brief (deterministic per topic+nonce)",
        f"- Seed: sha256(\"{topic}|{nonce}\") = `{seed}`",
        "",
    ]
    if items:
        lines += [
            "## Vetted opportunities",
            "",
            "_Drawn from the kin-treasury bounty watch log — source date marked per "
            "item. Nothing invented, no links fabricated._",
            "",
        ]
        for i, it in enumerate(items, 1):
            kind = "bounty" if it["kind"] == "bounty" else "lane/feed"
            lines.append(
                f"{i}. **{it['title']}** — {it['reward']} · {it['source']} "
                f"· watched {it['source_date']} · _{kind}_"
            )
            lines.append(f"   - Status: {it['status']}")
            lines.append(f"   - {it['url']}")
        lines.append("")
    else:
        lines += [
            "## Vetted opportunities",
            "",
            "_No vetted items matched this topic in the watch log. Omitted rather "
            "than invented — this brief carries no item listings for the topic._",
            "",
        ]
    lines += [
        "---",
        "_v1 demo brief — wakeandnorth tollbooth. Paid $2.00 USDC on Base Sepolia "
        "(testnet); the inline receipt carries the on-chain attestation._",
    ]
    return "\n".join(lines)


def build_brief(
    topic: str,
    nonce: str,
    receipt: dict,
    created_at: str | None = None,
) -> dict:
    """Assemble the spec-shaped brief dict. Pass created_at to pin timestamps."""
    seed = brief_seed(topic, nonce)
    created_at = created_at or datetime.now(timezone.utc).isoformat()
    return {
        "id": f"brief-{nonce[:8]}",
        "topic": topic,
        "nonce": nonce,
        "createdAt": created_at,
        "content": render_content(topic, nonce, created_at, seed),
        "receipt": receipt,
    }
