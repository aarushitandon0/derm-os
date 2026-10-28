"""Who may spend YouCam units, and how often anyone may scan.

Live scans need BOTH: DEMO_MODE=0 on the server AND the request header
X-Live-Passcode matching LIVE_SCAN_PASSCODE. Without the header the scan replays
recorded fixtures (labelled prepared data). A wrong passcode is refused, so a
typo never silently turns into a replay. If LIVE_SCAN_PASSCODE isn't set, live
scans are off entirely. The unit guard in youcam.py still applies on top.

Scan endpoints are rate limited per client IP (in memory, per process):
SCAN_RATE_LIMIT="<count>/<seconds>", default 30/600; "0" turns it off.
Behind a proxy (Render, etc.) set TRUST_PROXY=1 so the client IP is read from
the last X-Forwarded-For hop, which the proxy itself appended.
"""
from __future__ import annotations

import hmac
import os
import threading
import time
from collections import deque

from fastapi import HTTPException, Request

from .settings import flag

PASSCODE_HEADER = "X-Live-Passcode"


def demo_mode() -> bool:
    return flag("DEMO_MODE")


def live_passcode() -> str | None:
    return os.environ.get("LIVE_SCAN_PASSCODE") or None


def live_scans_setting() -> str:
    """'off' (DEMO_MODE=1), 'passcode' (DEMO_MODE=0 with a passcode set), 'disabled' (DEMO_MODE=0, none set)."""
    if demo_mode():
        return "off"
    return "passcode" if live_passcode() else "disabled"


def passcode_status(header: str | None) -> str:
    """'none' (no header), 'ok', or 'wrong' (also when live scans aren't enabled)."""
    if not header:
        return "none"
    code = live_passcode()
    if code and hmac.compare_digest(header.encode(), code.encode()):
        return "ok"
    return "wrong"


def scan_source(header: str | None) -> tuple[str, str | None]:
    """('live', None) or ('replay', reason). Raises 403 for a wrong passcode on a live-capable server."""
    if demo_mode():
        return "replay", "demo_mode"
    st = passcode_status(header)
    if st == "ok":
        return "live", None
    if st == "wrong":
        raise HTTPException(403, "Live scans need the right passcode. Remove it to use prepared demo data."
                            if live_passcode() else "Live scans aren't enabled on this server.")
    return "replay", "no_passcode"


# ---------------------------------------------------------------- rate limit
def _parse_limit(raw: str | None) -> tuple[int, float] | None:
    raw = (raw or "30/600").strip()
    if raw in ("0", "", "off"):
        return None
    try:
        n, _, secs = raw.partition("/")
        n_i, s_f = int(n), float(secs or 60)
    except ValueError:
        return 30, 600.0
    return (n_i, s_f) if n_i > 0 and s_f > 0 else None


class RateLimiter:
    def __init__(self, limit: tuple[int, float] | None, clock=time.monotonic):
        self.limit = limit
        self.clock = clock
        self.hits: dict[str, deque[float]] = {}
        self.lock = threading.Lock()

    def check(self, key: str) -> None:
        if not self.limit:
            return
        n, window = self.limit
        now = self.clock()
        with self.lock:
            q = self.hits.setdefault(key, deque())
            while q and now - q[0] >= window:
                q.popleft()
            if len(q) >= n:
                retry = max(1, int(window - (now - q[0])) + 1)
                raise HTTPException(429, f"Too many scans from this connection. Try again in {retry} s.",
                                    headers={"Retry-After": str(retry)})
            q.append(now)
            if len(self.hits) > 10_000:   # keep memory bounded on a long-running server
                for k in [k for k, v in self.hits.items() if not v or now - v[-1] >= window]:
                    del self.hits[k]


def client_ip(request: Request) -> str:
    if flag("TRUST_PROXY"):
        fwd = request.headers.get("x-forwarded-for", "")
        hops = [h.strip() for h in fwd.split(",") if h.strip()]
        if hops:
            return hops[-1]
    return request.client.host if request.client else "unknown"


def make_scan_limiter() -> RateLimiter:
    return RateLimiter(_parse_limit(os.environ.get("SCAN_RATE_LIMIT")))


def cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "*")
    return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()] or ["*"]
