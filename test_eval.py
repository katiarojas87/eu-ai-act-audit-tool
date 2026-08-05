"""Tests for the evaluation harness (eval/score.py and the golden set).

The scorer is the instrument. If it is wrong, every number it produces is wrong,
so it gets the same treatment as the rule engine: offline, deterministic tests.
No API key required.
"""
import json
from pathlib import Path

import pytest

from eval.run_eval import GOLDEN, load_cases
from eval.score import (
    THRESHOLDS, aggregate, check_thresholds, score_case, tier_verdict,
)
from rules import classify
from schema import Facts


# --- verdicts ------------------------------------------------------------------
def test_exact_match_is_correct():
    r = score_case({"is_ai_system": True}, Facts(is_ai_system=True))
    assert [x.verdict for x in r] == ["correct"]


def test_null_where_a_value_was_expected_is_abstention_not_error():
    """Leaving a fact unknown is recoverable; it becomes a follow-up question."""
    r = score_case({"is_ai_system": True}, Facts(is_ai_system=None))
    assert r[0].verdict == "abstained"


def test_asserting_the_opposite_is_wrong():
    r = score_case({"is_ai_system": True}, Facts(is_ai_system=False))
    assert r[0].verdict == "wrong"


def test_enum_default_counts_as_abstention():
    r = score_case({"gpai_relationship": "builds_or_finetunes"}, Facts())
    assert r[0].verdict == "abstained"


def test_wrong_enum_value_is_an_error_not_an_abstention():
    r = score_case({"gpai_relationship": "builds_or_finetunes"},
                   Facts(gpai_relationship="uses_api"))
    assert r[0].verdict == "wrong"


def test_expected_false_is_not_treated_as_abstention():
    """False is an answer. Only None/defaults count as declining to answer."""
    r = score_case({"is_ai_system": False}, Facts(is_ai_system=False))
    assert r[0].verdict == "correct"


def test_domain_lists_compare_order_insensitively():
    r = score_case({"high_risk_domains": ["employment", "credit"]},
                   Facts(high_risk_domains=["credit", "employment"]))
    assert r[0].verdict == "correct"


def test_empty_expected_list_versus_extra_domain_is_wrong():
    r = score_case({"high_risk_domains": []},
                   Facts(high_risk_domains=["employment"]))
    assert r[0].verdict == "wrong"


def test_prose_fields_are_not_scored():
    r = score_case({"purpose": "anything", "is_ai_system": True},
                   Facts(is_ai_system=True))
    assert [x.field for x in r] == ["is_ai_system"]


def test_unlabelled_fields_are_ignored():
    r = score_case({"is_ai_system": True},
                   Facts(is_ai_system=True, social_scoring=True))
    assert len(r) == 1


# --- tier verdicts -------------------------------------------------------------
@pytest.mark.parametrize("want,got,verdict", [
    ("ANNEX_III", "ANNEX_III", "exact"),
    ("ANNEX_III", "LIMITED", "under_warned"),
    ("PROHIBITED", "ANNEX_III", "under_warned"),
    ("MINIMAL", "ANNEX_III", "over_warned"),
    ("OUT_OF_SCOPE", "ANNEX_III", "over_warned"),
    ("ANNEX_III", "OUT_OF_SCOPE", "under_warned"),
])
def test_tier_verdict_direction(want, got, verdict):
    assert tier_verdict(want, got) == verdict


# --- aggregation ---------------------------------------------------------------
def _case(verdicts, tier_verdict_value=None):
    fields = []
    for i, v in enumerate(verdicts):
        fields += score_case(
            {"is_ai_system": True} if v == "correct" else
            {"social_scoring": True},
            Facts(is_ai_system=True) if v == "correct" else
            Facts(social_scoring=False if v == "wrong" else None))
        fields[-1].field = f"f{i}"
    return {"id": "x", "fields": fields, "tier_verdict": tier_verdict_value}


def test_aggregate_computes_rates():
    s = aggregate([_case(["correct", "wrong", "abstained"], "exact")])
    assert s["counts"] == {"correct": 1, "abstained": 1, "wrong": 1}
    assert s["field_accuracy"] == pytest.approx(1 / 3)
    assert s["wrong_rate"] == pytest.approx(1 / 3)
    assert s["tier_exact"] == 1.0


def test_aggregate_handles_no_tier_assertions():
    s = aggregate([_case(["correct"])])
    assert s["tier_exact"] == 0.0   # nothing asserted, no division error


def test_thresholds_treat_rates_as_ceilings_and_accuracy_as_floor():
    good = {"field_accuracy": 0.95, "wrong_rate": 0.01,
            "tier_exact": 0.90, "tier_under_warned": 0.0}
    assert all(p for *_, p in check_thresholds(good))

    bad = {**good, "wrong_rate": 0.20}
    failed = [m for m, _, _, p in check_thresholds(bad) if not p]
    assert failed == ["wrong_rate"]


def test_under_warning_threshold_is_strict():
    """Telling a client they owe less than they do is the worst failure."""
    assert THRESHOLDS["tier_under_warned"] <= 0.02


# --- the golden set itself -----------------------------------------------------
def test_golden_set_loads_and_is_substantial():
    cases = load_cases()
    assert len(cases) >= 40
    assert sum(len(c["expected"]) for c in cases) >= 150


def test_golden_set_covers_all_four_languages():
    langs = {c["lang"] for c in load_cases()}
    assert {"en", "nl", "fr", "es"} <= langs


def test_golden_set_covers_every_tier():
    tiers = {c.get("tier") for c in load_cases()}
    assert {"PROHIBITED", "ANNEX_I", "ANNEX_III", "LIMITED", "MINIMAL",
            "OUT_OF_SCOPE", "NOT_AI"} <= tiers


def test_golden_set_ids_are_unique():
    ids = [c["id"] for c in load_cases()]
    assert len(ids) == len(set(ids))


def test_golden_set_labels_agree_with_the_rule_engine():
    """Catches mistakes in the labels — the engine is the reference here."""
    mismatches = []
    for c in load_cases():
        if not c.get("tier"):
            continue
        got = classify(Facts.model_validate(c["expected"]), c["name"]).tier
        if got != c["tier"]:
            mismatches.append(f"{c['id']}: label={c['tier']} engine={got}")
    assert not mismatches, mismatches


def test_every_expected_field_exists_on_the_facts_model():
    """A typo in a label would silently never be scored."""
    valid = set(Facts.model_fields)
    for c in load_cases():
        unknown = set(c["expected"]) - valid
        assert not unknown, f"{c['id']} labels unknown field(s): {unknown}"


def test_golden_set_is_valid_json_with_a_readme():
    data = json.loads(Path(GOLDEN).read_text(encoding="utf-8"))
    assert "_readme" in data and data["cases"]


# --- uncertainty ---------------------------------------------------------------
# A point estimate on 64 observations is not a measurement. These guard the
# reporting discipline that keeps the accuracy claim defensible.
def test_wilson_interval_brackets_the_estimate():
    from eval.score import wilson
    lo, hi = wilson(61, 64)
    assert lo < 61 / 64 < hi
    assert 0.0 <= lo and hi <= 1.0


def test_wilson_is_not_zero_width_at_the_extremes():
    """0/64 wrong must not be reported as a certainty."""
    from eval.score import wilson
    lo, hi = wilson(0, 64)
    assert lo == 0.0 and hi > 0.03


def test_wilson_interval_narrows_as_the_sample_grows():
    from eval.score import wilson
    small = wilson(19, 20)
    large = wilson(950, 1000)
    assert (large[1] - large[0]) < (small[1] - small[0])


def test_wilson_handles_empty_sample():
    from eval.score import wilson
    assert wilson(0, 0) == (0.0, 1.0)


def test_fmt_ci_reports_the_denominator():
    from eval.score import fmt_ci
    out = fmt_ci(61, 64)
    assert "n=64" in out and "95% CI" in out


def test_aggregate_carries_intervals_and_denominators():
    s = aggregate([_case(["correct", "wrong", "abstained"], "exact")])
    assert s["n"]["fields"] == 3
    lo, hi = s["ci"]["field_accuracy"]
    assert lo < s["field_accuracy"] < hi
    assert "n=3" in s["display"]["field_accuracy"]


# --- threshold verdicts --------------------------------------------------------
def test_small_sample_that_clears_the_target_is_unproven_not_passed():
    """The exact failure mode this project had: 95.3% on n=64 read as PASS."""
    from eval.score import threshold_verdicts
    summary = {
        "field_accuracy": 0.953, "wrong_rate": 0.016,
        "tier_exact": 1.0, "tier_under_warned": 0.0,
        "counts": {"correct": 61, "abstained": 2, "wrong": 1},
        "tier_counts": {"exact": 15, "under_warned": 0, "over_warned": 0},
        "n": {"fields": 64, "tiers": 15},
    }
    v = {x["metric"]: x["verdict"] for x in threshold_verdicts(summary)}
    assert v["field_accuracy"] == "unproven"   # CI reaches below the 90% gate
    assert v["wrong_rate"] == "unproven"       # CI reaches above the 5% ceiling


def test_large_clean_sample_passes():
    from eval.score import threshold_verdicts
    summary = {
        "field_accuracy": 0.99, "wrong_rate": 0.0,
        "tier_exact": 0.99, "tier_under_warned": 0.0,
        "counts": {"correct": 1980, "abstained": 20, "wrong": 0},
        "tier_counts": {"exact": 990, "under_warned": 0, "over_warned": 0},
        "n": {"fields": 2000, "tiers": 1000},
    }
    assert all(x["verdict"] == "pass" for x in threshold_verdicts(summary))


def test_point_estimate_on_the_wrong_side_is_a_fail():
    from eval.score import threshold_verdicts
    summary = {
        "field_accuracy": 0.50, "wrong_rate": 0.40,
        "tier_exact": 0.50, "tier_under_warned": 0.30,
        "counts": {"correct": 50, "abstained": 10, "wrong": 40},
        "tier_counts": {"exact": 50, "under_warned": 30, "over_warned": 20},
        "n": {"fields": 100, "tiers": 100},
    }
    assert all(x["verdict"] == "fail" for x in threshold_verdicts(summary))


# --- obligation-level scoring --------------------------------------------------
def test_dropped_duty_is_caught_as_missing():
    """A correct tier that silently drops Art. 27 is a failed audit."""
    from eval.score import score_obligations
    expected = {"deployer:Art. 26(1)", "deployer:Art. 27", "all:Art. 4"}
    actual = {"deployer:Art. 26(1)", "all:Art. 4"}
    s = score_obligations(expected, actual)
    assert s["missing"] == ["deployer:Art. 27"]
    assert s["recall"] < 1.0 and s["precision"] == 1.0
    assert not s["exact"]


def test_duties_are_keyed_by_role():
    """provider:Art. 27 and deployer:Art. 27 are different claims about the law."""
    from eval.score import score_obligations
    s = score_obligations({"deployer:Art. 27"}, {"provider:Art. 27"})
    assert s["missing"] == ["deployer:Art. 27"]
    assert s["extra"] == ["provider:Art. 27"]


def test_obligation_keys_reflect_the_engine():
    from eval.score import obligation_keys
    from rules import classify
    a = classify(Facts(is_ai_system=True, high_risk_domains=["employment"],
                       placed_on_eu_market=True, developed_or_commissioned=True,
                       supplied_under_own_name=True), "x")
    keys = obligation_keys(a)
    assert "provider:Art. 9" in keys
    assert all(":" in k for k in keys)


# --- label sufficiency ---------------------------------------------------------
def test_unlabelled_decisive_field_is_detected():
    """A case that does not pin an Art. 2 carve-out does not pin its own answer."""
    from eval.completeness import analyse_case
    case = {"id": "t", "name": "CV Screener",
            "expected": {"is_ai_system": True, "high_risk_domains": ["employment"],
                         "placed_on_eu_market": True}}
    r = analyse_case(case)
    flagged = {d["field"] for d in r["decisive_unlabelled"]}
    # Left unlabelled, any of these flips the assessment to OUT_OF_SCOPE.
    assert "military_defence_national_security" in flagged
    assert not r["sufficient"]


def test_fully_pinned_case_reports_sufficient():
    """Labelling every decisive field makes the case self-determining."""
    from eval.completeness import analyse_case
    expected = {"is_ai_system": False}
    # Pin everything the engine could otherwise move on.
    for f in Facts.model_fields:
        expected.setdefault(f, Facts.model_fields[f].default)
    r = analyse_case({"id": "t", "name": "x", "expected": expected})
    assert r["sufficient"], r["decisive_unlabelled"]


def test_labelled_fields_are_never_flagged():
    from eval.completeness import analyse_case
    case = {"id": "t", "name": "x",
            "expected": {"is_ai_system": True, "social_scoring": True,
                         "social_scoring_detrimental_treatment": True}}
    flagged = {d["field"] for d in analyse_case(case)["decisive_unlabelled"]}
    assert not (flagged & set(case["expected"]))


# --- Article 2 scope gates -----------------------------------------------------
# These four decide whether the Regulation applies at all, so an unstated one is
# an unchecked assumption rather than a missing detail.
def test_every_case_states_the_scope_gates():
    from eval.completeness import validate_cases
    import json
    from eval.run_eval import SETS
    for which, path in SETS.items():
        cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
        incomplete = validate_cases(cases)
        assert not incomplete, f"{which}: {incomplete[:3]}"


def test_missing_scope_gate_is_reported():
    from eval.completeness import missing_required
    assert missing_required({"expected": {"is_ai_system": True}})
    full = {"expected": {g: False for g in
                         __import__("eval.completeness", fromlist=["x"]).SCOPE_GATES}}
    assert missing_required(full) == []


def test_scope_gates_are_no_longer_flagged_as_unlabelled():
    """The whole point of labelling them: completeness stops reporting them."""
    from eval.completeness import SCOPE_GATES, analyse_case
    import json
    from eval.run_eval import SETS
    cases = json.loads(SETS["golden"].read_text(encoding="utf-8"))["cases"]
    flagged = {d["field"] for c in cases[:12]
               for d in analyse_case(c)["decisive_unlabelled"]}
    assert not (flagged & set(SCOPE_GATES))


# --- near-miss boundaries ------------------------------------------------------
def test_near_miss_pairs_isolate_one_fact_and_move_the_outcome():
    from eval.near_miss_tests import check_pair, load_pairs
    pairs = load_pairs()
    assert len(pairs) >= 5
    for p in pairs:
        r = check_pair(p)
        assert r["isolated"], f"{r['id']} differs in {r['differing']}"
        assert r["sensitive"], f"{r['id']} moved {r['moved']}, needed {r['required']}"
        assert r["tiers_ok"], r["id"]
        assert r["invariant_ok"], r["invariant_detail"]


def test_near_miss_covers_the_documented_boundaries():
    from eval.near_miss_tests import load_pairs
    fields = {p["decisive_field"] for p in load_pairs()}
    assert {"insurance_life_or_health", "biometric_verification_only",
            "credit_fraud_detection_only", "gpai_relationship"} <= fields


def test_some_near_miss_pairs_share_a_tier():
    """If every pair moved the tier, the tier metric would suffice. It does not."""
    from eval.near_miss_tests import load_pairs
    assert any(p["a"]["tier"] == p["b"]["tier"] for p in load_pairs())


# --- obligation metrics --------------------------------------------------------
def test_f2_punishes_a_missing_duty_more_than_an_extra_one():
    from eval.score import score_obligations
    owed = {"provider:Art. 9", "provider:Art. 10", "provider:Art. 11"}
    dropped = score_obligations(owed, {"provider:Art. 9", "provider:Art. 10"})
    added = score_obligations(owed, owed | {"provider:Art. 99"})
    assert dropped["f2"] < added["f2"]
    assert dropped["under_warning_rate"] > 0
    assert added["under_warning_rate"] == 0


def test_aggregate_obligations_is_micro_averaged():
    from eval.score import aggregate_obligations
    big = ({f"provider:Art. {i}" for i in range(10)},
           {f"provider:Art. {i}" for i in range(10)})
    small = ({"all:Art. 4"}, set())
    agg = aggregate_obligations([big, small])
    assert agg["expected"] == 11 and agg["correct"] == 10
    assert agg["recall"] == pytest.approx(10 / 11)
    assert agg["exact_cases"] == 1


def test_slice_obligations_localises_the_error():
    from eval.score import slice_obligations
    pairs = [({"deployer:Art. 27", "provider:Art. 9"}, {"provider:Art. 9"})]
    by_role = slice_obligations(pairs, "role")
    assert by_role["deployer"]["missing"] == 1
    assert by_role["provider"]["missing"] == 0
    by_article = slice_obligations(pairs, "article")
    assert by_article["Art. 27"]["missing"] == 1


# --- annotation planning -------------------------------------------------------
def test_observations_needed_is_zero_when_already_proven():
    from eval.score import observations_needed
    assert observations_needed(1000, 1000, 0.85, ceiling=False) == 0


def test_proving_a_strict_ceiling_needs_many_more_cases():
    """0/17 under-warnings cannot demonstrate a 2% ceiling."""
    from eval.score import observations_needed
    need = observations_needed(0, 17, 0.02, ceiling=True)
    assert need is not None and need > 100


def test_scaffold_reports_a_gap_without_inventing_cases():
    from eval.scaffold_cases import current_counts
    tier, total = current_counts()
    assert tier > 0 and total >= tier
