"""Tests for resilience modules: rate limiter, retry, DLQ."""

import pytest
from unittest.mock import MagicMock
from app.resilience.rate_limiter import detect_rate_limit
from app.resilience.retry import is_retryable_exception, is_retryable_status, RetryExhaustedError
from app.resilience.dlq import scrub_payload, cap_payload
import httpx


class TestRateLimiter:
    def test_non_429_returns_none(self):
        resp = MagicMock()
        resp.status_code = 200
        assert detect_rate_limit(resp) is None

    def test_429_with_retry_after(self):
        resp = MagicMock()
        resp.status_code = 429
        resp.headers = {"Retry-After": "5"}
        result = detect_rate_limit(resp)
        assert result == 5.0

    def test_429_without_retry_after_uses_fallback(self):
        resp = MagicMock()
        resp.status_code = 429
        resp.headers = {}
        result = detect_rate_limit(resp)
        assert result == 10.0  # Default fallback


class TestRetry:
    def test_retryable_status_codes(self):
        assert is_retryable_status(500) is True
        assert is_retryable_status(502) is True
        assert is_retryable_status(503) is True
        assert is_retryable_status(504) is True
        assert is_retryable_status(400) is False
        assert is_retryable_status(404) is False
        assert is_retryable_status(429) is False

    def test_retryable_exceptions(self):
        assert is_retryable_exception(httpx.ConnectError("fail")) is True
        assert is_retryable_exception(httpx.ReadTimeout("timeout")) is True
        assert is_retryable_exception(TimeoutError()) is True
        assert is_retryable_exception(ConnectionResetError()) is True
        assert is_retryable_exception(ValueError("bad")) is False

    def test_retry_exhausted_error(self):
        err = RetryExhaustedError("test_op", 3, ValueError("final"))
        assert "test_op" in str(err)
        assert err.attempts == 3


class TestDLQ:
    def test_scrub_payload_redacts_secrets(self):
        payload = {"access_token": "secret123", "url": "https://api.com"}
        scrubbed = scrub_payload(payload)
        assert scrubbed["access_token"] == "[REDACTED]"
        assert scrubbed["url"] == "https://api.com"

    def test_scrub_payload_nested(self):
        payload = {"config": {"client_secret": "s3cret", "host": "localhost"}}
        scrubbed = scrub_payload(payload)
        assert scrubbed["config"]["client_secret"] == "[REDACTED]"
        assert scrubbed["config"]["host"] == "localhost"

    def test_scrub_payload_none(self):
        assert scrub_payload(None) is None

    def test_cap_payload_small(self):
        payload = {"key": "value"}
        assert cap_payload(payload, max_bytes=10000) == payload

    def test_cap_payload_large(self):
        payload = {"data": "x" * 20000}
        result = cap_payload(payload, max_bytes=100)
        assert result["_truncated"] is True
