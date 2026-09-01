"""
FailedExternalCall model — Dead Letter Queue (§10.7, §10.5).

Records external operations that exhausted their retry budget.
Sensitive fields are scrubbed and payload is size-capped before persistence.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import JSONB

from app.database import Base


class FailedExternalCall(Base):
    """
    Failed external call record (DLQ) per §10.7.

    target_service, operation, organization_id, scan_id,
    payload (scrubbed/capped JSON), attempts, last_error, status, created_at.
    """

    __tablename__ = "failed_external_calls"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    target_service = Column(String(100), nullable=False, index=True)  # e.g., "hubspot", "minio"
    operation = Column(String(255), nullable=False)  # e.g., "get_contacts_page"
    organization_id = Column(String(255), nullable=True, index=True)
    scan_id = Column(String(255), nullable=True, index=True)
    payload = Column(JSONB, nullable=True)  # Scrubbed and size-capped
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    status = Column(String(50), nullable=False, default="failed")  # failed, resolved, ignored
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    def __repr__(self) -> str:
        return f"<FailedExternalCall {self.target_service}/{self.operation} attempts={self.attempts}>"
