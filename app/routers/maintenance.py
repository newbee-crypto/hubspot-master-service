"""
Maintenance router (§10.3).

Cleanup and crash detection endpoints.
All endpoints require HMAC authentication.
"""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.hmac import AuthResult, hmac_auth_required
from app.database import get_db
from app.schemas.common import MessageResponse
from app.services.job_service import JobService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/maintenance",
    tags=["Maintenance"],
    dependencies=[Depends(hmac_auth_required)],
)


@router.post("/cleanup", response_model=MessageResponse)
def cleanup_old_scans(
    days_old: int = Query(default=30, ge=1, description="Delete scans older than N days"),
    db: Session = Depends(get_db),
):
    """Delete scans and their local files older than N days."""
    job_service = JobService(db)
    count = job_service.cleanup_old_jobs(days_old)
    return MessageResponse(
        message=f"Cleaned up {count} scans older than {days_old} days",
        detail={"deleted_count": count, "days_old": days_old},
    )


@router.post("/detect-crashed", response_model=MessageResponse)
def detect_crashed_jobs(
    timeout_minutes: int = Query(default=5, ge=1, description="Heartbeat stale timeout in minutes"),
    db: Session = Depends(get_db),
):
    """Flag jobs with stale heartbeats as CRASHED."""
    job_service = JobService(db)
    crashed = job_service.detect_crashed_jobs(timeout_minutes)
    scan_ids = [j.scan_id for j in crashed]
    return MessageResponse(
        message=f"Detected {len(crashed)} crashed jobs",
        detail={"crashed_scan_ids": scan_ids, "timeout_minutes": timeout_minutes},
    )
