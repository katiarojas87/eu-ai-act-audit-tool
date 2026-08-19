"""Component-based gap assessment for obligations.

The rule engine decides WHICH obligations apply (deterministic). This step then
assesses, from the client's component/architecture list, whether each obligation
is likely met — reusing the v1 idea (likely_gap / likely_in_place /
needs_confirmation) on top of the deterministic obligations. The LLM only judges
the gap here; it never changes the classification.
"""
from __future__ import annotations

import logging

import anthropic
from dotenv import load_dotenv

from secrets_env import normalise_env

import config
from json_extract import ExtractionError, extract_array
from schema import Obligation

load_dotenv()
normalise_env()   # a secret with a trailing newline breaks the HTTP header
_client = anthropic.Anthropic()
log = logging.getLogger("eu_ai_act.gaps")

_SYSTEM = """You assess COMPLIANCE GAPS for a list of EU AI Act obligations, using
ONLY the client's component/architecture list. You do not change the
classification — the obligations are already fixed.

For each obligation, return:
- status: "likely_gap" (architecture suggests it is NOT met — e.g. auto-sent
  rejection emails imply no human oversight; a model fine-tuned on past decisions
  implies likely training-data bias), "likely_in_place" (a component is evidence
  it is partly met — e.g. a database storing scores/decisions => logging), or
  "needs_confirmation" (cannot tell from the architecture).
- reasoning: one line citing the component(s) you used.
- gap_question: a short question the consultant can ask the client to confirm.

Reply with ONLY a JSON array, same length and order as the input obligations:
[{"status":"...","reasoning":"...","gap_question":"..."}]"""


def assess_gaps(obligations: list[Obligation], description: str,
                components: str) -> list[Obligation]:
    if not obligations:
        return obligations
    comp = (components or "").strip()
    if not comp:
        # No architecture given → nothing to reason from; ask to confirm.
        for o in obligations:
            o.status = "needs_confirmation"
            o.reasoning = ""
            if not o.gap_question:
                o.gap_question = f"Do you currently meet: {o.obligation}?"
        return obligations

    listing = "\n".join(f"{i+1}. {o.obligation}" for i, o in enumerate(obligations))
    user = (f"System description: {description}\n\nComponents / architecture:\n{comp}\n\n"
            f"Obligations to assess (keep this order):\n{listing}")
    try:
        resp = _client.messages.create(
            model=config.LLM_MODEL, max_tokens=3000,
            system=_SYSTEM, messages=[{"role": "user", "content": user}])
        text = next((b.text for b in resp.content if b.type == "text"), "")
        rows = extract_array(text)
    except ExtractionError as e:
        log.warning("gap assessment produced unparseable JSON: %s", e)
        rows = []
    except Exception:  # noqa: BLE001 — never let gap assessment break classification
        log.exception("gap assessment call failed; leaving obligations as needs_confirmation")
        rows = []

    for i, o in enumerate(obligations):
        r = rows[i] if i < len(rows) and isinstance(rows[i], dict) else {}
        o.status = r.get("status", "needs_confirmation")
        o.reasoning = r.get("reasoning", "")
        o.gap_question = r.get("gap_question", f"Do you currently meet: {o.obligation}?")
    return obligations
