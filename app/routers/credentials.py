"""
Credentials validation router (§10.3).

Validates HubSpot credentials without creating a job.
Requires HMAC authentication.
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.hmac import AuthResult, hmac_auth_required
from app.clients.hubspot_auth import HubSpotAuthClient
from app.database import get_db
from app.schemas.credentials import CredentialValidationResponse, HubSpotCredentials

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Credentials"], dependencies=[Depends(hmac_auth_required)])


@router.post("/validate-credentials", response_model=CredentialValidationResponse)
def validate_credentials(request: HubSpotCredentials):
    """
    Validate HubSpot credentials via a lightweight identity call.

    Does NOT create a job — just checks if the token is valid
    and returns account info on success.
    """
    auth_client = HubSpotAuthClient()
    result = auth_client.validate_credentials(request.model_dump())
    return CredentialValidationResponse(**result)
