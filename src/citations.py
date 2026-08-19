"""Verbatim source citations from the EU AI Act text.

Deterministic (no LLM, no vector search): each provision reference maps to one
or more anchor phrases; we locate the match in data/eu_ai_act.txt and return the
surrounding verbatim sentence, its character offset, and a link to the official
text on EUR-Lex. If an anchor is not found the provision simply carries no quote
— we never fabricate one.

Two guarantees the report depends on:

1. **Binding text first.** The file holds the recitals (non-binding, interpretive)
   before the enacting terms. A naive first-match lands in the preamble, so every
   lookup searches the operative region first and only falls back to a recital
   when the operative text yields nothing — and then says so (`kind="recital"`).
2. **No citations to provisions that do not exist.** A reference is structurally
   validated against the real numbering of the Regulation before we go looking,
   so a malformed ref (e.g. "Art. 5(1)(i)" — Article 5(1) stops at (h)) returns
   None instead of the nearest plausible-looking sentence.
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
        "(c) the placing on the market, the putting into service or the use of AI systems "
        "for the evaluation or classification of natural persons",
        "social behaviour or known, inferred or predicted personal or personality characteristics",
    ],
    "Art. 5(1)(d)": [
        "(d) the placing on the market, the putting into service for this specific purpose, "
        "or the use of an AI system for making risk assessments of natural persons",
        "committing a criminal offence, based solely on the profiling",
        "profiling of a natural person or on assessing their personality traits",
    ],
    "Art. 5(1)(e)": [
        "(e) the placing on the market, the putting into service for this specific purpose, "
        "or the use of AI systems that create or expand facial recognition databases",
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
        "ANNEX I List of Union harmonisation legislation",
        "intended to be used as a safety component of a product",
    ],
    "Annex II": [
        "ANNEX II List of criminal offences referred to in Article 5(1)",
        "List of criminal offences referred to in Article 5(1)",
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
        "(a) AI systems intended to be used by public authorities or on behalf of public "
        "authorities to evaluate the eligibility of natural persons",
        "eligibility of natural persons for essential public assistance",
        "essential public assistance benefits and services",
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


@lru_cache(maxsize=1)
def _norm() -> tuple[str, list[int]]:
    """The law text with every whitespace run collapsed to one space.

    Returns (normalised_text, offsets) where offsets[i] is the index of
    normalised_text[i] in the original file, so a match can still be reported at
    its true position.

    All matching happens on this form. The official text lays provisions out
    differently between editions — the consolidated version puts headings on
    their own line ("Article 3\\n\\nDefinitions") where the original runs them
    together — and an anchor should not care. Without this, switching to the
    consolidated text silently breaks every heading-based citation.
    """
    raw = _law_text()
    out: list[str] = []
    offsets: list[int] = []
    in_space = False
    for i, ch in enumerate(raw):
        if ch.isspace():
            if not in_space:
                out.append(" ")
                offsets.append(i)
                in_space = True
        else:
            out.append(ch)
            offsets.append(i)
            in_space = False
    return "".join(out), offsets


@lru_cache(maxsize=1)
def _norm_lower() -> str:
    return _norm()[0].lower()


def _to_source_offset(i: int) -> int:
    """Map a normalised index back to its position in the original file."""
    _, offsets = _norm()
    if not offsets:
        return i
    return offsets[min(i, len(offsets) - 1)]


@lru_cache(maxsize=1)
def _operative_start() -> int:
    """Offset where the enacting terms begin (everything before it is recitals).

    Article 1 is the first operative provision; the annexes sit after the last
    article, so [operative_start, end) covers all binding text.
    """
    text, _ = _norm()
    for marker in ("Article 1 Subject matter", "Article 1 Subject-matter",
                   "CHAPTER I GENERAL PROVISIONS Article 1"):
        i = text.find(marker)
        if i != -1:
            return i
    # A consolidated edition drops the recitals entirely, so there is nothing to
    # skip past. Treat everything as operative rather than hide text.
    return 0


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


# --- reference validity ------------------------------------------------------
# The real numbering of Regulation (EU) 2024/1689, so we never cite a provision
# that does not exist. Verified against data/eu_ai_act.txt.
# Art. 5(1)(a)–(h), plus (ba) and (bb) inserted by the Digital Omnibus
# (Regulation (EU) 2026/1744) — intimate imagery and child sexual abuse material.
_ART5_LETTERS = set("abcdefgh") | {"ba", "bb"}
_ART_PARAGRAPHS = {                       # article -> highest paragraph number
    3: 68, 5: 8, 6: 8, 26: 12, 27: 5, 50: 7, 51: 3, 53: 6, 55: 4,
}
_ANNEX_III_POINTS = {                     # Annex III point -> valid sub-letters
    1: set("ab"), 2: set("ab"), 3: set("abcd"), 4: set("ab"),
    5: set("abcde"), 6: set("abcde"), 7: set("abcd"), 8: set("ab"),
}

_VALID_RE = re.compile(
    r"^(?:Art\.?\s*(?P<art>\d+)|Annex\s+(?P<annex>[IVX]+))"
    # Paragraphs may be inserted as "1a", "1b" by an amending act.
    r"(?:\((?P<p1>\d+[a-z]?)\))?"
    # Points likewise: "(a)", and inserted "(ba)", "(bb)".
    r"(?:\((?P<p2>[a-z]{1,2})\))?"
    r"(?:-\((?P<p3>[a-z]{1,2})\))?\s*$"
)


def ref_is_valid(ref: str) -> bool:
    """True if `ref` names a provision that actually exists in the Regulation."""
    ref = ref.strip()
    if ref in ANCHORS:            # curated refs are valid by construction
        return True
    m = _VALID_RE.match(ref)
    if not m:
        return False
    if m.group("annex"):
        annex, p1, p2 = m.group("annex"), m.group("p1"), m.group("p2")
        if annex != "III":
            return annex in {"I", "II", "IV", "V", "VI", "VII", "VIII",
                             "IX", "X", "XI", "XII", "XIII"} and not p1
        if p1 is None:
            return True
        pt = int(p1)
        if pt not in _ANNEX_III_POINTS:
            return False
        return p2 is None or p2 in _ANNEX_III_POINTS[pt]
    art = int(m.group("art"))
    if art < 1 or art > 113:      # the Regulation has 113 articles
        return False
    p1, p2 = m.group("p1"), m.group("p2")
    if p1 is None:
        return True
    # "1a"/"1b" are paragraphs inserted by an amending act; validate the number.
    base = int(re.match(r"\d+", p1).group())
    if base < 1 or base > _ART_PARAGRAPHS.get(art, 20):
        return False
    if p2 is None:
        return True
    if art == 5:                  # Article 5(1) prohibitions, incl. inserted (ba)/(bb)
        return base == 1 and p2 in _ART5_LETTERS
    return True


_ART3_RE = re.compile(r"Art\.?\s*3\((\d{1,2})\)")

# Where each operative section starts in the official text, so a reference can
# be resolved structurally instead of relying on a hand-written anchor.
SECTION_STARTS: dict[str, tuple[str, int]] = {
    "Art. 5": ("The following AI practices shall be prohibited", 14000),
    "Art. 6": ("Article 6 Classification rules for high-risk AI systems", 6000),
    "Art. 50": ("Article 50 Transparency obligations for providers and deployers", 9000),
    "Art. 53": ("Article 53 Obligations for providers of general-purpose AI models", 9000),
    "Art. 55": ("Article 55 Obligations of providers of general-purpose AI models with systemic risk", 9000),
    "Annex III": ("ANNEX III High-risk AI systems referred to in Article 6(2)", 7000),
}

_REF_RE = re.compile(
    r"^(?P<sec>Art\.?\s*\d+|Annex\s+III)"
    r"(?:\((?P<p1>[\dA-Za-z]+)\))?"
    r"(?:\((?P<p2>[A-Za-z]+)\))?\s*$"
)


def _section_bounds(sec: str) -> tuple[int, int] | None:
    text, _ = _norm()
    key = re.sub(r"Art\.?\s*", "Art. ", sec.strip())
    entry = SECTION_STARTS.get(key)
    if not entry:
        return None
    marker, span = entry
    # Search from the enacting terms so a phrase echoed in a recital cannot
    # anchor the section.
    i = text.find(marker, _operative_start())
    if i == -1:
        return None
    return i, min(len(text), i + span)


def _structured(ref: str) -> dict | None:
    """Resolve refs like Art. 5(1)(f), Art. 50(2), Annex III(5)(b) structurally."""
    m = _REF_RE.match(ref.strip())
    if not m:
        return None
    # Prefer the article-heading window: it ends at the next article, so a
    # paragraph search cannot run past the end of the provision. The curated
    # spans in SECTION_STARTS are a fallback only.
    bounds = _provision_window(m.group("sec")) or _section_bounds(m.group("sec"))
    if not bounds:
        return None
    text, _ = _norm()
    start, end = bounds

    # Build the markers to walk, in order. For Article 5 the prohibitions sit
    # directly under paragraph 1, so the letter is the only marker that matters.
    parts = [p for p in (m.group("p1"), m.group("p2")) if p]
    is_art5 = m.group("sec").replace(".", "").replace(" ", "").lower() == "art5"
    if is_art5 and len(parts) == 2:
        parts = parts[1:]

    pos = start
    for part in parts:
        # Digits are paragraph numbers ("2. ") at every article, including 5 —
        # the letter form is only for lettered points ("(f) ").
        if part.isdigit():
            # A paragraph marker may start a line, follow the previous sentence
            # inline ("… law enforcement. 2. The use of …"), or in the
            # consolidated edition stand alone as "2." — accept all three.
            pat = re.compile(rf"(?:^|\s|\.\s)\s*{part}\.\s")
        else:
            pat = re.compile(rf"(?:^|\s)\(\s*{re.escape(part)}\s*\)\s")
        hit = pat.search(text, pos, end)
        if not hit:
            return None
        pos = hit.end() - 1

    # Stop at the first sentence break that still yields a readable quote. A bare
    # article reference otherwise clips to just its heading ("Article 48 CE
    # marking 1."), which tells the client nothing.
    min_end = pos + 60
    stop = text.find(";", min_end)
    dot = text.find(". ", min_end)
    cands = [x for x in (stop, dot) if x > pos]
    quote_end = min(cands) if cands else min(len(text) - 1, pos + 550)
    quote = _clean(text[pos:quote_end + 1])
    if len(quote) < 25:
        return None
    return {
        "ref": ref,
        "quote": quote,
        "location": f"enacting terms, character offset {_to_source_offset(pos):,}",
        "url": EURLEX_URL,
        "kind": "operative",
    }


def _article_3_definition(ref: str) -> dict | None:
    """Resolve any Article 3 definition — Art. 3(1) … Art. 3(42) — generically."""
    m = _ART3_RE.fullmatch(ref.strip())
    if not m:
        return None
    text, _ = _norm()
    start = text.find("Article 3 Definitions")
    if start == -1:
        return None
    n = m.group(1)
    # definitions read: "(N) ‘term’ means …"
    pat = re.compile(rf"\({n}\)\s*[‘'][^’']{{2,80}}[’']\s*means")
    hit = pat.search(text, start, start + 40000)
    if not hit:
        return None
    i = hit.start()
    end = text.find(";", i)
    stop = text.find(". ", i)
    end = min(x for x in (end, stop, i + 600) if x > i)
    return {
        "ref": ref,
        "quote": _clean(text[i:end + 1]),
        "location": f"Article 3 definitions, character offset {_to_source_offset(i):,}",
        "url": EURLEX_URL,
        "kind": "operative",
    }


@lru_cache(maxsize=128)
def _provision_window(ref: str) -> tuple[int, int] | None:
    """The slice of the enacting terms that `ref` lives in.

    Anchoring inside the provision's own region stops a phrase that is echoed
    elsewhere (a cross-reference in another article, a neighbouring annex point)
    from being quoted as if it were the provision itself.
    """
    text, _ = _norm()
    op = _operative_start()
    m = _VALID_RE.match(ref.strip()) or _REF_RE.match(ref.strip())
    if not m:
        return None

    if (m.groupdict().get("annex") or "").strip() == "III" or ref.strip().startswith("Annex III"):
        start = text.find("ANNEX III High-risk AI systems referred to in Article 6(2)", op)
        if start == -1:
            start = text.find("ANNEX III", op)
        if start == -1:
            return None
        end = text.find("ANNEX IV", start)
        return start, (end if end != -1 else min(len(text), start + 20000))

    art = m.groupdict().get("art") or m.groupdict().get("sec")
    digits = re.sub(r"\D", "", art or "")
    if not digits:
        return None
    n = int(digits)
    # Headings read "Article 9 Risk management system". Require a capital after
    # the number so "Article 9" inside a cross-reference cannot match.
    head = re.compile(rf"(?:^|\s)Article {n}\s+[A-Z]")
    hit = head.search(text, op)
    if not hit:
        return None
    start = hit.start()
    nxt = re.compile(rf"(?:^|\s)Article {n + 1}\s+[A-Z]").search(text, start + 1)
    end = nxt.start() if nxt else min(len(text), start + 20000)
    return start, end


def _quote_around(ref: str, i: int, anchor: str, kind: str) -> dict:
    """Expand an anchor hit into a readable verbatim window."""
    text, _ = _norm()
    # Back to the previous sentence break (only if close, so we don't drag in
    # the preceding provision), forward to the next one.
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
    where = "enacting terms" if kind == "operative" else "recital (non-binding)"
    return {
        "ref": ref,
        "quote": _clean(text[start:end]),
        "location": f"{where}, character offset {_to_source_offset(i):,}",
        "url": EURLEX_URL,
        "kind": kind,
    }


@lru_cache(maxsize=256)
def get_source(ref: str) -> dict | None:
    """Return {ref, quote, location, url, kind} for a provision, else None.

    Resolution order: binding text (curated anchor, then structural walk), and
    only then a recital — flagged as such, never passed off as operative text.
    """
    if not _law_text() or not ref_is_valid(ref):
        return None
    generic = _article_3_definition(ref)
    if generic:
        return generic

    low = _norm_lower()
    op = _operative_start()
    anchors = ANCHORS.get(ref, [])

    # 1. curated anchor inside the provision's own region — the tightest match
    window = _provision_window(ref)
    if window:
        lo, hi = window
        for anchor in anchors:
            i = low.find(anchor.lower(), lo, hi)
            if i != -1:
                return _quote_around(ref, i, anchor, "operative")

    # 2. resolve the reference structurally (already operative-bounded)
    structured = _structured(ref)
    if structured:
        return structured

    # 3. curated anchor anywhere in the enacting terms
    for anchor in anchors:
        i = low.find(anchor.lower(), op)
        if i != -1:
            return _quote_around(ref, i, anchor, "operative")

    # 4. last resort: a recital, explicitly labelled as non-binding
    for anchor in anchors:
        i = low.find(anchor.lower(), 0, op)
        if i != -1:
            return _quote_around(ref, i, anchor, "recital")
    return None


def quote_containing(ref: str, phrase: str) -> dict | None:
    """Quote the clause inside `ref` that contains `phrase`.

    Some provisions carry several independent statements — Art. 113(c) sets two
    different application dates in two sub-points — and the whole provision is
    the wrong quote for any one of them. This pins the quote to the clause that
    actually says the thing being cited.
    """
    if not ref_is_valid(ref):
        return None
    window = _provision_window(ref)
    if not window:
        return None
    text, _ = _norm()
    lo, hi = window
    i = text.lower().find(phrase.lower(), lo, hi)
    if i == -1:
        return None
    # A clause runs between semicolons or sentence ends.
    start = max(text.rfind("; ", lo, i), text.rfind(". ", lo, i))
    start = start + 2 if start != -1 else i
    ends = [e for e in (text.find("; ", i), text.find(". ", i)) if e != -1]
    end = min(ends) if ends else min(hi, i + 300)
    return {
        "ref": ref,
        "quote": _clean(text[start:end + 1]),
        "location": f"enacting terms, character offset {_to_source_offset(start):,}",
        "url": EURLEX_URL,
        "kind": "operative",
    }


def sources_for(refs: list[str]) -> list[dict]:
    out = []
    for r in refs:
        s = get_source(r)
        if s:
            out.append(s)
    return out
