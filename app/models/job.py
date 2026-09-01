"""
Job and JobCheckpoint models (§10.7).

Job: tracks a single extraction run (scan) for one HubSpot account.
JobCheckpoint: tracks pagination cursor per object type for pause/resume/crash-recovery.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.database import Base


class JobStatus(str, enum.Enum):
    """Job lifecycle states per §10.2."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    RESUMING = "RESUMING"
    NORMALIZING = "NORMALIZING"
    UPLOADING_TO_MINIO = "UPLOADING_TO_MINIO"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    CRASHED = "CRASHED"


# Terminal states — no transitions out of these
TERMINAL_STATES = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}

# Valid state transitions per §10.2
VALID_TRANSITIONS = {
    JobStatus.PENDING: {JobStatus.RUNNING, JobStatus.PAUSED, JobStatus.CANCELLED, JobStatus.FAILED},
    JobStatus.RUNNING: {
        JobStatus.PAUSED,
        JobStatus.NORMALIZING,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
        JobStatus.CRASHED,
    },
    JobStatus.PAUSED: {JobStatus.RESUMING, JobStatus.CANCELLED, JobStatus.FAILED},
    JobStatus.RESUMING: {JobStatus.RUNNING, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.NORMALIZING: {
        JobStatus.UPLOADING_TO_MINIO,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    },
    JobStatus.UPLOADING_TO_MINIO: {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.CRASHED: {JobStatus.RESUMING, JobStatus.CANCELLED, JobStatus.FAILED},
    # Terminal states — no transitions out
    JobStatus.COMPLETED: set(),
    JobStatus.FAILED: set(),
    JobStatus.CANCELLED: set(),
}


class Job(Base):
    """
    Core job/scan record (§10.7).

    Tracks identity, status, timing, and configuration for a single extraction run.
    Credentials are never persisted in plain form in the configuration column.
    """

    __tablename__ = "jobs"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scan_id = Column(String(255), unique=True, nullable=False, index=True)
    organization_id = Column(String(255), nullable=False, index=True)
    status = Column(
        Enum(JobStatus, name="job_status", create_constraint=True),
        nullable=False,
        default=JobStatus.PENDING,
    )

    # Configuration
    object_types = Column(JSONB, nullable=False, default=list)
    configuration = Column(JSONB, nullable=True)  # Scrubbed — no plaintext secrets

    # Progress tracking
    entity_record_counts = Column(JSONB, nullable=True, default=dict)
    error_message = Column(Text, nullable=True)

    # Timing
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    failed_at = Column(DateTime, nullable=True)
    normalized_at = Column(DateTime, nullable=True)
    minio_uploaded_at = Column(DateTime, nullable=True)

    # Heartbeat for crash detection
    last_heartbeat = Column(DateTime, nullable=True)

    # Relationships
    checkpoints = relationship("JobCheckpoint", back_populates="job", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Job scan_id={self.scan_id} status={self.status}>"


class JobCheckpoint(Base):
    """
    Pagination checkpoint per object type (§10.7).

    One row per (job, object_type). Stores the cursor position so that
    pause/resume and crash-recovery can continue without re-fetching.
    """

    __tablename__ = "job_checkpoints"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(PG_UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    object_type = Column(String(100), nullable=False)
    cursor = Column(String(500), nullable=True)  # HubSpot pagination cursor
    records_processed = Column(Integer, nullable=False, default=0)
    last_updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    job = relationship("Job", back_populates="checkpoints")

    __table_args__ = (
        UniqueConstraint("job_id", "object_type", name="uq_job_checkpoint_object_type"),
    )

    def __repr__(self) -> str:
        return f"<JobCheckpoint job_id={self.job_id} object_type={self.object_type} records={self.records_processed}>"
