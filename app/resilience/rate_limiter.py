"""
Rate limit handler (§10.5).

Detects HTTP 429 responses, reads the Retry-After header (falling back to a
configured default), sleeps, and signals the caller to retry the same request.

This is checked BEFORE generic retry logic — a rate-limit response is NOT a
failure to count against retry budget, just a "wait and continue" signal.
"""

import asyncio
import logging
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    """Raised when a rate limit (429) is detected."""

    def __init__(self, retry_after: float, message: str = "Rate limited"):
        self.retry_after = retry_after
        self.message = message
        super().__init__(message)


def detect_rate_limit(response: httpx.Response) -> Optional[float]:
    """
    Check if a response is a 429 rate limit.

    Returns the Retry-After delay in seconds if rate-limited, else None.
    """
    if response.status_code != 429:
        return None

    settings = get_settings()

    # Try to read Retry-After header
    retry_after_header = response.headers.get("Retry-After") or response.headers.get("retry-after")

    if retry_after_header:
        try:
            retry_after = float(retry_after_header)
            logger.info(f"Rate limited (429). Retry-After header: {retry_after}s")
            return retry_after
        except (ValueError, TypeError):
            pass

    # Fallback to configured default
    fallback = settings.HUBSPOT_RATE_LIMIT_RETRY_AFTER_FALLBACK
    logger.info(f"Rate limited (429). No valid Retry-After header, using fallback: {fallback}s")
    return float(fallback)


async def handle_rate_limit(response: httpx.Response) -> bool:
    """
    Handle a rate-limited response by sleeping and signaling retry.

    Returns True if rate-limited (caller should retry), False otherwise.
    """
    retry_after = detect_rate_limit(response)
    if retry_after is None:
        return False

    logger.warning(f"Rate limited by HubSpot. Waiting {retry_after}s before retrying...")
    await asyncio.sleep(retry_after)
    return True


def handle_rate_limit_sync(response: httpx.Response) -> bool:
    """
    Synchronous version of rate limit handling.

    Returns True if rate-limited (caller should retry), False otherwise.
    """
    import time

    retry_after = detect_rate_limit(response)
    if retry_after is None:
        return False

    logger.warning(f"Rate limited by HubSpot. Waiting {retry_after}s before retrying...")
    time.sleep(retry_after)
    return True
