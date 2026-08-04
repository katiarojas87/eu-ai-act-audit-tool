"""Tests for consultant-supplied Article 2 scope facts (scope_input.py).

No API key needed — the mapping is pure.
"""
import pytest

from rules import classify
from schema import Facts
from scope_input import ScopeOverride, to_fact_overrides


def _classify(scope: ScopeOverride, **extracted):
    """Simulate the API path: extraction result, then overrides applied on top."""
    data = {"is_ai_system": True, **extracted}
    data.update(to_fact_overrides(scope))
    return classify(Facts.model_validate(data), "T")


def test_nothing_set_overrides_nothing():
    assert to_fact_overrides(ScopeOverride()) == {}
    assert to_fact_overrides(None) == {}


def test_unticked_box_does_not_assert_false():
    """An unticked carve-out means 'not stated', not 'no'."""
    out = to_fact_overrides(ScopeOverride(nexus="eu_market"))
    assert "military_defence_national_security" not in out


@pytest.mark.parametrize("nexus,expected", [
    ("eu_market", {"placed_on_eu_market": True}),
    ("output_in_eu", {"established_outside_eu": True, "output_used_in_eu": True}),
    ("none", {"established_outside_eu": True, "output_used_in_eu": False,
              "placed_on_eu_market": False}),
])
def test_nexus_maps_to_the_right_facts(nexus, expected):
    assert to_fact_overrides(ScopeOverride(nexus=nexus)) == expected


def test_no_nexus_puts_the_system_out_of_scope():
    a = _classify(ScopeOverride(nexus="none"), high_risk_domains=["employment"])
    assert a.tier == "OUT_OF_SCOPE"
    assert a.obligations == []


def test_eu_market_keeps_it_in_scope():
    a = _classify(ScopeOverride(nexus="eu_market"), high_risk_domains=["employment"])
    assert a.tier == "ANNEX_III"
    assert a.territorial_scope.result == "Yes"


def test_override_beats_a_wrong_extraction():
    """The consultant knows; the description did not say."""
    a = _classify(ScopeOverride(nexus="none"),
                  high_risk_domains=["employment"], placed_on_eu_market=True)
    assert a.tier == "OUT_OF_SCOPE"


@pytest.mark.parametrize("field", [
    "military_defence_national_security",
    "sole_purpose_scientific_research",
    "personal_non_professional_use",
])
def test_each_carve_out_excludes(field):
    a = _classify(ScopeOverride(**{field: True}), high_risk_domains=["employment"])
    assert a.tier == "OUT_OF_SCOPE"


def test_real_world_testing_cancels_the_prerelease_carve_out():
    lab = _classify(ScopeOverride(nexus="eu_market", prerelease_research_testing=True),
                    high_risk_domains=["credit"], real_world_testing=False)
    assert lab.tier == "OUT_OF_SCOPE"

    field = _classify(ScopeOverride(nexus="eu_market", prerelease_research_testing=True,
                                    real_world_testing=True),
                      high_risk_domains=["credit"])
    assert field.tier == "ANNEX_III"


def test_every_carve_out_names_a_real_facts_field():
    from scope_input import CARVE_OUTS
    valid = set(Facts.model_fields)
    assert set(CARVE_OUTS) <= valid


def test_overrides_only_emit_known_facts_fields():
    valid = set(Facts.model_fields)
    every = ScopeOverride(nexus="none", military_defence_national_security=True,
                          sole_purpose_scientific_research=True,
                          prerelease_research_testing=True, real_world_testing=True,
                          personal_non_professional_use=True)
    assert set(to_fact_overrides(every)) <= valid
