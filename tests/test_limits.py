"""Tests for the abuse and spend controls (limits.py).

These are what stand between a leaked shared password and an unbounded
Anthropic invoice, so they get tested like the rule engine. No API key needed.
"""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def lim(monkeypatch):
    """A fresh limits module with small, fast thresholds."""
    monkeypatch.setenv("RATE_LIMIT_PER_HOUR", "3")
    monkeypatch.setenv("DAILY_CLASSIFY_CAP", "2")
    monkeypatch.setenv("MAX_AUTH_FAILURES", "2")
    monkeypatch.setenv("AUTH_LOCKOUT_SECONDS", "900")
    import limits
    return importlib.reload(limits)


def test_rate_limit_blocks_after_the_allowance(lim):
    for _ in range(3):
        lim.check_rate("1.2.3.4")
    with pytest.raises(lim.LimitExceeded) as e:
        lim.check_rate("1.2.3.4")
    assert e.value.status == 429
    assert e.value.retry_after and e.value.retry_after > 0


def test_rate_limit_is_per_client(lim):
    for _ in range(3):
        lim.check_rate("1.1.1.1")
    lim.check_rate("2.2.2.2")          # a different caller is unaffected


def test_daily_cap_bounds_total_spend(lim):
    lim.check_daily_cap()
    lim.check_daily_cap()
    with pytest.raises(lim.LimitExceeded):
        lim.check_daily_cap()


def test_failed_work_refunds_its_slot(lim):
    """An upstream failure spent nothing, so it must not consume the budget."""
    lim.check_daily_cap()
    lim.refund_daily()
    lim.check_daily_cap()
    lim.check_daily_cap()
    with pytest.raises(lim.LimitExceeded):
        lim.check_daily_cap()


def test_refund_never_goes_negative(lim):
    for _ in range(5):
        lim.refund_daily()
    assert lim.usage()["classifications"] == 0


def test_lockout_after_repeated_password_failures(lim):
    lim.check_not_locked_out("9.9.9.9")
    lim.record_auth_failure("9.9.9.9")
    lim.record_auth_failure("9.9.9.9")
    with pytest.raises(lim.LimitExceeded):
        lim.check_not_locked_out("9.9.9.9")


def test_a_correct_password_clears_the_failure_count(lim):
    lim.record_auth_failure("8.8.8.8")
    lim.clear_auth_failures("8.8.8.8")
    lim.check_not_locked_out("8.8.8.8")   # must not raise


def test_client_id_prefers_the_real_caller_from_the_proxy_header(lim):
    assert lim.client_id("203.0.113.7, 10.0.0.1", "10.0.0.1") == "203.0.113.7"
    assert lim.client_id(None, "10.0.0.1") == "10.0.0.1"


# --- endpoint behaviour --------------------------------------------------------
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "correct-horse")
    monkeypatch.setenv("RATE_LIMIT_PER_HOUR", "100")
    monkeypatch.setenv("DAILY_CLASSIFY_CAP", "100")
    monkeypatch.setenv("MAX_AUTH_FAILURES", "3")
    import limits
    importlib.reload(limits)
    import api
    importlib.reload(api)
    return TestClient(api.app)


def _body(**kw):
    base = {"name": "X", "description": "A system that does something."}
    base.update(kw)
    return base


def test_wrong_password_is_rejected(client):
    r = client.post("/classify", json=_body(), headers={"x-app-password": "nope"})
    assert r.status_code == 401


def test_missing_password_is_rejected(client):
    assert client.post("/classify", json=_body()).status_code == 401


def test_brute_force_is_locked_out(client):
    h = {"x-app-password": "nope", "x-forwarded-for": "5.5.5.5"}
    codes = [client.post("/classify", json=_body(), headers=h).status_code
             for _ in range(5)]
    assert 429 in codes, f"never locked out: {codes}"


def test_oversized_description_is_refused_before_it_is_billed(client):
    r = client.post("/classify",
                    json=_body(description="x" * 9000),
                    headers={"x-app-password": "correct-horse"})
    assert r.status_code == 422


def test_empty_description_is_refused(client):
    r = client.post("/classify", json=_body(description=""),
                    headers={"x-app-password": "correct-horse"})
    assert r.status_code == 422


def test_health_needs_no_password_and_stays_minimal(client):
    """/health is public (uptime checks can't carry the shared password), so it
    must not leak business-volume metrics like today's classification count."""
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "daily_cap" not in body and "classifications" not in body


def test_usage_reports_the_detail_health_no_longer_does(client):
    r = client.get("/usage", headers={"x-app-password": "correct-horse"})
    assert r.status_code == 200
    body = r.json()
    assert "daily_cap" in body and "classifications" in body


def test_usage_requires_the_password(client):
    assert client.get("/usage").status_code == 401


def test_report_endpoint_rejects_an_absurd_number_of_systems(client):
    r = client.post("/report", json={"client_name": "X", "systems": [{}] * 60},
                    headers={"x-app-password": "correct-horse"})
    assert r.status_code == 422
