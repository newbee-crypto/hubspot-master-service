"""
AuditLog model (§10.7).

Records every authentication outcome and significant system event
for security audit trail purposes.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import JSONB

from app.database import Base


class AuditLog(Base):
    """
    Audit log entry (§10.7).

    Fields match the specification:
    event_category, event_type, actor_client_id, actor_role, organization_id,
    entity_type, resource_type, resource_id, http_method, endpoint, request_ip,
    status_code, outcome, severity, error_detail, extra_metadata, created_at.
    """

    __tablename__ = "audit_logs"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_category = Column(String(100), nullable=False, index=True)
    event_type = Column(String(100), nullable=False, index=True)
    actor_client_id = Column(String(255), nullable=True)
    actor_role = Column(String(50), nullable=True)
    organization_id = Column(String(255), nullable=True, index=True)
    entity_type = Column(String(100), nullable=True)
    resource_type = Column(String(100), nullable=True)
    resource_id = Column(String(255), nullable=True)
    http_method = Column(String(10), nullable=True)
    endpoint = Column(String(500), nullable=True)
    request_ip = Column(String(45), nullable=True)
    status_code = Column(Integer, nullable=True)
    outcome = Column(String(50), nullable=False, index=True)  # success, failure, denied, etc.
    severity = Column(String(20), nullable=False, default="INFO")  # INFO, WARNING, ERROR, CRITICAL
    error_detail = Column(Text, nullable=True)
    extra_metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    def __repr__(self) -> str:
        return f"<AuditLog {self.event_type} outcome={self.outcome} at={self.created_at}>"
