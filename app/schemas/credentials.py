"""
Pydantic schemas for credential validation endpoint.
"""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class HubSpotCredentials(BaseModel):
    """Request body for POST /validate-credentials."""
    auth_type: str = Field(
        default="private_app",
        description="Authentication type: 'private_app' or 'oauth'",
    )
    access_token: str = Field(
        ..., min_length=1, description="HubSpot access token"
    )
    refresh_token: Optional[str] = Field(
        default=None, description="OAuth refresh token (required for OAuth flow)"
    )
    client_id: Optional[str] = Field(
        default=None, description="OAuth client ID (required for OAuth flow)"
    )
    client_secret: Optional[str] = Field(
        default=None, description="OAuth client secret (required for OAuth flow)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "auth_type": "private_app",
                "access_token": "pat-na1-xxxxxxxx",
            }
        }


class CredentialValidationResponse(BaseModel):
    """Response for POST /validate-credentials."""
    valid: bool
    portal_id: Optional[int] = None
    account_type: Optional[str] = None
    time_zone: Optional[str] = None
    error: Optional[str] = None
