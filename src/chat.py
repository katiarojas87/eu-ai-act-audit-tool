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
- ANSWER ONLY FROM THE JSON BELOW. Do not fill a gap from your own general
  knowledge of the EU AI Act: your training data may reflect an outdated or
  amended version of the Regulation, and the assessment's own citations are the
  only text you may treat as authoritative here.
- Ground every legal claim in the citations already present in the assessment
  JSON. If a question reaches a provision with no citation there, or a specific
  number — a deadline, a percentage, a fine amount, an article subsection — that
  is not written in the JSON, say plainly that it is not in this assessment.
  Never estimate one or reconstruct one from memory.
- This tool does not model everything in the Regulation. If asked about
  something it does not cover — administrative fines (Art. 99), downstream GPAI
  provider duties beyond the Art. 3(68) distinction, national implementing law —
  say so directly rather than answering from general knowledge.
- When you are not sure an answer is grounded in the JSON below, say so ("I
  don't have that in this assessment") rather than answering with confidence.
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
    context = assessment.model_dump_json(indent=2, exclude={"sig"})
    resp = _client.messages.create(
        model=config.LLM_MODEL, max_tokens=800,
        system=[
            {"type": "text", "text": _SYSTEM},
            {"type": "text", "text": context, "cache_control": {"type": "ephemeral"}},
        ],
        messages=messages,
    )
    text = next((b.text for b in resp.content if b.type == "text"), "").strip()
    if not text:
        # A silent empty reply reads to the user as the assistant ignoring
        # them. Raise so api.py's existing handler logs it, refunds the
        # chat-cap slot, and returns a real error instead.
        raise RuntimeError(f"chat model returned no text (stop_reason={resp.stop_reason!r})")
    return text
