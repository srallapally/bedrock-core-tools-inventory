# tests/test_retry.py
from unittest.mock import MagicMock, call

import pytest
from botocore.exceptions import ClientError

from retry import _THROTTLE_CODES, with_retry


def _throttle(code="Throttling"):
    return ClientError(
        {"Error": {"Code": code, "Message": "Rate exceeded"}},
        "ListRoles",
    )


def _access_denied():
    return ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Denied"}},
        "ListRoles",
    )


def test_success_on_first_try():
    fn = MagicMock(return_value="ok")
    assert with_retry(fn, max_attempts=3) == "ok"
    fn.assert_called_once()


def test_retries_on_throttle_then_succeeds(monkeypatch):
    monkeypatch.setattr("retry.time.sleep", MagicMock())
    monkeypatch.setattr("retry.random.uniform", lambda a, b: 0)
    fn = MagicMock(side_effect=[_throttle(), _throttle(), "ok"])
    assert with_retry(fn, max_attempts=5) == "ok"
    assert fn.call_count == 3


def test_no_retry_on_non_throttle_error(monkeypatch):
    sleep = MagicMock()
    monkeypatch.setattr("retry.time.sleep", sleep)
    fn = MagicMock(side_effect=_access_denied())
    with pytest.raises(ClientError) as exc_info:
        with_retry(fn, max_attempts=3)
    assert exc_info.value.response["Error"]["Code"] == "AccessDenied"
    fn.assert_called_once()
    sleep.assert_not_called()


def test_max_attempts_exhausted(monkeypatch):
    monkeypatch.setattr("retry.time.sleep", MagicMock())
    monkeypatch.setattr("retry.random.uniform", lambda a, b: 0)
    fn = MagicMock(side_effect=_throttle())
    with pytest.raises(ClientError):
        with_retry(fn, max_attempts=3)
    assert fn.call_count == 3


def test_sleep_not_called_on_immediate_success(monkeypatch):
    sleep = MagicMock()
    monkeypatch.setattr("retry.time.sleep", sleep)
    with_retry(MagicMock(return_value="ok"), max_attempts=3)
    sleep.assert_not_called()


def test_sleep_called_between_retries(monkeypatch):
    sleep = MagicMock()
    monkeypatch.setattr("retry.time.sleep", sleep)
    monkeypatch.setattr("retry.random.uniform", lambda a, b: b)
    fn = MagicMock(side_effect=[_throttle(), _throttle(), "ok"])
    with_retry(fn, max_attempts=5, base_delay=1.0)
    # attempt 0: uniform(0, 1.0 * 2^0) → b = 1.0
    # attempt 1: uniform(0, 1.0 * 2^1) → b = 2.0
    assert sleep.call_count == 2
    assert sleep.call_args_list[0] == call(1.0)
    assert sleep.call_args_list[1] == call(2.0)


def test_jitter_upper_bound_scales_with_attempt(monkeypatch):
    uniform = MagicMock(return_value=0)
    monkeypatch.setattr("retry.time.sleep", MagicMock())
    monkeypatch.setattr("retry.random.uniform", uniform)
    fn = MagicMock(side_effect=[_throttle(), _throttle(), "ok"])
    with_retry(fn, max_attempts=5, base_delay=2.0)
    # attempt 0: uniform(0, 2.0 * 2^0) = uniform(0, 2.0)
    # attempt 1: uniform(0, 2.0 * 2^1) = uniform(0, 4.0)
    assert uniform.call_args_list[0] == call(0, 2.0)
    assert uniform.call_args_list[1] == call(0, 4.0)


def test_all_throttle_codes_are_retried(monkeypatch):
    monkeypatch.setattr("retry.time.sleep", MagicMock())
    monkeypatch.setattr("retry.random.uniform", lambda a, b: 0)
    for code in _THROTTLE_CODES:
        fn = MagicMock(side_effect=[_throttle(code), "ok"])
        assert with_retry(fn, max_attempts=3) == "ok"
