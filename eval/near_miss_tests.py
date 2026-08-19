"""Near-miss boundary evaluator: does one decisive fact move the outcome?

    python eval/near_miss_tests.py            # run every pair
    python eval/near_miss_tests.py --verbose  # show the full delta
    python eval/near_miss_tests.py --pair nm-insurance-line

WHY PAIRS

Aggregate accuracy hides boundaries. A set full of obvious cases can score 97%
while getting every carve-out wrong, because the carve-outs are rare and the
obvious cases are many. The tool's entire value is the boundaries — motor vs
health insurance, badge reader vs watchlist, fraud vs creditworthiness — so
those get tested directly, with everything else held constant.

Each pair asserts three things:

  ISOLATION   a and b differ in exactly one labelled fact. Without this a
              difference in outcome proves nothing about that fact.
  SENSITIVITY flipping the decisive fact moves the outcome, in the dimension
              the pair documents (tier, cited articles, or duty set).
  INVARIANCE  changing facts the boundary does not depend on leaves the tier
              alone. A rule that fires on the right input but also on the wrong
              one is not a rule.

Pairs 4 and 5 share a tier on purpose. The tier metric is blind to them, which
is exactly why an eval built only on tiers is not enough: Annex III(6) vs III(8)
changes the citation, and Art. 53 vs Art. 3(68) changes the entire duty set.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from eval.score import obligation_keys  # noqa: E402
from rules import classify  # noqa: E402
from schema import Facts  # noqa: E402

PAIRS_FILE = Path(__file__).parent / "near_miss_set.json"


def load_pairs(pair_id: str | None = None) -> list[dict]:
    pairs = json.loads(PAIRS_FILE.read_text(encoding="utf-8"))["pairs"]
    return [p for p in pairs if p["id"] == pair_id] if pair_id else pairs


def _outcome(case: dict) -> dict:
    a = classify(Facts.model_validate(case["expected"]), case["name"])
    articles = sorted({r for c in (a.high_risk, a.prohibited_practice,
                                   a.transparency, a.gpai) for r in c.articles})
    return {"tier": a.tier, "roles": sorted(a.roles), "is_gpai": a.is_gpai,
            "articles": articles, "duties": sorted(obligation_keys(a))}


def check_pair(pair: dict) -> dict:
    ea, eb = pair["a"]["expected"], pair["b"]["expected"]
    field = pair["decisive_field"]

    # ISOLATION -------------------------------------------------------------
    same_keys = set(ea) == set(eb)
    differing = [k for k in ea if ea.get(k) != eb.get(k)] if same_keys else ["<key mismatch>"]
    isolated = same_keys and differing == [field]

    oa, ob = _outcome(pair["a"]), _outcome(pair["b"])

    # SENSITIVITY -----------------------------------------------------------
    moved = {d for d in ("tier", "articles", "duties", "roles", "is_gpai")
             if oa[d] != ob[d]}
    required = set(pair["differs_in"])
    sensitive = required <= moved

    # Declared tiers must also be what the engine actually produces.
    tiers_ok = (oa["tier"] == pair["a"]["tier"] and ob["tier"] == pair["b"]["tier"])

    # INVARIANCE ------------------------------------------------------------
    invariant_ok, invariant_detail = True, []
    for k, v in pair.get("tier_invariant", {}).items():
        for side, case, base in (("a", pair["a"], oa), ("b", pair["b"], ob)):
            probe = Facts.model_validate(case["expected"]).model_copy(update={k: v})
            got = classify(probe, case["name"]).tier
            if got != base["tier"]:
                invariant_ok = False
                invariant_detail.append(f"{side}: {k}={v!r} moved tier "
                                        f"{base['tier']} -> {got}")

    return {"id": pair["id"], "field": field, "differing": differing,
            "isolated": isolated, "sensitive": sensitive, "tiers_ok": tiers_ok,
            "invariant_ok": invariant_ok, "invariant_detail": invariant_detail,
            "moved": sorted(moved), "required": sorted(required),
            "a": oa, "b": ob,
            "ok": isolated and sensitive and tiers_ok and invariant_ok}


def run(pairs: list[dict], verbose: bool = False) -> int:
    results = [check_pair(p) for p in pairs]
    by_id = {p["id"]: p for p in pairs}

    print("=" * 74)
    print(f"NEAR-MISS BOUNDARIES — {len(results)} pairs")
    print("=" * 74)

    for r in results:
        p = by_id[r["id"]]
        print(f"\n{'PASS' if r['ok'] else 'FAIL'}  {r['id']}   [{p['purpose']}]")
        print(f"      decisive fact : {r['field']}")
        print(f"      a {p['a']['tier']:<12} {p['a']['name']}")
        print(f"      b {p['b']['tier']:<12} {p['b']['name']}")
        print(f"      outcome moved in: {', '.join(r['moved']) or 'NOTHING'}"
              f"   (required: {', '.join(r['required'])})")
        if not r["isolated"]:
            print(f"      ISOLATION FAIL  differs in {r['differing']}, "
                  f"expected only [{r['field']}]")
        if not r["sensitive"]:
            print("      SENSITIVITY FAIL  the decisive fact did not move the "
                  "required dimension")
        if not r["tiers_ok"]:
            print(f"      TIER LABEL FAIL  engine gave {r['a']['tier']}/"
                  f"{r['b']['tier']}, labels say {p['a']['tier']}/{p['b']['tier']}")
        for d in r["invariant_detail"]:
            print(f"      INVARIANCE FAIL  {d}")

        if verbose:
            for dim in ("tier", "roles", "is_gpai", "articles", "duties"):
                if r["a"][dim] != r["b"][dim]:
                    print(f"        {dim}:")
                    if dim in ("articles", "duties"):
                        only_a = sorted(set(r['a'][dim]) - set(r['b'][dim]))
                        only_b = sorted(set(r['b'][dim]) - set(r['a'][dim]))
                        if only_a:
                            print(f"          only a: {', '.join(only_a)}")
                        if only_b:
                            print(f"          only b: {', '.join(only_b)}")
                    else:
                        print(f"          a={r['a'][dim]}  b={r['b'][dim]}")
            print(f"        reasoning: {p['reasoning']}")

    passed = sum(1 for r in results if r["ok"])
    print("\n" + "=" * 74)
    print(f"  {passed}/{len(results)} boundaries hold")
    print("=" * 74)
    return 0 if passed == len(results) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pair", help="run a single pair id")
    ap.add_argument("--verbose", action="store_true", help="show the full delta")
    args = ap.parse_args()
    pairs = load_pairs(args.pair)
    if not pairs:
        print("No pairs matched.")
        return 1
    return run(pairs, args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
