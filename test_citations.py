"""Tests for the citation resolver (citations.py).

These lock in the two guarantees the client report depends on: every cited
provision resolves to *binding* text, and a provision that does not exist gets
no quote at all.
"""
import pytest

from citations import ANCHORS, _operative_start, get_source, ref_is_valid
from rules import ANNEX_III_MAP, PROHIBITED_RULES

ALL_REFS = sorted(ANCHORS)


@pytest.mark.parametrize("ref", ALL_REFS)
def test_every_curated_ref_resolves(ref):
    assert get_source(ref) is not None, f"{ref} has no verbatim source"


@pytest.mark.parametrize("ref", ALL_REFS)
def test_every_curated_ref_resolves_to_binding_text(ref):
    """Recitals are interpretive aids — never quote one as the provision."""
    s = get_source(ref)
    assert s["kind"] == "operative", (
        f"{ref} resolved to a recital: {s['quote'][:90]!r}")


@pytest.mark.parametrize("ref", ALL_REFS)
def test_quotes_come_from_the_enacting_terms(ref):
    offset = int(get_source(ref)["location"].split()[-1].replace(",", ""))
    assert offset >= _operative_start(), f"{ref} points into the preamble"


@pytest.mark.parametrize("bogus", [
    "Art. 5(1)(i)",     # Article 5(1) stops at (h)
    "Art. 5(1)(z)",
    "Annex III(9)",     # Annex III has 8 points
    "Annex III(5)(z)",
    "Art. 50(9)",       # Article 50 has 7 paragraphs
    "Art. 200",         # the Regulation has 113 articles
    "Art. 0",
    "not a reference",
])
def test_nonexistent_provisions_get_no_quote(bogus):
    assert not ref_is_valid(bogus)
    assert get_source(bogus) is None, f"fabricated a source for {bogus}"


@pytest.mark.parametrize("ref", [
    "Art. 3(1)", "Art. 5(1)(a)-(b)", "Art. 6(3)", "Art. 6(7)",
    "Annex III(5)(b)", "Annex III(8)", "Art. 53", "Art. 26(1)",
])
def test_real_provisions_are_accepted(ref):
    assert ref_is_valid(ref)


def test_quotes_are_verbatim_substrings_of_the_law():
    """Whitespace-normalised, every quote must appear in the source text."""
    import re

    from citations import _law_text
    haystack = re.sub(r"\s+", " ", _law_text())
    for ref in ALL_REFS:
        quote = get_source(ref)["quote"]
        assert quote in haystack, f"{ref} quote is not verbatim: {quote[:80]!r}"


def test_annex_i_is_not_just_article_6_again():
    """Annex I must quote Annex I, not the Article 6(1) sentence citing it."""
    assert get_source("Annex I")["quote"] != get_source("Art. 6(1)")["quote"]


def test_every_provision_the_engine_can_cite_has_a_source():
    """No rule may cite something the report cannot show the client."""
    refs = {p.ref for p in PROHIBITED_RULES}
    refs |= {pt for pt, _ in ANNEX_III_MAP.values()}
    refs |= {"Art. 3(1)", "Art. 5", "Art. 6", "Art. 6(1)", "Art. 6(2)", "Annex I",
             "Art. 50", "Art. 50(1)", "Art. 50(3)", "Art. 53", "Art. 55",
             # Article 5 exceptions and safeguards
             "Art. 5(1)(f)", "Art. 5(1)(h)", "Art. 5(2)", "Art. 5(3)", "Annex II",
             # role and obligation provisions
             "Art. 3(3)", "Art. 3(4)", "Art. 4", "Art. 25(1)", "Art. 26", "Art. 27",
             "Art. 17", "Art. 43", "Art. 47", "Art. 48", "Art. 49"}
    missing = sorted(r for r in refs if get_source(r) is None)
    assert not missing, f"cited but unsourceable: {missing}"


def test_quotes_are_substantial_enough_to_read():
    for ref in ALL_REFS:
        assert len(get_source(ref)["quote"]) >= 40, f"{ref} quote is too short"
