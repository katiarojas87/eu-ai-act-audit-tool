"""Deterministic EU AI Act rule engine.

Pure Python: given extracted Facts, decide every dimension of the assessment.
The LLM never decides here — it only supplies Facts (see facts.py). Each
conclusion carries its article reference, the triggering fact, and a status
(definitive / conditional / unresolved).
"""
from __future__ import annotations

from citations import sources_for
from schema import Assessment, Conclusion, Facts, Obligation, SourceQuote

# --- application dates (post-Digital-Omnibus) --------------------------------
DATE_PROHIBITED = "2 February 2025 (in force)"
DATE_GPAI = "2 August 2025 (in force)"
DATE_TRANSPARENCY = "2 August 2026"
DATE_ANNEX_III = "2 December 2027"
DATE_ANNEX_I = "2 August 2028"

# --- prohibited practices (Article 5) → (fact attr, article, paraphrase) -----
PROHIBITED_RULES = [
    ("manipulative_or_exploitative", "Art. 5(1)(a)-(b)",
     "manipulative/deceptive techniques or exploitation of vulnerabilities"),
    ("social_scoring", "Art. 5(1)(c)", "social scoring leading to detrimental treatment"),
    ("predictive_policing_profiling_only", "Art. 5(1)(d)",
     "predicting criminal offences based solely on profiling"),
    ("untargeted_facial_scraping", "Art. 5(1)(e)",
     "untargeted scraping of facial images"),
    ("biometric_categorisation_sensitive", "Art. 5(1)(g)",
     "biometric categorisation inferring sensitive attributes"),
    ("realtime_remote_biometric_id_public_le", "Art. 5(1)(h)",
     "real-time remote biometric identification in public spaces for law enforcement"),
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

HIGH_RISK_OBLIGATIONS = [
    "Risk management system (continuous, across lifecycle)",
    "Data governance — representative, bias-examined training data",
    "Technical documentation (Annex IV) before placing on market",
    "Automatic record-keeping / logging (traceability)",
    "Transparency and instructions for use to deployers",
    "Human oversight (ability to intervene / override)",
    "Accuracy, robustness and cybersecurity",
    "Quality management system (providers)",
    "Conformity assessment + EU declaration of conformity + CE marking",
    "Registration in the EU database (Annex III systems)",
    "Post-market monitoring system",
    "Reporting of serious incidents to authorities",
    "Fundamental Rights Impact Assessment (FRIA)",
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


def _evaluate_prohibited(f: Facts) -> Conclusion:
    hits, unknowns = [], []
    for attr, art, para in PROHIBITED_RULES:
        v = getattr(f, attr)
        if v is True:
            hits.append((art, para))
        elif v is None:
            unknowns.append(art)
    # emotion recognition in workplace/education is a separate, context-gated ban
    if f.emotion_recognition is True and f.emotion_context == "workplace_education":
        hits.append(("Art. 5(1)(f)", "emotion recognition in workplace/education"))
    elif f.emotion_recognition is None:
        unknowns.append("Art. 5(1)(f)")

    if hits:
        return Conclusion(
            result="Yes",
            detail="; ".join(p for _, p in hits),
            articles=[a for a, _ in hits],
            trigger="one or more prohibited-practice facts are true",
            status="definitive",
        )
    if unknowns:
        return Conclusion(
            result="Possible", detail="cannot rule out without more facts",
            articles=sorted(set(unknowns)),
            trigger="key prohibited-practice facts unknown", status="unresolved")
    return Conclusion(result="No", detail="no prohibited practice detected",
                      articles=["Art. 5"], trigger="all prohibited facts false",
                      status="definitive")


def _evaluate_high_risk(f: Facts) -> Conclusion:
    if f.safety_component_regulated_product is True:
        return Conclusion(result="ANNEX_I",
                          detail="safety component of a regulated product",
                          articles=["Art. 6(1)", "Annex I"],
                          trigger="safety_component_regulated_product = true",
                          status="definitive")
    if f.high_risk_domains:
        pts = [ANNEX_III_MAP[d] for d in f.high_risk_domains if d in ANNEX_III_MAP]
        return Conclusion(result="ANNEX_III",
                          detail="; ".join(p for _, p in pts),
                          articles=["Art. 6(2)"] + [a for a, _ in pts],
                          trigger=f"high-risk domain(s): {', '.join(f.high_risk_domains)}",
                          status="definitive")
    if f.safety_component_regulated_product is None and not f.high_risk_domains:
        return Conclusion(result="Unclear", detail="high-risk domain not established",
                          articles=["Art. 6", "Annex III"],
                          trigger="no high-risk domain identified yet",
                          status="unresolved")
    return Conclusion(result="No", detail="not a high-risk use case",
                      articles=["Art. 6"], trigger="no Annex I/III trigger",
                      status="definitive")


def _evaluate_transparency(f: Facts) -> Conclusion:
    hits, unknowns = [], []
    if f.interacts_with_people is True:
        hits.append(("Art. 50(1)", "chatbot must disclose it is AI"))
    elif f.interacts_with_people is None:
        unknowns.append("Art. 50(1)")
    if f.generates_synthetic_content is True:
        hits.append(("Art. 50(2)/(4)", "AI-generated/deepfake content must be labelled"))
    elif f.generates_synthetic_content is None:
        unknowns.append("Art. 50(2)")
    if f.emotion_recognition is True or f.biometric_categorisation_sensitive is True:
        hits.append(("Art. 50(3)", "inform persons exposed to emotion/biometric systems"))

    if hits:
        return Conclusion(result="Yes", detail="; ".join(p for _, p in hits),
                          articles=[a for a, _ in hits],
                          trigger="a transparency trigger is true", status="definitive")
    if unknowns:
        return Conclusion(result="Possible", detail="depends on interaction/output",
                          articles=sorted(set(unknowns)),
                          trigger="transparency facts unknown", status="unresolved")
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
                     transparency: Conclusion) -> list[Obligation]:
    out: list[Obligation] = []
    if tier == "PROHIBITED":
        out.append(Obligation(obligation="Cease use immediately (prohibited practice)",
                              deadline=DATE_PROHIBITED, status="likely_gap",
                              reasoning="System matches an Article 5 prohibition."))
        return out
    if tier in ("ANNEX_I", "ANNEX_III"):
        dl = DATE_ANNEX_I if tier == "ANNEX_I" else DATE_ANNEX_III
        out += [Obligation(obligation=o, deadline=dl) for o in HIGH_RISK_OBLIGATIONS]
    if transparency.result == "Yes":
        out.append(Obligation(obligation="Transparency: disclosure / labelling",
                              deadline=DATE_TRANSPARENCY,
                              reasoning=transparency.detail))
    if is_gpai:
        out += [Obligation(obligation=o, deadline=DATE_GPAI) for o in GPAI_OBLIGATIONS]
        if systemic:
            out += [Obligation(obligation=o, deadline=DATE_GPAI)
                    for o in GPAI_SYSTEMIC_OBLIGATIONS]
    return out


def classify(f: Facts, system_name: str = "") -> Assessment:
    is_ai = _with_sources(Conclusion(
        result={True: "Yes", False: "No", None: "Unclear"}[f.is_ai_system],
        detail="within the EU AI Act definition of an AI system (Art. 3(1))",
        articles=["Art. 3(1)"],
        trigger=f"is_ai_system = {f.is_ai_system}",
        status="definitive" if _known(f.is_ai_system) else "unresolved"))

    prohibited = _with_sources(_evaluate_prohibited(f))
    high_risk = _with_sources(_evaluate_high_risk(f))
    transparency = _with_sources(_evaluate_transparency(f))
    gpai = _with_sources(_evaluate_gpai(f))

    # headline tier
    if f.is_ai_system is False:
        tier = "NOT_AI"
    elif prohibited.result == "Yes":
        tier = "PROHIBITED"
    elif high_risk.result in ("ANNEX_I", "ANNEX_III"):
        tier = high_risk.result
    elif transparency.result == "Yes":
        tier = "LIMITED"
    else:
        tier = "MINIMAL"

    date = {
        "PROHIBITED": DATE_PROHIBITED, "ANNEX_I": DATE_ANNEX_I,
        "ANNEX_III": DATE_ANNEX_III, "LIMITED": DATE_TRANSPARENCY,
        "MINIMAL": "—", "NOT_AI": "—",
    }[tier]

    is_gpai = gpai.result == "Yes"
    systemic = f.gpai_systemic_risk is True

    # missing information = decisive facts still unknown
    missing = []
    for c in (is_ai, prohibited, high_risk, transparency):
        if c.status == "unresolved":
            missing.append(f"{c.detail} — {', '.join(c.articles)}")
    if f.organisation_role == "unknown":
        missing.append("Organisation role (provider / deployer / importer / distributor)")

    confidence = "high"
    if missing:
        confidence = "low" if (not _known(f.is_ai_system) or len(missing) >= 3) else "medium"

    human_review = (
        tier in ("PROHIBITED", "ANNEX_I", "ANNEX_III")
        or prohibited.result in ("Yes", "Possible")
        or confidence != "high"
    )

    return Assessment(
        system_name=system_name,
        tier=tier,
        is_gpai=is_gpai,
        is_ai_system=is_ai,
        prohibited_practice=prohibited,
        high_risk=high_risk,
        transparency=transparency,
        gpai=gpai,
        organisation_role=f.organisation_role,
        application_date=date,
        confidence=confidence,
        missing_information=missing,
        human_review_required=human_review,
        obligations=_obligations_for(tier, is_gpai, systemic, transparency),
    )
