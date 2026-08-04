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
