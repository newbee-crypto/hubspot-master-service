"""
Health check and stats endpoints (§10.3).

Public/unauthenticated — no HMAC required.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.clients.minio_client import MinIOClient
from app.config import get_settings
from app.database import get_db
from app.schemas.common import HealthResponse, ServiceComponent, StatsResponse
from app.services.job_service import JobService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)):
    """
    Liveness/readiness probe.

    Checks DB and MinIO connectivity.
    Returns 200 even if a component is unhealthy (use 'status' field to determine).
    """
    settings = get_settings()
    components = {}

    # Check database
    try:
        db.execute(text("SELECT 1"))
        components["database"] = ServiceComponent(status="healthy")
    except Exception as e:
        components["database"] = ServiceComponent(status="unhealthy", error=str(e)[:200])

    # Check MinIO
    try:
        minio_client = MinIOClient()
        if minio_client.check_health():
            components["minio"] = ServiceComponent(status="healthy")
        else:
            components["minio"] = ServiceComponent(status="unhealthy", error="Cannot reach MinIO")
    except Exception as e:
        components["minio"] = ServiceComponent(status="unhealthy", error=str(e)[:200])

    # Overall status
    all_healthy = all(c.status == "healthy" for c in components.values())
    any_healthy = any(c.status == "healthy" for c in components.values())

    if all_healthy:
        overall = "healthy"
    elif any_healthy:
        overall = "degraded"
    else:
        overall = "unhealthy"

    return HealthResponse(
        status=overall,
        environment=settings.APP_ENV,
        timestamp=datetime.utcnow(),
        components=components,
    )


@router.get("/stats", response_model=StatsResponse)
def service_stats(db: Session = Depends(get_db)):
    """Lightweight service-level counters."""
    job_service = JobService(db)
    stats = job_service.get_statistics()

    return StatsResponse(
        total_scans=stats.get("total", 0),
        status_counts=stats,
        timestamp=datetime.utcnow(),
    )
