"""
Generic retry logic (§10.5).

Bounded-retry executor for external calls. Handles transient failures
(timeouts, connection errors, 500/502/503/504).

429 is NOT treated as a generic retryable error — it's handled separately
by the rate limiter before this logic runs.
"""

import asyncio
import logging
import random
import time
from typing import Any, Callable, List, Optional, Set, TypeVar

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

# HTTP status codes classified as transient / retryable
RETRYABLE_STATUS_CODES: Set[int] = {500, 502, 503, 504}


class RetryExhaustedError(Exception):
    """Raised when all retry attempts have been exhausted."""

    def __init__(self, operation: str, attempts: int, last_error: Exception):
        self.operation = operation
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(
            f"Operation '{operation}' failed after {attempts} attempts. "
            f"Last error: {last_error}"
        )


def is_retryable_exception(exc: Exception) -> bool:
    """
    Classify whether an exception is transient and retryable.

    Retryable: timeouts, connection errors, 500/502/503/504.
    Not retryable: 429 (handled by rate limiter), 4xx client errors, etc.
    """
    # Connection-level errors
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return True

    # Read/write timeouts
    if isinstance(exc, (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout)):
        return True

    # Generic timeout
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return True

    # Connection reset / broken pipe
    if isinstance(exc, (ConnectionError, ConnectionResetError, BrokenPipeError)):
        return True

    return False


def is_retryable_status(status_code: int) -> bool:
    """Check if an HTTP status code is retryable."""
    return status_code in RETRYABLE_STATUS_CODES


class HttpResponseError(Exception):
    """Raised for non-retryable HTTP errors."""

    def __init__(self, status_code: int, message: str = ""):
        self.status_code = status_code
        self.message = message
        super().__init__(f"HTTP {status_code}: {message}")


async def retry_call(
    fn: Callable,
    *args,
    max_retries: Optional[int] = None,
    delays: Optional[List[float]] = None,
    jitter: Optional[float] = None,
    op_label: str = "external_call",
    **kwargs,
) -> Any:
    """
    Execute an async function with bounded retries and configurable delays.

    Args:
        fn: Async callable to execute.
        max_retries: Max number of retry attempts (default from config).
        delays: List of delay values in seconds for each retry (default from config).
        jitter: Random jitter factor (0-1) added to each delay (default from config).
        op_label: Label for logging purposes.

    Returns:
        The result of the callable.

    Raises:
        RetryExhaustedError: If all retries are exhausted.
        HttpResponseError: For non-retryable HTTP errors.
    """
    settings = get_settings()

    if max_retries is None:
        max_retries = settings.EXTERNAL_CALL_MAX_RETRIES
    if delays is None:
        delays = settings.retry_delays
    if jitter is None:
        jitter = settings.EXTERNAL_CALL_JITTER

    last_error: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        try:
            result = await fn(*args, **kwargs)
            return result
        except Exception as exc:
            last_error = exc

            if attempt >= max_retries:
                break

            if not is_retryable_exception(exc):
                # Not retryable — raise immediately
                raise

            # Calculate delay with jitter
            delay_index = min(attempt, len(delays) - 1)
            base_delay = delays[delay_index] if delays else 1.0
            actual_delay = base_delay + random.uniform(0, jitter * base_delay)

            logger.warning(
                f"[{op_label}] Attempt {attempt + 1}/{max_retries + 1} failed: {exc}. "
                f"Retrying in {actual_delay:.2f}s..."
            )
            await asyncio.sleep(actual_delay)

    raise RetryExhaustedError(op_label, max_retries + 1, last_error)


def retry_call_sync(
    fn: Callable,
    *args,
    max_retries: Optional[int] = None,
    delays: Optional[List[float]] = None,
    jitter: Optional[float] = None,
    op_label: str = "external_call",
    **kwargs,
) -> Any:
    """Synchronous version of retry_call."""
    settings = get_settings()

    if max_retries is None:
        max_retries = settings.EXTERNAL_CALL_MAX_RETRIES
    if delays is None:
        delays = settings.retry_delays
    if jitter is None:
        jitter = settings.EXTERNAL_CALL_JITTER

    last_error: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        try:
            result = fn(*args, **kwargs)
            return result
        except Exception as exc:
            last_error = exc

            if attempt >= max_retries:
                break

            if not is_retryable_exception(exc):
                raise

            delay_index = min(attempt, len(delays) - 1)
            base_delay = delays[delay_index] if delays else 1.0
            actual_delay = base_delay + random.uniform(0, jitter * base_delay)

            logger.warning(
                f"[{op_label}] Attempt {attempt + 1}/{max_retries + 1} failed: {exc}. "
                f"Retrying in {actual_delay:.2f}s..."
            )
            time.sleep(actual_delay)

    raise RetryExhaustedError(op_label, max_retries + 1, last_error)
