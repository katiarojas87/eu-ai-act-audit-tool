"""Scoring for the fact-extraction evaluation.

Pure functions, no API calls — so the scoring logic itself is unit-testable.

The rule engine is deterministic and well covered by tests, so the only place a
real assessment can go wrong is fact extraction. This module turns "did the LLM
read the description correctly?" into numbers.

Three verdicts per labelled field, deliberately kept distinct:

    correct    — matches the label
    abstained  — the model left it unknown (null / the field default)
    wrong      — the model asserted something untrue

`wrong` and `abstained` are NOT the same failure. An abstention produces a
follow-up question and a visible gap in the report; a wrong value produces a
confident, incorrect assessment that nobody is prompted to check. The headline
metric therefore separates them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from schema import Facts

# Field defaults, so "the model said nothing" can be told apart from
# "the model said no".
_DEFAULTS: dict[str, Any] = Facts().model_dump()

# Fields whose value is prose, not a decision — never scored.
_UNSCORED = {"purpose", "sector", "affected_persons"}


@dataclass
class FieldResult:
    field: str
    expected: Any
    actual: Any
    verdict: str          # "correct" | "abstained" | "wrong"

    @property
    def ok(self) -> bool:
        return self.verdict == "correct"


def _is_abstention(field: str, actual: Any) -> bool:
    """True when the model declined to commit, rather than answering."""
    if actual is None:
        return True
    default = _DEFAULTS.get(field)
    # An empty list or the enum default ("none"/"unknown") means "not stated".
    return actual == default and default in (None, "none", "unknown", [])


def _equal(expected: Any, actual: Any) -> bool:
    if isinstance(expected, list) and isinstance(actual, list):
        return sorted(expected) == sorted(actual)
    return expected == actual


def score_case(expected: dict, actual: Facts) -> list[FieldResult]:
    """Score one case. Only fields present in `expected` are scored.

    Labelling every field of every case would be busywork; each case labels the
    fields that matter for it, and unlabelled fields are ignored.
    """
    got = actual.model_dump()
    results = []
    for field, want in expected.items():
        if field in _UNSCORED:
            continue
        have = got.get(field)
        if _equal(want, have):
            verdict = "correct"
        elif _is_abstention(field, have) and not _is_abstention(field, want):
            verdict = "abstained"
        else:
            verdict = "wrong"
        results.append(FieldResult(field, want, have, verdict))
    return results


# Tiers ordered by how much compliance work they imply. Predicting a tier below
# the true one is an under-warning: the client is told they owe less than they do.
_TIER_SEVERITY = {
    "OUT_OF_SCOPE": 0, "NOT_AI": 0, "UNDETERMINED": 1, "MINIMAL": 1,
    "LIMITED": 2, "ANNEX_III": 3, "ANNEX_I": 3, "PROHIBITED": 4,
}


def tier_verdict(expected_tier: str, actual_tier: str) -> str:
    """"exact" | "under_warned" | "over_warned"."""
    if expected_tier == actual_tier:
        return "exact"
    want = _TIER_SEVERITY.get(expected_tier, 1)
    have = _TIER_SEVERITY.get(actual_tier, 1)
    return "under_warned" if have < want else "over_warned"


def aggregate(per_case: list[dict]) -> dict:
    """Roll individual case results into the scorecard.

    `per_case` entries: {"id", "fields": [FieldResult], "tier_verdict": str}
    """
    fields = [r for c in per_case for r in c["fields"]]
    n = len(fields) or 1
    counts = {v: sum(1 for r in fields if r.verdict == v)
              for v in ("correct", "abstained", "wrong")}

    by_field: dict[str, dict] = {}
    for r in fields:
        s = by_field.setdefault(r.field, {"correct": 0, "abstained": 0, "wrong": 0})
        s[r.verdict] += 1

    tiers = [c["tier_verdict"] for c in per_case if c.get("tier_verdict")]
    t = len(tiers) or 1
    return {
        "cases": len(per_case),
        "fields_scored": len(fields),
        "field_accuracy": counts["correct"] / n,
        "wrong_rate": counts["wrong"] / n,
        "abstention_rate": counts["abstained"] / n,
        "counts": counts,
        "by_field": dict(sorted(
            by_field.items(),
            key=lambda kv: (-kv[1]["wrong"], -kv[1]["abstained"]))),
        "tier_exact": sum(1 for v in tiers if v == "exact") / t,
        "tier_under_warned": sum(1 for v in tiers if v == "under_warned") / t,
        "tier_over_warned": sum(1 for v in tiers if v == "over_warned") / t,
        "tier_counts": {v: tiers.count(v)
                        for v in ("exact", "under_warned", "over_warned")},
    }


# Thresholds the tool should meet before a report goes to a client.
THRESHOLDS = {
    "field_accuracy": 0.90,
    "wrong_rate": 0.05,        # asserting something untrue
    "tier_exact": 0.85,
    "tier_under_warned": 0.02,  # telling a client they owe less than they do
}


def check_thresholds(summary: dict) -> list[tuple[str, float, float, bool]]:
    """Returns (metric, actual, threshold, passed) for each gate."""
    out = []
    for metric, limit in THRESHOLDS.items():
        actual = summary[metric]
        # Rates are ceilings; accuracies are floors.
        passed = actual <= limit if metric.endswith("rate") or "warned" in metric \
            else actual >= limit
        out.append((metric, actual, limit, passed))
    return out
