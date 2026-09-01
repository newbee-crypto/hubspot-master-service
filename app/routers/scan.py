"""
Scan (extraction) router (§10.3).

All endpoints require HMAC authentication.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from starlette.status import HTTP_202_ACCEPTED

from app.auth.hmac import AuthResult, hmac_auth_required
from app.database import get_db
from app.schemas.scan import (
    ScanListResponse,
    ScanResumeRequest,
    ScanStartRequest,
    ScanStartResponse,
    ScanStatisticsResponse,
    ScanStatusResponse,
    ScanSummary,
)
from app.schemas.common import MessageResponse
from app.services.extraction_service import ExtractionService
from app.services.job_service import InvalidTransitionError, JobNotFoundError, JobService
from app.utils.pagination import build_pagination_info
from app.utils.serialization import deep_serialize

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scan", tags=["Scan"], dependencies=[Depends(hmac_auth_required)])


@router.post("/start", response_model=ScanStartResponse, status_code=HTTP_202_ACCEPTED)
def start_scan(
    request: ScanStartRequest,
    db: Session = Depends(get_db),
):
    """
    Start a new scan for a HubSpot account.

    Creates a job record and kicks off background extraction.
    Returns 202 immediately — does not wait for extraction to finish.
    """
    service = ExtractionService(db)
    try:
        result = service.start_scan(request.model_dump())
        return ScanStartResponse(**result)
    except Exception as exc:
        logger.error(f"Failed to start scan: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)[:500])


@router.get("/{scan_id}/status", response_model=ScanStatusResponse)
def get_scan_status(scan_id: str, db: Session = Depends(get_db)):
    """Get the current status of a scan with checkpoint details."""
    service = ExtractionService(db)
    try:
        result = service.get_scan_status(scan_id)
        return ScanStatusResponse(**result)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Scan not found: {scan_id}")


@router.post("/{scan_id}/pause", response_model=MessageResponse)
def pause_scan(scan_id: str, db: Session = Depends(get_db)):
    """
    Flag a scan to pause at the next checkpoint boundary.

    Only from RUNNING or PENDING state.
    """
    job_service = JobService(db)
    try:
        job = job_service.pause_job(scan_id)
        return MessageResponse(
            message=f"Scan {scan_id} paused",
            scan_id=scan_id,
            detail={"status": job.status.value},
        )
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Scan not found: {scan_id}")
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/{scan_id}/resume", response_model=MessageResponse)
def resume_scan(
    scan_id: str,
    request: ScanResumeRequest,
    db: Session = Depends(get_db),
):
    """
    Resume a paused or crashed scan from the last checkpoint.

    Requires credentials for re-authentication.
    """
    service = ExtractionService(db)
    try:
        result = service.resume_scan(scan_id, request.credentials)
        return MessageResponse(
            message=result.get("message", "Scan resuming"),
            scan_id=scan_id,
            detail={"status": result.get("status")},
        )
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Scan not found: {scan_id}")
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/{scan_id}/cancel", response_model=MessageResponse)
def cancel_scan(scan_id: str, db: Session = Depends(get_db)):
    """Cancel a scan. Allowed from any non-terminal state."""
    job_service = JobService(db)
    try:
        job = job_service.cancel_job(scan_id)
        return MessageResponse(
            message=f"Scan {scan_id} cancelled",
            scan_id=scan_id,
            detail={"status": job.status.value},
        )
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Scan not found: {scan_id}")
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/list", response_model=ScanListResponse)
def list_scans(
    organization_id: str = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List past/active scans with optional organization filter and pagination."""
    job_service = JobService(db)
    result = job_service.list_jobs(organization_id=organization_id, page=page, page_size=page_size)

    scans = []
    for job in result["jobs"]:
        scans.append(ScanSummary(
            scan_id=job.scan_id,
            organization_id=job.organization_id,
            status=job.status.value,
            object_types=job.object_types,
            entity_record_counts=job.entity_record_counts,
            created_at=job.created_at.isoformat() if job.created_at else None,
            completed_at=job.completed_at.isoformat() if job.completed_at else None,
        ))

    pagination = build_pagination_info(result["page"], result["page_size"], result["total"])

    return ScanListResponse(scans=scans, pagination=pagination)


@router.get("/statistics", response_model=ScanStatisticsResponse)
def get_scan_statistics(db: Session = Depends(get_db)):
    """Aggregate scan counts by status."""
    service = ExtractionService(db)
    stats = service.get_scan_statistics()
    return ScanStatisticsResponse(statistics=stats)


@router.delete("/{scan_id}/remove", response_model=MessageResponse)
def remove_scan(scan_id: str, db: Session = Depends(get_db)):
    """
    Delete a scan's records and local files.

    Blocked while the scan is actively running.
    """
    service = ExtractionService(db)
    try:
        result = service.remove_scan(scan_id)
        return MessageResponse(
            message=result.get("message", "Scan removed"),
            scan_id=scan_id,
        )
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Scan not found: {scan_id}")
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
