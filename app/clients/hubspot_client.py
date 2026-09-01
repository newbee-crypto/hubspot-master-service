"""
HubSpot CRM API client (§10.4).

Fetches data from HubSpot CRM v3 API with:
- Cursor-based pagination (after/paging.next.after)
- Rate-limit awareness (429 handled separately from retry budget)
- Generic retry for transient failures
- Association fetching (especially for Deals)
- DLQ recording on exhaustion

Supports: Contacts, Companies, Deals, Tickets, Owners.
"""

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.resilience.dlq import write_to_dlq
from app.resilience.rate_limiter import detect_rate_limit
from app.resilience.retry import (
    RetryExhaustedError,
    is_retryable_status,
    is_retryable_exception,
)

logger = logging.getLogger(__name__)

# HubSpot CRM v3 object type to API endpoint mapping
OBJECT_TYPE_ENDPOINTS = {
    "contacts": "/crm/v3/objects/contacts",
    "companies": "/crm/v3/objects/companies",
    "deals": "/crm/v3/objects/deals",
    "tickets": "/crm/v3/objects/tickets",
    "owners": "/crm/v3/owners",
}

# Default properties to fetch per object type
DEFAULT_PROPERTIES = {
    "contacts": [
        "firstname", "lastname", "email", "phone", "company",
        "jobtitle", "lifecyclestage", "hs_lead_status",
        "createdate", "lastmodifieddate",
    ],
    "companies": [
        "name", "domain", "industry", "numberofemployees",
        "annualrevenue", "city", "state", "country", "phone",
        "createdate", "lastmodifieddate",
    ],
    "deals": [
        "dealname", "dealstage", "pipeline", "amount",
        "closedate", "createdate", "lastmodifieddate",
        "hs_deal_stage_probability", "dealtype",
    ],
    "tickets": [
        "subject", "content", "hs_pipeline", "hs_pipeline_stage",
        "hs_ticket_priority", "hs_ticket_category",
        "createdate", "lastmodifieddate",
    ],
}


class HubSpotAPIClient:
    """
    HubSpot CRM API client with pagination, rate limiting, and retry support.
    """

    def __init__(self, access_token: str, db: Optional[Session] = None):
        """
        Args:
            access_token: Valid HubSpot access token.
            db: Optional database session for DLQ writes.
        """
        self._access_token = access_token
        self._db = db
        self._settings = get_settings()
        self._base_url = self._settings.HUBSPOT_API_BASE_URL
        self._timeout = self._settings.HUBSPOT_REQUEST_TIMEOUT

    def get_page(
        self,
        object_type: str,
        after_cursor: Optional[str] = None,
        page_size: Optional[int] = None,
        properties: Optional[List[str]] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """
        Fetch one page of records for a given object type.

        Uses cursor-based pagination via the 'after' parameter.

        Args:
            object_type: One of contacts, companies, deals, tickets, owners.
            after_cursor: Pagination cursor from previous page (None for first page).
            page_size: Number of records per page.
            properties: List of properties to fetch (uses defaults if None).

        Returns:
            Tuple of (records_list, next_cursor). next_cursor is None if no more pages.

        Raises:
            RetryExhaustedError: If all retries are exhausted.
            HttpResponseError: For non-retryable HTTP errors.
        """
        if page_size is None:
            page_size = self._settings.HUBSPOT_DEFAULT_PAGE_SIZE

        endpoint = OBJECT_TYPE_ENDPOINTS.get(object_type)
        if not endpoint:
            raise ValueError(f"Unsupported object type: {object_type}")

        url = f"{self._base_url}{endpoint}"
        params: Dict[str, Any] = {"limit": min(page_size, self._settings.HUBSPOT_MAX_PAGE_SIZE)}

        if after_cursor:
            params["after"] = after_cursor

        # Add properties (not applicable for owners endpoint)
        if object_type != "owners":
            props = properties or DEFAULT_PROPERTIES.get(object_type, [])
            if props:
                params["properties"] = ",".join(props)

        return self._make_paginated_request(url, params, object_type)

    def get_associations(
        self,
        object_type: str,
        record_id: str,
        to_object_type: str,
    ) -> List[Dict[str, Any]]:
        """
        Fetch associations for a record (e.g., deal → contacts).

        Args:
            object_type: Source object type (e.g., "deals").
            record_id: The source record ID.
            to_object_type: Target object type (e.g., "contacts").

        Returns:
            List of association records.
        """
        url = (
            f"{self._base_url}/crm/v3/objects/{object_type}/{record_id}"
            f"/associations/{to_object_type}"
        )

        return self._make_request_with_retries(
            url, {}, f"get_associations_{object_type}_to_{to_object_type}"
        )

    def _make_paginated_request(
        self,
        url: str,
        params: Dict[str, Any],
        object_type: str,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Make a paginated API request with rate-limit and retry handling."""
        op_label = f"get_{object_type}_page"
        settings = self._settings
        max_retries = settings.EXTERNAL_CALL_MAX_RETRIES
        delays = settings.retry_delays
        jitter = settings.EXTERNAL_CALL_JITTER

        import random

        last_error = None

        for attempt in range(max_retries + 1):
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.get(
                        url,
                        params=params,
                        headers=self._build_headers(),
                    )

                    # Check for rate limiting FIRST (before retry logic)
                    retry_after = detect_rate_limit(response)
                    if retry_after is not None:
                        logger.warning(
                            f"[{op_label}] Rate limited. Sleeping {retry_after}s..."
                        )
                        time.sleep(retry_after)
                        continue  # Retry same request — does NOT count against retry budget

                    # Check for retryable server errors
                    if is_retryable_status(response.status_code):
                        raise httpx.HTTPStatusError(
                            f"Server error {response.status_code}",
                            request=response.request,
                            response=response,
                        )

                    response.raise_for_status()

                    # Parse response
                    data = response.json()
                    records = data.get("results", [])
                    next_cursor = None

                    # HubSpot pagination: paging.next.after
                    paging = data.get("paging", {})
                    next_info = paging.get("next", {})
                    if next_info:
                        next_cursor = next_info.get("after")

                    return records, next_cursor

            except Exception as exc:
                last_error = exc

                if attempt >= max_retries:
                    break

                if not is_retryable_exception(exc) and not (
                    isinstance(exc, httpx.HTTPStatusError)
                    and is_retryable_status(exc.response.status_code)
                ):
                    break  # Non-retryable error

                delay_index = min(attempt, len(delays) - 1)
                base_delay = delays[delay_index] if delays else 1.0
                actual_delay = base_delay + random.uniform(0, jitter * base_delay)

                logger.warning(
                    f"[{op_label}] Attempt {attempt + 1}/{max_retries + 1} failed: {exc}. "
                    f"Retrying in {actual_delay:.2f}s..."
                )
                time.sleep(actual_delay)

        # All retries exhausted — write to DLQ
        error_msg = str(last_error) if last_error else "Unknown error"
        if self._db:
            write_to_dlq(
                db=self._db,
                target_service="hubspot",
                operation=op_label,
                payload={"url": url, "params": {k: v for k, v in params.items()}},
                attempts=max_retries + 1,
                error=error_msg,
            )

        raise RetryExhaustedError(op_label, max_retries + 1, last_error)

    def _make_request_with_retries(
        self,
        url: str,
        params: Dict[str, Any],
        op_label: str,
    ) -> List[Dict[str, Any]]:
        """Make a non-paginated API request with rate-limit and retry handling."""
        settings = self._settings
        max_retries = settings.EXTERNAL_CALL_MAX_RETRIES
        delays = settings.retry_delays
        jitter = settings.EXTERNAL_CALL_JITTER

        import random

        last_error = None

        for attempt in range(max_retries + 1):
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.get(
                        url,
                        params=params,
                        headers=self._build_headers(),
                    )

                    # Rate limit check first
                    retry_after = detect_rate_limit(response)
                    if retry_after is not None:
                        time.sleep(retry_after)
                        continue

                    if is_retryable_status(response.status_code):
                        raise httpx.HTTPStatusError(
                            f"Server error {response.status_code}",
                            request=response.request,
                            response=response,
                        )

                    response.raise_for_status()
                    data = response.json()
                    return data.get("results", [])

            except Exception as exc:
                last_error = exc
                if attempt >= max_retries:
                    break
                if not is_retryable_exception(exc) and not (
                    isinstance(exc, httpx.HTTPStatusError)
                    and is_retryable_status(exc.response.status_code)
                ):
                    break

                delay_index = min(attempt, len(delays) - 1)
                base_delay = delays[delay_index] if delays else 1.0
                actual_delay = base_delay + random.uniform(0, jitter * base_delay)
                time.sleep(actual_delay)

        if self._db:
            write_to_dlq(
                db=self._db,
                target_service="hubspot",
                operation=op_label,
                payload={"url": url, "params": params},
                attempts=max_retries + 1,
                error=str(last_error) if last_error else "Unknown error",
            )

        raise RetryExhaustedError(op_label, max_retries + 1, last_error)

    def _build_headers(self) -> Dict[str, str]:
        """Build request headers with authorization. Never logs the token."""
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
