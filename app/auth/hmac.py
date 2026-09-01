"""
HMAC authentication middleware (§10.6).

Dual-key scheme:
- Coordinator key: full access (GET/POST/DELETE)
- Engineer/read-only key: GET-only, for inspection endpoints

Required headers: X-HS-Signature, X-HS-Timestamp, X-HS-Client-ID, X-HS-Nonce
Canonical string: METHOD\nPATH\nTIMESTAMP\nNONCE\nSHA256(BODY)
Signed with HMAC-SHA256.

Nonce replay protection, timestamp freshness window, and audit logging
on every auth outcome.
"""

import hashlib
import hmac
import logging
import time
from collections import OrderedDict
from typing import Optional, Tuple

from fastapi import Depends, HTTPException, Request
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN

from app.config import get_settings

logger = logging.getLogger(__name__)

# In-memory nonce cache with TTL for replay protection
# OrderedDict for efficient eviction of oldest entries
_nonce_cache: OrderedDict[str, float] = OrderedDict()
_MAX_NONCE_CACHE_SIZE = 10000


class AuthResult:
    """Result of HMAC authentication."""

    def __init__(
        self,
        authenticated: bool,
        client_id: Optional[str] = None,
        role: Optional[str] = None,
        error: Optional[str] = None,
    ):
        self.authenticated = authenticated
        self.client_id = client_id
        self.role = role  # "coordinator" or "engineer"
        self.error = error


def _compute_signature(
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    body: bytes,
    secret_key: str,
) -> str:
    """
    Compute HMAC-SHA256 signature from canonical string.

    Canonical string format: METHOD\nPATH\nTIMESTAMP\nNONCE\nSHA256(BODY)
    """
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = f"{method}\n{path}\n{timestamp}\n{nonce}\n{body_hash}"
    signature = hmac.new(
        secret_key.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return signature


def _check_nonce(nonce: str) -> bool:
    """
    Check if a nonce has been seen before (replay protection).
    Returns True if nonce is fresh (not replayed), False if replayed.
    """
    now = time.time()

    # Evict expired entries
    settings = get_settings()
    max_age = settings.HMAC_SIGNATURE_MAX_AGE
    while _nonce_cache:
        oldest_nonce, oldest_time = next(iter(_nonce_cache.items()))
        if now - oldest_time > max_age:
            _nonce_cache.pop(oldest_nonce)
        else:
            break

    # Cap cache size
    while len(_nonce_cache) >= _MAX_NONCE_CACHE_SIZE:
        _nonce_cache.popitem(last=False)

    if nonce in _nonce_cache:
        return False  # Replay detected

    _nonce_cache[nonce] = now
    return True


def _verify_request(
    method: str,
    path: str,
    headers: dict,
    body: bytes,
) -> AuthResult:
    """
    Verify HMAC-signed request.

    Returns AuthResult with authentication outcome.
    """
    settings = get_settings()

    if not settings.HMAC_ENABLED:
        return AuthResult(authenticated=True, client_id="hmac-disabled", role="coordinator")

    # Extract required headers
    signature = headers.get("x-hs-signature")
    timestamp = headers.get("x-hs-timestamp")
    client_id = headers.get("x-hs-client-id")
    nonce = headers.get("x-hs-nonce")

    if not all([signature, timestamp, client_id, nonce]):
        missing = []
        if not signature:
            missing.append("X-HS-Signature")
        if not timestamp:
            missing.append("X-HS-Timestamp")
        if not client_id:
            missing.append("X-HS-Client-ID")
        if not nonce:
            missing.append("X-HS-Nonce")
        return AuthResult(
            authenticated=False,
            client_id=client_id,
            error=f"Missing required headers: {', '.join(missing)}",
        )

    # Timestamp freshness
    try:
        req_time = float(timestamp)
        now = time.time()
        if abs(now - req_time) > settings.HMAC_SIGNATURE_MAX_AGE:
            return AuthResult(
                authenticated=False,
                client_id=client_id,
                error=f"Timestamp expired (age={abs(now - req_time):.0f}s, max={settings.HMAC_SIGNATURE_MAX_AGE}s)",
            )
    except (ValueError, TypeError):
        return AuthResult(
            authenticated=False,
            client_id=client_id,
            error="Invalid timestamp format",
        )

    # Nonce replay check
    if not _check_nonce(nonce):
        return AuthResult(
            authenticated=False,
            client_id=client_id,
            error="Nonce replay detected",
        )

    # Try coordinator key first
    expected_coordinator = _compute_signature(
        method, path, timestamp, nonce, body, settings.HMAC_SECRET_KEY_CORE
    )
    if hmac.compare_digest(signature, expected_coordinator):
        return AuthResult(authenticated=True, client_id=client_id, role="coordinator")

    # Try engineer key
    if settings.HMAC_SECRET_KEY_ENGINEER:
        expected_engineer = _compute_signature(
            method, path, timestamp, nonce, body, settings.HMAC_SECRET_KEY_ENGINEER
        )
        if hmac.compare_digest(signature, expected_engineer):
            return AuthResult(authenticated=True, client_id=client_id, role="engineer")

    return AuthResult(
        authenticated=False,
        client_id=client_id,
        error="Invalid signature",
    )


async def hmac_auth_required(request: Request) -> AuthResult:
    """
    FastAPI dependency that enforces HMAC authentication.

    Reads the full request body for signature verification, then
    restores it so downstream handlers can read it too.

    Raises HTTP 401 if authentication fails.
    Raises HTTP 403 if engineer key tries non-GET method.
    """
    settings = get_settings()

    if not settings.HMAC_ENABLED:
        return AuthResult(authenticated=True, client_id="hmac-disabled", role="coordinator")

    body = await request.body()

    # Build lowercase header dict
    headers = {k.lower(): v for k, v in request.headers.items()}

    result = _verify_request(
        method=request.method,
        path=request.url.path,
        headers=headers,
        body=body,
    )

    if not result.authenticated:
        logger.warning(
            f"HMAC auth failed: {result.error} "
            f"(client={result.client_id}, method={request.method}, path={request.url.path})"
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail=result.error or "Authentication failed",
        )

    # Engineer key: GET-only
    if result.role == "engineer" and request.method != "GET":
        logger.warning(
            f"HMAC auth denied: engineer key attempted {request.method} "
            f"(client={result.client_id}, path={request.url.path})"
        )
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Engineer credentials only allow GET requests",
        )

    logger.debug(
        f"HMAC auth success: client={result.client_id}, role={result.role}, "
        f"method={request.method}, path={request.url.path}"
    )
    return result


async def hmac_auth_optional(request: Request) -> AuthResult:
    """
    Optional HMAC auth — does not raise on failure, returns unauthenticated result.
    Used for public/health endpoints that may optionally accept auth.
    """
    settings = get_settings()
    if not settings.HMAC_ENABLED:
        return AuthResult(authenticated=True, client_id="hmac-disabled", role="coordinator")

    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    # If no auth headers present at all, return unauthenticated (but don't reject)
    if not headers.get("x-hs-signature"):
        return AuthResult(authenticated=False, client_id=None, role=None)

    return _verify_request(
        method=request.method,
        path=request.url.path,
        headers=headers,
        body=body,
    )
