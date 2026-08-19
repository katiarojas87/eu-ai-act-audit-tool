"""Normalise secrets injected from the environment.

A secret stored with a trailing newline — which is what happens when you paste a
key into `gcloud secrets create --data-file=-` and press Enter before Ctrl-D —
produces an illegal HTTP header value. The Anthropic SDK surfaces that as
`APIConnectionError: Connection error`, which reads like a network fault and
sends you looking in entirely the wrong place. It cost a debugging round here.

Stripping on read is safe: no credential has meaningful leading or trailing
whitespace, so this can only turn a broken value into a working one.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("eu_ai_act.secrets")

# Values injected from a secret store, where stray whitespace is plausible.
_SENSITIVE = ("ANTHROPIC_API_KEY", "APP_PASSWORD")


def normalise_env() -> list[str]:
    """Strip surrounding whitespace from secret env vars. Returns those fixed."""
    fixed = []
    for name in _SENSITIVE:
        raw = os.environ.get(name)
        if raw is None:
            continue
        clean = raw.strip()
        if clean != raw:
            os.environ[name] = clean
            fixed.append(name)
            # Never log the value, only that it needed fixing.
            log.warning(
                "%s had surrounding whitespace and was stripped. Re-store it "
                "without a trailing newline: printf %%s '<value>' | "
                "gcloud secrets versions add <secret> --data-file=-", name)
    return fixed
