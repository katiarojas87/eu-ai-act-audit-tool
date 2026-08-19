"""Grounded Q&A about one already-computed assessment.

This is NOT a second path to a classification. The tier, roles, obligations
and citations below are already fixed — decided by the deterministic rule
engine (rules.py) before this module is ever called. The chat only explains
and elaborates on that fixed result; it cannot move the tier, add or drop an
obligation, or invent a citation the assessment does not already carry. If a
user asks "what if X were different", the right answer is "re-run the
assessment with that fact changed", not a quiet reclassification inside a chat
reply.
"""
from __future__ import annotations

import anthropic
from dotenv import load_dotenv

from secrets_env import normalise_env

import config
from schema import Assessment

load_dotenv()
normalise_env()   # a secret with a trailing newline breaks the HTTP header
_client = anthropic.Anthropic()

_SYSTEM = """You answer questions about ONE already-computed EU AI Act assessment,
reproduced below as JSON. A deterministic rule engine (not you) decided its tier,
roles and obligations from a set of extracted facts, and resolved every legal
citation it carries.

Rules:
- You do not reclassify the system. The tier, roles and obligations are fixed.
  If asked whether a fact could change the outcome, explain what would need to
  be true and that the assessment must be re-run to reflect it — never assert a
  new tier or obligation yourself.
- Ground every legal claim in the citations already present in the assessment
  JSON. If a question reaches a provision that has no citation there, say so
  rather than inventing a quote or an article number.
- Be concise — a few sentences, not a legal memo — unless asked to elaborate.
- This is not legal advice, and say so if the question calls for it (e.g. "can
  we ship this?", "will we be fined?").
- The description may be in Dutch, French, English or Spanish; answer in the
  language the question was asked in.

ASSESSMENT:
"""


def answer(assessment: Assessment, messages: list[dict]) -> str:
    """Answer the latest message in `messages`, grounded in `assessment`.

    `messages` is the full conversation so far, Anthropic Messages-API shape
    (`{"role": "user"|"assistant", "content": str}`), ending in the new user
    question. The assessment JSON is marked cacheable: it is identical on every
    turn of the same conversation, so Anthropic's prompt cache makes a five-turn
    conversation cost roughly one assessment's worth of input tokens, not five.
    """
    context = assessment.model_dump_json(indent=2)
    resp = _client.messages.create(
        model=config.LLM_MODEL, max_tokens=800,
        system=[
            {"type": "text", "text": _SYSTEM},
            {"type": "text", "text": context, "cache_control": {"type": "ephemeral"}},
        ],
        messages=messages,
    )
    return next((b.text for b in resp.content if b.type == "text"), "").strip()
