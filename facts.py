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
- gpai_relationship: "builds_or_finetunes" if they train/fine-tune a foundation
  model; "integrates_distributes" if they ship a product built on one;
  "uses_api" if they only call one via API; "none" otherwise.
- emotion_context: "workplace_education" only if emotion recognition is used in a
  workplace or educational setting.

Reply with ONLY a JSON object matching these keys (omit a key to leave it null/default):
is_ai_system, purpose, sector, affected_persons, organisation_role,
high_risk_domains, interacts_with_people, generates_synthetic_content, profiling,
emotion_recognition, emotion_context, biometric_categorisation_sensitive,
realtime_remote_biometric_id_public_le, social_scoring, manipulative_or_exploitative,
predictive_policing_profiling_only, untargeted_facial_scraping,
safety_component_regulated_product, gpai_relationship, gpai_systemic_risk,
human_oversight."""


def extract_facts(name: str, description: str, components: str = "") -> Facts:
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
    return Facts.model_validate(data)


if __name__ == "__main__":
    f = extract_facts(
        "CV Screener",
        "Tool die cv's van sollicitanten filtert en rangschikt, met een model dat "
        "is fijngetuned op eerdere aanwervingen, en automatisch afwijzingsmails stuurt.")
    print(f.model_dump_json(indent=2))
    from rules import classify
    print("\nTIER:", classify(f).tier)
