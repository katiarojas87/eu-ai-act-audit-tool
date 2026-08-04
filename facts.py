"""LLM fact extraction — the ONLY place the model touches classification.

The model reads the plain-language description (grounded with RAG context) and
fills the structured Facts. It does NOT decide the tier; rules.py does that.
"""
from __future__ import annotations

import json

import anthropic
from dotenv import load_dotenv

import config
from retriever import retrieve
from schema import Facts

load_dotenv()
_client = anthropic.Anthropic()

_SYSTEM = """You extract STRUCTURED FACTS about an AI system for an EU AI Act
assessment. You do NOT classify risk and you do NOT decide obligations — a
separate deterministic rule engine does that. Your only job is to fill the fact
fields truthfully from the description.

Rules:
- The description may be in Dutch, French, English or Spanish.
- For every boolean fact, answer true or false ONLY if the description gives you
  enough to be sure. If you cannot tell, use null (do NOT guess) — an honest null
  produces a follow-up question, a wrong guess produces a wrong assessment.
- high_risk_domains: include only domains the system clearly operates in, from:
  employment, education, credit, insurance, essential_public_services, justice,
  migration, biometrics, law_enforcement, critical_infrastructure.
- ANNEX III CARVE-OUTS — these domains are narrower than they sound:
    biometric_verification_only — true if it only confirms a person is who they
      claim to be (unlocking a phone, a door badge). Annex III(1)(a) excludes it.
    credit_fraud_detection_only — true if it is used to detect financial fraud
      rather than to score creditworthiness. Annex III(5)(b) excludes it.
    insurance_life_or_health — true only for LIFE or HEALTH insurance. Motor,
      property and other lines are not covered by Annex III(5)(c).
- ARTICLE 50 EXCEPTIONS:
    ai_interaction_obvious — is it obvious to a reasonable person that they are
      dealing with an AI? (50(1) exception)
    assistive_or_no_substantial_alteration — does it only assist standard editing
      or leave the input substantially unaltered? (50(2) exception)
    deepfake_content — does it generate or manipulate image/audio/video that is a
      deep fake? (triggers 50(4))
    artistic_creative_satirical_work — is the output part of an evidently
      artistic, creative, satirical or fictional work? (limits 50(4))
    text_published_public_interest — is AI-generated text published to inform the
      public on matters of public interest? (50(4) second subparagraph)
    human_editorial_review — did a person review it and take editorial
      responsibility? (50(4) exception)
    law_enforcement_authorised_detection — is the system authorised by law to
      detect, prevent, investigate or prosecute criminal offences? (runs through
      50(1)-(4))
- gpai_relationship: "builds_or_finetunes" if they train/fine-tune a foundation
  model; "integrates_distributes" if they ship a product built on one;
  "uses_api" if they only call one via API; "none" otherwise.
- emotion_context: "workplace_education" only if emotion recognition is used in a
  workplace or educational setting.
- ARTICLE 5 ELEMENTS AND EXCEPTIONS — almost no prohibition is absolute. When you
  set a prohibition trigger to true, also answer its qualifiers if the
  description allows; leaving them null is fine and yields "prohibited unless…":
    causes_significant_harm — does the manipulation/exploitation cause, or is it
      likely to cause, SIGNIFICANT harm? Required for both 5(1)(a) and 5(1)(b).
    social_scoring_detrimental_treatment — does the score actually lead to
      detrimental treatment that is out of context, unjustified or
      disproportionate? Required for 5(1)(c).
    predictive_policing_supports_human_assessment — true if it merely supports a
      human assessment already based on objective, verifiable facts linked to a
      criminal activity (this takes it OUT of 5(1)(d)).
    emotion_medical_or_safety_purpose — true if the emotion system is intended
      for medical or safety reasons (takes it OUT of 5(1)(f)).
    biometric_lawful_dataset_filtering — true if it only labels/filters a
      lawfully acquired biometric dataset, or categorises biometric data for law
      enforcement (takes it OUT of 5(1)(g)).
    rbi_permitted_objective — for real-time remote biometric identification, one
      of "victim_search", "imminent_threat", "serious_offence" if the description
      names such a purpose, else "none".
    rbi_prior_authorisation — true only if the description says each use is
      authorised in advance by a judicial or independent authority.
- subliminal_or_manipulative (5(1)(a)) and exploits_vulnerabilities (5(1)(b)) are
  SEPARATE prohibitions — set whichever the description supports.
- TERRITORIAL SCOPE (Art. 2) — the Regulation does not apply to everything:
    placed_on_eu_market   — is the system placed on the market or put into
                            service in the EU?
    output_used_in_eu     — if the organisation is outside the EU, is the
                            system's OUTPUT used in the Union?
    military_defence_national_security — used exclusively for military, defence
                            or national security purposes? (Art. 2(3))
    sole_purpose_scientific_research   — built and put into service solely for
                            scientific research and development? (Art. 2(6))
    prerelease_research_testing        — research/testing/development before the
                            system is placed on the market? (Art. 2(8))
    real_world_testing    — does that testing happen in real-world conditions?
                            (this cancels the Art. 2(8) exclusion)
    personal_non_professional_use      — a natural person using it purely
                            personally, not professionally? (Art. 2(10))
- ROLE FACTS — do NOT try to decide whether they are a "provider" or "deployer";
  that is a legal conclusion the rule engine draws. Just answer what they did:
    developed_or_commissioned  — did they build it, or have it built for them?
    supplied_under_own_name    — do they offer it to others under their own name
                                 or trademark? (Selling, licensing, or making it
                                 available — free or paid.)
    uses_under_own_authority   — do they use it in their own operations?
    rebranded_or_modified      — did they put their name on a bought system,
                                 substantially modify it, or change what it is
                                 used for? (Fine-tuning a vendor model on their
                                 own data counts.)
    imports_from_third_country — do they bring a non-EU company's system into
                                 the EU market?
    makes_available_on_market  — do they resell or distribute someone else's
                                 system without being its provider or importer?
    established_outside_eu     — is the organisation itself outside the EU?
  Leave organisation_role as "unknown" — a human sets it when they know it.
- public_body_or_public_service: true if the organisation is a public authority
  or a private entity delivering a public service (schools, hospitals, utilities,
  social services). Drives the Art. 27 FRIA duty.
- sectoral_regime: "financial_services" if they are a bank, insurer or other
  regulated financial institution; "medical_devices" if under the MDR/IVDR;
  "other_sectoral" for another EU quality-system regime; else "none".
- profiling: true if the system evaluates personal aspects of natural persons
  (performance, economic situation, health, preferences, behaviour, location).
  This is decisive for Art. 6(3), so answer it whenever the description allows.
- art_6_3_ground: leave "none" unless the description makes clear the system does
  no more than one of: "narrow_procedural_task" (a narrow procedural step),
  "improves_human_output" (polishes work a human already completed),
  "detects_patterns" (flags patterns/deviations without replacing the human
  assessment), "preparatory_task" (prepares an assessment someone else makes).
  A system that scores, ranks, filters or decides about people is NOT covered by
  any of these — leave "none".

Reply with ONLY a JSON object matching these keys (omit a key to leave it null/default):
is_ai_system, purpose, sector, affected_persons, high_risk_domains,
placed_on_eu_market, output_used_in_eu, military_defence_national_security,
sole_purpose_scientific_research, prerelease_research_testing, real_world_testing,
personal_non_professional_use,
developed_or_commissioned, supplied_under_own_name, uses_under_own_authority,
rebranded_or_modified, imports_from_third_country, makes_available_on_market,
established_outside_eu, public_body_or_public_service, sectoral_regime,
biometric_verification_only, credit_fraud_detection_only, insurance_life_or_health,
interacts_with_people, ai_interaction_obvious, generates_synthetic_content,
assistive_or_no_substantial_alteration, deepfake_content,
artistic_creative_satirical_work, text_published_public_interest,
human_editorial_review, law_enforcement_authorised_detection, profiling,
emotion_recognition, emotion_context, emotion_medical_or_safety_purpose,
biometric_categorisation_sensitive, biometric_lawful_dataset_filtering,
realtime_remote_biometric_id_public_le, rbi_permitted_objective,
rbi_prior_authorisation, social_scoring, social_scoring_detrimental_treatment,
subliminal_or_manipulative, exploits_vulnerabilities, causes_significant_harm,
predictive_policing_profiling_only, predictive_policing_supports_human_assessment,
untargeted_facial_scraping, safety_component_regulated_product, art_6_3_ground,
gpai_relationship, gpai_systemic_risk, human_oversight."""


def extract_facts(name: str, description: str, components: str = "",
                  organisation_role: str = "unknown") -> Facts:
    """Extract Facts from a description.

    `organisation_role` is the consultant's override: when they know the client's
    role from the conversation, it beats anything inferred from the text.
    """
    passages = retrieve(f"{name}. {description} {components}", k=config.TOP_K)
    context = "\n\n".join(f"[{p['source']}]\n{p['text']}" for p in passages)
    user = (f"LEGAL CONTEXT (for grounding definitions only):\n{context}\n\n"
            f"AI SYSTEM\nName: {name}\nDescription: {description}\n"
            f"Components: {components or '(none provided)'}")

    resp = _client.messages.create(
        model=config.LLM_MODEL, max_tokens=2000,
        system=_SYSTEM, messages=[{"role": "user", "content": user}],
    )
    text = next((b.text for b in resp.content if b.type == "text"), "")
    start, end = text.find("{"), text.rfind("}")
    data = json.loads(text[start:end + 1]) if start != -1 else {}
    if organisation_role and organisation_role != "unknown":
        data["organisation_role"] = organisation_role
    return Facts.model_validate(data)


if __name__ == "__main__":
    f = extract_facts(
        "CV Screener",
        "Tool die cv's van sollicitanten filtert en rangschikt, met een model dat "
        "is fijngetuned op eerdere aanwervingen, en automatisch afwijzingsmails stuurt.")
    print(f.model_dump_json(indent=2))
    from rules import classify
    print("\nTIER:", classify(f).tier)
