"""SQLite idempotency ledger for the wakeandnorth tollbooth.

Single-use nonce ledger. The EIP-3009 payment nonce (hex) is the idempotency
key. Row lifecycle: verified -> settled -> delivered.

Invariants (settled on the wire, do not weaken):
- A nonce marked `delivered` is NEVER regenerated and NEVER re-charged.
  Retries return the stored brief bytes.
- `settled` means money arrived on-chain but bytes have not been flushed yet.
  Settled-but-undelivered rows stay open and are re-servable.
- Only transition to `delivered` AFTER the response body is flushed.
- Rows expire after 48h; beyond that a nonce is treated as new intent.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS payments (
    nonce_hex   TEXT PRIMARY KEY,
    tx_hash     TEXT,
    payer       TEXT,
    status      TEXT NOT NULL,          -- verified | settled | delivered
    topic       TEXT,                   -- brief order topic (NULL for /v1/brief)
    brief_hash  TEXT,
    brief_json  TEXT,
    created_at  TEXT NOT NULL,
    settled_at  TEXT,
    delivered_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
-- Successfully settled payment signatures (sha256 of the raw PAYMENT-SIGNATURE
-- header). Powers the 409 fast-path: a replayed signature is identified
-- WITHOUT re-verification and re-served from the ledger. Only written after
-- a successful settle + 200 response, so it can never shadow a live payment.
CREATE TABLE IF NOT EXISTS settled_signatures (
    sig_hash    TEXT PRIMARY KEY,
    nonce_hex   TEXT NOT NULL,
    settled_at  TEXT NOT NULL
);
"""

EXPIRY = timedelta(hours=48)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Ledger:
    def __init__(self, path: str):
        self._path = path
        self._lock = threading.Lock()
        conn = sqlite3.connect(path)
        conn.executescript(SCHEMA)
        # Migrate pre-topic databases: ADD COLUMN is a no-op guard.
        try:
            conn.execute("ALTER TABLE payments ADD COLUMN topic TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists
        conn.commit()
        conn.close()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _expired(self, row: sqlite3.Row) -> bool:
        created = datetime.fromisoformat(row["created_at"])
        return datetime.now(timezone.utc) - created > EXPIRY

    # -- writes ----------------------------------------------------------

    def mark_verified(self, nonce_hex: str) -> dict:
        """First sight of a payment nonce. Idempotent: returns existing row."""
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM payments WHERE nonce_hex = ?", (nonce_hex,)
            ).fetchone()
            if row and not self._expired(row):
                return dict(row)
            conn.execute(
                "INSERT OR REPLACE INTO payments "
                "(nonce_hex, status, created_at) VALUES (?, 'verified', ?)",
                (nonce_hex, _now()),
            )
            row = conn.execute(
                "SELECT * FROM payments WHERE nonce_hex = ?", (nonce_hex,)
            ).fetchone()
            return dict(row)

    def mark_settled(self, nonce_hex: str, tx_hash: str, payer: str | None = None) -> dict:
        """Money arrived on-chain. Row stays open until bytes are delivered."""
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM payments WHERE nonce_hex = ?", (nonce_hex,)
            ).fetchone()
            if row is None or self._expired(row):
                conn.execute(
                    "INSERT OR REPLACE INTO payments "
                    "(nonce_hex, tx_hash, payer, status, created_at, settled_at) "
                    "VALUES (?, ?, ?, 'settled', ?, ?)",
                    (nonce_hex, tx_hash, payer, _now(), _now()),
                )
            elif row["status"] == "verified":
                conn.execute(
                    "UPDATE payments SET tx_hash = ?, payer = COALESCE(?, payer), "
                    "status = 'settled', settled_at = ? WHERE nonce_hex = ?",
                    (tx_hash, payer, _now(), nonce_hex),
                )
            # delivered rows are never touched: same bytes, no re-charge
            row = conn.execute(
                "SELECT * FROM payments WHERE nonce_hex = ?", (nonce_hex,)
            ).fetchone()
            return dict(row)

    def store_brief(self, nonce_hex: str, brief: dict) -> str:
        """Store the generated brief bytes; returns sha256 of canonical JSON."""
        canonical = json.dumps(brief, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        with self._lock, self._conn() as conn:
            conn.execute(
                "UPDATE payments SET brief_hash = ?, brief_json = ? "
                "WHERE nonce_hex = ?",
                (digest, canonical, nonce_hex),
            )
        return digest

    def mark_delivered(self, nonce_hex: str) -> None:
        """ONLY call after the response body has been flushed to the client."""
        with self._lock, self._conn() as conn:
            conn.execute(
                "UPDATE payments SET status = 'delivered', delivered_at = ? "
                "WHERE nonce_hex = ? AND status = 'settled'",
                (_now(), nonce_hex),
            )

    def set_topic(self, nonce_hex: str, topic: str) -> None:
        """Record the brief order topic on the payment row."""
        with self._lock, self._conn() as conn:
            conn.execute(
                "UPDATE payments SET topic = ? WHERE nonce_hex = ?",
                (topic, nonce_hex),
            )

    def record_signature(self, sig_hash: str, nonce_hex: str) -> None:
        """Remember a successfully settled payment signature (idempotent)."""
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO settled_signatures "
                "(sig_hash, nonce_hex, settled_at) VALUES (?, ?, ?)",
                (sig_hash, nonce_hex, _now()),
            )

    def get_signature(self, sig_hash: str) -> dict | None:
        """Look up a settled signature by sha256 of the raw header value."""
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM settled_signatures WHERE sig_hash = ?",
                (sig_hash,),
            ).fetchone()
            return dict(row) if row else None

    # -- reads -----------------------------------------------------------

    def get(self, nonce_hex: str) -> dict | None:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM payments WHERE nonce_hex = ?", (nonce_hex,)
            ).fetchone()
            if row is None or self._expired(row):
                return None
            return dict(row)

    def stats(self) -> dict:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM payments GROUP BY status"
            ).fetchall()
            return {r["status"]: r["n"] for r in rows}
