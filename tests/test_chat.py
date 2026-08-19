"""Guard rails for the /chat endpoint.

Same philosophy as test_limits.py's endpoint tests: exercise the password
gate, the request validation and the daily cap without ever reaching
chat.answer() — that call needs a real API key, so it is out of scope for a
suite that must run offline. What's tested here is everything that stands
between a leaked password and an unbounded per-turn bill.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from rules import classify
from schema import Facts


@pytest.fixture
def assessment_dict() -> dict:
    a = classify(Facts(is_ai_system=True, high_risk_domains=["employment"],
                       placed_on_eu_market=True, developed_or_commissioned=True,
                       supplied_under_own_name=True), "CV Screener")
    return a.model_dump()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "correct-horse")
    monkeypatch.setenv("RATE_LIMIT_PER_HOUR", "100")
    monkeypatch.setenv("DAILY_CHAT_CAP", "2")
    monkeypatch.setenv("MAX_AUTH_FAILURES", "3")
    import limits
    importlib.reload(limits)
    import api
    importlib.reload(api)
    return TestClient(api.app)


def _body(assessment_dict, **kw):
    base = {"assessment": assessment_dict,
            "messages": [{"role": "user", "content": "Why is this high-risk?"}]}
    base.update(kw)
    return base


def test_wrong_password_is_rejected(client, assessment_dict):
    r = client.post("/chat", json=_body(assessment_dict),
                    headers={"x-app-password": "nope"})
    assert r.status_code == 401


def test_missing_password_is_rejected(client, assessment_dict):
    assert client.post("/chat", json=_body(assessment_dict)).status_code == 401


def test_empty_messages_is_refused(client, assessment_dict):
    r = client.post("/chat", json=_body(assessment_dict, messages=[]),
                    headers={"x-app-password": "correct-horse"})
    assert r.status_code == 422


def test_last_message_must_be_from_the_user(client, assessment_dict):
    r = client.post("/chat", json=_body(
        assessment_dict,
        messages=[{"role": "user", "content": "hi"},
                  {"role": "assistant", "content": "hello"}]),
        headers={"x-app-password": "correct-horse"})
    assert r.status_code == 400


def test_oversized_message_is_refused(client, assessment_dict):
    r = client.post("/chat", json=_body(
        assessment_dict, messages=[{"role": "user", "content": "x" * 4001}]),
        headers={"x-app-password": "correct-horse"})
    assert r.status_code == 422


def test_too_many_messages_is_refused(client, assessment_dict):
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": "hi"}
              for i in range(41)]
    r = client.post("/chat", json=_body(assessment_dict, messages=history),
                    headers={"x-app-password": "correct-horse"})
    assert r.status_code == 422


def test_daily_chat_cap_is_independent_of_the_classify_cap(monkeypatch):
    """A chat-heavy day must not eat into the classification budget, or vice versa."""
    monkeypatch.setenv("DAILY_CLASSIFY_CAP", "1")
    monkeypatch.setenv("DAILY_CHAT_CAP", "1")
    import limits
    importlib.reload(limits)
    limits.check_daily_cap()
    limits.check_daily_chat_cap()   # must not raise — separate counters
    with pytest.raises(limits.LimitExceeded):
        limits.check_daily_cap()
    with pytest.raises(limits.LimitExceeded):
        limits.check_daily_chat_cap()


def test_chat_refund_never_goes_negative(monkeypatch):
    monkeypatch.setenv("DAILY_CHAT_CAP", "5")
    import limits
    importlib.reload(limits)
    for _ in range(3):
        limits.refund_daily_chat()
    assert limits.usage()["chat_messages"] == 0
