"""
HubSpot authentication client (§10.4).

Supports:
- Private-app token (static Bearer token)
- OAuth 2.0 access token + refresh token flow
- Credential validation via lightweight identity call

Never logs tokens, secrets, or credentials.
"""

import logging
import time
from typing import Any, Dict, Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class HubSpotAuthClient:
    """
    HubSpot authentication manager.

    Handles token retrieval, caching, refresh, and validation.
    """

    def __init__(self):
        self._token_cache: Dict[str, Dict[str, Any]] = {}
        self._settings = get_settings()

    def get_access_token(self, credentials: Dict[str, Any]) -> str:
        """
        Get a valid access token for HubSpot API calls.

        For private-app tokens: returns the token directly.
        For OAuth: refreshes if expired, caches until near expiry.

        Args:
            credentials: Dict with 'access_token' and optionally
                        'refresh_token', 'client_id', 'client_secret'.

        Returns:
            A valid access token string.

        Raises:
            ValueError: If credentials are missing or invalid.
            httpx.HTTPError: If token refresh fails.
        """
        auth_type = credentials.get("auth_type", "private_app")

        if auth_type == "private_app":
            token = credentials.get("access_token")
            if not token:
                raise ValueError("Private-app token not provided")
            return token

        # OAuth flow
        return self._get_oauth_token(credentials)

    def _get_oauth_token(self, credentials: Dict[str, Any]) -> str:
        """Handle OAuth token retrieval with caching and refresh."""
        cache_key = credentials.get("client_id", "default")

        # Check cache
        cached = self._token_cache.get(cache_key)
        if cached and cached.get("expires_at", 0) > time.time() + 60:
            # Token is still valid (with 60s buffer)
            return cached["access_token"]

        # Try using existing access token first
        access_token = credentials.get("access_token")
        if access_token and not cached:
            # First use — cache it with a reasonable expiry
            self._token_cache[cache_key] = {
                "access_token": access_token,
                "expires_at": time.time() + 1800,  # Assume 30min if not specified
            }
            return access_token

        # Need to refresh
        refresh_token = credentials.get("refresh_token")
        if not refresh_token:
            if access_token:
                return access_token
            raise ValueError("No access token or refresh token available")

        return self._refresh_oauth_token(credentials, cache_key)

    def _refresh_oauth_token(self, credentials: Dict[str, Any], cache_key: str) -> str:
        """
        Refresh an OAuth access token using the refresh token.

        Never logs the tokens or secrets involved.
        """
        client_id = credentials.get("client_id") or self._settings.HUBSPOT_CLIENT_ID
        client_secret = credentials.get("client_secret") or self._settings.HUBSPOT_CLIENT_SECRET
        refresh_token = credentials.get("refresh_token")

        if not all([client_id, client_secret, refresh_token]):
            raise ValueError("Missing OAuth credentials for token refresh")

        logger.info("Refreshing HubSpot OAuth token...")

        with httpx.Client(timeout=self._settings.HUBSPOT_REQUEST_TIMEOUT) as client:
            response = client.post(
                f"{self._settings.HUBSPOT_API_BASE_URL}/oauth/v1/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                },
            )
            response.raise_for_status()
            data = response.json()

        access_token = data.get("access_token")
        expires_in = data.get("expires_in", 1800)

        if not access_token:
            raise ValueError("OAuth token refresh did not return an access token")

        # Cache the new token
        self._token_cache[cache_key] = {
            "access_token": access_token,
            "expires_at": time.time() + expires_in,
        }

        logger.info("HubSpot OAuth token refreshed successfully")
        return access_token

    def validate_credentials(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate HubSpot credentials via a lightweight identity call.

        Performs a simple API call to verify the token is valid without
        creating a job. Returns account info on success.

        Args:
            credentials: Dict with auth credentials.

        Returns:
            Dict with validation result and account info.

        Never logs the credentials being validated.
        """
        try:
            token = self.get_access_token(credentials)

            with httpx.Client(timeout=self._settings.HUBSPOT_REQUEST_TIMEOUT) as client:
                # Use the account info endpoint as a lightweight identity check
                response = client.get(
                    f"{self._settings.HUBSPOT_API_BASE_URL}/account-info/v3/details",
                    headers={"Authorization": f"Bearer {token}"},
                )

                if response.status_code == 200:
                    account_info = response.json()
                    return {
                        "valid": True,
                        "portal_id": account_info.get("portalId"),
                        "account_type": account_info.get("accountType"),
                        "time_zone": account_info.get("timeZone"),
                    }
                elif response.status_code == 401:
                    return {"valid": False, "error": "Invalid or expired credentials"}
                else:
                    return {
                        "valid": False,
                        "error": f"Unexpected response (HTTP {response.status_code})",
                    }

        except ValueError as e:
            return {"valid": False, "error": str(e)}
        except httpx.HTTPError as e:
            return {"valid": False, "error": f"Connection error: {type(e).__name__}"}

    def clear_cache(self) -> None:
        """Clear the token cache."""
        self._token_cache.clear()
