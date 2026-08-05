"""Label sufficiency: prove the eval set pins down the answers it claims.

    python eval/completeness.py                  # development set
    python eval/completeness.py --set holdout
    python eval/completeness.py --case en-cv-ranking-provider --verbose

THE PROBLEM THIS SOLVES

Each case labels a handful of the ~60 fact fields — the ones whoever wrote it
was thinking about. Every unlabelled field is silently assumed to be the
default, and nothing checks whether that assumption is load-bearing. So a
headline like "95.3% field accuracy" measures the fields someone chose to look
at, which is exactly the objection a hostile reader raises first: you scored
your own selection.

THE FIX

`rules.py` is deterministic and runs in microseconds, so sufficiency is not a
matter of opinion — it is decidable by brute force. For every unlabelled field,
try every value it could take and re-run the engine. If the assessment the
client would receive changes, that field is DECISIVE for this case and leaving
it unlabelled means the case does not pin its own answer. If nothing changes
across all values, the field is provably inert here and its absence is
defensible in writing.

That turns "we labelled what mattered" into "every field capable of changing
this assessment is labelled, and here is the check that proves it" — a claim
that survives someone trying to break it.

Decisiveness is judged on what the client actually receives: the tier, the
roles, and the duty set. A field that only perturbs prose is not decisive.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.score import obligation_keys  # noqa: E402
from rules import classify  # noqa: E402
from schema import _ENUM_DEFAULTS, Facts, HighRiskDomain  # noqa: E402

SETS = {
    "golden": Path(__file__).parent / "golden_set.json",
    "holdout": Path(__file__).parent / "holdout_set.json",
}

# Prose fields carry no decision weight, and the consultant override is set by a
# human in the UI rather than extracted, so neither belongs in this analysis.
_SKIP = {"purpose", "sector", "affected_persons", "organisation_role"}

# --- legal scope gates (Article 2) -------------------------------------------
# These four decide whether the Regulation applies AT ALL. Any one of them being
# true takes the system out of scope entirely (Art. 2(3), 2(6), 2(8), 2(10)) and
# zeroes the obligation list, so an unstated one is not a missing detail — it is
# an unchecked assumption that the Regulation applies. They are mandatory in
# every case, including the ones where the answer is an obvious "false":
# labelling the obvious is what lets the eval catch the model getting it wrong.
SCOPE_GATES = (
    "military_defence_national_security",   # Art. 2(3)
    "sole_purpose_scientific_research",     # Art. 2(6)
    "prerelease_research_testing",          # Art. 2(8)
    "personal_non_professional_use",        # Art. 2(10)
)


def missing_required(case: dict) -> list[str]:
    """Scope gates this case fails to state. Empty means the case is admissible."""
    return [g for g in SCOPE_GATES if g not in case.get("expected", {})]


def validate_cases(cases: list[dict]) -> list[tuple[str, list[str]]]:
    """Every case must state every scope gate. Returns the offenders."""
    return [(c["id"], m) for c in cases if (m := missing_required(c))]


def _candidate_values(field: str) -> list:
    """Every value this field could plausibly take, other than its default."""
    if field == "high_risk_domains":
        # The full power set is 2^10; single domains are enough to expose
        # whether the field is load-bearing at all.
        return [[d] for d in HighRiskDomain.__args__]
    if field in _ENUM_DEFAULTS:
        default, allowed = _ENUM_DEFAULTS[field]
        return [v for v in sorted(allowed) if v != default]
    return [True, False]


def _signature(facts: Facts, name: str) -> tuple:
    """What the client receives — the only thing decisiveness is judged on."""
    a = classify(facts, name)
    return (a.tier, tuple(sorted(a.roles)), frozenset(obligation_keys(a)))


def analyse_case(case: dict) -> dict:
    """Which unlabelled fields would change this case's assessment?"""
    labelled = {k for k in case["expected"] if k not in _SKIP}
    base_facts = Facts.model_validate(case["expected"])
    base = _signature(base_facts, case["name"])

    decisive: list[dict] = []
    for field in Facts.model_fields:
        if field in _SKIP or field in labelled:
            continue
        for value in _candidate_values(field):
            probe = base_facts.model_copy(update={field: value})
            sig = _signature(probe, case["name"])
            if sig != base:
                decisive.append({
                    "field": field,
                    "value": value,
                    "tier": f"{base[0]} -> {sig[0]}" if sig[0] != base[0] else base[0],
                    "changes_tier": sig[0] != base[0],
                    "duties_delta": len(sig[2] ^ base[2]),
                })
                break   # one witness is enough to prove the field is decisive

    return {
        "id": case["id"],
        "tier": base[0],
        "labelled": len(labelled),
        "decisive_unlabelled": decisive,
        # Sufficiency for this case: of the fields that could change the answer,
        # how many are actually pinned down by a label?
        "sufficient": not decisive,
    }


def run(cases: list[dict], verbose: bool = False, report: str | None = None) -> int:
    results = [analyse_case(c) for c in cases]

    total_decisive = sum(len(r["decisive_unlabelled"]) for r in results)
    tier_movers = sum(1 for r in results
                      for d in r["decisive_unlabelled"] if d["changes_tier"])
    sufficient = sum(1 for r in results if r["sufficient"])
    labelled_total = sum(r["labelled"] for r in results)

    print("=" * 74)
    print(f"LABEL SUFFICIENCY — {len(results)} cases, {labelled_total} labelled fields")
    print("=" * 74)
    print(f"  cases that fully pin their own answer   {sufficient}/{len(results)}")
    print(f"  unlabelled-but-decisive field instances {total_decisive}")
    print(f"    ...of which would move the TIER       {tier_movers}")

    # Which fields go unlabelled while carrying weight, across the whole set.
    by_field: dict[str, dict] = {}
    for r in results:
        for d in r["decisive_unlabelled"]:
            s = by_field.setdefault(d["field"], {"cases": 0, "tier": 0})
            s["cases"] += 1
            s["tier"] += int(d["changes_tier"])

    if by_field:
        print("\nFIELDS THAT CHANGE ANSWERS BUT ARE OFTEN UNLABELLED")
        print("  (label these first — ranked by how many cases they can flip)")
        ranked = sorted(by_field.items(), key=lambda kv: (-kv[1]["tier"], -kv[1]["cases"]))
        for field, s in ranked[:20]:
            print(f"    {field:48} {s['cases']:3} cases  ({s['tier']} move the tier)")

    if verbose:
        for r in results:
            if not r["decisive_unlabelled"]:
                continue
            print(f"\n  {r['id']}  [{r['tier']}]  {r['labelled']} labels")
            for d in r["decisive_unlabelled"]:
                flag = "TIER" if d["changes_tier"] else f"{d['duties_delta']:>3} duties"
                print(f"      {flag}  {d['field']}={d['value']!r}  ({d['tier']})")

    if report:
        Path(report).write_text(json.dumps(results, indent=2, default=str),
                                encoding="utf-8")
        print(f"\nWritten to {report}")

    print("\nHOW TO READ THIS")
    print("  Every line above is a fact the model could get wrong without the")
    print("  scorecard noticing. Add it to the case's `expected` block — even as")
    print("  `false` — and the eval starts checking it. A case with no lines")
    print("  fully determines its own answer.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", dest="which", choices=sorted(SETS), default="golden")
    ap.add_argument("--case", help="analyse a single case id")
    ap.add_argument("--verbose", action="store_true",
                    help="list every decisive field, per case")
    ap.add_argument("--report", help="write full results to this JSON file")
    args = ap.parse_args()

    cases = json.loads(SETS[args.which].read_text(encoding="utf-8"))["cases"]
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
    if not cases:
        print("No cases matched.")
        return 1
    return run(cases, args.verbose, args.report)


if __name__ == "__main__":
    raise SystemExit(main())
