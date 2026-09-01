"""
Dead Letter Queue (DLQ) writer (§10.5).

Persists exhausted external calls into failed_external_calls table.
Scrubs sensitive fields and caps payload size.
Never raises — DLQ writes must not crash the application.
"""

import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.failed_call import FailedExternalCall

logger = logging.getLogger(__name__)

# Keys that must be redacted from payloads before persistence
SENSITIVE_KEYS = {
    "access_token",
    "refresh_token",
    "token",
    "secret",
    "password",
    "client_secret",
    "api_key",
    "authorization",
    "hmac",
    "credential",
    "private_key",
}


def scrub_payload(payload: Any) -> Any:
    """
    Recursively redact sensitive keys from a payload before DLQ persistence.

    Replaces values of sensitive keys with '[REDACTED]'.
    Never persists secrets or credentials in the DLQ.
    """
    if payload is None:
        return None

    if isinstance(payload, dict):
        scrubbed = {}
        for key, value in payload.items():
            if any(s in key.lower() for s in SENSITIVE_KEYS):
                scrubbed[key] = "[REDACTED]"
            else:
                scrubbed[key] = scrub_payload(value)
        return scrubbed

    if isinstance(payload, list):
        return [scrub_payload(item) for item in payload]

    if isinstance(payload, str):
        # Don't log very long strings (possible base64-encoded tokens)
        if len(payload) > 500:
            return payload[:200] + "...[TRUNCATED]"

    return payload


def cap_payload(payload: Any, max_bytes: Optional[int] = None) -> Any:
    """
    Cap the serialized payload size to prevent oversized DLQ entries.
    """
    settings = get_settings()
    if max_bytes is None:
        max_bytes = settings.DLQ_PAYLOAD_MAX_BYTES

    try:
        serialized = json.dumps(payload, default=str)
        if len(serialized.encode("utf-8")) <= max_bytes:
            return payload
        # Truncate
        return {"_truncated": True, "preview": serialized[:max_bytes], "original_size": len(serialized)}
    except (TypeError, ValueError):
        return {"_error": "Could not serialize payload"}


def write_to_dlq(
    db: Session,
    target_service: str,
    operation: str,
    payload: Any = None,
    attempts: int = 0,
    error: Optional[str] = None,
    organization_id: Optional[str] = None,
    scan_id: Optional[str] = None,
) -> Optional[FailedExternalCall]:
    """
    Persist an exhausted external call to the DLQ.

    Scrubs sensitive fields and caps payload size before writing.
    Never raises — DLQ writes must not crash the application.

    Args:
        db: Database session.
        target_service: e.g., "hubspot", "minio".
        operation: e.g., "get_contacts_page".
        payload: Request/context data (will be scrubbed and capped).
        attempts: Number of retry attempts made.
        error: The final error message.
        organization_id: Optional org context.
        scan_id: Optional scan context.

    Returns:
        The created FailedExternalCall record, or None on failure.
    """
    try:
        # Scrub sensitive data, then cap size
        safe_payload = cap_payload(scrub_payload(payload))

        # Scrub error message too — don't leak secrets in error strings
        safe_error = error
        if safe_error:
            for sensitive in SENSITIVE_KEYS:
                # Simple redaction — won't catch all patterns but covers common cases
                if sensitive in safe_error.lower():
                    safe_error = "[Error contained sensitive data — redacted]"
                    break

        record = FailedExternalCall(
            target_service=target_service,
            operation=operation,
            organization_id=organization_id,
            scan_id=scan_id,
            payload=safe_payload,
            attempts=attempts,
            last_error=safe_error[:2000] if safe_error else None,  # Cap error length
            status="failed",
        )

        db.add(record)
        db.commit()
        db.refresh(record)

        logger.info(
            f"DLQ entry created: {target_service}/{operation} "
            f"(attempts={attempts}, scan_id={scan_id})"
        )
        return record

    except Exception as exc:
        # DLQ writes must never crash the application
        logger.error(f"Failed to write DLQ entry: {exc}", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        return None
