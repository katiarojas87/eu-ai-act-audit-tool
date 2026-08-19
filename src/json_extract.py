"""Pull a JSON object/array out of an LLM text response.

Claude is asked to reply with ONLY JSON, but "only" is a request, not a
guarantee — a stray preamble sentence, markdown fencing, or a response cut off
by max_tokens can all produce text that isn't valid JSON on its own. Both
callers used to slice between the first/last bracket and hand the result
straight to json.loads with no guard; a malformed slice raised an uncaught
JSONDecodeError. Centralising the slice-and-parse here means the fix (a real
exception instead of a crash) only has to happen once.
"""
from __future__ import annotations

import json


class ExtractionError(ValueError):
    """No parseable JSON object/array found in the model's response."""


def extract_object(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ExtractionError("no JSON object found in the model's response")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise ExtractionError(f"unparseable JSON object: {e}") from e


def extract_array(text: str) -> list:
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end < start:
        raise ExtractionError("no JSON array found in the model's response")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise ExtractionError(f"unparseable JSON array: {e}") from e
