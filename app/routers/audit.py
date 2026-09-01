"""
Audit router (§10.3).

Paginated audit log query and rolling-window stats.
All endpoints require HMAC authentication.
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.hmac import AuthResult, hmac_auth_required
from app.database import get_db
from app.services.audit_service import AuditService
from app.utils.pagination import build_pagination_info
from app.utils.serialization import deep_serialize

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/audit",
    tags=["Audit"],
    dependencies=[Depends(hmac_auth_required)],
)


@router.get("/logs")
def get_audit_logs(
    org_id: Optional[str] = Query(default=None),
    event_category: Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    outcome: Optional[str] = Query(default=None),
    from_date: Optional[str] = Query(default=None, description="ISO datetime string"),
    to_date: Optional[str] = Query(default=None, description="ISO datetime string"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Paginated audit log query with optional filters."""
    audit_service = AuditService(db)

    # Parse date strings
    parsed_from = None
    parsed_to = None
    try:
        if from_date:
            parsed_from = datetime.fromisoformat(from_date)
        if to_date:
            parsed_to = datetime.fromisoformat(to_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use ISO format (YYYY-MM-DDTHH:MM:SS)")

    result = audit_service.get_audit_logs(
        org_id=org_id,
        event_category=event_category,
        event_type=event_type,
        outcome=outcome,
        from_date=parsed_from,
        to_date=parsed_to,
        page=page,
        page_size=page_size,
    )

    # Serialize audit log entries
    logs = []
    for log in result["logs"]:
        logs.append(deep_serialize({
            "id": log.id,
            "event_category": log.event_category,
            "event_type": log.event_type,
            "actor_client_id": log.actor_client_id,
            "actor_role": log.actor_role,
            "organization_id": log.organization_id,
            "entity_type": log.entity_type,
            "resource_type": log.resource_type,
            "resource_id": log.resource_id,
            "http_method": log.http_method,
            "endpoint": log.endpoint,
            "request_ip": log.request_ip,
            "status_code": log.status_code,
            "outcome": log.outcome,
            "severity": log.severity,
            "error_detail": log.error_detail,
            "extra_metadata": log.extra_metadata,
            "created_at": log.created_at,
        }))

    pagination = build_pagination_info(result["page"], result["page_size"], result["total"])

    return {
        "logs": logs,
        "pagination": pagination,
    }


@router.get("/stats")
def get_audit_stats(
    window_minutes: int = Query(default=60, ge=1, description="Rolling window in minutes"),
    db: Session = Depends(get_db),
):
    """Rolling-window audit aggregates."""
    audit_service = AuditService(db)
    return audit_service.get_audit_stats(window_minutes)
