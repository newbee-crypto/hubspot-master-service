"""
Job service (§10.4).

Manages job lifecycle, state machine transitions, checkpoints, heartbeat,
and crash detection. Enforces the FSM rules from §10.2.
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.job import (
    Job,
    JobCheckpoint,
    JobStatus,
    TERMINAL_STATES,
    VALID_TRANSITIONS,
)

logger = logging.getLogger(__name__)


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""
    pass


class JobNotFoundError(Exception):
    """Raised when a job is not found."""
    pass


class JobService:
    """
    Job lifecycle management service.

    Handles creation, status updates, checkpoint management,
    heartbeat tracking, and crash detection.
    """

    def __init__(self, db: Session):
        self.db = db

    # -------------------------------------------------------------------------
    # Job CRUD
    # -------------------------------------------------------------------------

    def create_job(
        self,
        scan_id: str,
        organization_id: str,
        object_types: List[str],
        configuration: Optional[Dict[str, Any]] = None,
    ) -> Job:
        """
        Create a new job record.

        Credentials are never persisted in plain form — the configuration
        column stores only non-sensitive parameters.
        """
        # Scrub any sensitive data from configuration before storing
        safe_config = self._scrub_configuration(configuration) if configuration else {}

        job = Job(
            id=uuid.uuid4(),
            scan_id=scan_id,
            organization_id=organization_id,
            status=JobStatus.PENDING,
            object_types=object_types,
            configuration=safe_config,
            entity_record_counts={},
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)

        logger.info(f"Created job scan_id={scan_id} org={organization_id} objects={object_types}")
        return job

    def get_job(self, scan_id: str) -> Job:
        """Fetch a job by scan_id. Raises JobNotFoundError if not found."""
        job = self.db.query(Job).filter(Job.scan_id == scan_id).first()
        if not job:
            raise JobNotFoundError(f"Job not found: {scan_id}")
        return job

    def get_job_by_id(self, job_id: uuid.UUID) -> Job:
        """Fetch a job by its UUID. Raises JobNotFoundError if not found."""
        job = self.db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise JobNotFoundError(f"Job not found: {job_id}")
        return job

    def list_jobs(
        self,
        organization_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """List jobs with optional org filter and pagination."""
        query = self.db.query(Job)
        if organization_id:
            query = query.filter(Job.organization_id == organization_id)
        query = query.order_by(Job.created_at.desc())

        total = query.count()
        offset = (page - 1) * page_size
        jobs = query.offset(offset).limit(page_size).all()

        return {
            "jobs": jobs,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    # -------------------------------------------------------------------------
    # State Machine (§10.2)
    # -------------------------------------------------------------------------

    def update_job_status(self, scan_id: str, new_status: JobStatus) -> Job:
        """
        Transition a job to a new status, enforcing FSM rules.

        Raises InvalidTransitionError if the transition is not allowed.
        """
        job = self.get_job(scan_id)
        current = job.status

        if current in TERMINAL_STATES:
            raise InvalidTransitionError(
                f"Cannot transition from terminal state {current.value}"
            )

        allowed = VALID_TRANSITIONS.get(current, set())
        if new_status not in allowed:
            raise InvalidTransitionError(
                f"Invalid transition: {current.value} → {new_status.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )

        job.status = new_status
        job.updated_at = datetime.utcnow()

        # Set timing fields based on status
        if new_status == JobStatus.RUNNING:
            if job.started_at is None:
                job.started_at = datetime.utcnow()
            job.last_heartbeat = datetime.utcnow()
        elif new_status == JobStatus.COMPLETED:
            job.completed_at = datetime.utcnow()
        elif new_status == JobStatus.FAILED:
            job.failed_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(job)

        logger.info(f"Job {scan_id}: {current.value} → {new_status.value}")
        return job

    def complete_job(self, scan_id: str, stats: Optional[Dict] = None) -> Job:
        """Mark a job as completed with optional stats."""
        job = self.update_job_status(scan_id, JobStatus.COMPLETED)
        if stats:
            job.entity_record_counts = stats
            self.db.commit()
        return job

    def fail_job(self, scan_id: str, error: str) -> Job:
        """Mark a job as failed with an error message."""
        job = self.get_job(scan_id)
        # Allow fail from any non-terminal state
        if job.status not in TERMINAL_STATES:
            job.status = JobStatus.FAILED
            job.error_message = error[:2000]  # Cap error length
            job.failed_at = datetime.utcnow()
            job.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(job)
            logger.error(f"Job {scan_id} failed: {error[:200]}")
        return job

    def cancel_job(self, scan_id: str) -> Job:
        """
        Cancel a job. Allowed from any non-terminal state (§10.2).
        """
        job = self.get_job(scan_id)
        if job.status in TERMINAL_STATES:
            raise InvalidTransitionError(
                f"Cannot cancel job in terminal state {job.status.value}"
            )
        job.status = JobStatus.CANCELLED
        job.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(job)
        logger.info(f"Job {scan_id} cancelled")
        return job

    def pause_job(self, scan_id: str) -> Job:
        """
        Flag a job to pause at the next checkpoint boundary.
        Only from RUNNING or PENDING (§10.2).
        """
        job = self.get_job(scan_id)
        if job.status not in (JobStatus.RUNNING, JobStatus.PENDING):
            raise InvalidTransitionError(
                f"Cannot pause from {job.status.value}. Must be RUNNING or PENDING."
            )
        job.status = JobStatus.PAUSED
        job.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(job)
        logger.info(f"Job {scan_id} paused")
        return job

    def resume_job(self, scan_id: str) -> Job:
        """
        Resume a paused or crashed job (§10.2).
        Idempotent if already RUNNING or RESUMING.
        """
        job = self.get_job(scan_id)
        if job.status in (JobStatus.RUNNING, JobStatus.RESUMING):
            return job  # Idempotent
        if job.status in TERMINAL_STATES:
            raise InvalidTransitionError(
                f"Cannot resume from terminal state {job.status.value}"
            )
        if job.status not in (JobStatus.PAUSED, JobStatus.CRASHED):
            raise InvalidTransitionError(
                f"Cannot resume from {job.status.value}. Must be PAUSED or CRASHED."
            )
        job.status = JobStatus.RESUMING
        job.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(job)
        logger.info(f"Job {scan_id} resuming")
        return job

    # -------------------------------------------------------------------------
    # Checkpoints
    # -------------------------------------------------------------------------

    def save_checkpoint(
        self,
        scan_id: str,
        object_type: str,
        cursor: Optional[str],
        records_processed: int,
    ) -> JobCheckpoint:
        """
        Save or update a checkpoint for a (job, object_type) pair.

        Every successfully fetched page results in a checkpoint update.
        """
        job = self.get_job(scan_id)

        checkpoint = (
            self.db.query(JobCheckpoint)
            .filter(
                JobCheckpoint.job_id == job.id,
                JobCheckpoint.object_type == object_type,
            )
            .first()
        )

        if checkpoint:
            checkpoint.cursor = cursor
            checkpoint.records_processed = records_processed
            checkpoint.last_updated_at = datetime.utcnow()
        else:
            checkpoint = JobCheckpoint(
                id=uuid.uuid4(),
                job_id=job.id,
                object_type=object_type,
                cursor=cursor,
                records_processed=records_processed,
            )
            self.db.add(checkpoint)

        self.db.commit()
        self.db.refresh(checkpoint)
        return checkpoint

    def get_latest_checkpoint(
        self, scan_id: str, object_type: str
    ) -> Optional[JobCheckpoint]:
        """Get the latest checkpoint for a (job, object_type) pair."""
        job = self.get_job(scan_id)
        return (
            self.db.query(JobCheckpoint)
            .filter(
                JobCheckpoint.job_id == job.id,
                JobCheckpoint.object_type == object_type,
            )
            .first()
        )

    def get_all_checkpoints(self, scan_id: str) -> List[JobCheckpoint]:
        """Get all checkpoints for a job."""
        job = self.get_job(scan_id)
        return (
            self.db.query(JobCheckpoint)
            .filter(JobCheckpoint.job_id == job.id)
            .all()
        )

    # -------------------------------------------------------------------------
    # Heartbeat
    # -------------------------------------------------------------------------

    def update_heartbeat(self, scan_id: str) -> None:
        """Update the job heartbeat timestamp."""
        job = self.get_job(scan_id)
        job.last_heartbeat = datetime.utcnow()
        job.updated_at = datetime.utcnow()
        self.db.commit()

    # -------------------------------------------------------------------------
    # Crash Detection
    # -------------------------------------------------------------------------

    def detect_crashed_jobs(self, timeout_minutes: int = 5) -> List[Job]:
        """
        Flag jobs with stale heartbeats as CRASHED.

        A job is considered crashed if it's in RUNNING state and its
        last_heartbeat is older than timeout_minutes.
        """
        threshold = datetime.utcnow() - timedelta(minutes=timeout_minutes)
        crashed_jobs = (
            self.db.query(Job)
            .filter(
                Job.status == JobStatus.RUNNING,
                Job.last_heartbeat < threshold,
            )
            .all()
        )

        for job in crashed_jobs:
            job.status = JobStatus.CRASHED
            job.error_message = (
                f"Heartbeat stale for >{timeout_minutes} minutes. "
                f"Last heartbeat: {job.last_heartbeat}"
            )
            job.updated_at = datetime.utcnow()
            logger.warning(f"Job {job.scan_id} marked as CRASHED (stale heartbeat)")

        if crashed_jobs:
            self.db.commit()

        return crashed_jobs

    # -------------------------------------------------------------------------
    # Cleanup
    # -------------------------------------------------------------------------

    def cleanup_old_jobs(self, days_old: int) -> int:
        """Delete jobs older than N days. Returns count of deleted jobs."""
        threshold = datetime.utcnow() - timedelta(days=days_old)
        count = (
            self.db.query(Job)
            .filter(Job.created_at < threshold)
            .delete(synchronize_session=False)
        )
        self.db.commit()
        logger.info(f"Cleaned up {count} jobs older than {days_old} days")
        return count

    def remove_job(self, scan_id: str) -> bool:
        """
        Delete a specific job and its checkpoints.
        Blocked while the job is actively running.
        """
        job = self.get_job(scan_id)
        if job.status == JobStatus.RUNNING:
            raise InvalidTransitionError("Cannot remove a running job. Pause or cancel it first.")

        self.db.delete(job)
        self.db.commit()
        logger.info(f"Removed job {scan_id}")
        return True

    # -------------------------------------------------------------------------
    # Statistics
    # -------------------------------------------------------------------------

    def get_statistics(self) -> Dict[str, Any]:
        """Aggregate counts by status."""
        results = (
            self.db.query(Job.status, func.count(Job.id))
            .group_by(Job.status)
            .all()
        )
        stats = {status.value: 0 for status in JobStatus}
        for status, count in results:
            stats[status.value] = count
        stats["total"] = sum(stats.values())
        return stats

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _scrub_configuration(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Remove sensitive fields from configuration before database storage."""
        sensitive_keys = {
            "access_token", "refresh_token", "client_secret",
            "api_key", "token", "secret", "password", "credential",
        }
        scrubbed = {}
        for key, value in config.items():
            if any(s in key.lower() for s in sensitive_keys):
                scrubbed[key] = "[REDACTED]"
            elif isinstance(value, dict):
                scrubbed[key] = self._scrub_configuration(value)
            else:
                scrubbed[key] = value
        return scrubbed
