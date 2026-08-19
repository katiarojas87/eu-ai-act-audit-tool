"""Tamper-evidence for Assessment objects crossing the client boundary.

An Assessment travels to the browser after /classify, then comes BACK as raw
client input on every /chat and /report call — there is no server-side session
holding the "real" copy. Without a check, editing that JSON in devtools before
sending it produces a chat that discusses, or a branded PDF that states, a
tier or obligation the rule engine never actually concluded. For a tool whose
whole pitch is "deterministic, not made up", that gap is worth closing: sign
what /classify hands out, verify it on the way back in.

Keyed off APP_PASSWORD (or a dedicated ASSESSMENT_SIGNING_KEY, if set) so no
new required secret exists. Local dev with neither configured still signs and
verifies consistently with an empty key — a no-op in effect, matching that
mode's already-open posture (see api.py's ALLOW_NO_PASSWORD).
"""
from __future__ import annotations

import hashlib
import hmac
import os

from schema import Assessment


def _key() -> bytes:
    key = os.environ.get("ASSESSMENT_SIGNING_KEY") or os.environ.get("APP_PASSWORD") or ""
    return key.encode()


def _payload(assessment: Assessment) -> bytes:
    # Exclude the signature field itself so signing is idempotent. Pydantic
    # serialises a given model's fields in the same declared order every time,
    # so this is deterministic without needing to sort keys by hand.
    return assessment.model_dump_json(exclude={"sig"}).encode()


def sign(assessment: Assessment) -> str:
    return hmac.new(_key(), _payload(assessment), hashlib.sha256).hexdigest()


def verify(assessment: Assessment) -> bool:
    expected = sign(assessment)
    return hmac.compare_digest(expected, assessment.sig or "")
