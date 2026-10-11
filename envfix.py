"""VM quirk workaround: sanitize no_proxy for httpx.

The runtime sets no_proxy/NO_PROXY with bracketed IPv6 entries like [::1].
httpx's NO_PROXY parsing calls URLPattern() on each entry and raises
`InvalidURL: Invalid port: ':1]'` on the brackets.

This strips bracketed entries process-locally before httpx is imported.
Safe: the unbracketed equivalents (::1) remain, and this only affects
this process's proxy bypass list, not the proxy itself.
"""

from __future__ import annotations

import os


def sanitize_no_proxy() -> None:
    for var in ("no_proxy", "NO_PROXY"):
        val = os.environ.get(var)
        if not val:
            continue
        kept = [e for e in val.split(",") if "[" not in e and "]" not in e]
        os.environ[var] = ",".join(kept)


sanitize_no_proxy()
