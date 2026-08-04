"""Verbatim source citations from the EU AI Act text.

Deterministic (no LLM, no vector search): each provision reference maps to one
or more anchor phrases; we locate the first match in data/eu_ai_act.txt and
return the surrounding verbatim sentence, its character offset, and a link to
the official text on EUR-Lex. If an anchor is not found the provision simply
carries no quote — we never fabricate one.
"""
from __future__ import annotations

import re
from functools import lru_cache

import config

EURLEX_URL = "https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng"

# provision ref -> candidate anchor phrases (operative text first, recital fallback)
ANCHORS: dict[str, list[str]] = {
    "Art. 3(1)": [
        "‘AI system’ means a machine-based system that is designed to operate",
        "machine-based system that is designed to operate with varying levels of autonomy",
    ],
    "Art. 5": [
        "The following AI practices shall be prohibited",
    ],
    "Art. 5(1)(a)-(b)": [
        "subliminal techniques beyond a person",
        "subliminal components such as audio, image, video stimuli that persons cannot perceive",
    ],
    "Art. 5(1)(c)": [
        "social behaviour or known, inferred or predicted personal or personality characteristics",
    ],
    "Art. 5(1)(d)": [
        "committing a criminal offence, based solely on the profiling",
        "risk of a natural person offending or reoffending not solely on the basis of the profiling",
        "profiling of a natural person or on assessing their personality traits",
    ],
    "Art. 5(1)(e)": [
        "facial recognition databases through the untargeted scraping of facial images",
        "untargeted scraping of facial images from the internet or CCTV footage",
    ],
    "Art. 5(1)(f)": [
        "infer emotions of a natural person in the areas of workplace and education",
        "identify or infer emotions",
    ],
    "Art. 5(1)(g)": [
        "biometric categorisation systems that categorise individually natural persons based on their biometric data to deduce or infer",
    ],
    "Art. 5(1)(h)": [
        "remote biometric identification systems in publicly accessible spaces for the purpose",
        "remote biometric identification systems in publicly accessible spaces",
    ],
    "Art. 6(1)": [
        "intended to be used as a safety component of a product",
        "safety component of a product, or the AI system is itself a product",
    ],
    "Annex I": [
        "intended to be used as a safety component of a product",
    ],
    "Art. 6(2)": [
        "In addition to the high-risk AI systems referred to in paragraph 1, AI systems referred to in Annex III",
        "AI systems referred to in Annex III shall be considered to be high-risk",
    ],
    "Annex III(1)": [
        "Biometrics, in so far as their use is permitted",
        "remote biometric identification systems",
    ],
    "Annex III(2)": [
        "safety components in the management and operation of critical digital infrastructure",
        "critical digital infrastructure, road traffic",
    ],
    "Annex III(3)": [
        "determine access or admission or to assign natural persons to educational",
    ],
    "Annex III(4)": [
        "recruitment or selection of natural persons, in particular to place targeted job advertisements",
        "recruitment or selection of natural persons",
    ],
    "Annex III(5)(a)": [
        "essential public assistance benefits and services",
        "eligibility of natural persons for essential public assistance",
    ],
    "Annex III(5)(b)": [
        "evaluate the creditworthiness of natural persons or establish their credit score",
        "creditworthiness of natural persons",
    ],
    "Annex III(5)(c)": [
        "risk assessment and pricing in relation to natural persons in the case of life and health insurance",
    ],
    "Annex III(6)": [
        "AI systems intended to be used by or on behalf of law enforcement authorities",
    ],
    "Annex III(7)": [
        "migration, asylum and border control management",
    ],
    "Annex III(8)": [
        "administration of justice and democratic processes",
    ],
    "Art. 50(1)": [
        "intended to interact directly with natural persons are designed and developed in such a way",
    ],
    "Art. 50(2)": [
        "generating synthetic audio, image, video or text content",
    ],
    "Art. 50(2)/(4)": [
        "generating synthetic audio, image, video or text content",
    ],
    "Art. 50(3)": [
        "an emotion recognition system or a biometric categorisation system",
    ],
    "Art. 53": [
        "draw up and keep up-to-date the technical documentation of the model",
    ],
    "Art. 55": [
        "general-purpose AI models with systemic risk shall",
        "perform model evaluation in accordance with standardised protocols",
    ],
}


@lru_cache(maxsize=1)
def _law_text() -> str:
    """The official text, with non-breaking spaces normalised to plain spaces.

    The substitution is 1:1, so character offsets still match the source file.
    """
    path = config.DATA_DIR / "eu_ai_act.txt"
    try:
        return path.read_text(encoding="utf-8").replace("\xa0", " ")
    except OSError:
        return ""


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


@lru_cache(maxsize=256)
def get_source(ref: str) -> dict | None:
    """Return {ref, quote, location, url} for a provision, or None if not found."""
    text = _law_text()
    if not text:
        return None
    low = text.lower()
    for anchor in ANCHORS.get(ref, []):
        i = low.find(anchor.lower())
        if i == -1:
            continue
        # Expand to a readable window: back to the previous sentence break
        # (only if it is close, so we don't drag in the preceding provision),
        # forward to the next one.
        start = i
        window = max(0, i - 120)
        cut = text.rfind(". ", window, i)
        if cut != -1:
            start = cut + 2
        elif window < i:
            # no sentence break nearby — keep a little lead-in if it is a heading
            lead = text.rfind("\n", window, i)
            start = lead + 1 if lead != -1 else i
        end = min(len(text), i + len(anchor) + 220)
        stop = text.find(". ", i + len(anchor), end)
        if stop != -1:
            end = stop + 1
        quote = _clean(text[start:end])
        return {
            "ref": ref,
            "quote": quote,
            "location": f"official text, character offset {i:,}",
            "url": EURLEX_URL,
        }
    return None


def sources_for(refs: list[str]) -> list[dict]:
    out = []
    for r in refs:
        s = get_source(r)
        if s:
            out.append(s)
    return out
