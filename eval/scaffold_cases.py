"""Generate annotation stubs for the cases the gates still need.

    python eval/scaffold_cases.py                 # how many more cases, and why
    python eval/scaffold_cases.py --count 20      # write 20 stubs to annotate
    python eval/scaffold_cases.py --count 20 --domain employment

Proving `tier_under_warned <= 2%` is not a coding problem, it is an annotation
problem: 0 under-warnings in 17 cases is compatible with a true rate near 18%,
and only more labelled cases close that. This script says exactly how many are
outstanding and writes the stubs so the work can be handed to whoever does the
legal annotation.

It deliberately does NOT invent descriptions or labels. A fabricated case makes
the number go up and the evidence go down, which is the opposite of the point.
Each stub carries nulls, a TODO, and every field the case must state — the
annotator supplies a real system description and the facts that follow from it.

Stubs land in `eval/pending_set.json`, which no scorer reads. Move a case into
golden_set.json (or holdout_set.json) only once it is fully annotated and
`--check-labels` passes on it.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.completeness import SCOPE_GATES  # noqa: E402
from eval.score import THRESHOLDS, observations_needed  # noqa: E402
from schema import HighRiskDomain  # noqa: E402

SETS = {"golden": Path(__file__).parent / "golden_set.json",
        "holdout": Path(__file__).parent / "holdout_set.json"}
PENDING = Path(__file__).parent / "pending_set.json"

# Fields an annotator must decide for a case to pin its own answer. The scope
# gates are mandatory everywhere; the rest are the facts that most often move a
# tier (see eval/completeness.py for the evidence).
REQUIRED = list(SCOPE_GATES) + [
    "is_ai_system", "placed_on_eu_market", "developed_or_commissioned",
    "supplied_under_own_name", "uses_under_own_authority",
    "safety_component_regulated_product", "subliminal_or_manipulative",
    "exploits_vulnerabilities", "social_scoring", "interacts_with_people",
    "generates_synthetic_content",
]


def current_counts() -> tuple[int, int]:
    """(tier-asserting cases, total cases) across the scored sets."""
    tier = total = 0
    for p in SETS.values():
        cases = json.loads(p.read_text(encoding="utf-8"))["cases"]
        total += len(cases)
        tier += sum(1 for c in cases if c.get("tier") is not None)
    return tier, total


def report_gap() -> int:
    tier, total = current_counts()
    print("=" * 74)
    print(f"ANNOTATION GAP — {tier} tier-asserting cases across {total} total")
    print("=" * 74)
    print("\nAssuming every further case is classified correctly, each gate needs:")
    worst = 0
    for metric in ("tier_exact", "tier_under_warned"):
        limit = THRESHOLDS[metric]
        ceiling = "warned" in metric
        # Best case: current record is clean.
        succ = 0 if ceiling else tier
        need = observations_needed(succ, tier, limit, ceiling)
        worst = max(worst, need or 0)
        shown = "more than 5000" if need is None else f"+{need}"
        print(f"  {metric:20} target {limit:>6.0%}   {shown} tier-asserting cases")
    print(f"\n  Binding constraint: about {tier + worst} tier-asserting cases in "
          f"total ({worst} more).")
    print("  Every one must be a real system description with facts an annotator")
    print("  can defend. Inventing them raises n and lowers the evidence.")
    return 0


def write_stubs(count: int, domain: str | None, prefix: str) -> int:
    existing = json.loads(PENDING.read_text(encoding="utf-8"))["cases"] \
        if PENDING.exists() else []
    start = len(existing) + 1
    stubs = []
    for i in range(start, start + count):
        expected: dict = {f: None for f in REQUIRED}
        expected["high_risk_domains"] = [domain] if domain else []
        stubs.append({
            "id": f"{prefix}-{i:03d}",
            "lang": "TODO  one of: nl / fr / en / es",
            "name": "TODO  short system name",
            "description": "TODO  a real, plain-language description of one AI "
                           "system, as a client would describe it. Do not write it "
                           "to match a label.",
            "components": "TODO  architecture, or '' if not supplied",
            "expected": dict(sorted(expected.items())),
            "tier": "TODO  PROHIBITED / ANNEX_I / ANNEX_III / LIMITED / MINIMAL / "
                    "OUT_OF_SCOPE / NOT_AI / UNDETERMINED — or null if the case "
                    "does not assert one",
            "tier_asserting_case": True,
            "_note": "TODO  which provision decides this, and why. A case without "
                     "reasoning cannot be reviewed by counsel.",
        })

    PENDING.write_text(json.dumps({
        "_readme": [
            "PENDING annotation stubs — NOT read by any scorer.",
            "",
            "Generated by eval/scaffold_cases.py. Every field marked TODO must be",
            "completed by someone who can defend the classification. Replace the",
            "nulls in `expected` with real values: null means 'the description",
            "genuinely does not say', which is a legitimate answer, not a default.",
            "",
            "When a case is complete, move it into golden_set.json (development)",
            "or holdout_set.json (never tuned against), then run:",
            "  python eval/run_eval.py --check-labels",
            "which verifies the labelled facts actually reach the labelled tier",
            "and that the Article 2 scope gates are all stated.",
        ],
        "cases": existing + stubs}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(f"Wrote {count} stubs to {PENDING} ({len(existing) + count} pending total)")
    print(f"Each needs {len(REQUIRED)} fact decisions plus a description and reasoning.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, help="number of stubs to write")
    ap.add_argument("--domain", choices=sorted(HighRiskDomain.__args__),
                    help="pre-fill a high-risk domain")
    ap.add_argument("--prefix", default="pending", help="case id prefix")
    args = ap.parse_args()
    if not args.count:
        return report_gap()
    return write_stubs(args.count, args.domain, args.prefix)


if __name__ == "__main__":
    raise SystemExit(main())
