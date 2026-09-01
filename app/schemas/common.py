"""
Shared Pydantic models: error responses, pagination, health, stats.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Standard error response envelope."""
    error: str
    detail: Optional[str] = None
    status_code: int = 400


class PaginationInfo(BaseModel):
    """Standard pagination metadata."""
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    total_pages: int = Field(ge=0)
    has_next: bool = False
    has_previous: bool = False


class ServiceComponent(BaseModel):
    """Health check for a single service component."""
    status: str  # "healthy" or "unhealthy"
    latency_ms: Optional[float] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str  # "healthy" or "degraded" or "unhealthy"
    version: str = "1.0.0"
    environment: str = "development"
    timestamp: datetime
    components: Dict[str, ServiceComponent] = {}


class StatsResponse(BaseModel):
    """Service-level statistics response."""
    total_scans: int = 0
    status_counts: Dict[str, int] = {}
    timestamp: datetime


class MessageResponse(BaseModel):
    """Generic message response."""
    message: str
    scan_id: Optional[str] = None
    detail: Optional[Dict[str, Any]] = None
