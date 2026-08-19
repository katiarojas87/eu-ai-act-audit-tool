"""Tamper-evidence for Assessment objects (integrity.py).

/chat and /report take an Assessment back from the client with no server-side
session behind it — these tests are what stop a devtools-edited tier or
obligation list from reaching a client's chat answer or PDF report.
"""
from __future__ import annotations

import pytest

import integrity
from rules import classify
from schema import Facts


@pytest.fixture
def assessment():
    return classify(Facts(is_ai_system=True, high_risk_domains=["employment"],
                          placed_on_eu_market=True, developed_or_commissioned=True,
                          supplied_under_own_name=True), "CV Screener")


def test_a_freshly_signed_assessment_verifies(assessment):
    assessment.sig = integrity.sign(assessment)
    assert integrity.verify(assessment)


def test_an_unsigned_assessment_does_not_verify(assessment):
    assert assessment.sig == ""
    assert not integrity.verify(assessment)


def test_editing_a_signed_field_breaks_verification(assessment):
    assessment.sig = integrity.sign(assessment)
    assessment.tier = "MINIMAL"          # simulates a devtools-edited payload
    assert not integrity.verify(assessment)


def test_editing_an_obligation_breaks_verification(assessment):
    assessment.sig = integrity.sign(assessment)
    if assessment.obligations:
        assessment.obligations[0].status = "likely_in_place"
        assert not integrity.verify(assessment)


def test_a_signature_from_a_different_key_does_not_verify(assessment, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "key-one")
    assessment.sig = integrity.sign(assessment)
    monkeypatch.setenv("APP_PASSWORD", "key-two")
    assert not integrity.verify(assessment)


def test_signing_is_deterministic_for_the_same_content(assessment):
    assert integrity.sign(assessment) == integrity.sign(assessment)
