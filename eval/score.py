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

import math
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


# --- uncertainty ------------------------------------------------------------
# A point estimate from 64 observations is not a measurement, it is an anecdote
# with a decimal point. Every rate this module reports carries a Wilson score
# interval so the sample size is impossible to hide: "95.3%" and
# "95.3% (95% CI 87.0-98.4%, n=64)" invite very different questions, and only
# the second one is defensible in front of someone who wants it not to be true.


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Preferred over the normal approximation because it stays inside [0, 1] and
    stays sane at the extremes — where these numbers live (0 wrong out of 64
    should not report a zero-width interval).
    """
    if n <= 0:
        return (0.0, 1.0)
    p = successes / n
    d = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def fmt_ci(successes: int, n: int) -> str:
    """'95.3% (95% CI 87.0-98.4%, n=64)' — the only honest way to print a rate."""
    if n <= 0:
        return "n/a (n=0)"
    lo, hi = wilson(successes, n)
    return f"{successes / n:.1%} (95% CI {lo:.1%}-{hi:.1%}, n={n})"


# --- obligation-level scoring ------------------------------------------------
# Field accuracy measures an intermediate. The client receives an OBLIGATION
# LIST, and nothing here measured it until now. A correct ANNEX_III tier that
# silently drops the Art. 27 FRIA is a failed audit that scores as a perfect
# result, so duties are keyed by the role that owes them: "deployer:Art. 27" and
# "provider:Art. 27" are different claims about the law.


def obligation_keys(assessment) -> set[str]:
    """The duty set an assessment asserts, as {"role:article"}."""
    return {f"{o.role}:{o.article}" for o in assessment.obligations if o.article}


def score_obligations(expected: set[str], actual: set[str]) -> dict:
    """Compare two duty sets.

    `missing` is the one that matters: a duty the client owes and was not told
    about. `extra` costs them money and credibility but not compliance.
    """
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    hit = len(expected & actual)
    return {
        "expected": len(expected),
        "actual": len(actual),
        "correct": hit,
        "missing": missing,
        "extra": extra,
        "recall": hit / len(expected) if expected else 1.0,
        "precision": hit / len(actual) if actual else 1.0,
        "exact": not missing and not extra,
    }


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
    n_exact = sum(1 for v in tiers if v == "exact")
    return {
        "cases": len(per_case),
        "fields_scored": len(fields),
        "field_accuracy": counts["correct"] / n,
        "wrong_rate": counts["wrong"] / n,
        "abstention_rate": counts["abstained"] / n,
        "counts": counts,
        # Every headline rate travels with its interval and its denominator, so
        # a summary cannot be quoted without them.
        "ci": {
            "field_accuracy": wilson(counts["correct"], len(fields)),
            "wrong_rate": wilson(counts["wrong"], len(fields)),
            "tier_exact": wilson(n_exact, len(tiers)),
        },
        "n": {"fields": len(fields), "tiers": len(tiers)},
        "display": {
            "field_accuracy": fmt_ci(counts["correct"], len(fields)),
            "wrong_rate": fmt_ci(counts["wrong"], len(fields)),
            "tier_exact": fmt_ci(n_exact, len(tiers)),
        },
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


def _is_ceiling(metric: str) -> bool:
    """Rates and under-warnings are ceilings; accuracies are floors."""
    return metric.endswith("rate") or "warned" in metric


def check_thresholds(summary: dict) -> list[tuple[str, float, float, bool]]:
    """Returns (metric, actual, threshold, passed) for each gate."""
    out = []
    for metric, limit in THRESHOLDS.items():
        actual = summary[metric]
        passed = actual <= limit if _is_ceiling(metric) else actual >= limit
        out.append((metric, actual, limit, passed))
    return out


# How many observations each gate is computed from.
_METRIC_DENOMINATOR = {
    "field_accuracy": "fields", "wrong_rate": "fields",
    "tier_exact": "tiers", "tier_under_warned": "tiers",
}


def threshold_verdicts(summary: dict) -> list[dict]:
    """Judge each gate against the CONFIDENCE INTERVAL, not the point estimate.

    A point estimate that clears a threshold on 64 observations has not
    demonstrated anything — the interval may straddle the gate in both
    directions. Three verdicts, because "we cannot tell yet" is a real answer
    and collapsing it into PASS is how an accuracy claim becomes indefensible:

        pass     — the whole interval is on the right side of the gate
        unproven — the estimate clears it but the interval straddles it;
                   the sample is too small to support the claim
        fail     — the estimate itself is on the wrong side
    """
    counts, tiers = summary["counts"], summary.get("tier_counts", {})
    n = summary.get("n") or {"fields": summary.get("fields_scored", 0),
                             "tiers": sum(tiers.values())}
    successes = {
        "field_accuracy": counts["correct"],
        "wrong_rate": counts["wrong"],
        "tier_exact": tiers.get("exact", 0),
        "tier_under_warned": tiers.get("under_warned", 0),
    }

    out = []
    for metric, limit in THRESHOLDS.items():
        denom = n.get(_METRIC_DENOMINATOR[metric], 0)
        lo, hi = wilson(successes[metric], denom)
        actual = summary[metric]
        if _is_ceiling(metric):
            verdict = "fail" if actual > limit else ("pass" if hi <= limit else "unproven")
        else:
            verdict = "fail" if actual < limit else ("pass" if lo >= limit else "unproven")
        out.append({"metric": metric, "actual": actual, "limit": limit,
                    "lo": lo, "hi": hi, "n": denom, "verdict": verdict,
                    "display": fmt_ci(successes[metric], denom)})
    return out
