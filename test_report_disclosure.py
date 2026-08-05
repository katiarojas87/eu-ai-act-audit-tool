"""The client report must disclose its own uncertainty.

A compliance product that keeps `human_review_required` and its unmodelled areas
in JSON, while the PDF reads like a finding, is misleading in the way that
matters most — the PDF is what reaches the decision-maker. These tests pin the
disclosure to the rendered document, not to the data model.
"""
from __future__ import annotations

import pytest

from rules import classify
from schema import Facts

# PDF rendering is the only part of this project that needs third-party
# packages. Skip rather than fail when they are absent: the rest of the suite is
# pure Python and must stay runnable under any interpreter, so a missing
# optional dependency cannot be allowed to abort collection for everything else.
pytest.importorskip("reportlab", reason="PDF rendering deps not installed")
pypdf = pytest.importorskip("pypdf", reason="PDF text extraction not installed")

from report_v2 import generate_report  # noqa: E402  (must follow the skips)


def _text(assessments, client="Disclosure Test") -> str:
    path = generate_report(client, assessments)
    try:
        reader = pypdf.PdfReader(str(path))
        return "".join(p.extract_text() for p in reader.pages)
    finally:
        path.unlink(missing_ok=True)


@pytest.fixture(scope="module")
def high_risk_text() -> str:
    a = classify(Facts(is_ai_system=True, high_risk_domains=["employment"],
                       placed_on_eu_market=True, developed_or_commissioned=True,
                       supplied_under_own_name=True), "CV Screener")
    assert a.human_review_required
    return _text([a])


def test_methodology_is_stated_in_the_report(high_risk_text):
    assert "How this assessment was produced" in high_risk_text
    # The central design claim must reach the reader, not just the README.
    assert "deterministic" in high_risk_text


def test_unmodelled_areas_are_disclosed(high_risk_text):
    assert "What this assessment does not cover" in high_risk_text
    assert "Art. 99" in high_risk_text          # fines are not modelled
    assert "conformity assessment" in high_risk_text


def test_human_review_banner_is_visible_and_gives_a_reason(high_risk_text):
    assert "HUMAN REVIEW REQUIRED" in high_risk_text
    assert "heaviest duties" in high_risk_text


def test_not_legal_advice_notice_survives(high_risk_text):
    assert "NOT LEGAL ADVICE" in high_risk_text


def test_banner_is_absent_when_no_review_is_required():
    """The warning must mean something — it cannot appear on every report."""
    a = classify(Facts(is_ai_system=True, placed_on_eu_market=True,
                       safety_component_regulated_product=False,
                       high_risk_domains=[], uses_under_own_authority=True,
                       subliminal_or_manipulative=False, exploits_vulnerabilities=False,
                       social_scoring=False, interacts_with_people=False,
                       generates_synthetic_content=False,
                       military_defence_national_security=False,
                       sole_purpose_scientific_research=False,
                       prerelease_research_testing=False,
                       personal_non_professional_use=False), "Spam Filter")
    if a.human_review_required:          # engine decides; only assert the pairing
        pytest.skip("engine still requires review for this fact set")
    assert "HUMAN REVIEW REQUIRED" not in _text([a])
