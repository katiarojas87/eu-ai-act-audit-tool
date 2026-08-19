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
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from eval.completeness import SCOPE_GATES, validate_cases  # noqa: E402
from eval.score import (  # noqa: E402
    aggregate, aggregate_obligations, check_thresholds, obligation_keys,
    score_case, slice_obligations, threshold_verdicts, tier_verdict,
)
from rules import classify  # noqa: E402
from schema import Facts  # noqa: E402

SETS = {
    # development: used to diagnose and fix extraction, so scores on it are
    # optimistic — the prompt has seen these failures.
    "golden": Path(__file__).parent / "golden_set.json",
    # held out: never used for tuning, so this is the unbiased figure.
    "holdout": Path(__file__).parent / "holdout_set.json",
}
GOLDEN = SETS["golden"]


def load_cases(lang: str | None = None, limit: int | None = None,
               case_id: str | None = None, which: str = "golden") -> list[dict]:
    cases = json.loads(SETS[which].read_text(encoding="utf-8"))["cases"]
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

    # A case that does not state the Art. 2 scope gates has not been checked
    # against the question of whether the Regulation applies at all.
    incomplete = validate_cases(cases)
    print(f"\nScope-gate check: {len(cases) - len(incomplete)}/{len(cases)} cases "
          f"state all {len(SCOPE_GATES)} Article 2 gates")
    for cid, gates in incomplete:
        print(f"  INCOMPLETE {cid}: missing {', '.join(gates)}")
    if not incomplete:
        print("  every case states its scope gates")
    return 1 if (bad or incomplete) else 0


def run(cases: list[dict], report_path: str | None) -> int:
    from facts import extract_facts   # imported late: needs an API key

    per_case, raw = [], []
    duty_pairs: list[tuple[set, set]] = []
    for i, c in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {c['id']} ({c['lang']}) …", flush=True)
        try:
            actual = extract_facts(c["name"], c["description"], c.get("components", ""))
        except Exception as e:  # noqa: BLE001
            print(f"    extraction FAILED: {e}")
            continue

        fields = score_case(c["expected"], actual)
        entry = {"id": c["id"], "fields": fields, "tier_verdict": None}

        # The duty list is what the client receives, so score it end-to-end:
        # duties the labelled facts imply, against duties the EXTRACTED facts
        # produce. A field error only matters if it changes what someone is
        # told to do, and this is where that shows up.
        want_duties = obligation_keys(classify(Facts.model_validate(c["expected"]),
                                               c["name"]))
        got_duties = obligation_keys(classify(actual, c["name"]))
        duty_pairs.append((want_duties, got_duties))
        entry["duty_missing"] = sorted(want_duties - got_duties)
        entry["duty_extra"] = sorted(got_duties - want_duties)

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
        for d in entry["duty_missing"]:
            print(f"    DUTY DROPPED {d}")
        for d in entry["duty_extra"]:
            print(f"    duty added   {d}")

    if not per_case:
        print("No cases scored.")
        return 1

    summary = aggregate(per_case)
    if duty_pairs:
        summary["obligations"] = aggregate_obligations(duty_pairs)
        summary["obligations_by_role"] = slice_obligations(duty_pairs, "role")
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
    disp = summary.get("display", {})
    print(f"  correct    {c['correct']:4}   {disp.get('field_accuracy', '')}")
    print(f"  abstained  {c['abstained']:4}   {summary['abstention_rate']:6.1%}"
          "   (left unknown — becomes a follow-up question)")
    print(f"  wrong      {c['wrong']:4}   {disp.get('wrong_rate', '')}"
          "   (asserted something untrue)")

    tc = summary["tier_counts"]
    print(f"\nEND-TO-END TIER  ({sum(tc.values())} cases assert a tier)")
    print(f"  exact         {tc['exact']:4}   {disp.get('tier_exact', '')}")
    print(f"  under-warned  {tc['under_warned']:4}   {summary['tier_under_warned']:6.1%}"
          "   (client told they owe LESS than they do)")
    print(f"  over-warned   {tc['over_warned']:4}   {summary['tier_over_warned']:6.1%}")

    ob = summary.get("obligations")
    if ob:
        print(f"\nOBLIGATIONS  ({ob['expected']} duties owed across {ob['cases']} cases)")
        print("  the duty list is what the client actually receives")
        print(f"  recall        {ob['display']['recall']}")
        print(f"  precision     {ob['display']['precision']}")
        print(f"  F2            {ob['f2']:.3f}   (recall weighted 4x: omitting a "
              "duty is the costly error)")
        print(f"  under-warned  {ob['under_warning_rate']:6.2%}   "
              f"({len(ob['missing'])} owed duties never surfaced)")
        print(f"  exact set     {ob['display']['exact_rate']}")
        worst = [(k, v) for k, v in summary.get("obligations_by_role", {}).items()
                 if v["missing"]]
        for role, v in worst[:5]:
            print(f"    {role:14} missing={v['missing']:3} of {v['expected']:3} owed")

    weak = [(f, s) for f, s in summary["by_field"].items() if s["wrong"] or s["abstained"]]
    if weak:
        print("\nWEAKEST FIELDS")
        for field, s in weak[:12]:
            print(f"  {field:42} wrong={s['wrong']:2} abstained={s['abstained']:2} "
                  f"correct={s['correct']:2}")

    # Gates are judged against the interval, not the point estimate: on samples
    # this size an estimate can clear a threshold while the interval straddles
    # it, and reporting that as PASS is how the accuracy claim becomes
    # indefensible the moment someone checks the arithmetic.
    print("\nTHRESHOLDS  (judged on the confidence interval, not the estimate)")
    verdicts = threshold_verdicts(summary)
    for v in verdicts:
        mark = {"pass": "PASS    ", "unproven": "UNPROVEN", "fail": "FAIL    "}[v["verdict"]]
        print(f"  {mark}  {v['metric']:20} {v['display']}  (target {v['limit']:.0%})")

    unproven = [v for v in verdicts if v["verdict"] == "unproven"]
    if unproven:
        print(f"\n  {len(unproven)} gate(s) UNPROVEN — the estimate clears the target "
              "but the sample")
        print("  is too small to show it. Do NOT report these as met. To prove them,")
        print("  assuming every further observation is clean:")
        for v in unproven:
            unit = "labelled fields" if v["metric"] in (
                "field_accuracy", "wrong_rate") else "tier-asserting cases"
            need = ("more than 5000" if v["needed"] is None else f"+{v['needed']}")
            print(f"    {v['metric']:20} {need} {unit}  "
                  f"(have {v['n']})")

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
    ap.add_argument("--set", dest="which", choices=sorted(SETS), default="golden",
                    help="'golden' (development, tuned against) or 'holdout' "
                         "(never tuned against — the unbiased figure)")
    args = ap.parse_args()

    cases = load_cases(args.lang, args.limit, args.case, args.which)
    if args.which == "holdout" and not args.check_labels:
        print("Running the HELD-OUT set. Do not tune facts.py on these results — "
              "reproduce a failure in the development set first.\n")
    if not cases:
        print("No cases matched.")
        return 1
    return check_labels(cases) if args.check_labels else run(cases, args.report)


if __name__ == "__main__":
    raise SystemExit(main())
