"""Unit tests for the deterministic rule engine (rules.py)."""
from rules import classify
from schema import Facts


# --- the three required demo cases -------------------------------------------
def test_recruitment_cv_ranking():
    f = Facts(is_ai_system=True, high_risk_domains=["employment"],
              organisation_role="provider", gpai_relationship="builds_or_finetunes")
    a = classify(f, "CV Screener")
    assert a.tier == "ANNEX_III"
    assert a.high_risk.result == "ANNEX_III"
    assert any("Annex III(4)" in art for art in a.high_risk.articles)
    assert a.is_gpai is True
    assert a.application_date.startswith("2 December 2027")
    assert a.human_review_required is True
    assert len(a.obligations) >= 13  # 13 high-risk + GPAI


def test_customer_service_chatbot():
    f = Facts(is_ai_system=True, interacts_with_people=True,
              organisation_role="deployer", gpai_relationship="uses_api")
    a = classify(f, "Support Bot")
    assert a.tier == "LIMITED"
    assert a.transparency.result == "Yes"
    assert "Art. 50(1)" in a.transparency.articles
    assert a.is_gpai is False


def test_emotion_recognition_workplace():
    f = Facts(is_ai_system=True, emotion_recognition=True,
              emotion_context="workplace_education", organisation_role="deployer")
    a = classify(f, "Mood Monitor")
    assert a.tier == "PROHIBITED"
    assert a.prohibited_practice.result == "Yes"
    assert "Art. 5(1)(f)" in a.prohibited_practice.articles


# --- edge cases --------------------------------------------------------------
def test_prohibited_overrides_high_risk():
    f = Facts(is_ai_system=True, social_scoring=True, high_risk_domains=["employment"])
    a = classify(f, "Score-o-matic")
    assert a.tier == "PROHIBITED"  # prohibited wins the headline
    assert a.high_risk.result == "ANNEX_III"  # but the dimension is still reported


def test_annex_i_regulated_product():
    f = Facts(is_ai_system=True, safety_component_regulated_product=True)
    a = classify(f, "Medical Device AI")
    assert a.tier == "ANNEX_I"
    assert a.application_date.startswith("2 August 2028")


def test_minimal_when_nothing_triggers():
    f = Facts(is_ai_system=True, interacts_with_people=False,
              generates_synthetic_content=False)
    a = classify(f, "Spam Filter")
    assert a.tier == "MINIMAL"
    assert a.is_gpai is False


def test_unknown_is_ai_is_unresolved():
    f = Facts(is_ai_system=None)
    a = classify(f, "Mystery")
    assert a.is_ai_system.status == "unresolved"
    assert a.confidence == "low"
    assert a.human_review_required is True
    assert a.missing_information  # non-empty


def test_gpai_systemic_adds_extra_obligations():
    base = classify(Facts(is_ai_system=True, gpai_relationship="builds_or_finetunes"))
    systemic = classify(Facts(is_ai_system=True, gpai_relationship="builds_or_finetunes",
                              gpai_systemic_risk=True))
    assert len(systemic.obligations) > len(base.obligations)


def test_credit_scoring_annex_iii_point5():
    f = Facts(is_ai_system=True, high_risk_domains=["credit"], organisation_role="provider")
    a = classify(f, "CrediScore")
    assert a.tier == "ANNEX_III"
    assert any("Annex III(5)(b)" in art for art in a.high_risk.articles)


def test_provenance_present_on_every_dimension():
    a = classify(Facts(is_ai_system=True, high_risk_domains=["education"]))
    for c in (a.is_ai_system, a.prohibited_practice, a.high_risk,
              a.transparency, a.gpai):
        assert c.articles           # cites something
        assert c.trigger            # names the triggering fact
        assert c.status in ("definitive", "conditional", "unresolved")
