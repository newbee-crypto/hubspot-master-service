"""Pydantic schemas package for request/response models."""

from app.schemas.common import ErrorResponse, PaginationInfo, HealthResponse, StatsResponse
from app.schemas.scan import ScanStartRequest, ScanStatusResponse, ScanListResponse
from app.schemas.normalization import NormalizeRequest, NormalizedTablesResponse, SupportedObjectsResponse
from app.schemas.credentials import HubSpotCredentials, CredentialValidationResponse

__all__ = [
    "ErrorResponse",
    "PaginationInfo",
    "HealthResponse",
    "StatsResponse",
    "ScanStartRequest",
    "ScanStatusResponse",
    "ScanListResponse",
    "NormalizeRequest",
    "NormalizedTablesResponse",
    "SupportedObjectsResponse",
    "HubSpotCredentials",
    "CredentialValidationResponse",
]
