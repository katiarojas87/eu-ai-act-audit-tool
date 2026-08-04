"""Consultant-supplied Article 2 scope facts, from the UI.

Scope is the one area where relying on the description is weakest: a client
describing their system almost never volunteers "none of our output is used in
the EU" or "this is pre-market testing only". Absence of mention leaves scope
unresolved, so the tool assumes the Regulation applies and an out-of-scope
system is never identified as such.

These overrides let the consultant state what they already know. As with the
role override, an explicit answer beats inference.

An unticked carve-out asserts nothing — it is left to extraction rather than
being read as "false". Only a positive statement overrides.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

# What connects this system to the Union, if anything.
Nexus = Literal[
    "unknown",        # not stated — infer from the description
    "eu_market",      # placed on the market / put into service in the Union
    "output_in_eu",   # established outside the EU, output used in the Union
    "none",           # no EU nexus at all
]

CARVE_OUTS = (
    "military_defence_national_security",
    "sole_purpose_scientific_research",
    "prerelease_research_testing",
    "real_world_testing",
    "personal_non_professional_use",
)


class ScopeOverride(BaseModel):
    """Article 2 facts supplied by the consultant rather than inferred."""
    nexus: Nexus = "unknown"
    military_defence_national_security: bool = False
    sole_purpose_scientific_research: bool = False
    prerelease_research_testing: bool = False
    real_world_testing: bool = False
    personal_non_professional_use: bool = False


_NEXUS_FACTS: dict[str, dict[str, Any]] = {
    "eu_market": {"placed_on_eu_market": True},
    "output_in_eu": {"established_outside_eu": True, "output_used_in_eu": True},
    "none": {"established_outside_eu": True, "output_used_in_eu": False,
             "placed_on_eu_market": False},
}


def to_fact_overrides(scope: ScopeOverride | None) -> dict[str, Any]:
    """Translate the UI's answers into Facts field values.

    Only positive statements are emitted. A "unknown" nexus and unticked boxes
    produce nothing, leaving those facts to extraction.
    """
    if scope is None:
        return {}
    out: dict[str, Any] = dict(_NEXUS_FACTS.get(scope.nexus, {}))
    for field in CARVE_OUTS:
        if getattr(scope, field):
            out[field] = True
    return out
