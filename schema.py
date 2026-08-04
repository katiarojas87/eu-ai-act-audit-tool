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
HighRiskDomain = Literal[
    "employment", "education", "credit", "insurance",
    "essential_public_services", "justice", "migration",
    "biometrics", "law_enforcement", "critical_infrastructure",
]
GpaiRelationship = Literal[
    "none", "uses_api", "builds_or_finetunes", "integrates_distributes",
]
HumanOversight = Literal["effective", "limited", "none", "unknown"]
Status = Literal["definitive", "conditional", "unresolved"]


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
    organisation_role: OrgRole = "unknown"
    high_risk_domains: list[HighRiskDomain] = Field(default_factory=list)

    interacts_with_people: Tri = None            # chatbot → transparency
    generates_synthetic_content: Tri = None      # deepfake/synthetic media → transparency
    profiling: Tri = None

    emotion_recognition: Tri = None
    emotion_context: Literal["workplace_education", "other", "none"] = "none"
    biometric_categorisation_sensitive: Tri = None
    realtime_remote_biometric_id_public_le: Tri = None
    social_scoring: Tri = None
    manipulative_or_exploitative: Tri = None
    predictive_policing_profiling_only: Tri = None
    untargeted_facial_scraping: Tri = None

    safety_component_regulated_product: Tri = None   # Annex I

    gpai_relationship: GpaiRelationship = "none"
    gpai_systemic_risk: Tri = None
    human_oversight: HumanOversight = "unknown"

    # The LLM may emit explicit null for non-boolean fields; map those to the
    # field default (the Tri booleans keep None = unknown).
    @model_validator(mode="before")
    @classmethod
    def _coerce_nulls(cls, data):
        if isinstance(data, dict):
            defaults = {
                "purpose": "", "sector": "", "affected_persons": "",
                "organisation_role": "unknown", "high_risk_domains": [],
                "emotion_context": "none", "gpai_relationship": "none",
                "human_oversight": "unknown",
            }
            for k, dflt in defaults.items():
                if k in data and data[k] is None:
                    data[k] = dflt
        return data


class SourceQuote(BaseModel):
    """A verbatim excerpt from the official EU AI Act text."""
    ref: str                          # e.g. "Annex III(4)"
    quote: str                        # the exact sentence from the law
    location: str = ""                # where it sits in the official text
    url: str = ""                     # link to the official text


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


class Assessment(BaseModel):
    """The full multi-dimensional result — never a single label."""
    system_name: str = ""
    tier: str = "NOT_AI"              # headline tier for badge/PDF compatibility
    is_gpai: bool = False

    is_ai_system: Conclusion
    prohibited_practice: Conclusion
    high_risk: Conclusion
    transparency: Conclusion
    gpai: Conclusion

    organisation_role: str = "unknown"
    application_date: str = "—"
    confidence: Literal["high", "medium", "low"] = "low"
    missing_information: list[str] = Field(default_factory=list)
    human_review_required: bool = True

    obligations: list[Obligation] = Field(default_factory=list)
