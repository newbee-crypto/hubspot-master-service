"""
Normalization router (§10.3).

All endpoints require HMAC authentication.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.hmac import AuthResult, hmac_auth_required
from app.database import get_db
from app.schemas.normalization import (
    NormalizeRequest,
    NormalizeResponse,
    NormalizedTablesResponse,
    ObjectTableMapping,
    SupportedObjectsResponse,
    TableInfo,
)
from app.services.job_service import JobNotFoundError
from app.services.normalization_service import NormalizationService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/normalization",
    tags=["Normalization"],
    dependencies=[Depends(hmac_auth_required)],
)


@router.post("/{scan_id}/normalize", response_model=NormalizeResponse)
def normalize_scan(
    scan_id: str,
    request: NormalizeRequest,
    db: Session = Depends(get_db),
):
    """
    Run the normalization pipeline for a completed scan.

    Flattens raw HubSpot data into clean relational tables,
    optionally saves to disk and uploads to MinIO.
    """
    service = NormalizationService(db)
    try:
        result = service.normalize_scan(
            scan_id=scan_id,
            output_format=request.format,
            save_to_disk=request.save_to_disk,
            upload_to_minio=request.upload_to_minio,
        )
        return NormalizeResponse(**result)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Scan not found: {scan_id}")
    except Exception as exc:
        logger.error(f"Normalization failed for {scan_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)[:500])


@router.get("/{scan_id}/tables", response_model=NormalizedTablesResponse)
def list_normalized_tables(scan_id: str, db: Session = Depends(get_db)):
    """List normalized table files for a scan."""
    service = NormalizationService(db)
    try:
        # Verify scan exists
        service.job_service.get_job(scan_id)
        tables = service.list_normalized_tables(scan_id)
        return NormalizedTablesResponse(
            scan_id=scan_id,
            tables=[TableInfo(**t) for t in tables],
        )
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Scan not found: {scan_id}")


@router.get("/supported-objects", response_model=SupportedObjectsResponse)
def get_supported_objects():
    """Static catalog of supported HubSpot objects and their output tables."""
    catalog = NormalizationService.get_supported_objects()
    return SupportedObjectsResponse(
        supported_objects=[ObjectTableMapping(**obj) for obj in catalog]
    )
