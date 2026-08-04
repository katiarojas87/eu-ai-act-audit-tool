"""Typed data models for the deterministic EU AI Act classifier (v2)."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

# A fact that is True / False / unknown (None). Unknown drives "unresolved".
Tri = Optional[bool]

OrgRole = Literal[
    "provider", "deployer", "importer", "distributor",
    "downstream_provider", "unknown",
]
# Sectoral regimes that absorb part of the AI Act's quality-management duty.
SectoralRegime = Literal["none", "financial_services", "medical_devices", "other_sectoral"]
# Art. 5(1)(h)(i)-(iii): the only objectives for which real-time remote biometric
# identification in public spaces may be used for law enforcement.
RbiObjective = Literal[
    "none",             # no permitted objective claimed → the ban applies
    "victim_search",    # (i) victims of abduction/trafficking, missing persons
    "imminent_threat",  # (ii) substantial imminent threat to life, or terrorism
    "serious_offence",  # (iii) Annex II offence, ≥4 years' custodial sentence
]
HighRiskDomain = Literal[
    "employment", "education", "credit", "insurance",
    "essential_public_services", "justice", "migration",
    "biometrics", "law_enforcement", "critical_infrastructure",
]
GpaiRelationship = Literal[
    "none", "uses_api", "builds_or_finetunes", "integrates_distributes",
]
# Article 6(3): an Annex III system is NOT high-risk if it does not pose a
# significant risk of harm because it only does one of these. Never available
# where the system performs profiling of natural persons (Art. 6(3) last subpara).
Art63Ground = Literal[
    "none",                    # no derogation ground claimed → stays high-risk
    "narrow_procedural_task",  # Art. 6(3)(a)
    "improves_human_output",   # Art. 6(3)(b)
    "detects_patterns",        # Art. 6(3)(c)
    "preparatory_task",        # Art. 6(3)(d)
]
HumanOversight = Literal["effective", "limited", "none", "unknown"]
Status = Literal["definitive", "conditional", "unresolved"]


# Accepted values per enum field, with the default used when the LLM emits
# something outside the set. Kept at module level: pydantic reserves
# leading-underscore class attributes for private state.
_ENUM_DEFAULTS: dict[str, tuple[str, set[str]]] = {
    "organisation_role": ("unknown", set(OrgRole.__args__)),
    "emotion_context": ("none", {"workplace_education", "other", "none"}),
    "gpai_relationship": ("none", set(GpaiRelationship.__args__)),
    "human_oversight": ("unknown", set(HumanOversight.__args__)),
    "art_6_3_ground": ("none", set(Art63Ground.__args__)),
    "sectoral_regime": ("none", set(SectoralRegime.__args__)),
    "rbi_permitted_objective": ("none", set(RbiObjective.__args__)),
}
_STR_FIELDS = ("purpose", "sector", "affected_persons")


class Facts(BaseModel):
    """Structured facts extracted from the user's description by the LLM.

    The LLM fills these; it does NOT decide the classification. Use None for any
    trigger it genuinely cannot determine — that produces an 'unresolved' result
    and a follow-up question rather than a guess.
    """
    is_ai_system: Tri = None
    purpose: str = ""
    sector: str = ""
    affected_persons: str = ""
    high_risk_domains: list[HighRiskDomain] = Field(default_factory=list)

    # --- territorial scope (Article 2) ---------------------------------------
    # The Regulation does not apply to everything everywhere. Without these the
    # tool hands a full EU compliance report to a system with no EU nexus.
    placed_on_eu_market: Tri = None          # Art. 2(1)(a): placed/put into service in the Union
    output_used_in_eu: Tri = None            # Art. 2(1)(c): third-country actor, output used in the Union
    # Express carve-outs.
    military_defence_national_security: Tri = None   # Art. 2(3), "exclusively"
    sole_purpose_scientific_research: Tri = None     # Art. 2(6)
    prerelease_research_testing: Tri = None          # Art. 2(8), before placing on market
    real_world_testing: Tri = None                   # defeats the Art. 2(8) carve-out
    personal_non_professional_use: Tri = None        # Art. 2(10), natural persons only

    # --- role in the AI value chain ------------------------------------------
    # Role is a legal conclusion (Art. 3(3)–(7), Art. 25), not something to ask
    # the model for directly. Collect observable facts; rules.py derives the
    # role. A single organisation can hold several roles for one system — e.g.
    # building an in-house tool makes you provider AND deployer.
    developed_or_commissioned: Tri = None     # built it, or had it built
    supplied_under_own_name: Tri = None       # offered to others under own brand
    uses_under_own_authority: Tri = None      # uses it in its own operations
    rebranded_or_modified: Tri = None         # Art. 25(1): role escalates to provider
    imports_from_third_country: Tri = None    # Art. 3(6) importer
    makes_available_on_market: Tri = None     # Art. 3(7) distributor
    established_outside_eu: Tri = None        # Art. 22 authorised representative

    # Consultant override: set from the UI when the role is known from the
    # client conversation. Beats anything derived from the description.
    organisation_role: OrgRole = "unknown"

    # Art. 17(3)/(4): an existing sectoral quality system can absorb the QMS duty.
    sectoral_regime: SectoralRegime = "none"
    public_body_or_public_service: Tri = None  # Art. 27 FRIA trigger

    # --- Annex III carve-outs -------------------------------------------------
    # Each of these domains is narrower than its label suggests; without them the
    # tool marks ordinary systems high-risk.
    biometric_verification_only: Tri = None   # Annex III(1)(a): verification is excluded
    credit_fraud_detection_only: Tri = None   # Annex III(5)(b): fraud detection excluded
    insurance_life_or_health: Tri = None      # Annex III(5)(c): life/health insurance ONLY

    # --- transparency (Article 50) -------------------------------------------
    interacts_with_people: Tri = None            # Art. 50(1): chatbot disclosure
    ai_interaction_obvious: Tri = None           # 50(1) exception: obvious to a
                                                 # reasonably well-informed person
    generates_synthetic_content: Tri = None      # Art. 50(2): mark synthetic output
    assistive_or_no_substantial_alteration: Tri = None   # 50(2) exception
    deepfake_content: Tri = None                 # Art. 50(4): deployer disclosure
    artistic_creative_satirical_work: Tri = None # 50(4): limits, does not remove
    text_published_public_interest: Tri = None   # Art. 50(4) second subparagraph
    human_editorial_review: Tri = None           # 50(4) exception for published text
    # Common to 50(1)-(4): authorised by law to detect, prevent, investigate or
    # prosecute criminal offences.
    law_enforcement_authorised_detection: Tri = None

    profiling: Tri = None

    # --- Article 5 prohibitions ----------------------------------------------
    # Almost every prohibition has statutory elements and express exceptions.
    # Each trigger below is paired with the facts that qualify it, so the engine
    # can say "prohibited unless X" instead of an unqualified "cease use".
    emotion_recognition: Tri = None
    emotion_context: Literal["workplace_education", "other", "none"] = "none"
    emotion_medical_or_safety_purpose: Tri = None   # Art. 5(1)(f) exception

    biometric_categorisation_sensitive: Tri = None
    biometric_lawful_dataset_filtering: Tri = None  # Art. 5(1)(g) exception

    realtime_remote_biometric_id_public_le: Tri = None
    # Art. 5(1)(h)(i)-(iii): the objectives that can make real-time RBI lawful.
    rbi_permitted_objective: RbiObjective = "none"
    rbi_prior_authorisation: Tri = None              # Art. 5(3)

    social_scoring: Tri = None
    social_scoring_detrimental_treatment: Tri = None  # Art. 5(1)(c)(i)-(ii) element

    # (a) subliminal/manipulative and (b) exploitation of vulnerabilities are
    # separate prohibitions; both require significant harm.
    subliminal_or_manipulative: Tri = None
    exploits_vulnerabilities: Tri = None
    causes_significant_harm: Tri = None              # element of both (a) and (b)
    # Legacy single field: seeds (a) and (b) when they are not set directly.
    manipulative_or_exploitative: Tri = None

    predictive_policing_profiling_only: Tri = None
    # Art. 5(1)(d) exception: supporting a human assessment already grounded in
    # objective, verifiable facts linked to criminal activity.
    predictive_policing_supports_human_assessment: Tri = None

    untargeted_facial_scraping: Tri = None           # Art. 5(1)(e): no exception

    safety_component_regulated_product: Tri = None   # Annex I
    # Art. 6(3) derogation: only set when the description clearly shows the
    # system does no more than one of these. Defaults to "none" (stays high-risk)
    # so an unstated case fails safe.
    art_6_3_ground: Art63Ground = "none"

    gpai_relationship: GpaiRelationship = "none"
    gpai_systemic_risk: Tri = None
    human_oversight: HumanOversight = "unknown"

    # Fact extraction must degrade, never crash. The LLM may emit an explicit
    # null, a boolean where an enum was expected, or an unknown category — none
    # of which should take down a client's whole assessment. Anything we cannot
    # interpret becomes the field default, which means "unknown" and produces a
    # follow-up question rather than a 500.
    @model_validator(mode="before")
    @classmethod
    def _coerce_loose_values(cls, data):
        if not isinstance(data, dict):
            return data

        for k in _STR_FIELDS:
            if k in data and not isinstance(data[k], str):
                data[k] = "" if data[k] is None else str(data[k])

        for k, (dflt, allowed) in _ENUM_DEFAULTS.items():
            # isinstance guard first: an unhashable value (dict/list) would
            # otherwise raise on the membership test.
            if k in data and (not isinstance(data[k], str) or data[k] not in allowed):
                data[k] = dflt

        if "high_risk_domains" in data:
            v = data["high_risk_domains"]
            if not isinstance(v, list):
                v = [] if v is None else [v]
            data["high_risk_domains"] = [
                d for d in v if d in set(HighRiskDomain.__args__)]

        # Tri fields: only True/False/None are meaningful. Map "yes"/"no"
        # strings, drop anything else to None (= unknown).
        for k, field in cls.model_fields.items():
            if k in data and field.annotation is Tri:
                v = data[k]
                if isinstance(v, str):
                    low = v.strip().lower()
                    v = True if low in ("true", "yes") else (
                        False if low in ("false", "no") else None)
                data[k] = v if isinstance(v, bool) or v is None else None

        # `manipulative_or_exploitative` predates the split of Art. 5(1)(a) from
        # 5(1)(b). Seed both from it when they were not supplied directly.
        legacy = data.get("manipulative_or_exploitative")
        if legacy is not None:
            for k in ("subliminal_or_manipulative", "exploits_vulnerabilities"):
                if data.get(k) is None:
                    data[k] = legacy
        return data


class SourceQuote(BaseModel):
    """A verbatim excerpt from the official EU AI Act text."""
    ref: str                          # e.g. "Annex III(4)"
    quote: str                        # the exact sentence from the law
    location: str = ""                # where it sits in the official text
    url: str = ""                     # link to the official text
    # "operative" = binding enacting terms; "recital" = non-binding preamble,
    # an interpretive aid only. Never present a recital as the rule itself.
    kind: Literal["operative", "recital"] = "operative"


class Conclusion(BaseModel):
    """One dimension of the assessment, with provenance."""
    result: str                       # e.g. "Yes", "No", "Possible", "ANNEX_III"
    detail: str = ""                  # short paraphrase / category
    articles: list[str] = Field(default_factory=list)
    trigger: str = ""                 # the factual answer that triggered it
    status: Status = "unresolved"
    sources: list[SourceQuote] = Field(default_factory=list)  # verbatim law text
    # Provisions we cite but could not locate verbatim in the official text.
    # Surfaced as "confirmation needed" — never silently omitted.
    unsourced: list[str] = Field(default_factory=list)


class Obligation(BaseModel):
    obligation: str
    deadline: str
    status: str = "needs_confirmation"
    reasoning: str = ""
    gap_question: str = ""
    # Which role owes this duty, and the provision imposing it — so the report
    # can group duties by role instead of handing everyone the same list.
    role: str = "all"
    article: str = ""


class Assessment(BaseModel):
    """The full multi-dimensional result — never a single label."""
    system_name: str = ""
    tier: str = "NOT_AI"              # headline tier for badge/PDF compatibility
    is_gpai: bool = False

    territorial_scope: Conclusion | None = None   # Art. 2 — does the Act apply at all?
    is_ai_system: Conclusion
    prohibited_practice: Conclusion
    high_risk: Conclusion
    transparency: Conclusion
    gpai: Conclusion

    organisation_role: str = "unknown"      # headline role (first derived)
    roles: list[str] = Field(default_factory=list)   # every role that applies
    role_basis: Conclusion | None = None    # how the roles were derived, with citations
    application_date: str = "—"
    confidence: Literal["high", "medium", "low"] = "low"
    missing_information: list[str] = Field(default_factory=list)
    human_review_required: bool = True

    obligations: list[Obligation] = Field(default_factory=list)
