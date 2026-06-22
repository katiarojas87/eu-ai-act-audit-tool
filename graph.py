"""
LangGraph reasoning pipeline for an EU AI Act audit.

Flow:
    intake -> retrieve -> classify -> (uncertain? -> clarify) -> obligations -> END

Each AI system the client uses is run through this graph and produces a
structured classification + obligations + gaps.
"""
from __future__ import annotations

import json
from typing import Literal, Optional, TypedDict

import anthropic
from dotenv import load_dotenv
from langgraph.graph import END, StateGraph

import config
from retriever import retrieve

load_dotenv()  # load ANTHROPIC_API_KEY from .env
client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #
class AuditState(TypedDict, total=False):
    # input
    system_name: str
    description: str          # plain-language description (any of NL/FR/EN/ES)
    components: str           # optional architecture / component list (free text)
    clarifications: dict      # answers to follow-up questions {question: answer}
    # working
    passages: list[dict]      # retrieved law context
    # output
    tier: str                 # PROHIBITED | ANNEX_I | ANNEX_III | LIMITED | MINIMAL
    annex_category: str       # e.g. "4. Employment" when ANNEX_III
    rationale: str
    triggering_articles: list[str]
    confidence: str           # high | medium | low
    needs_review: bool
    follow_up_questions: list[str]
    # GPAI is an ORTHOGONAL flag: a system can be e.g. ANNEX_III *and* GPAI.
    is_gpai: bool
    gpai_rationale: str
    obligations: list[dict]   # [{obligation, applies, deadline, gap_question}]


def _llm_json(system: str, user: str) -> dict:
    """Call Claude and parse a JSON object from the reply."""
    resp = client.messages.create(
        model=config.LLM_MODEL,
        max_tokens=config.LLM_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = next((b.text for b in resp.content if b.type == "text"), "")
    # Be forgiving: pull out the first {...} block.
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        return json.loads(text[start : end + 1])
    raise ValueError(f"No JSON in model reply:\n{text}")


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #
def node_retrieve(state: AuditState) -> AuditState:
    query = f"{state['system_name']}. {state['description']} {state.get('components', '')}"
    return {"passages": retrieve(query)}


def node_classify(state: AuditState) -> AuditState:
    context = "\n\n".join(f"[{p['source']}]\n{p['text']}" for p in state["passages"])
    clar = state.get("clarifications") or {}
    clar_text = "\n".join(f"Q: {q}\nA: {a}" for q, a in clar.items()) or "(none yet)"

    system = (
        "You are an EU AI Act (Regulation 2024/1689) compliance classifier. "
        "Classify the described AI system into exactly one risk tier using ONLY the "
        "provided legal context. The system description may be in Dutch, French, "
        "English or Spanish. Be precise and cite article/annex references.\n\n"
        "Tiers (pick ONE, based on the USE CASE): PROHIBITED, "
        "ANNEX_I (high-risk in regulated products), ANNEX_III (high-risk use case), "
        "LIMITED (transparency only), MINIMAL.\n"
        "Do NOT use GPAI here — GPAI is assessed separately as a flag, not a tier.\n"
        'Reply with JSON only:\n'
        '{"tier": "...", "annex_category": "...", "rationale": "...", '
        '"triggering_articles": ["..."], "confidence": "high|medium|low", '
        '"follow_up_questions": ["..."]}\n'
        "Set confidence=low and provide follow_up_questions when the description is "
        "ambiguous about what triggers (or rules out) high-risk classification."
    )
    user = (
        f"LEGAL CONTEXT:\n{context}\n\n"
        f"AI SYSTEM\nName: {state['system_name']}\n"
        f"Description: {state['description']}\n"
        f"Components: {state.get('components') or '(none provided)'}\n"
        f"Clarifications:\n{clar_text}"
    )
    data = _llm_json(system, user)
    data["needs_review"] = data.get("confidence") == "low"
    return data


def node_gpai(state: AuditState) -> AuditState:
    """Orthogonal check: is the organisation a GPAI (foundation-model) provider?

    GPAI obligations are triggered by building, fine-tuning, or integrating a
    general-purpose / foundation model — independent of the use-case risk tier.
    Training a small classical model (regression, decision tree) is NOT GPAI.
    """
    system = (
        "You decide whether an organisation has GPAI (general-purpose AI model) "
        "obligations under the EU AI Act. This is INDEPENDENT of the risk tier.\n\n"
        "Answer is_gpai=true ONLY if the organisation builds, fine-tunes, or "
        "integrates/distributes a general-purpose FOUNDATION model (e.g. an LLM "
        "like GPT, Claude, Llama, Mistral; a large vision or multimodal model).\n"
        "Answer is_gpai=false if it only: calls such a model via API for inference "
        "(no weight changes), uses pre-trained embeddings as-is, or trains a small "
        "classical/task-specific model (regression, decision tree, a custom CNN). "
        "Those do not create GPAI provider obligations.\n"
        "The description may be in Dutch, French, English or Spanish.\n"
        'Reply with JSON only: {"is_gpai": true|false, "gpai_rationale": "..."}'
    )
    user = (f"System: {state['system_name']}\n"
            f"Description: {state['description']}\n"
            f"Components: {state.get('components') or '(none provided)'}")
    data = _llm_json(system, user)
    return {"is_gpai": bool(data.get("is_gpai")),
            "gpai_rationale": data.get("gpai_rationale", "")}


def node_obligations(state: AuditState) -> AuditState:
    obligations_ref = (config.KNOWLEDGE_DIR / "obligations.md").read_text(encoding="utf-8")
    gpai_note = ""
    if state.get("is_gpai"):
        gpai_note = ("\nThis system is ALSO a GPAI provider — additionally include "
                     "the GPAI obligations from the reference (technical documentation, "
                     "info to downstream providers, copyright policy, training-data "
                     "summary; plus systemic-risk duties only if applicable).")

    components = (state.get("components") or "").strip()
    if components:
        status_note = (
            "\nThe client provided a COMPONENT / ARCHITECTURE list. For each "
            "obligation, REASON from those components and assign a 'status':\n"
            "  'likely_gap' — the architecture suggests the obligation is NOT met "
            "(e.g. auto-sent rejection emails imply no human oversight; a model "
            "fine-tuned on past decisions implies likely training-data bias).\n"
            "  'likely_in_place' — a component is evidence the obligation is "
            "partly met (e.g. a database storing scores/decisions => logging).\n"
            "  'needs_confirmation' — cannot tell from the architecture; must ask.\n"
            "Add a one-line 'reasoning' citing the component(s) you used.")
        status_fields = '"status": "likely_gap|likely_in_place|needs_confirmation", "reasoning": "...", '
    else:
        status_note = ("\nNo component list was provided, so set every status to "
                       "'needs_confirmation' with empty reasoning.")
        status_fields = '"status": "needs_confirmation", "reasoning": "", '

    system = (
        "You map an already-classified AI system to its concrete EU AI Act "
        "obligations using the reference below. Return the obligations that apply "
        "to THIS tier. For each, add a short 'gap_question' the consultant can ask "
        "the client to confirm compliance." + gpai_note + status_note + "\n\n"
        f"OBLIGATIONS REFERENCE:\n{obligations_ref}\n\n"
        'Reply with JSON only:\n'
        '{"obligations": [{"obligation": "...", "deadline": "...", '
        + status_fields + '"gap_question": "..."}]}'
    )
    user = (
        f"System: {state['system_name']}\n"
        f"Tier: {state['tier']}\n"
        f"Is GPAI: {state.get('is_gpai', False)}\n"
        f"Annex category: {state.get('annex_category', '-')}\n"
        f"Rationale: {state.get('rationale', '')}\n"
        f"Components:\n{components or '(none provided)'}"
    )
    return _llm_json(system, user)


def _route(state: AuditState) -> Literal["clarify", "obligations"]:
    # If low confidence AND we have not yet asked the client, surface questions.
    if state.get("needs_review") and not state.get("clarifications"):
        return "clarify"
    return "obligations"


def node_clarify(state: AuditState) -> AuditState:
    # Terminal-ish node: the UI collects answers and re-runs the graph with
    # clarifications filled in. Nothing to compute here.
    return {}


# --------------------------------------------------------------------------- #
# Build graph
# --------------------------------------------------------------------------- #
def build_graph():
    g = StateGraph(AuditState)
    g.add_node("retrieve", node_retrieve)
    g.add_node("classify", node_classify)
    g.add_node("gpai", node_gpai)
    g.add_node("clarify", node_clarify)
    g.add_node("obligations", node_obligations)

    g.set_entry_point("retrieve")
    g.add_edge("retrieve", "classify")
    g.add_edge("classify", "gpai")
    g.add_conditional_edges("gpai", _route,
                            {"clarify": "clarify", "obligations": "obligations"})
    g.add_edge("clarify", END)
    g.add_edge("obligations", END)
    return g.compile()


GRAPH = build_graph()


def audit_system(system_name: str, description: str, components: str = "",
                 clarifications: Optional[dict] = None) -> AuditState:
    """Run one AI system through the full pipeline."""
    return GRAPH.invoke({
        "system_name": system_name,
        "description": description,
        "components": components,
        "clarifications": clarifications or {},
    })


if __name__ == "__main__":
    # Quick smoke test (requires ingest.py to have been run + ANTHROPIC_API_KEY set)
    result = audit_system(
        "HR CV Screener",
        "Tool die automatisch cv's van sollicitanten filtert en rangschikt.",  # Dutch
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
