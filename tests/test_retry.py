"""Regression tests for the shared adapter retry helpers.

Covers the behavior the per-adapter copies used to own: Sleeper-style 429
Retry-After handling, 5xx retries, connection-error retries, and named
function-level backoff with jitter. All network access is mocked and all
sleeps are monkeypatched — these tests never wait or hit the network.
"""
from unittest.mock import Mock

import pytest
import requests

from ffanalytics.adapters import _retry
from ffanalytics.adapters import sleeper


def _ok_response(payload):
    response = Mock()
    response.status_code = 200
    response.headers = {}
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def _rate_limited_response(retry_after="0"):
    response = Mock()
    response.status_code = 429
    response.headers = {"Retry-After": retry_after}
    response.raise_for_status = Mock()
    return response


def test_get_with_retry_honors_retry_after_header(monkeypatch):
    sleeps = []
    monkeypatch.setattr(_retry.time, "sleep", sleeps.append)
    http = Mock()
    http.get.side_effect = [
        _rate_limited_response("0"),
        _ok_response({"ok": True}),
    ]

    result = _retry.get_with_retry(http, "https://example.test", timeout=5)

    assert result.json() == {"ok": True}
    assert http.get.call_count == 2
    assert sleeps == [0.0]


def test_get_with_retry_retries_server_errors_then_returns(monkeypatch):
    sleeps = []
    monkeypatch.setattr(_retry.time, "sleep", sleeps.append)
    http = Mock()
    server_error = Mock()
    server_error.status_code = 500
    server_error.headers = {}
    server_error.raise_for_status = Mock()
    http.get.side_effect = [server_error, server_error, _ok_response({"ok": True})]

    result = _retry.get_with_retry(http, "https://example.test", max_retries=3)

    assert result.json() == {"ok": True}
    assert http.get.call_count == 3
    assert sleeps == [1.0, 2.0]
    server_error.raise_for_status.assert_not_called()


def test_get_with_retry_reraises_connection_errors_after_retries(monkeypatch):
    sleeps = []
    monkeypatch.setattr(_retry.time, "sleep", sleeps.append)
    http = Mock()
    http.get.side_effect = requests.ConnectionError("down")

    with pytest.raises(requests.ConnectionError):
        _retry.get_with_retry(http, "https://example.test", max_retries=2)

    assert http.get.call_count == 2
    assert sleeps == [1.0]


def test_call_with_retry_keeps_backoff_and_jitter(monkeypatch):
    sleeps = []
    monkeypatch.setattr(_retry.time, "sleep", sleeps.append)
    monkeypatch.setattr(_retry.random, "uniform", lambda _a, _b: 0.25)
    calls = {"count": 0}

    def flaky():
        calls["count"] += 1
        if calls["count"] < 2:
            raise ValueError("boom")
        return "ok"

    assert _retry.call_with_retry(flaky, name="sleeper", max_retries=3) == "ok"
    assert calls["count"] == 2
    assert sleeps == [1.75]


def test_call_with_retry_raises_after_final_attempt(monkeypatch):
    sleeps = []
    monkeypatch.setattr(_retry.time, "sleep", sleeps.append)
    monkeypatch.setattr(_retry.random, "uniform", lambda _a, _b: 0.0)

    with pytest.raises(ValueError, match="boom"):
        _retry.call_with_retry(
            lambda: (_ for _ in ()).throw(ValueError("boom")),
            max_retries=2,
        )

    assert sleeps == [1.5]


def test_sleeper_keeps_rate_limit_behavior_through_shared_helper(monkeypatch):
    sleeps = []
    monkeypatch.setattr(_retry.time, "sleep", sleeps.append)
    session = Mock()
    session.get.side_effect = [
        _rate_limited_response("0"),
        _ok_response({"season": "2026"}),
    ]

    assert sleeper.get_nfl_state(session=session) == {"season": "2026"}
    assert session.get.call_count == 2
    assert sleeps == [0.0]
