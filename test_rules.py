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


# --- Article 6(3) derogation --------------------------------------------------
def test_art_6_3_takes_annex_iii_system_out_of_high_risk():
    f = Facts(is_ai_system=True, high_risk_domains=["employment"],
              art_6_3_ground="narrow_procedural_task", profiling=False,
              organisation_role="provider")
    a = classify(f, "CV spell-checker")
    assert a.high_risk.result == "ANNEX_III_EXEMPT"
    assert a.tier != "ANNEX_III"
    assert "Art. 6(3)" in a.high_risk.articles


def test_profiling_defeats_the_art_6_3_derogation():
    f = Facts(is_ai_system=True, high_risk_domains=["employment"],
              art_6_3_ground="narrow_procedural_task", profiling=True)
    a = classify(f, "Candidate ranker")
    assert a.tier == "ANNEX_III"
    assert a.high_risk.result == "ANNEX_III"
    assert "profiling" in a.high_risk.detail


def test_art_6_3_is_conditional_while_profiling_unknown():
    f = Facts(is_ai_system=True, high_risk_domains=["credit"],
              art_6_3_ground="preparatory_task", profiling=None)
    a = classify(f, "Pre-screener")
    assert a.high_risk.status == "conditional"
    assert a.human_review_required is True
    assert any("profil" in m.lower() for m in a.missing_information)


def test_art_6_3_exempt_still_carries_documentation_duties():
    f = Facts(is_ai_system=True, high_risk_domains=["education"],
              art_6_3_ground="improves_human_output", profiling=False)
    obligations = [o.obligation for o in classify(f).obligations]
    assert any("Art. 6(3)" in o for o in obligations)
    assert any("Register" in o for o in obligations)


def test_derogation_not_applied_unless_a_ground_is_claimed():
    f = Facts(is_ai_system=True, high_risk_domains=["employment"], profiling=False)
    assert classify(f).tier == "ANNEX_III"   # fails safe


# --- unknown / conditional handling -------------------------------------------
def test_unknown_ai_system_is_undetermined_not_minimal():
    a = classify(Facts(), "Mystery")
    assert a.tier == "UNDETERMINED"
    assert a.confidence == "low"
    assert a.human_review_required is True


def test_emotion_recognition_ban_is_conditional_on_the_exception():
    f = Facts(is_ai_system=True, emotion_recognition=True,
              emotion_context="workplace_education")
    a = classify(f, "Mood Monitor")
    assert a.tier == "PROHIBITED"
    assert a.prohibited_practice.status == "conditional"
    assert "medical" in a.prohibited_practice.detail


def test_irrelevant_prohibitions_do_not_block_a_clean_result():
    """A spam filter should not sit forever at 'cannot rule out biometric scraping'."""
    f = Facts(is_ai_system=True, interacts_with_people=False,
              generates_synthetic_content=False, safety_component_regulated_product=False,
              manipulative_or_exploitative=False, social_scoring=False,
              organisation_role="deployer", placed_on_eu_market=True)
    a = classify(f, "Spam Filter")
    assert a.prohibited_practice.result == "No"
    assert a.confidence == "high"
    assert a.human_review_required is False


def test_biometric_context_reopens_the_gated_prohibitions():
    f = Facts(is_ai_system=True, high_risk_domains=["biometrics"],
              manipulative_or_exploitative=False, social_scoring=False)
    a = classify(f, "Face ID")
    assert a.prohibited_practice.result == "Possible"
    assert any("5(1)" in art for art in a.prohibited_practice.articles)


def test_confidence_discriminates_across_inputs():
    """A confidence signal that is always the same value carries no information."""
    clean = Facts(is_ai_system=True, interacts_with_people=False,
                  generates_synthetic_content=False, safety_component_regulated_product=False,
                  manipulative_or_exploitative=False, social_scoring=False,
                  organisation_role="provider", placed_on_eu_market=True)
    assert classify(clean).confidence == "high"
    assert classify(Facts()).confidence == "low"


# --- role derivation and role-split obligations -------------------------------
def _hr(**kw):
    base = dict(is_ai_system=True, high_risk_domains=["employment"])
    base.update(kw)
    return Facts(**base)


def _obligations(a, role=None):
    return [o.obligation for o in a.obligations if role is None or o.role == role]


def test_deployer_is_never_told_to_ce_mark():
    """A deployer cannot lawfully CE-mark a system it did not build."""
    a = classify(_hr(developed_or_commissioned=False, uses_under_own_authority=True))
    assert a.roles == ["deployer"]
    joined = " ".join(_obligations(a))
    for provider_only in ("CE marking", "Conformity assessment",
                          "EU declaration of conformity", "Quality management system"):
        assert provider_only not in joined, f"deployer was told to: {provider_only}"


def test_deployer_gets_article_26_duties():
    a = classify(_hr(developed_or_commissioned=False, uses_under_own_authority=True))
    arts = {o.article for o in a.obligations}
    assert {"Art. 26(1)", "Art. 26(2)", "Art. 26(6)", "Art. 26(7)"} <= arts


def test_provider_gets_the_full_article_16_chain():
    a = classify(_hr(developed_or_commissioned=True, supplied_under_own_name=True))
    assert a.roles == ["provider"]
    arts = {o.article for o in a.obligations}
    assert {"Art. 9", "Art. 11", "Art. 17", "Art. 43", "Art. 47", "Art. 48"} <= arts
    assert not any(o.article.startswith("Art. 26") for o in a.obligations)


def test_in_house_build_is_provider_and_deployer():
    a = classify(_hr(developed_or_commissioned=True, supplied_under_own_name=True,
                     uses_under_own_authority=True))
    assert set(a.roles) == {"provider", "deployer"}
    assert _obligations(a, "provider") and _obligations(a, "deployer")


def test_art_25_escalates_a_modifier_to_provider():
    """Fine-tuning a bought model moves the whole provider burden onto you."""
    a = classify(_hr(developed_or_commissioned=False, uses_under_own_authority=True,
                     rebranded_or_modified=True))
    assert "provider" in a.roles
    assert "Art. 25(1)" in a.role_basis.articles
    assert any("CE marking" in o for o in _obligations(a, "provider"))


def test_unknown_role_shows_both_lists_labelled():
    a = classify(_hr())
    assert a.roles == ["unknown"]
    assert _obligations(a, "provider") and _obligations(a, "deployer")
    assert any("role" in m.lower() for m in a.missing_information)


def test_consultant_override_beats_inference():
    a = classify(_hr(developed_or_commissioned=True, supplied_under_own_name=True,
                     organisation_role="deployer"))
    assert a.roles == ["deployer"]
    assert "CE marking" not in " ".join(_obligations(a))


def test_ai_literacy_applies_to_everyone_at_every_tier():
    for f in (_hr(uses_under_own_authority=True),
              Facts(is_ai_system=True, interacts_with_people=True,
                    uses_under_own_authority=True),
              Facts(is_ai_system=True, uses_under_own_authority=True)):
        assert "Art. 4" in {o.article for o in classify(f).obligations}


def test_fria_only_where_article_27_applies():
    # credit deployer → FRIA owed outright
    credit = classify(Facts(is_ai_system=True, high_risk_domains=["credit"],
                            uses_under_own_authority=True))
    fria = [o for o in credit.obligations if o.article == "Art. 27"]
    assert fria and "only if" not in fria[0].obligation

    # ordinary private employer, status unknown → conditional, not asserted
    empl = classify(_hr(uses_under_own_authority=True))
    fria = [o for o in empl.obligations if o.article == "Art. 27"]
    assert fria and "only if" in fria[0].obligation


def test_article_17_4_carve_out_for_financial_institutions():
    a = classify(Facts(is_ai_system=True, high_risk_domains=["credit"],
                       developed_or_commissioned=True, supplied_under_own_name=True,
                       sectoral_regime="financial_services"))
    qms = [o for o in a.obligations if o.article == "Art. 17(4)"]
    assert qms, "financial institution did not get the Art. 17(4) carve-out"
    assert "(g)" in qms[0].reasoning and "(h)" in qms[0].reasoning


def test_non_eu_provider_needs_an_authorised_representative():
    a = classify(_hr(developed_or_commissioned=True, supplied_under_own_name=True,
                     established_outside_eu=True))
    assert "Art. 22" in {o.article for o in a.obligations}


def test_every_obligation_names_a_role_and_an_article():
    a = classify(_hr(developed_or_commissioned=True, supplied_under_own_name=True,
                     uses_under_own_authority=True))
    for o in a.obligations:
        assert o.role, f"{o.obligation} has no role"
        assert o.article, f"{o.obligation} has no article"


def test_role_basis_is_cited():
    a = classify(_hr(uses_under_own_authority=True))
    assert a.role_basis.articles
    assert a.role_basis.sources, "role derivation has no verbatim source"


# --- provenance ---------------------------------------------------------------
def test_every_source_quote_is_binding_text():
    a = classify(Facts(is_ai_system=True, high_risk_domains=["employment"]))
    for c in (a.is_ai_system, a.prohibited_practice, a.high_risk, a.transparency, a.gpai):
        for s in c.sources:
            assert s.kind == "operative", f"{s.ref} quoted a non-binding recital"


def test_provenance_present_on_every_dimension():
    a = classify(Facts(is_ai_system=True, high_risk_domains=["education"]))
    for c in (a.is_ai_system, a.prohibited_practice, a.high_risk,
              a.transparency, a.gpai):
        assert c.articles           # cites something
        assert c.trigger            # names the triggering fact
        assert c.status in ("definitive", "conditional", "unresolved")


# --- malformed LLM output must degrade, never crash ---------------------------
def test_malformed_llm_output_does_not_break_extraction():
    """A bad field is 'unknown', not a 500. Observed live: human_oversight=false."""
    payloads = [
        {"is_ai_system": True, "human_oversight": False},          # bool for an enum
        {"organisation_role": "user", "gpai_relationship": "maybe"},  # unknown category
        {"high_risk_domains": "employment"},                        # str instead of list
        {"high_risk_domains": ["employment", "astrology"]},         # invalid member
        {"emotion_context": {"nested": 1}, "purpose": 42},          # unhashable / wrong type
        {"profiling": "true", "interacts_with_people": "unknown"},  # stringly-typed bools
        {"organisation_role": ["provider"], "high_risk_domains": None},
    ]
    for p in payloads:
        f = Facts.model_validate(p)      # must not raise
        classify(f, "Robustness")        # and must classify


def test_loose_values_are_coerced_to_the_right_meaning():
    assert Facts.model_validate({"profiling": "true"}).profiling is True
    assert Facts.model_validate({"profiling": "no"}).profiling is False
    assert Facts.model_validate({"profiling": "dunno"}).profiling is None
    assert Facts.model_validate({"human_oversight": False}).human_oversight == "unknown"
    assert Facts.model_validate(
        {"high_risk_domains": ["credit", "bogus"]}).high_risk_domains == ["credit"]


# --- Article 5 elements and exceptions ----------------------------------------
def _ai(**kw):
    return Facts(is_ai_system=True, **kw)


def test_art_5_1_f_medical_exception_defeats_the_ban():
    a = classify(_ai(emotion_recognition=True, emotion_context="workplace_education",
                     emotion_medical_or_safety_purpose=True))
    assert a.tier != "PROHIBITED"


def test_art_5_1_f_is_definitive_once_the_exception_is_ruled_out():
    a = classify(_ai(emotion_recognition=True, emotion_context="workplace_education",
                     emotion_medical_or_safety_purpose=False))
    assert a.tier == "PROHIBITED"
    assert a.prohibited_practice.status == "definitive"


def test_art_5_1_d_human_assessment_exception():
    banned = classify(_ai(predictive_policing_profiling_only=True,
                          high_risk_domains=["law_enforcement"]))
    assert banned.tier == "PROHIBITED"
    assert banned.prohibited_practice.status == "conditional"

    ok = classify(_ai(predictive_policing_profiling_only=True,
                      predictive_policing_supports_human_assessment=True,
                      high_risk_domains=["law_enforcement"]))
    assert ok.tier != "PROHIBITED"


def test_art_5_1_g_lawful_dataset_filtering_exception():
    ok = classify(_ai(biometric_categorisation_sensitive=True,
                      biometric_lawful_dataset_filtering=True,
                      high_risk_domains=["biometrics"]))
    assert ok.tier != "PROHIBITED"


def test_art_5_1_a_requires_significant_harm():
    """Manipulation without significant harm is not caught by Art. 5(1)(a)."""
    no_harm = classify(_ai(subliminal_or_manipulative=True,
                           causes_significant_harm=False, social_scoring=False))
    assert no_harm.tier != "PROHIBITED"

    harm = classify(_ai(subliminal_or_manipulative=True, causes_significant_harm=True))
    assert harm.tier == "PROHIBITED"
    assert harm.prohibited_practice.status == "definitive"


def test_art_5_1_c_requires_detrimental_treatment():
    ok = classify(_ai(social_scoring=True, social_scoring_detrimental_treatment=False,
                      subliminal_or_manipulative=False, exploits_vulnerabilities=False))
    assert ok.tier != "PROHIBITED"

    bad = classify(_ai(social_scoring=True, social_scoring_detrimental_treatment=True))
    assert bad.tier == "PROHIBITED"
    assert bad.prohibited_practice.status == "definitive"


def test_art_5_1_e_scraping_has_no_exception():
    a = classify(_ai(untargeted_facial_scraping=True))
    assert a.tier == "PROHIBITED"
    assert a.prohibited_practice.status == "definitive"


def test_art_5_1_a_and_b_are_separate_prohibitions():
    a = classify(_ai(exploits_vulnerabilities=True, causes_significant_harm=True,
                     subliminal_or_manipulative=False))
    assert "Art. 5(1)(b)" in a.prohibited_practice.articles
    assert "Art. 5(1)(a)" not in a.prohibited_practice.articles


def test_legacy_manipulative_field_still_works():
    """Older callers set one merged field; it must seed both (a) and (b)."""
    f = Facts.model_validate({"is_ai_system": True,
                              "manipulative_or_exploitative": True,
                              "causes_significant_harm": True})
    a = classify(f)
    assert a.tier == "PROHIBITED"
    assert {"Art. 5(1)(a)", "Art. 5(1)(b)"} <= set(a.prohibited_practice.articles)


# --- Article 5(1)(h): real-time remote biometric identification ---------------
def _rbi(**kw):
    return _ai(realtime_remote_biometric_id_public_le=True,
               high_risk_domains=["law_enforcement", "biometrics"],
               uses_under_own_authority=True, **kw)


def test_rbi_without_a_permitted_objective_is_banned():
    a = classify(_rbi())
    assert a.tier == "PROHIBITED"
    assert a.prohibited_practice.status == "definitive"


def test_rbi_with_objective_but_unknown_authorisation_is_conditional():
    a = classify(_rbi(rbi_permitted_objective="imminent_threat"))
    assert a.tier == "PROHIBITED"
    assert a.prohibited_practice.status == "conditional"
    # and the report must not tell them to switch it off outright
    assert any("Suspend use" in o.obligation for o in a.obligations)


def test_rbi_properly_authorised_is_not_prohibited_but_carries_safeguards():
    a = classify(_rbi(rbi_permitted_objective="victim_search",
                      rbi_prior_authorisation=True))
    assert a.tier != "PROHIBITED"
    arts = {o.article for o in a.obligations}
    assert {"Art. 5(3)", "Art. 5(2)", "Art. 5(4)", "Art. 5(5)"} <= arts


def test_rbi_without_authorisation_is_banned_even_with_a_valid_objective():
    a = classify(_rbi(rbi_permitted_objective="serious_offence",
                      rbi_prior_authorisation=False))
    assert a.tier == "PROHIBITED"
    assert a.prohibited_practice.status == "definitive"


def test_conditional_prohibition_never_says_cease_immediately():
    """The costliest false positive: shutting down a lawful system."""
    a = classify(_ai(emotion_recognition=True, emotion_context="workplace_education"))
    assert a.prohibited_practice.status == "conditional"
    joined = " ".join(o.obligation for o in a.obligations)
    assert "Cease use immediately" not in joined
    assert "Suspend use" in joined


def test_exemption_stays_visible_when_other_facts_are_unknown():
    a = classify(_ai(emotion_recognition=True, emotion_context="workplace_education",
                     emotion_medical_or_safety_purpose=True,
                     high_risk_domains=["biometrics"]))
    assert "medical" in a.prohibited_practice.detail


def test_every_article_5_provision_cited_has_a_source():
    from citations import get_source
    for f in (_ai(subliminal_or_manipulative=True, causes_significant_harm=True),
              _ai(exploits_vulnerabilities=True, causes_significant_harm=True),
              _ai(social_scoring=True, social_scoring_detrimental_treatment=True),
              _ai(predictive_policing_profiling_only=True),
              _ai(untargeted_facial_scraping=True),
              _ai(biometric_categorisation_sensitive=True),
              _ai(emotion_recognition=True, emotion_context="workplace_education"),
              _rbi()):
        a = classify(f)
        for ref in a.prohibited_practice.articles:
            assert get_source(ref), f"{ref} has no verbatim source"


# --- Article 2: territorial scope ---------------------------------------------
def test_us_only_system_is_out_of_scope():
    """The Act does not reach a third-country system whose output is not used here."""
    a = classify(_ai(high_risk_domains=["employment"], established_outside_eu=True,
                     output_used_in_eu=False, uses_under_own_authority=True))
    assert a.tier == "OUT_OF_SCOPE"
    assert a.obligations == []
    assert a.territorial_scope.status == "definitive"


def test_third_country_system_is_in_scope_when_output_used_in_the_union():
    a = classify(_ai(high_risk_domains=["employment"], established_outside_eu=True,
                     output_used_in_eu=True))
    assert a.tier == "ANNEX_III"
    assert "Art. 2(1)(c)" in a.territorial_scope.articles


def test_placing_on_the_eu_market_brings_it_in_scope():
    a = classify(_ai(high_risk_domains=["credit"], placed_on_eu_market=True))
    assert a.territorial_scope.result == "Yes"
    assert "Art. 2(1)(a)" in a.territorial_scope.articles


def test_military_and_national_security_are_excluded():
    a = classify(_ai(high_risk_domains=["law_enforcement"], placed_on_eu_market=True,
                     military_defence_national_security=True))
    assert a.tier == "OUT_OF_SCOPE"
    assert "Art. 2(3)" in a.territorial_scope.articles


def test_scientific_research_is_excluded():
    a = classify(_ai(high_risk_domains=["employment"],
                     sole_purpose_scientific_research=True))
    assert a.tier == "OUT_OF_SCOPE"
    assert "Art. 2(6)" in a.territorial_scope.articles


def test_personal_non_professional_use_is_excluded():
    a = classify(_ai(personal_non_professional_use=True, interacts_with_people=True))
    assert a.tier == "OUT_OF_SCOPE"
    assert "Art. 2(10)" in a.territorial_scope.articles


def test_prerelease_testing_excluded_but_real_world_testing_is_not():
    lab = classify(_ai(high_risk_domains=["credit"], prerelease_research_testing=True,
                       real_world_testing=False))
    assert lab.tier == "OUT_OF_SCOPE"

    field = classify(_ai(high_risk_domains=["credit"], prerelease_research_testing=True,
                         real_world_testing=True, placed_on_eu_market=True))
    assert field.tier == "ANNEX_III"


def test_prerelease_testing_is_conditional_while_real_world_unknown():
    a = classify(_ai(high_risk_domains=["credit"], prerelease_research_testing=True))
    assert a.tier == "OUT_OF_SCOPE"
    assert a.territorial_scope.status == "conditional"
    assert a.human_review_required is True


def test_unknown_scope_does_not_silently_exclude():
    """Absent facts we assume the Regulation applies, and say so."""
    a = classify(_ai(high_risk_domains=["employment"]))
    assert a.tier == "ANNEX_III"
    assert a.territorial_scope.result == "Unclear"
    assert a.obligations
    assert any("Art. 2(1)" in m for m in a.missing_information)


def test_scope_conclusion_is_cited():
    for f in (_ai(placed_on_eu_market=True),
              _ai(military_defence_national_security=True),
              _ai(sole_purpose_scientific_research=True),
              _ai(established_outside_eu=True, output_used_in_eu=True)):
        a = classify(f)
        assert a.territorial_scope.articles
        assert a.territorial_scope.sources, "scope conclusion has no verbatim source"


# --- Annex III carve-outs (the domains are narrower than their labels) --------
def _dom(**kw):
    return Facts(is_ai_system=True, placed_on_eu_market=True, **kw)


def test_motor_insurance_is_not_high_risk():
    """Annex III(5)(c) covers life and health insurance only."""
    a = classify(_dom(high_risk_domains=["insurance"], insurance_life_or_health=False))
    assert a.high_risk.result == "No"
    assert a.tier != "ANNEX_III"


def test_life_insurance_is_high_risk():
    a = classify(_dom(high_risk_domains=["insurance"], insurance_life_or_health=True))
    assert a.tier == "ANNEX_III"


def test_insurance_line_unknown_is_conditional():
    a = classify(_dom(high_risk_domains=["insurance"]))
    assert a.tier == "ANNEX_III"
    assert a.high_risk.status == "conditional"


def test_biometric_verification_is_excluded():
    """A door badge reader confirming a claimed identity — Annex III(1)(a)."""
    a = classify(_dom(high_risk_domains=["biometrics"], biometric_verification_only=True))
    assert a.high_risk.result == "No"


def test_fraud_detection_is_excluded_from_credit():
    a = classify(_dom(high_risk_domains=["credit"], credit_fraud_detection_only=True))
    assert a.high_risk.result == "No"

    scoring = classify(_dom(high_risk_domains=["credit"],
                            credit_fraud_detection_only=False))
    assert scoring.tier == "ANNEX_III"


def test_carve_out_does_not_swallow_a_second_engaged_domain():
    a = classify(_dom(high_risk_domains=["insurance", "employment"],
                      insurance_life_or_health=False))
    assert a.tier == "ANNEX_III"
    assert "Annex III(4)" in a.high_risk.articles
    assert "Annex III(5)(c)" not in a.high_risk.articles


def test_carve_outs_still_allow_art_6_3_analysis():
    a = classify(_dom(high_risk_domains=["credit"], art_6_3_ground="preparatory_task"))
    assert a.high_risk.status == "conditional"


# --- Article 50 exceptions ----------------------------------------------------
def test_art_50_1_obviousness_exception():
    obvious = classify(_dom(interacts_with_people=True, ai_interaction_obvious=True))
    assert "exception applies" in obvious.transparency.detail

    not_obvious = classify(_dom(interacts_with_people=True, ai_interaction_obvious=False,
                                law_enforcement_authorised_detection=False))
    assert not_obvious.transparency.result == "Yes"
    assert "Art. 50(1)" in not_obvious.transparency.articles


def test_art_50_2_assistive_editing_exception():
    a = classify(_dom(generates_synthetic_content=True,
                      assistive_or_no_substantial_alteration=True))
    assert "assistive function" in a.transparency.detail


def test_art_50_law_enforcement_exception_runs_through():
    a = classify(_dom(interacts_with_people=True, generates_synthetic_content=False,
                      law_enforcement_authorised_detection=True))
    assert "criminal offences" in a.transparency.detail


def test_art_50_4_deepfake_disclosure():
    a = classify(_dom(deepfake_content=True, generates_synthetic_content=True,
                      assistive_or_no_substantial_alteration=False,
                      law_enforcement_authorised_detection=False))
    assert a.transparency.result == "Yes"
    assert "Art. 50(4)" in a.transparency.articles


def test_artistic_work_limits_rather_than_removes_the_duty():
    a = classify(_dom(deepfake_content=True, generates_synthetic_content=True,
                      assistive_or_no_substantial_alteration=False,
                      law_enforcement_authorised_detection=False,
                      artistic_creative_satirical_work=True))
    assert a.transparency.result == "Yes"          # still owed
    assert "does not hamper" in a.transparency.detail   # but limited


def test_editorial_review_exempts_published_ai_text():
    a = classify(_dom(text_published_public_interest=True,
                      generates_synthetic_content=False,
                      law_enforcement_authorised_detection=False,
                      human_editorial_review=True, deepfake_content=False,
                      interacts_with_people=False))
    assert "editorial responsibility" in a.transparency.detail


def test_deepfake_screening_does_not_hang_a_non_generative_system():
    """A spam filter must not sit unresolved on deep-fake questions."""
    a = classify(_dom(interacts_with_people=False, generates_synthetic_content=False,
                      safety_component_regulated_product=False,
                      manipulative_or_exploitative=False, social_scoring=False,
                      organisation_role="deployer"))
    assert a.transparency.result == "No"
    assert a.confidence == "high"


def test_every_article_50_provision_cited_has_a_source():
    from citations import get_source
    for f in (_dom(interacts_with_people=True, ai_interaction_obvious=False,
                   law_enforcement_authorised_detection=False),
              _dom(generates_synthetic_content=True,
                   assistive_or_no_substantial_alteration=False,
                   law_enforcement_authorised_detection=False),
              _dom(deepfake_content=True, generates_synthetic_content=True,
                   assistive_or_no_substantial_alteration=False,
                   law_enforcement_authorised_detection=False),
              _dom(emotion_recognition=True, law_enforcement_authorised_detection=False)):
        for ref in classify(f).transparency.articles:
            assert get_source(ref), f"{ref} has no verbatim source"


# --- application dates must be sourced ----------------------------------------
def test_every_dated_obligation_has_a_legal_basis():
    """The dates were the only uncited legal content in the tool."""
    from rules import DATE_ANNEX_I, DATE_ANNEX_III, DATE_TRANSPARENCY, date_basis
    for d in (DATE_ANNEX_III, DATE_ANNEX_I, DATE_TRANSPARENCY):
        basis, url = date_basis(d)
        assert basis and url.startswith("https://eur-lex.europa.eu")


def test_deferred_dates_cite_the_amending_regulation():
    from rules import DATE_ANNEX_I, DATE_ANNEX_III, date_basis
    for d in (DATE_ANNEX_III, DATE_ANNEX_I):
        basis, _ = date_basis(d)
        assert "2026/1744" in basis, "a deferred date must name the amending act"
        assert "deferred from" in basis


def test_ai_literacy_wording_matches_the_amended_article_4():
    """Art. 1(5) of the Omnibus replaced 'ensure' with 'take measures to support'."""
    a = classify(_hr(uses_under_own_authority=True))
    lit = [o for o in a.obligations if o.article == "Art. 4"]
    assert lit, "Art. 4 obligation missing"
    text = lit[0].obligation.lower()
    assert "take measures to support" in text
    assert "ensure" not in text
    assert "does not require guaranteeing" in lit[0].reasoning.lower()


def test_generative_systems_get_the_article_50_transitional_note():
    a = classify(Facts(is_ai_system=True, placed_on_eu_market=True,
                       generates_synthetic_content=True,
                       assistive_or_no_substantial_alteration=False,
                       law_enforcement_authorised_detection=False,
                       uses_under_own_authority=True))
    t = [o for o in a.obligations if o.article == "Art. 50"]
    assert t and "four-month transitional" in t[0].reasoning
