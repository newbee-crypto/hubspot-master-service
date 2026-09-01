"""
Pydantic schemas for scan (extraction) endpoints.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ScanStartRequest(BaseModel):
    """Request body for POST /scan/start."""
    organization_id: str = Field(..., min_length=1, description="Organization identifier")
    object_types: Optional[List[str]] = Field(
        default=None,
        description="HubSpot object types to extract. Defaults to all supported types.",
    )
    credentials: Dict[str, Any] = Field(
        ..., description="HubSpot credentials (access_token, auth_type, etc.)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "organization_id": "org_12345",
                "object_types": ["contacts", "companies", "deals"],
                "credentials": {
                    "auth_type": "private_app",
                    "access_token": "pat-na1-xxxxxxxx",
                },
            }
        }


class ScanStartResponse(BaseModel):
    """Response for POST /scan/start."""
    scan_id: str
    status: str
    object_types: List[str]
    message: str


class CheckpointInfo(BaseModel):
    """Progress checkpoint for a single object type."""
    records_processed: int = 0
    has_more: bool = False
    last_updated: Optional[str] = None


class ScanStatusResponse(BaseModel):
    """Response for GET /scan/{scan_id}/status."""
    scan_id: str
    organization_id: str
    status: str
    object_types: Optional[List[str]] = None
    entity_record_counts: Optional[Dict[str, int]] = None
    checkpoints: Optional[Dict[str, CheckpointInfo]] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None


class ScanSummary(BaseModel):
    """Summary of a scan for list responses."""
    scan_id: str
    organization_id: str
    status: str
    object_types: Optional[List[str]] = None
    entity_record_counts: Optional[Dict[str, int]] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None


class ScanListResponse(BaseModel):
    """Response for GET /scan/list."""
    scans: List[ScanSummary]
    pagination: Dict[str, Any]


class ScanStatisticsResponse(BaseModel):
    """Response for GET /scan/statistics."""
    statistics: Dict[str, int]


class ScanResumeRequest(BaseModel):
    """Request body for POST /scan/{scan_id}/resume."""
    credentials: Dict[str, Any] = Field(
        ..., description="HubSpot credentials for re-authentication"
    )
