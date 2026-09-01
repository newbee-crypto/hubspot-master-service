"""
Audit service (§10.4).

Fire-and-forget audit log writer + paginated query + rolling-window stats.
Non-blocking — audit failures never crash the application.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.audit import AuditLog

logger = logging.getLogger(__name__)


class AuditService:
    """
    Audit log management service.

    Provides write (fire-and-forget), query, and aggregation capabilities.
    """

    def __init__(self, db: Session):
        self.db = db

    def write_audit(
        self,
        event_category: str,
        event_type: str,
        outcome: str,
        organization_id: Optional[str] = None,
        actor_client_id: Optional[str] = None,
        actor_role: Optional[str] = None,
        entity_type: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        http_method: Optional[str] = None,
        endpoint: Optional[str] = None,
        request_ip: Optional[str] = None,
        status_code: Optional[int] = None,
        severity: str = "INFO",
        error_detail: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[AuditLog]:
        """
        Write an audit log entry. Fire-and-forget — never raises.

        Args:
            event_category: e.g., "auth", "scan", "normalization", "maintenance"
            event_type: e.g., "scan_started", "auth_success", "auth_failure"
            outcome: e.g., "success", "failure", "denied"
            organization_id: Optional org context
            severity: INFO, WARNING, ERROR, CRITICAL

        Returns:
            The created AuditLog record, or None on failure.
        """
        try:
            entry = AuditLog(
                event_category=event_category,
                event_type=event_type,
                outcome=outcome,
                organization_id=organization_id,
                actor_client_id=actor_client_id,
                actor_role=actor_role,
                entity_type=entity_type,
                resource_type=resource_type,
                resource_id=resource_id,
                http_method=http_method,
                endpoint=endpoint,
                request_ip=request_ip,
                status_code=status_code,
                severity=severity,
                error_detail=error_detail[:2000] if error_detail else None,
                extra_metadata=extra_metadata,
            )
            self.db.add(entry)
            self.db.commit()
            self.db.refresh(entry)
            return entry
        except Exception as exc:
            logger.error(f"Failed to write audit log: {exc}", exc_info=True)
            try:
                self.db.rollback()
            except Exception:
                pass
            return None

    def get_audit_logs(
        self,
        org_id: Optional[str] = None,
        event_category: Optional[str] = None,
        event_type: Optional[str] = None,
        outcome: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """
        Query audit logs with filters and pagination.

        Returns dict with 'logs' list and 'pagination' info.
        """
        query = self.db.query(AuditLog)

        if org_id:
            query = query.filter(AuditLog.organization_id == org_id)
        if event_category:
            query = query.filter(AuditLog.event_category == event_category)
        if event_type:
            query = query.filter(AuditLog.event_type == event_type)
        if outcome:
            query = query.filter(AuditLog.outcome == outcome)
        if from_date:
            query = query.filter(AuditLog.created_at >= from_date)
        if to_date:
            query = query.filter(AuditLog.created_at <= to_date)

        query = query.order_by(AuditLog.created_at.desc())
        total = query.count()
        offset = (page - 1) * page_size
        logs = query.offset(offset).limit(page_size).all()

        return {
            "logs": logs,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def get_audit_stats(self, window_minutes: int = 60) -> Dict[str, Any]:
        """
        Get rolling-window audit aggregates.

        Returns counts grouped by event_category and outcome
        within the last `window_minutes`.
        """
        threshold = datetime.utcnow() - timedelta(minutes=window_minutes)

        # Count by category
        category_counts = (
            self.db.query(AuditLog.event_category, func.count(AuditLog.id))
            .filter(AuditLog.created_at >= threshold)
            .group_by(AuditLog.event_category)
            .all()
        )

        # Count by outcome
        outcome_counts = (
            self.db.query(AuditLog.outcome, func.count(AuditLog.id))
            .filter(AuditLog.created_at >= threshold)
            .group_by(AuditLog.outcome)
            .all()
        )

        # Total in window
        total = (
            self.db.query(func.count(AuditLog.id))
            .filter(AuditLog.created_at >= threshold)
            .scalar()
        )

        return {
            "window_minutes": window_minutes,
            "total_events": total or 0,
            "by_category": {cat: count for cat, count in category_counts},
            "by_outcome": {outcome: count for outcome, count in outcome_counts},
        }
