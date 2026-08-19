"""Abuse and spend controls for the public API.

The tool is reachable from the internet behind a shared password, and every
classification costs two Opus calls. Without limits, one leaked password — or
one enthusiastic script — bills the owner until the credit runs out. These are
the cheapest controls that make that bounded rather than open-ended.

Deliberately in-process and dependency-free: this runs on one small Cloud Run
container, so a Redis dependency would cost more than it buys. Consequence to
know: with several instances the caps apply PER INSTANCE, so the real ceiling is
the cap times the instance count. Set max-instances accordingly.
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from datetime import date

# Per-client request rate.
RATE_LIMIT = int(os.environ.get("RATE_LIMIT_PER_HOUR", "30"))
RATE_WINDOW = 3600

# A hard ceiling on billable work per UTC day, so a bad day cannot become a
# bad month. Classification and chat are the endpoints that spend money, each
# capped separately since a chat turn (one short Opus call) costs far less
# than a classification (two, including full fact extraction).
DAILY_CAP = int(os.environ.get("DAILY_CLASSIFY_CAP", "200"))
DAILY_CHAT_CAP = int(os.environ.get("DAILY_CHAT_CAP", "500"))

# Failed password attempts before a client is locked out for a while. The gate
# is a single shared secret, so it must not be brute-forceable.
MAX_FAILURES = int(os.environ.get("MAX_AUTH_FAILURES", "10"))
LOCKOUT_SECONDS = int(os.environ.get("AUTH_LOCKOUT_SECONDS", "900"))

_lock = threading.Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)
_failures: dict[str, deque[float]] = defaultdict(deque)
_spend = {"day": date.today(), "count": 0}
_chat_spend = {"day": date.today(), "count": 0}


class LimitExceeded(Exception):
    """Raised with an HTTP status and a message safe to show a caller."""

    def __init__(self, status: int, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.retry_after = retry_after


def _prune(q: deque[float], window: float, now: float) -> None:
    while q and now - q[0] > window:
        q.popleft()


def check_rate(client: str) -> None:
    """Per-client request rate over a rolling hour."""
    now = time.time()
    with _lock:
        q = _hits[client]
        _prune(q, RATE_WINDOW, now)
        if len(q) >= RATE_LIMIT:
            wait = int(RATE_WINDOW - (now - q[0])) + 1
            raise LimitExceeded(
                429, f"Rate limit reached ({RATE_LIMIT}/hour). Try again later.",
                retry_after=wait)
        q.append(now)


def check_daily_cap() -> None:
    """Global ceiling on billable classifications per UTC day."""
    with _lock:
        today = date.today()
        if _spend["day"] != today:
            _spend["day"], _spend["count"] = today, 0
        if _spend["count"] >= DAILY_CAP:
            raise LimitExceeded(
                429, "The daily assessment limit for this deployment has been "
                     "reached. It resets at midnight UTC.")
        _spend["count"] += 1


def refund_daily() -> None:
    """Give back a slot when the work did not happen (e.g. upstream failure)."""
    with _lock:
        _spend["count"] = max(0, _spend["count"] - 1)


def check_daily_chat_cap() -> None:
    """Global ceiling on chat turns per UTC day. Separate from check_daily_cap:
    a chat reply is one short call, not a full classification, so it gets its
    own, larger budget rather than competing with classify for the same one."""
    with _lock:
        today = date.today()
        if _chat_spend["day"] != today:
            _chat_spend["day"], _chat_spend["count"] = today, 0
        if _chat_spend["count"] >= DAILY_CHAT_CAP:
            raise LimitExceeded(
                429, "The daily chat limit for this deployment has been "
                     "reached. It resets at midnight UTC.")
        _chat_spend["count"] += 1


def refund_daily_chat() -> None:
    with _lock:
        _chat_spend["count"] = max(0, _chat_spend["count"] - 1)


def check_not_locked_out(client: str) -> None:
    now = time.time()
    with _lock:
        q = _failures[client]
        _prune(q, LOCKOUT_SECONDS, now)
        if len(q) >= MAX_FAILURES:
            wait = int(LOCKOUT_SECONDS - (now - q[0])) + 1
            raise LimitExceeded(
                429, "Too many failed attempts. Try again later.", retry_after=wait)


def record_auth_failure(client: str) -> None:
    with _lock:
        _failures[client].append(time.time())


def clear_auth_failures(client: str) -> None:
    with _lock:
        _failures.pop(client, None)


def client_id(forwarded_for: str | None, fallback: str) -> str:
    """Identify the caller.

    Cloud Run puts the real client first in X-Forwarded-For. The header is
    spoofable, so this bounds honest use and slows abuse — it is not a security
    boundary on its own. The daily cap is what actually bounds spend.
    """
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return fallback


def usage() -> dict:
    with _lock:
        return {"day": _spend["day"].isoformat(), "classifications": _spend["count"],
                "daily_cap": DAILY_CAP, "rate_limit_per_hour": RATE_LIMIT,
                "chat_messages": _chat_spend["count"], "chat_daily_cap": DAILY_CHAT_CAP}
