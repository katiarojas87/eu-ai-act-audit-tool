"""Evaluate fact extraction against the golden set.

    python eval/run_eval.py --check-labels     # offline: are the labels self-consistent?
    python eval/run_eval.py                    # full run (calls the API, costs money)
    python eval/run_eval.py --limit 5          # cheap smoke test
    python eval/run_eval.py --lang nl          # one language
    python eval/run_eval.py --report out.json  # save raw results

The rule engine is deterministic and covered by unit tests, so the remaining
error surface is extraction: does the model read a plain-language description
correctly? This script measures that, and separates two failure modes that
matter differently to a client:

    abstained — the model left a fact unknown. The report shows a gap and asks a
                follow-up question. Recoverable.
    wrong     — the model asserted something untrue. The report is confidently
                incorrect and nothing prompts anyone to check it. Not recoverable.

`--check-labels` needs no API key: it runs the labelled facts through rules.py
and verifies each case reaches the tier the label claims, which catches mistakes
in the golden set itself.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.score import (  # noqa: E402
    aggregate, check_thresholds, score_case, tier_verdict,
)
from rules import classify  # noqa: E402
from schema import Facts  # noqa: E402

GOLDEN = Path(__file__).parent / "golden_set.json"


def load_cases(lang: str | None = None, limit: int | None = None,
               case_id: str | None = None) -> list[dict]:
    cases = json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]
    if case_id:
        cases = [c for c in cases if c["id"] == case_id]
    if lang:
        cases = [c for c in cases if c["lang"] == lang]
    return cases[:limit] if limit else cases


def check_labels(cases: list[dict]) -> int:
    """Offline sanity check: do the labelled facts produce the labelled tier?

    A `tier` of null means "the label does not assert a tier" — used where the
    interesting property is a carve-out rather than the headline.
    """
    bad = []
    for c in cases:
        expected_tier = c.get("tier")
        if expected_tier is None:
            continue
        got = classify(Facts.model_validate(c["expected"]), c["name"]).tier
        if got != expected_tier:
            bad.append((c["id"], expected_tier, got))
    print(f"Label check: {len(cases)} cases, "
          f"{sum(1 for c in cases if c.get('tier'))} assert a tier")
    for cid, want, got in bad:
        print(f"  MISMATCH {cid}: label says {want}, engine says {got}")
    if not bad:
        print("  all labelled tiers agree with the rule engine")
    return 1 if bad else 0


def run(cases: list[dict], report_path: str | None) -> int:
    from facts import extract_facts   # imported late: needs an API key

    per_case, raw = [], []
    for i, c in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {c['id']} ({c['lang']}) …", flush=True)
        try:
            actual = extract_facts(c["name"], c["description"], c.get("components", ""))
        except Exception as e:  # noqa: BLE001
            print(f"    extraction FAILED: {e}")
            continue

        fields = score_case(c["expected"], actual)
        entry = {"id": c["id"], "fields": fields, "tier_verdict": None}
        if c.get("tier"):
            got = classify(actual, c["name"]).tier
            entry["tier_verdict"] = tier_verdict(c["tier"], got)
            entry["tier_expected"], entry["tier_actual"] = c["tier"], got
        per_case.append(entry)
        raw.append({
            "id": c["id"], "lang": c["lang"],
            "tier_expected": c.get("tier"), "tier_actual": entry.get("tier_actual"),
            "fields": [{"field": r.field, "expected": r.expected,
                        "actual": r.actual, "verdict": r.verdict} for r in fields],
        })

        for r in fields:
            if r.verdict != "correct":
                mark = "WRONG " if r.verdict == "wrong" else "abstain"
                print(f"    {mark} {r.field}: expected {r.expected!r}, got {r.actual!r}")

    if not per_case:
        print("No cases scored.")
        return 1

    summary = aggregate(per_case)
    _print_summary(summary, per_case)

    if report_path:
        Path(report_path).write_text(
            json.dumps({"summary": summary, "cases": raw}, indent=2, default=str),
            encoding="utf-8")
        print(f"\nRaw results written to {report_path}")

    return 0 if all(p for *_, p in check_thresholds(summary)) else 1


def _print_summary(summary: dict, per_case: list[dict]) -> None:
    print("\n" + "=" * 72)
    print(f"FACT EXTRACTION — {summary['cases']} cases, "
          f"{summary['fields_scored']} labelled fields")
    print("=" * 72)
    c = summary["counts"]
    print(f"  correct    {c['correct']:4}   {summary['field_accuracy']:6.1%}")
    print(f"  abstained  {c['abstained']:4}   {summary['abstention_rate']:6.1%}"
          "   (left unknown — becomes a follow-up question)")
    print(f"  wrong      {c['wrong']:4}   {summary['wrong_rate']:6.1%}"
          "   (asserted something untrue)")

    tc = summary["tier_counts"]
    print(f"\nEND-TO-END TIER  ({sum(tc.values())} cases assert a tier)")
    print(f"  exact         {tc['exact']:4}   {summary['tier_exact']:6.1%}")
    print(f"  under-warned  {tc['under_warned']:4}   {summary['tier_under_warned']:6.1%}"
          "   (client told they owe LESS than they do)")
    print(f"  over-warned   {tc['over_warned']:4}   {summary['tier_over_warned']:6.1%}")

    weak = [(f, s) for f, s in summary["by_field"].items() if s["wrong"] or s["abstained"]]
    if weak:
        print("\nWEAKEST FIELDS")
        for field, s in weak[:12]:
            print(f"  {field:42} wrong={s['wrong']:2} abstained={s['abstained']:2} "
                  f"correct={s['correct']:2}")

    print("\nTHRESHOLDS")
    for metric, actual, limit, passed in check_thresholds(summary):
        print(f"  {'PASS' if passed else 'FAIL'}  {metric:20} "
              f"{actual:6.1%}  (target {limit:.0%})")

    misses = [c for c in per_case if c.get("tier_verdict") == "under_warned"]
    if misses:
        print("\nUNDER-WARNED CASES — review these first")
        for m in misses:
            print(f"  {m['id']}: label {m['tier_expected']} -> got {m['tier_actual']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check-labels", action="store_true",
                    help="offline: verify the golden set against the rule engine")
    ap.add_argument("--limit", type=int, help="only run the first N cases")
    ap.add_argument("--lang", help="filter by language (nl/fr/en/es)")
    ap.add_argument("--case", help="run a single case id")
    ap.add_argument("--report", help="write raw results to this JSON file")
    args = ap.parse_args()

    cases = load_cases(args.lang, args.limit, args.case)
    if not cases:
        print("No cases matched.")
        return 1
    return check_labels(cases) if args.check_labels else run(cases, args.report)


if __name__ == "__main__":
    raise SystemExit(main())
