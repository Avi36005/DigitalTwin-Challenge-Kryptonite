"""Opt-in public synthetic demonstration mode (``GLUCOTWIN_PUBLIC_DEMO=1``); off by default.

When enabled the API serves synthetic participants only, gives every visitor an anonymous cookie, keeps each visitor's
replay sessions private to that visitor, caps and expires sessions, and rate-limits requests per visitor and per IP.
Nothing here identifies a person: the cookie is a random token and only its hash is kept with a session.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass

COOKIE = "gt_visitor"
COOKIE_MAX_AGE = 7 * 24 * 3600
_TOKEN = re.compile(r"^[0-9a-f]{32}$")


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        v = int(os.environ.get(name, default))
    except ValueError:
        return default
    return v if v > 0 else default


@dataclass(frozen=True)
class PublicConfig:
    enabled: bool = False
    session_idle_minutes: int = 120
    max_sessions_per_visitor: int = 5
    max_sessions: int = 300
    visitor_requests_per_minute: int = 600
    ip_requests_per_minute: int = 1200
    trust_proxy: bool = False
    cookie_secure: bool = False


def load_config() -> PublicConfig:
    if not _flag("GLUCOTWIN_PUBLIC_DEMO"):
        return PublicConfig()
    return PublicConfig(
        enabled=True,
        session_idle_minutes=_int("GLUCOTWIN_PUBLIC_SESSION_IDLE_MINUTES", 120),
        max_sessions_per_visitor=_int("GLUCOTWIN_PUBLIC_MAX_SESSIONS_PER_VISITOR", 5),
        max_sessions=_int("GLUCOTWIN_PUBLIC_MAX_SESSIONS", 300),
        visitor_requests_per_minute=_int("GLUCOTWIN_PUBLIC_VISITOR_RPM", 600),
        ip_requests_per_minute=_int("GLUCOTWIN_PUBLIC_IP_RPM", 1200),
        trust_proxy=_flag("GLUCOTWIN_TRUST_PROXY"),
        cookie_secure=_flag("GLUCOTWIN_COOKIE_SECURE"),
    )


def new_token() -> str:
    return secrets.token_hex(16)


def valid_token(token: str | None) -> bool:
    return bool(token) and bool(_TOKEN.match(token))


def owner_of(token: str) -> str:
    """What a session stores about its visitor: a hash of the cookie, never the cookie itself."""
    return hashlib.sha256(token.encode()).hexdigest()[:32]


class RateLimiter:
    """Token buckets per key (refill = limit per minute, burst = the same limit)."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._b: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, per_minute: int) -> bool:
        now = self.clock()
        with self._lock:
            tokens, last = self._b.get(key, (float(per_minute), now))
            tokens = min(float(per_minute), tokens + (now - last) * per_minute / 60.0)
            ok = tokens >= 1.0
            self._b[key] = (tokens - 1.0 if ok else tokens, now)
            if len(self._b) > 20000:  # drop full buckets of idle clients
                self._b = {k: v for k, v in self._b.items() if now - v[1] < 120}
            return ok
