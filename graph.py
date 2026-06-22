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
    clarifications: dict      # answers to follow-up questions {question: answer}
    # working
    passages: list[dict]      # retrieved law context
    # output
    tier: str                 # PROHIBITED | ANNEX_I | ANNEX_III | LIMITED | MINIMAL | GPAI
    annex_category: str       # e.g. "4. Employment" when ANNEX_III
    rationale: str
    triggering_articles: list[str]
    confidence: str           # high | medium | low
    needs_review: bool
    follow_up_questions: list[str]
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
    query = f"{state['system_name']}. {state['description']}"
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
        "Tiers: PROHIBITED, ANNEX_I (high-risk in regulated products), "
        "ANNEX_III (high-risk use case), LIMITED (transparency only), MINIMAL, GPAI.\n"
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
        f"Clarifications:\n{clar_text}"
    )
    data = _llm_json(system, user)
    data["needs_review"] = data.get("confidence") == "low"
    return data


def node_obligations(state: AuditState) -> AuditState:
    obligations_ref = (config.KNOWLEDGE_DIR / "obligations.md").read_text(encoding="utf-8")
    system = (
        "You map an already-classified AI system to its concrete EU AI Act "
        "obligations using the reference below. Return only obligations that apply "
        "to THIS tier. For each, add a short 'gap_question' the consultant can ask "
        "the client to check compliance.\n\n"
        f"OBLIGATIONS REFERENCE:\n{obligations_ref}\n\n"
        'Reply with JSON only:\n'
        '{"obligations": [{"obligation": "...", "deadline": "...", '
        '"gap_question": "..."}]}'
    )
    user = (
        f"System: {state['system_name']}\n"
        f"Tier: {state['tier']}\n"
        f"Annex category: {state.get('annex_category', '-')}\n"
        f"Rationale: {state.get('rationale', '')}"
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
    g.add_node("clarify", node_clarify)
    g.add_node("obligations", node_obligations)

    g.set_entry_point("retrieve")
    g.add_edge("retrieve", "classify")
    g.add_conditional_edges("classify", _route,
                            {"clarify": "clarify", "obligations": "obligations"})
    g.add_edge("clarify", END)
    g.add_edge("obligations", END)
    return g.compile()


GRAPH = build_graph()


def audit_system(system_name: str, description: str,
                 clarifications: Optional[dict] = None) -> AuditState:
    """Run one AI system through the full pipeline."""
    return GRAPH.invoke({
        "system_name": system_name,
        "description": description,
        "clarifications": clarifications or {},
    })


if __name__ == "__main__":
    # Quick smoke test (requires ingest.py to have been run + ANTHROPIC_API_KEY set)
    result = audit_system(
        "HR CV Screener",
        "Tool die automatisch cv's van sollicitanten filtert en rangschikt.",  # Dutch
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
