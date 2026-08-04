"""Deterministic EU AI Act rule engine.

Pure Python: given extracted Facts, decide every dimension of the assessment.
The LLM never decides here — it only supplies Facts (see facts.py). Each
conclusion carries its article reference, the triggering fact, and a status
(definitive / conditional / unresolved).
"""
from __future__ import annotations

from typing import NamedTuple

from citations import sources_for
from schema import Assessment, Conclusion, Facts, Obligation, SourceQuote

# --- application dates (post-Digital-Omnibus) --------------------------------
DATE_PROHIBITED = "2 February 2025 (in force)"
DATE_GPAI = "2 August 2025 (in force)"
DATE_TRANSPARENCY = "2 August 2026"
DATE_ANNEX_III = "2 December 2027"
DATE_ANNEX_I = "2 August 2028"
DATE_AI_LITERACY = "2 February 2025 (in force)"

# --- prohibited practices (Article 5) ----------------------------------------
# Almost none of the Article 5 bans is absolute: each has statutory elements
# that must be met and, in most cases, an express exception. Modelling only the
# trigger produces "cease use immediately" for systems that are in fact lawful —
# the most damaging error this tool can make. Each rule therefore carries:
#   requires    — further elements that must ALSO hold for the ban to bite
#   defeated_by — facts that, if true, take the system out of the prohibition
# An unresolved element or exception yields a *conditional* result, never a
# definitive one.


class Prohibition(NamedTuple):
    attr: str                       # the triggering fact
    ref: str                        # the provision
    label: str                      # short paraphrase for the report
    requires: tuple = ()            # (fact attr, description) — must be True
    defeated_by: tuple = ()         # (fact attr, description) — True ⇒ not prohibited


PROHIBITED_RULES = [
    Prohibition(
        "subliminal_or_manipulative", "Art. 5(1)(a)",
        "subliminal, manipulative or deceptive techniques distorting behaviour",
        requires=(("causes_significant_harm",
                   "the distortion causes or is likely to cause significant harm"),)),
    Prohibition(
        "exploits_vulnerabilities", "Art. 5(1)(b)",
        "exploitation of vulnerabilities of age, disability or social/economic situation",
        requires=(("causes_significant_harm",
                   "the distortion causes or is likely to cause significant harm"),)),
    Prohibition(
        "social_scoring", "Art. 5(1)(c)",
        "social scoring leading to detrimental treatment",
        requires=(("social_scoring_detrimental_treatment",
                   "the score leads to detrimental treatment that is out of context, "
                   "unjustified or disproportionate"),)),
    Prohibition(
        "predictive_policing_profiling_only", "Art. 5(1)(d)",
        "predicting criminal offences based solely on profiling",
        defeated_by=(("predictive_policing_supports_human_assessment",
                      "it supports a human assessment already based on objective, "
                      "verifiable facts directly linked to a criminal activity"),)),
    Prohibition(
        "untargeted_facial_scraping", "Art. 5(1)(e)",
        "untargeted scraping of facial images"),          # no statutory exception
    Prohibition(
        "biometric_categorisation_sensitive", "Art. 5(1)(g)",
        "biometric categorisation inferring sensitive attributes",
        defeated_by=(("biometric_lawful_dataset_filtering",
                      "it only labels or filters a lawfully acquired biometric "
                      "dataset, or categorises biometric data in law enforcement"),)),
]

# --- Annex III domain → (point, paraphrase) ----------------------------------
ANNEX_III_MAP = {
    "biometrics": ("Annex III(1)", "biometrics"),
    "critical_infrastructure": ("Annex III(2)", "critical infrastructure"),
    "education": ("Annex III(3)", "education and vocational training"),
    "employment": ("Annex III(4)", "employment, workers management"),
    "credit": ("Annex III(5)(b)", "creditworthiness / credit scoring"),
    "insurance": ("Annex III(5)(c)", "life/health insurance risk & pricing"),
    "essential_public_services": ("Annex III(5)(a)", "access to essential public services"),
    "law_enforcement": ("Annex III(6)", "law enforcement"),
    "migration": ("Annex III(7)", "migration, asylum and border control"),
    "justice": ("Annex III(8)", "administration of justice"),
}

# --- obligations, split by the role that actually owes them ------------------
# The Act assigns duties by role. Handing a deployer the provider's list tells
# them to do things they cannot lawfully do (a deployer cannot CE-mark a product
# they did not build) while omitting everything they do owe under Art. 26.

# Providers of high-risk AI systems — Art. 16 and the articles it points to.
PROVIDER_HIGH_RISK_OBLIGATIONS = [
    ("Risk management system (continuous, across lifecycle)", "Art. 9"),
    ("Data governance — representative, bias-examined training data", "Art. 10"),
    ("Technical documentation (Annex IV) before placing on market", "Art. 11"),
    ("Automatic record-keeping / logging (traceability)", "Art. 12"),
    ("Transparency and instructions for use to deployers", "Art. 13"),
    ("Human oversight designed into the system", "Art. 14"),
    ("Accuracy, robustness and cybersecurity", "Art. 15"),
    ("Quality management system", "Art. 17"),
    ("Conformity assessment", "Art. 43"),
    ("EU declaration of conformity (keep 10 years)", "Art. 47"),
    ("CE marking affixed before placing on the market", "Art. 48"),
    ("Registration in the EU database", "Art. 49"),
    ("Post-market monitoring system", "Art. 72"),
    ("Reporting of serious incidents to authorities", "Art. 73"),
    ("Corrective actions and duty to inform if non-conforming", "Art. 20"),
    ("Cooperation with competent authorities", "Art. 21"),
]

# Deployers of high-risk AI systems — Art. 26 (and Art. 27 for FRIA).
DEPLOYER_HIGH_RISK_OBLIGATIONS = [
    ("Use the system in accordance with the instructions for use", "Art. 26(1)"),
    ("Assign human oversight to competent, trained natural persons", "Art. 26(2)"),
    ("Ensure input data is relevant and sufficiently representative", "Art. 26(4)"),
    ("Monitor operation; suspend use and inform the provider on risk", "Art. 26(5)"),
    ("Keep automatically generated logs for at least 6 months", "Art. 26(6)"),
    ("Inform workers' representatives and affected workers before workplace use",
     "Art. 26(7)"),
    ("Inform natural persons subject to decisions made with the system", "Art. 26(11)"),
    ("Cooperate with competent authorities", "Art. 26(12)"),
]

IMPORTER_OBLIGATIONS = [
    ("Verify the provider carried out the conformity assessment", "Art. 23"),
    ("Verify CE marking, EU declaration of conformity and documentation", "Art. 23"),
    ("Indicate name and contact address on the system or its packaging", "Art. 23"),
    ("Keep a copy of the certificate and instructions for 10 years", "Art. 23"),
]

DISTRIBUTOR_OBLIGATIONS = [
    ("Verify CE marking, declaration of conformity and instructions before supplying",
     "Art. 24"),
    ("Do not make available a system you know to be non-conforming; take corrective "
     "action", "Art. 24"),
]

# Art. 4 binds providers AND deployers, at every risk tier, already in force.
UNIVERSAL_OBLIGATIONS = [
    ("AI literacy — ensure staff operating or using the system are sufficiently "
     "trained", "Art. 4"),
]
GPAI_OBLIGATIONS = [
    "Technical documentation of the model",
    "Information & documentation to downstream providers",
    "Copyright-compliance policy",
    "Public summary of training content",
]
GPAI_SYSTEMIC_OBLIGATIONS = [
    "Model evaluation & adversarial testing",
    "Systemic-risk assessment & mitigation",
    "Serious-incident reporting to the AI Office",
    "Cybersecurity protection",
]


def _known(v):
    return v is not None


def _with_sources(c: Conclusion) -> Conclusion:
    """Attach the verbatim EU AI Act text behind each cited provision.

    Any provision we cannot locate verbatim is listed in `unsourced` so the
    report can flag it as "confirmation needed" rather than pass it off as
    verified.
    """
    found = sources_for(c.articles)
    c.sources = [SourceQuote(**s) for s in found]
    got = {s["ref"] for s in found}
    c.unsourced = [a for a in c.articles if a not in got]
    return c


# Which prohibited-practice facts are worth asking about for a given system.
# Screening every system against all eight prohibitions produces a permanent
# "cannot rule out" — a chatbot does not need biometric scraping ruled out. Two
# prohibitions can catch any system and are always screened; the rest only
# matter when the system touches the relevant context.
_ALWAYS_RELEVANT = {"subliminal_or_manipulative", "exploits_vulnerabilities",
                    "social_scoring"}
_CONTEXT_GATED = {
    "predictive_policing_profiling_only": {"law_enforcement", "justice"},
    "untargeted_facial_scraping": {"biometrics", "law_enforcement"},
    "biometric_categorisation_sensitive": {"biometrics", "law_enforcement"},
    "realtime_remote_biometric_id_public_le": {"biometrics", "law_enforcement"},
}


RBI_OBJECTIVE_LABEL = {
    "victim_search": "targeted search for victims of abduction, trafficking or sexual "
                     "exploitation, or for missing persons (Art. 5(1)(h)(i))",
    "imminent_threat": "prevention of a specific, substantial and imminent threat to "
                       "life or physical safety, or of a terrorist attack "
                       "(Art. 5(1)(h)(ii))",
    "serious_offence": "locating or identifying a suspect of an Annex II offence "
                       "punishable by at least four years (Art. 5(1)(h)(iii))",
}


# Art. 50(4) duties only arise once the system produces synthetic output at all.
# Screening a spam filter for deep fakes leaves it permanently "unresolved".
_SYNTHETIC_GATED = {"deepfake_content", "text_published_public_interest"}


def _prohibition_is_relevant(attr: str, f: Facts) -> bool:
    if attr in _SYNTHETIC_GATED:
        return f.generates_synthetic_content is not False
    if attr in _ALWAYS_RELEVANT:
        return True
    gate = _CONTEXT_GATED.get(attr)
    if gate is None:
        return True
    if gate & set(f.high_risk_domains):
        return True
    # biometric facts are also in play once any biometric signal is present
    return bool(gate & {"biometrics"}) and (
        f.emotion_recognition is True or f.biometric_categorisation_sensitive is True)


# Art. 2 carve-outs: (fact attr, provision, why it falls outside the Regulation).
SCOPE_EXCLUSIONS = [
    ("military_defence_national_security", "Art. 2(3)",
     "used exclusively for military, defence or national security purposes"),
    ("sole_purpose_scientific_research", "Art. 2(6)",
     "developed and put into service for the sole purpose of scientific research "
     "and development"),
    ("personal_non_professional_use", "Art. 2(10)",
     "used by a natural person in the course of a purely personal, non-professional "
     "activity"),
]


def _evaluate_scope(f: Facts) -> Conclusion:
    """Article 2: does the Regulation apply to this system at all?

    Conservative by design. An established carve-out puts the system out of
    scope; otherwise, absent a clear EU nexus we do NOT quietly exclude it — we
    continue the assessment and flag the scope question as unresolved.
    """
    for attr, ref, why in SCOPE_EXCLUSIONS:
        if getattr(f, attr) is True:
            return Conclusion(
                result="No", detail=f"outside the scope of the Regulation — {why}",
                articles=[ref, "Art. 2"],
                trigger=f"{attr} = true", status="definitive")

    # Art. 2(8): pre-market research, testing and development — but testing in
    # real-world conditions is expressly NOT covered by that exclusion.
    if f.prerelease_research_testing is True and f.real_world_testing is not True:
        status = "conditional" if f.real_world_testing is None else "definitive"
        note = ("" if f.real_world_testing is False else
                " — unless it involves testing in real-world conditions, which is not "
                "covered by this exclusion")
        return Conclusion(
            result="No",
            detail="outside scope — research, testing or development activity prior to "
                   "the system being placed on the market or put into service" + note,
            articles=["Art. 2(8)"],
            trigger="prerelease_research_testing = true", status=status)

    hooks = []
    if f.placed_on_eu_market is True:
        hooks.append(("Art. 2(1)(a)", "placed on the market or put into service in the Union"))
    if f.uses_under_own_authority is True and f.established_outside_eu is not True:
        hooks.append(("Art. 2(1)(b)", "deployer established or located in the Union"))
    if f.established_outside_eu is True and f.output_used_in_eu is True:
        hooks.append(("Art. 2(1)(c)",
                      "third-country provider/deployer whose output is used in the Union"))
    if f.imports_from_third_country is True or f.makes_available_on_market is True:
        hooks.append(("Art. 2(1)(d)", "importer or distributor of an AI system"))

    if hooks:
        return Conclusion(
            result="Yes", detail="; ".join(d for _, d in hooks),
            articles=[a for a, _ in hooks] + ["Art. 2"],
            trigger="an Article 2(1) connecting factor is established",
            status="definitive")

    # No established nexus and no established carve-out: say so rather than
    # assuming either way. The assessment continues on the safe assumption that
    # the Regulation applies.
    if f.established_outside_eu is True and f.output_used_in_eu is False:
        return Conclusion(
            result="No",
            detail="no EU nexus — established in a third country and the output is not "
                   "used in the Union",
            articles=["Art. 2(1)"],
            trigger="established_outside_eu = true, output_used_in_eu = false",
            status="definitive")

    return Conclusion(
        result="Unclear",
        detail="no EU connecting factor established; the assessment below assumes the "
               "Regulation applies",
        articles=["Art. 2(1)"],
        trigger="territorial-scope facts unknown", status="unresolved")


def _derive_roles(f: Facts) -> tuple[list[str], Conclusion]:
    """Work out which role(s) the organisation holds for THIS system.

    Role is a legal conclusion drawn from what the organisation did (Art. 3(3)–(7)),
    not a label to ask for. One organisation can hold several roles at once —
    building a tool and using it in-house makes you provider and deployer both.
    Art. 25(1) escalates a deployer/distributor/importer to provider where they
    rebrand, substantially modify, or repurpose the system.
    """
    roles: list[str] = []
    arts: list[str] = []
    reasons: list[str] = []

    # Consultant override wins: they know the answer from the client conversation.
    if f.organisation_role != "unknown":
        return [f.organisation_role], Conclusion(
            result=f.organisation_role,
            detail=f"role set explicitly to '{f.organisation_role}'",
            articles=["Art. 3(3)", "Art. 3(4)"],
            trigger="organisation_role provided by the consultant",
            status="definitive")

    if f.developed_or_commissioned is True and f.supplied_under_own_name is not False:
        roles.append("provider")
        arts.append("Art. 3(3)")
        reasons.append("develops the system and supplies it under its own name")
    if f.uses_under_own_authority is True:
        roles.append("deployer")
        arts.append("Art. 3(4)")
        reasons.append("uses the system under its own authority")
    if f.imports_from_third_country is True:
        roles.append("importer")
        arts.append("Art. 3(6)")
        reasons.append("places a third-country system on the Union market")
    if (f.makes_available_on_market is True and "provider" not in roles
            and "importer" not in roles):
        roles.append("distributor")
        arts.append("Art. 3(7)")
        reasons.append("makes the system available on the Union market")

    # Art. 25(1): rebranding / substantial modification / repurposing makes you
    # the provider, and the original provider drops out (Art. 25(2)).
    if f.rebranded_or_modified is True:
        arts.append("Art. 25(1)")
        reasons.append("rebranded or substantially modified the system, which makes "
                       "it the provider under Art. 25(1)")
        if "provider" not in roles:
            roles.insert(0, "provider")

    if not roles:
        return ["unknown"], Conclusion(
            result="unknown",
            detail="the organisation's role in the value chain is not established",
            articles=["Art. 3(3)", "Art. 3(4)"],
            trigger="no role-determining facts available",
            status="unresolved")

    return roles, Conclusion(
        result=" + ".join(roles),
        detail="; ".join(reasons),
        articles=sorted(set(arts)),
        trigger="derived from the organisation's relationship to the system",
        status="definitive")


def _evaluate_one(p: Prohibition, f: Facts) -> tuple[str, str]:
    """Apply one Article 5 prohibition. Returns (state, note).

    state: "hit"        — every element met, no exception applies
           "conditional"— triggered, but an element or exception is unresolved
           "exempt"     — an express exception applies, or an element fails
           "clear"      — not triggered
           "unknown"    — the trigger itself is unknown
    """
    if getattr(f, p.attr) is False:
        return "clear", ""
    if getattr(f, p.attr) is None:
        return ("unknown", "") if _prohibition_is_relevant(p.attr, f) else ("clear", "")

    # Triggered. An established exception defeats the ban outright.
    for attr, desc in p.defeated_by:
        if getattr(f, attr) is True:
            return "exempt", f"the exception applies: {desc}"
    # A failed statutory element means the practice is simply not caught.
    for attr, desc in p.requires:
        if getattr(f, attr) is False:
            return "exempt", f"an element of the prohibition is not met: {desc}"
    # Anything still unresolved keeps the finding conditional, not definitive.
    pending = [desc for attr, desc in p.requires if getattr(f, attr) is None]
    pending += [f"unless {desc}" for attr, desc in p.defeated_by
                if getattr(f, attr) is None]
    if pending:
        return "conditional", "; ".join(pending)
    return "hit", ""


def _evaluate_emotion_recognition(f: Facts) -> tuple[str, str]:
    """Art. 5(1)(f): banned in workplace/education, except for medical or safety."""
    if f.emotion_recognition is None:
        relevant = {"employment", "education", "biometrics"} & set(f.high_risk_domains)
        return ("unknown", "") if relevant else ("clear", "")
    if f.emotion_recognition is False or f.emotion_context != "workplace_education":
        return "clear", ""
    if f.emotion_medical_or_safety_purpose is True:
        return "exempt", ("the exception applies: the system is intended for medical "
                          "or safety reasons")
    if f.emotion_medical_or_safety_purpose is None:
        return "conditional", ("unless it is intended to be put in place for medical "
                               "or safety reasons")
    return "hit", ""


def _evaluate_rbi(f: Facts) -> tuple[str, str]:
    """Art. 5(1)(h): real-time remote biometric ID is restricted, not absolutely banned.

    Use is permissible where strictly necessary for one of the (i)-(iii)
    objectives, and then only with the Art. 5(2)-(3) safeguards.
    """
    if f.realtime_remote_biometric_id_public_le is None:
        relevant = {"biometrics", "law_enforcement"} & set(f.high_risk_domains)
        return ("unknown", "") if relevant else ("clear", "")
    if f.realtime_remote_biometric_id_public_le is False:
        return "clear", ""
    if f.rbi_permitted_objective == "none":
        return "hit", ""
    label = RBI_OBJECTIVE_LABEL[f.rbi_permitted_objective]
    if f.rbi_prior_authorisation is True:
        return "exempt", (f"permitted under Art. 5(1)(h): {label}, with the prior "
                          "authorisation required by Art. 5(3)")
    if f.rbi_prior_authorisation is False:
        return "hit", (f"a permitted objective is claimed ({label}) but the prior "
                       "authorisation required by Art. 5(3) is absent")
    return "conditional", (f"a permitted objective is claimed ({label}); lawful only if "
                           "strictly necessary AND authorised in advance by a judicial "
                           "or independent authority (Art. 5(3))")


def _evaluate_prohibited(f: Facts) -> Conclusion:
    hits, conditional, unknowns, exempt = [], [], [], []

    evaluations = [(p.ref, p.label, *_evaluate_one(p, f)) for p in PROHIBITED_RULES]
    evaluations.append(("Art. 5(1)(f)", "emotion recognition in workplace/education",
                        *_evaluate_emotion_recognition(f)))
    evaluations.append(("Art. 5(1)(h)", "real-time remote biometric identification in "
                        "publicly accessible spaces for law enforcement",
                        *_evaluate_rbi(f)))

    for ref, label, state, note in evaluations:
        entry = (ref, f"{label} — {note}" if note else label)
        if state == "hit":
            hits.append(entry)
        elif state == "conditional":
            conditional.append(entry)
        elif state == "exempt":
            exempt.append(entry)
        elif state == "unknown":
            unknowns.append(ref)

    if hits:
        return Conclusion(
            result="Yes",
            detail="; ".join(d for _, d in hits),
            articles=[a for a, _ in hits],
            trigger="every element of a prohibition is met and no exception applies",
            status="definitive")
    if conditional:
        return Conclusion(
            result="Yes",
            detail="; ".join(d for _, d in conditional),
            articles=[a for a, _ in conditional],
            trigger="a prohibition is triggered but an element or exception is unresolved",
            status="conditional")
    if unknowns:
        # An established exception is a real finding — keep it visible instead of
        # letting unrelated unknowns bury it.
        detail = "cannot rule out without more facts"
        if exempt:
            detail = ("; ".join(d for _, d in exempt)
                      + " — but other prohibitions cannot be ruled out without "
                        "more facts")
        return Conclusion(
            result="Possible", detail=detail,
            articles=sorted(set(unknowns) | {a for a, _ in exempt}),
            trigger="context-relevant prohibited-practice facts unknown",
            status="unresolved")
    if exempt:
        return Conclusion(
            result="No",
            detail="; ".join(d for _, d in exempt),
            articles=[a for a, _ in exempt],
            trigger="a statutory exception applies or an element is not met",
            status="definitive")
    return Conclusion(result="No", detail="no prohibited practice detected",
                      articles=["Art. 5"],
                      trigger="all context-relevant prohibited facts are false",
                      status="definitive")


def _domain_status(domain: str, f: Facts) -> tuple[str, str]:
    """Is this Annex III domain actually engaged? Returns (state, note).

    The domain labels are broader than the Annex: "insurance" covers only life
    and health, "biometrics" excludes plain verification, "credit" excludes fraud
    detection. Without these carve-outs the tool marks motor-insurance pricing
    and office door-badge readers as high-risk.
    """
    if domain == "biometrics":
        if f.biometric_verification_only is True:
            return "out", ("biometric verification whose sole purpose is confirming a "
                           "claimed identity is excluded — Annex III(1)(a)")
        if f.biometric_verification_only is None:
            return "unclear", ("unless it is biometric verification only, which Annex "
                               "III(1)(a) excludes")
    elif domain == "credit":
        if f.credit_fraud_detection_only is True:
            return "out", ("AI used to detect financial fraud is excluded — "
                           "Annex III(5)(b)")
        if f.credit_fraud_detection_only is None:
            return "unclear", ("unless it is used solely to detect financial fraud, "
                               "which Annex III(5)(b) excludes")
    elif domain == "insurance":
        if f.insurance_life_or_health is False:
            return "out", ("only life and health insurance are covered — "
                           "Annex III(5)(c)")
        if f.insurance_life_or_health is None:
            return "unclear", ("only if it concerns life or health insurance; "
                               "Annex III(5)(c) covers no other line")
    return "in", ""


ART_6_3_LABEL = {
    "narrow_procedural_task": "performs a narrow procedural task (Art. 6(3)(a))",
    "improves_human_output": "improves the result of a previously completed human "
                             "activity (Art. 6(3)(b))",
    "detects_patterns": "detects decision-making patterns without replacing human "
                        "assessment (Art. 6(3)(c))",
    "preparatory_task": "performs a preparatory task to an assessment (Art. 6(3)(d))",
}


def _evaluate_high_risk(f: Facts) -> Conclusion:
    if f.safety_component_regulated_product is True:
        return Conclusion(result="ANNEX_I",
                          detail="safety component of a regulated product",
                          articles=["Art. 6(1)", "Annex I"],
                          trigger="safety_component_regulated_product = true",
                          status="definitive")
    if f.high_risk_domains:
        # Apply the Annex III carve-outs before anything else: a domain that is
        # carved out never engaged the high-risk regime in the first place.
        engaged, unclear, excluded = [], [], []
        for d in f.high_risk_domains:
            if d not in ANNEX_III_MAP:
                continue
            state, note = _domain_status(d, f)
            (engaged if state == "in" else unclear if state == "unclear"
             else excluded).append((d, note))

        if not engaged and not unclear and excluded:
            return Conclusion(
                result="No",
                detail="; ".join(f"{ANNEX_III_MAP[d][1]}: {note}" for d, note in excluded),
                articles=["Art. 6(2)"] + [ANNEX_III_MAP[d][0] for d, _ in excluded],
                trigger="every candidate Annex III domain is carved out",
                status="definitive")

        # An unresolved carve-out keeps the domain in play but makes the finding
        # conditional — it must not short-circuit the Art. 6(3) analysis below.
        domain_caveat = "; ".join(note for _, note in unclear)
        active = [d for d, _ in engaged] + [d for d, _ in unclear]
        pts = [ANNEX_III_MAP[d] for d in active]
        arts = ["Art. 6(2)"] + [a for a, _ in pts]
        domains = ", ".join(active)
        ground = f.art_6_3_ground

        # Art. 6(3): the derogation is unavailable where the system profiles
        # natural persons — that check comes first and is absolute.
        if ground != "none" and f.profiling is True:
            return Conclusion(
                result="ANNEX_III",
                detail="; ".join(p for _, p in pts) +
                       " — Art. 6(3) derogation unavailable: the system performs profiling",
                articles=arts + ["Art. 6(3)"],
                trigger=f"high-risk domain(s): {domains}; profiling = true",
                status="definitive")
        if ground != "none":
            status = "conditional" if f.profiling is None else "definitive"
            note = (" (profiling not established — the derogation fails if the system "
                    "profiles natural persons)" if f.profiling is None else "")
            return Conclusion(
                result="ANNEX_III_EXEMPT",
                detail=f"in {', '.join(p for _, p in pts)}, but {ART_6_3_LABEL[ground]}"
                       f" and so does not pose a significant risk of harm{note}",
                articles=arts + ["Art. 6(3)", "Art. 6(4)"],
                trigger=f"high-risk domain(s): {domains}; art_6_3_ground = {ground}",
                status=status)

        return Conclusion(
            result="ANNEX_III",
            detail="; ".join(p for _, p in pts)
                   + (f" — {domain_caveat}" if domain_caveat else ""),
            articles=arts,
            trigger=f"high-risk domain(s): {domains}",
            status="conditional" if domain_caveat else "definitive")
    if f.safety_component_regulated_product is None:
        return Conclusion(result="Unclear", detail="high-risk domain not established",
                          articles=["Art. 6", "Annex III"],
                          trigger="no high-risk domain identified yet",
                          status="unresolved")
    return Conclusion(result="No", detail="not a high-risk use case",
                      articles=["Art. 6"], trigger="no Annex I/III trigger",
                      status="definitive")


# Article 50 duties, each with the exceptions the paragraph actually contains.
# The law-enforcement carve-out ("authorised by law to detect, prevent,
# investigate or prosecute criminal offences") runs through 50(1)-(4).
_LE_EXCEPTION = ("law_enforcement_authorised_detection",
                 "the system is authorised by law to detect, prevent, investigate or "
                 "prosecute criminal offences")

TRANSPARENCY_RULES = [
    Prohibition(
        "interacts_with_people", "Art. 50(1)",
        "inform people they are interacting with an AI system",
        defeated_by=(("ai_interaction_obvious",
                      "it is obvious to a reasonably well-informed, observant and "
                      "circumspect person"), _LE_EXCEPTION)),
    Prohibition(
        "generates_synthetic_content", "Art. 50(2)",
        "mark synthetic output in a machine-readable format",
        defeated_by=(("assistive_or_no_substantial_alteration",
                      "the system only performs an assistive function for standard "
                      "editing, or does not substantially alter the input data"),
                     _LE_EXCEPTION)),
    Prohibition(
        "deepfake_content", "Art. 50(4)",
        "disclose that deep-fake content is artificially generated or manipulated",
        defeated_by=(_LE_EXCEPTION,)),
    Prohibition(
        "text_published_public_interest", "Art. 50(4)",
        "disclose AI-generated text published to inform the public on matters of "
        "public interest",
        defeated_by=(("human_editorial_review",
                      "the content underwent human review and a person holds editorial "
                      "responsibility for the publication"), _LE_EXCEPTION)),
]


def _evaluate_transparency(f: Facts) -> Conclusion:
    hits, conditional, unknowns, exempt = [], [], [], []

    evaluations = [(r.ref, r.label, *_evaluate_one(r, f)) for r in TRANSPARENCY_RULES]

    # Art. 50(3): deployers of emotion-recognition or biometric-categorisation
    # systems must inform those exposed — same law-enforcement carve-out.
    if f.emotion_recognition is True or f.biometric_categorisation_sensitive is True:
        label = "inform persons exposed to emotion recognition / biometric categorisation"
        if f.law_enforcement_authorised_detection is True:
            evaluations.append(("Art. 50(3)", label, "exempt",
                                f"the exception applies: {_LE_EXCEPTION[1]}"))
        elif f.law_enforcement_authorised_detection is None:
            evaluations.append(("Art. 50(3)", label, "conditional",
                                f"unless {_LE_EXCEPTION[1]}"))
        else:
            evaluations.append(("Art. 50(3)", label, "hit", ""))

    for ref, label, state, note in evaluations:
        entry = (ref, f"{label} — {note}" if note else label)
        if state == "hit":
            hits.append(entry)
        elif state == "conditional":
            conditional.append(entry)
        elif state == "exempt":
            exempt.append(entry)
        elif state == "unknown":
            unknowns.append(ref)

    # Art. 50(4): an evidently artistic, creative, satirical or fictional work
    # does not remove the duty — it limits it to a disclosure that does not
    # hamper enjoyment of the work.
    if f.artistic_creative_satirical_work is True and (hits or conditional):
        note = (" (artistic/creative/satirical work: disclosure limited to an "
                "appropriate manner that does not hamper display or enjoyment)")
        target = hits or conditional
        target[-1] = (target[-1][0], target[-1][1] + note)

    if hits:
        return Conclusion(result="Yes", detail="; ".join(d for _, d in hits),
                          articles=[a for a, _ in hits],
                          trigger="a transparency duty applies and no exception does",
                          status="definitive")
    if conditional:
        return Conclusion(result="Yes", detail="; ".join(d for _, d in conditional),
                          articles=[a for a, _ in conditional],
                          trigger="a transparency duty is triggered but an exception "
                                  "is unresolved",
                          status="conditional")
    if unknowns:
        # Keep an established exception visible rather than letting unrelated
        # unknowns bury it.
        detail = "depends on interaction/output"
        if exempt:
            detail = ("; ".join(d for _, d in exempt)
                      + " — other transparency triggers remain unresolved")
        return Conclusion(result="Possible", detail=detail,
                          articles=sorted(set(unknowns) | {a for a, _ in exempt}),
                          trigger="transparency facts unknown", status="unresolved")
    if exempt:
        return Conclusion(result="No", detail="; ".join(d for _, d in exempt),
                          articles=[a for a, _ in exempt],
                          trigger="an Article 50 exception applies", status="definitive")
    return Conclusion(result="No", detail="no transparency obligation",
                      articles=["Art. 50"], trigger="no transparency trigger",
                      status="definitive")


def _evaluate_gpai(f: Facts) -> Conclusion:
    if f.gpai_relationship in ("builds_or_finetunes", "integrates_distributes"):
        arts = ["Art. 53"]
        detail = "provider of / building on a general-purpose AI model"
        if f.gpai_systemic_risk is True:
            arts.append("Art. 55")
            detail += " with systemic risk"
        return Conclusion(result="Yes", detail=detail, articles=arts,
                          trigger=f"gpai_relationship = {f.gpai_relationship}",
                          status="definitive")
    if f.gpai_relationship == "uses_api":
        return Conclusion(result="No",
                          detail="only calls a foundation model via API (no weight changes)",
                          articles=["Art. 53"], trigger="gpai_relationship = uses_api",
                          status="definitive")
    return Conclusion(result="No", detail="no general-purpose model relationship",
                      articles=["Art. 53"], trigger="gpai_relationship = none",
                      status="definitive")


def _obligations_for(tier: str, is_gpai: bool, systemic: bool,
                     transparency: Conclusion,
                     high_risk: Conclusion | None = None,
                     roles: list[str] | None = None,
                     f: Facts | None = None,
                     prohibited: Conclusion | None = None) -> list[Obligation]:
    roles = roles or ["unknown"]
    f = f or Facts()
    out: list[Obligation] = []
    if tier == "PROHIBITED":
        conditional = prohibited is not None and prohibited.status == "conditional"
        if conditional:
            out.append(Obligation(
                obligation="Suspend use and confirm with counsel whether the statutory "
                           "exception applies",
                deadline=DATE_PROHIBITED, status="needs_confirmation",
                role="all", article=", ".join(prohibited.articles) or "Art. 5",
                reasoning=prohibited.detail,
                gap_question="Can you evidence that the exception applies to this use?"))
        else:
            out.append(Obligation(
                obligation="Cease use immediately (prohibited practice)",
                deadline=DATE_PROHIBITED, status="likely_gap",
                role="all", article=", ".join(prohibited.articles) if prohibited
                                    else "Art. 5",
                reasoning=(prohibited.detail if prohibited
                           else "System matches an Article 5 prohibition.")))
        return out
    # Art. 5(2)-(4): where real-time remote biometric ID is used under one of the
    # Art. 5(1)(h) objectives, it is lawful only with these safeguards.
    if f.realtime_remote_biometric_id_public_le is True and \
            f.rbi_permitted_objective != "none":
        out += [
            Obligation(
                obligation="Obtain prior authorisation from a judicial or independent "
                           "administrative authority for each use",
                deadline=DATE_PROHIBITED, role="deployer", article="Art. 5(3)",
                status="likely_gap" if f.rbi_prior_authorisation is False
                       else "needs_confirmation",
                reasoning="Use may begin without authorisation only in duly justified "
                          "urgency, and it must then be requested within 24 hours.",
                gap_question="Is each deployment authorised in advance by a judicial or "
                             "independent authority?"),
            Obligation(
                obligation="Complete a Fundamental Rights Impact Assessment before use",
                deadline=DATE_PROHIBITED, role="deployer", article="Art. 5(2)",
                reasoning="Art. 5(2) requires a completed FRIA under Art. 27 before the "
                          "system may be authorised."),
            Obligation(
                obligation="Register the system in the EU database before use",
                deadline=DATE_PROHIBITED, role="deployer", article="Art. 49",
                reasoning="Required by Art. 5(2); in urgent cases registration must "
                          "follow without undue delay."),
            Obligation(
                obligation="Notify each use to the market surveillance authority and the "
                           "national data protection authority",
                deadline=DATE_PROHIBITED, role="deployer", article="Art. 5(4)"),
            Obligation(
                obligation="Confirm national law authorises this use, with temporal, "
                           "geographic and personal limits",
                deadline=DATE_PROHIBITED, role="deployer", article="Art. 5(5)",
                reasoning="Art. 5(1)(h) applies only in so far as national law provides "
                          "for the authorisation."),
        ]

    if high_risk is not None and high_risk.result == "ANNEX_III_EXEMPT":
        # Art. 6(4): claiming the derogation is not free — the assessment must be
        # documented before placing on the market, and the system still registered.
        out += [
            Obligation(
                obligation="Document the Art. 6(3) derogation assessment before "
                           "placing on the market",
                deadline=DATE_ANNEX_III, status="likely_gap",
                role="provider", article="Art. 6(4)",
                reasoning="Art. 6(4) requires the provider to document why the system "
                          "falls outside the high-risk regime.",
                gap_question="Has the Art. 6(3) assessment been written down and kept "
                             "available for national authorities?"),
            Obligation(
                obligation="Register the system in the EU database as Annex III-exempt",
                deadline=DATE_ANNEX_III, status="needs_confirmation",
                role="provider", article="Art. 49(2)",
                reasoning="Art. 49(2) requires registration even where Art. 6(3) applies.",
                gap_question="Is the system registered under Art. 49(2)?"),
        ]
    if tier in ("ANNEX_I", "ANNEX_III"):
        dl = DATE_ANNEX_I if tier == "ANNEX_I" else DATE_ANNEX_III
        unknown_role = roles == ["unknown"]

        if "provider" in roles or unknown_role:
            for text, art in PROVIDER_HIGH_RISK_OBLIGATIONS:
                # Art. 17(4): financial institutions under Union financial services
                # law are deemed to meet the QMS duty, except points (g), (h), (i).
                if art == "Art. 17" and f.sectoral_regime == "financial_services":
                    out.append(Obligation(
                        obligation="Quality management system — largely satisfied by "
                                   "your internal governance under Union financial "
                                   "services law",
                        deadline=dl, role="provider", article="Art. 17(4)",
                        reasoning="Art. 17(4) deems the QMS duty fulfilled for financial "
                                  "institutions, EXCEPT points (g) risk management, "
                                  "(h) post-market monitoring and (i) incident reporting, "
                                  "which are still owed in full.",
                        gap_question="Do your existing internal governance arrangements "
                                     "cover Art. 17(1)(a)–(f) and (j)–(m)?"))
                    continue
                if art == "Art. 17" and f.sectoral_regime in ("medical_devices",
                                                              "other_sectoral"):
                    out.append(Obligation(
                        obligation="Quality management system — may be merged into your "
                                   "existing sectoral quality system",
                        deadline=dl, role="provider", article="Art. 17(3)",
                        reasoning="Art. 17(3) allows the Art. 17(1) aspects to be included "
                                  "in a quality management system kept under sectoral "
                                  "Union law rather than duplicated.",
                        gap_question="Which Art. 17(1) aspects are already covered by your "
                                     "sectoral quality system?"))
                    continue
                out.append(Obligation(obligation=text, deadline=dl,
                                      role="provider", article=art))
            if f.established_outside_eu is True:
                out.append(Obligation(
                    obligation="Appoint an authorised representative established in the "
                               "Union", deadline=dl, role="provider", article="Art. 22",
                    reasoning="Providers established outside the Union must appoint an "
                              "authorised representative before placing the system on "
                              "the market."))

        if "deployer" in roles or unknown_role:
            out += [Obligation(obligation=t, deadline=dl, role="deployer", article=a)
                    for t, a in DEPLOYER_HIGH_RISK_OBLIGATIONS]
            # Art. 27: FRIA is owed only by public bodies, private providers of
            # public services, and deployers of credit / life-health-insurance
            # systems — not by every deployer.
            fria_domains = {"credit", "insurance", "essential_public_services"}
            if f.public_body_or_public_service is True or (
                    fria_domains & set(f.high_risk_domains)):
                out.append(Obligation(
                    obligation="Fundamental Rights Impact Assessment (FRIA)",
                    deadline=dl, role="deployer", article="Art. 27",
                    reasoning="Art. 27 applies to public bodies, private entities "
                              "providing public services, and deployers of Annex III(5)(b) "
                              "creditworthiness or (5)(c) life/health insurance systems."))
            elif f.public_body_or_public_service is None:
                out.append(Obligation(
                    obligation="Fundamental Rights Impact Assessment (FRIA) — only if you "
                               "are a public body or provide a public service",
                    deadline=dl, role="deployer", article="Art. 27",
                    reasoning="Art. 27 does not apply to every deployer; confirm status.",
                    gap_question="Are you a body governed by public law, or a private "
                                 "entity providing a public service?"))

        if "importer" in roles:
            out += [Obligation(obligation=t, deadline=dl, role="importer", article=a)
                    for t, a in IMPORTER_OBLIGATIONS]
        if "distributor" in roles:
            out += [Obligation(obligation=t, deadline=dl, role="distributor", article=a)
                    for t, a in DISTRIBUTOR_OBLIGATIONS]

    if transparency.result == "Yes":
        out.append(Obligation(obligation="Transparency: disclosure / labelling",
                              deadline=DATE_TRANSPARENCY, role="all",
                              article="Art. 50", reasoning=transparency.detail))
    if is_gpai:
        out += [Obligation(obligation=o, deadline=DATE_GPAI, role="provider",
                           article="Art. 53") for o in GPAI_OBLIGATIONS]
        if systemic:
            out += [Obligation(obligation=o, deadline=DATE_GPAI, role="provider",
                               article="Art. 55") for o in GPAI_SYSTEMIC_OBLIGATIONS]

    # Art. 4 AI literacy binds providers and deployers at every tier, and has
    # applied since 2 February 2025.
    if tier not in ("NOT_AI",) and (
            {"provider", "deployer"} & set(roles) or roles == ["unknown"]):
        out += [Obligation(obligation=t, deadline=DATE_AI_LITERACY, role="all",
                           article=a) for t, a in UNIVERSAL_OBLIGATIONS]
    return out


def classify(f: Facts, system_name: str = "") -> Assessment:
    is_ai = _with_sources(Conclusion(
        result={True: "Yes", False: "No", None: "Unclear"}[f.is_ai_system],
        detail="within the EU AI Act definition of an AI system (Art. 3(1))",
        articles=["Art. 3(1)"],
        trigger=f"is_ai_system = {f.is_ai_system}",
        status="definitive" if _known(f.is_ai_system) else "unresolved"))

    scope = _with_sources(_evaluate_scope(f))
    roles, role_basis = _derive_roles(f)
    role_basis = _with_sources(role_basis)

    prohibited = _with_sources(_evaluate_prohibited(f))
    high_risk = _with_sources(_evaluate_high_risk(f))
    transparency = _with_sources(_evaluate_transparency(f))
    gpai = _with_sources(_evaluate_gpai(f))

    # headline tier
    if scope.result == "No":
        # Article 2 settles it: no obligations arise under this Regulation.
        tier = "OUT_OF_SCOPE"
    elif f.is_ai_system is False:
        tier = "NOT_AI"
    elif f.is_ai_system is None:
        # Nothing is known about the most basic question — say so rather than
        # falling through to a reassuring MINIMAL badge.
        tier = "UNDETERMINED"
    elif prohibited.result == "Yes":
        tier = "PROHIBITED"
    elif high_risk.result in ("ANNEX_I", "ANNEX_III"):
        tier = high_risk.result
    elif transparency.result == "Yes":
        tier = "LIMITED"
    else:
        # Includes ANNEX_III_EXEMPT: Art. 6(3) takes it out of the high-risk
        # regime, so the headline follows the remaining dimensions.
        tier = "MINIMAL"

    date = {
        "PROHIBITED": DATE_PROHIBITED, "ANNEX_I": DATE_ANNEX_I,
        "ANNEX_III": DATE_ANNEX_III, "LIMITED": DATE_TRANSPARENCY,
        "MINIMAL": "—", "NOT_AI": "—", "UNDETERMINED": "—", "OUT_OF_SCOPE": "—",
    }[tier]

    is_gpai = gpai.result == "Yes"
    systemic = f.gpai_systemic_risk is True

    # missing information = decisive facts still unknown
    missing = []
    if scope.status == "unresolved":
        missing.append("Whether the system is placed on the EU market, or its output "
                       "used in the Union — Art. 2(1)")
    for c in (is_ai, prohibited, high_risk, transparency):
        if c.status == "unresolved":
            missing.append(f"{c.detail} — {', '.join(c.articles)}")
    if roles == ["unknown"]:
        missing.append("Organisation role (provider / deployer / importer / distributor) "
                       "— obligations for BOTH provider and deployer are listed until "
                       "this is settled — Art. 3(3), Art. 3(4)")
    if high_risk.result == "ANNEX_III_EXEMPT" and f.profiling is None:
        missing.append("Whether the system profiles natural persons — decisive for "
                       "the Art. 6(3) derogation")

    confidence = "high"
    if missing:
        confidence = "low" if (not _known(f.is_ai_system) or len(missing) >= 3) else "medium"

    human_review = (
        tier in ("PROHIBITED", "ANNEX_I", "ANNEX_III", "UNDETERMINED")
        or prohibited.result in ("Yes", "Possible")
        or high_risk.result == "ANNEX_III_EXEMPT"   # a claimed derogation must be checked
        or confidence == "low"
    )

    if tier == "OUT_OF_SCOPE":
        # Nothing is owed under this Regulation, so no obligations and no review.
        return Assessment(
            system_name=system_name, tier=tier, is_gpai=is_gpai,
            territorial_scope=scope, is_ai_system=is_ai,
            prohibited_practice=prohibited, high_risk=high_risk,
            transparency=transparency, gpai=gpai,
            organisation_role=roles[0], roles=roles, role_basis=role_basis,
            application_date="—",
            confidence="high" if scope.status == "definitive" else "medium",
            missing_information=[],
            human_review_required=scope.status != "definitive",
            obligations=[])

    return Assessment(
        system_name=system_name,
        tier=tier,
        territorial_scope=scope,
        is_gpai=is_gpai,
        is_ai_system=is_ai,
        prohibited_practice=prohibited,
        high_risk=high_risk,
        transparency=transparency,
        gpai=gpai,
        organisation_role=roles[0],
        roles=roles,
        role_basis=role_basis,
        application_date=date,
        confidence=confidence,
        missing_information=missing,
        human_review_required=human_review,
        obligations=_obligations_for(tier, is_gpai, systemic, transparency,
                                     high_risk, roles, f, prohibited),
    )
