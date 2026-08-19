"""Tests for secret normalisation (secrets_env.py).

A trailing newline in ANTHROPIC_API_KEY produced an illegal HTTP header, which
the Anthropic SDK reported as `APIConnectionError: Connection error` — a message
that points at the network rather than at the secret. These lock in the fix.
"""
import logging

from secrets_env import normalise_env


def test_trailing_newline_is_stripped(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test123\n")
    assert normalise_env() == ["ANTHROPIC_API_KEY"]
    import os
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-test123"


def test_surrounding_whitespace_of_every_kind(monkeypatch):
    import os
    for raw in ("k\n", "k\r\n", " k ", "\tk\t", "k\n\n"):
        monkeypatch.setenv("APP_PASSWORD", raw)
        normalise_env()
        assert os.environ["APP_PASSWORD"] == "k", f"failed for {raw!r}"


def test_clean_values_are_left_alone(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-clean")
    monkeypatch.setenv("APP_PASSWORD", "EUAIACT")
    assert normalise_env() == []


def test_absent_variables_are_not_invented(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    import os
    assert normalise_env() == []
    assert "ANTHROPIC_API_KEY" not in os.environ


def test_the_warning_never_contains_the_secret(monkeypatch, caplog):
    """A log line that leaks the key would be worse than the bug it reports."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-supersecret-value\n")
    with caplog.at_level(logging.WARNING):
        normalise_env()
    assert caplog.text, "expected a warning"
    assert "supersecret" not in caplog.text
    assert "sk-ant" not in caplog.text
