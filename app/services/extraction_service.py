"""
Extraction service — top-level orchestrator (§10.4).

start_scan → creates job, launches background workflow, returns immediately.
_execute_scan → for each object type: authenticate → page → checkpoint → pause/cancel check.
resume_scan → continues from last saved checkpoint per object type.
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.clients.hubspot_auth import HubSpotAuthClient
from app.clients.hubspot_client import HubSpotAPIClient
from app.config import get_settings
from app.database import get_session_factory
from app.models.job import JobStatus
from app.services.job_service import JobService, JobNotFoundError, InvalidTransitionError

logger = logging.getLogger(__name__)

# In-memory registry of running background tasks
_running_tasks: Dict[str, asyncio.Task] = {}


class ExtractionService:
    """
    Top-level extraction orchestrator.

    Manages the lifecycle of scan workflows and coordinates
    background data extraction from HubSpot.
    """

    def __init__(self, db: Session):
        self.db = db
        self.job_service = JobService(db)
        self.auth_client = HubSpotAuthClient()
        self._settings = get_settings()

    def start_scan(self, request_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Start a new scan.

        Creates a job record and kicks off the background extraction workflow.
        Returns immediately (the caller should not wait for extraction to finish).

        Args:
            request_config: Dict containing:
                - organization_id: str
                - object_types: list[str] (optional, defaults to all)
                - credentials: dict with auth info
                - Any other scan parameters

        Returns:
            Dict with scan_id and initial status.
        """
        organization_id = request_config.get("organization_id", "")
        object_types = request_config.get("object_types", [
            "contacts", "companies", "deals", "tickets", "owners"
        ])
        credentials = request_config.get("credentials", {})

        # Generate scan ID
        scan_id = f"scan_{uuid.uuid4().hex[:12]}"

        # Create the job record (credentials are scrubbed before storage)
        job = self.job_service.create_job(
            scan_id=scan_id,
            organization_id=organization_id,
            object_types=object_types,
            configuration=request_config,
        )

        # Launch background extraction
        task = asyncio.create_task(
            self._run_extraction_in_background(scan_id, object_types, credentials)
        )
        _running_tasks[scan_id] = task

        logger.info(f"Scan started: {scan_id} for org={organization_id}")

        return {
            "scan_id": scan_id,
            "status": JobStatus.PENDING.value,
            "object_types": object_types,
            "message": "Scan started successfully",
        }

    async def _run_extraction_in_background(
        self,
        scan_id: str,
        object_types: List[str],
        credentials: Dict[str, Any],
    ) -> None:
        """
        Background extraction wrapper.

        Runs the synchronous extraction in a thread to avoid blocking the event loop.
        """
        try:
            await asyncio.to_thread(
                self._execute_scan, scan_id, object_types, credentials
            )
        except Exception as exc:
            logger.error(f"Background scan {scan_id} failed: {exc}", exc_info=True)
        finally:
            _running_tasks.pop(scan_id, None)

    def _execute_scan(
        self,
        scan_id: str,
        object_types: List[str],
        credentials: Dict[str, Any],
    ) -> None:
        """
        Execute the full extraction workflow (runs in a background thread).

        For each object type:
        1. Authenticate (get access token)
        2. Page through records
        3. Checkpoint after every page
        4. Check pause/cancel at checkpoint boundaries
        5. Save raw data to local files

        On completion → NORMALIZING → UPLOADING → COMPLETED
        On error → FAILED
        """
        # Create a new DB session for this thread
        SessionLocal = get_session_factory()
        db = SessionLocal()
        try:
            job_service = JobService(db)

            # Transition to RUNNING
            job_service.update_job_status(scan_id, JobStatus.RUNNING)

            # Get access token
            access_token = self.auth_client.get_access_token(credentials)
            api_client = HubSpotAPIClient(access_token, db=db)

            total_stats: Dict[str, int] = {}
            data_dir = self._get_scan_data_dir(scan_id)
            os.makedirs(data_dir, exist_ok=True)

            for obj_type in object_types:
                # Check pause/cancel before starting each object type
                if self._should_stop(scan_id, db):
                    return

                records_count = self._fetch_object_type(
                    scan_id, obj_type, api_client, job_service, db, data_dir
                )

                if records_count is None:
                    # Paused or cancelled during fetch
                    return

                total_stats[obj_type] = records_count
                job_service.update_heartbeat(scan_id)

            # Update record counts
            job = job_service.get_job(scan_id)
            job.entity_record_counts = total_stats
            db.commit()

            # Transition through final states
            job_service.update_job_status(scan_id, JobStatus.NORMALIZING)
            job.normalized_at = datetime.utcnow()
            db.commit()

            job_service.update_job_status(scan_id, JobStatus.UPLOADING_TO_MINIO)
            job.minio_uploaded_at = datetime.utcnow()
            db.commit()

            job_service.complete_job(scan_id, total_stats)
            logger.info(f"Scan {scan_id} completed. Stats: {total_stats}")

        except InvalidTransitionError as exc:
            logger.warning(f"Scan {scan_id} state transition error: {exc}")
        except Exception as exc:
            logger.error(f"Scan {scan_id} failed: {exc}", exc_info=True)
            try:
                job_service.fail_job(scan_id, str(exc)[:1000])
            except Exception:
                pass
        finally:
            db.close()

    def _fetch_object_type(
        self,
        scan_id: str,
        object_type: str,
        api_client: HubSpotAPIClient,
        job_service: JobService,
        db: Session,
        data_dir: str,
    ) -> Optional[int]:
        """
        Fetch all pages for one object type with checkpointing.

        Returns the total records fetched, or None if paused/cancelled.
        """
        # Check for existing checkpoint (resume support)
        checkpoint = job_service.get_latest_checkpoint(scan_id, object_type)
        cursor = checkpoint.cursor if checkpoint else None
        records_processed = checkpoint.records_processed if checkpoint else 0

        all_records = []
        page_num = 0

        logger.info(
            f"[{scan_id}] Fetching {object_type} "
            f"(resume from cursor={cursor}, records={records_processed})"
        )

        while True:
            # Check pause/cancel at checkpoint boundary
            if self._should_stop(scan_id, db):
                return None

            # Fetch one page
            try:
                records, next_cursor = api_client.get_page(
                    object_type=object_type,
                    after_cursor=cursor,
                )
            except Exception as exc:
                logger.error(f"[{scan_id}] Failed to fetch {object_type} page: {exc}")
                raise

            page_num += 1
            records_processed += len(records)
            all_records.extend(records)

            # Save checkpoint after every successful page
            job_service.save_checkpoint(
                scan_id=scan_id,
                object_type=object_type,
                cursor=next_cursor,
                records_processed=records_processed,
            )

            # Update heartbeat
            job_service.update_heartbeat(scan_id)

            logger.debug(
                f"[{scan_id}] {object_type} page {page_num}: "
                f"{len(records)} records, total={records_processed}, "
                f"next_cursor={'yes' if next_cursor else 'none'}"
            )

            if next_cursor is None:
                # No more pages
                break

            cursor = next_cursor

        # Save raw records to disk
        self._save_raw_records(data_dir, object_type, all_records)

        logger.info(f"[{scan_id}] Completed {object_type}: {records_processed} records")
        return records_processed

    def _should_stop(self, scan_id: str, db: Session) -> bool:
        """
        Check if the job should stop (paused or cancelled).

        Called at checkpoint boundaries for cooperative pause/cancel.
        """
        try:
            job_service = JobService(db)
            job = job_service.get_job(scan_id)
            db.refresh(job)

            if job.status == JobStatus.PAUSED:
                logger.info(f"[{scan_id}] Job paused at checkpoint boundary")
                return True
            if job.status == JobStatus.CANCELLED:
                logger.info(f"[{scan_id}] Job cancelled at checkpoint boundary")
                return True

            return False
        except Exception:
            return False

    def resume_scan(self, scan_id: str, credentials: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resume a paused or crashed scan from the last checkpoint.

        Args:
            scan_id: The scan to resume.
            credentials: HubSpot credentials for re-authentication.

        Returns:
            Dict with scan status.
        """
        job = self.job_service.resume_job(scan_id)
        object_types = job.object_types or []

        # Launch background extraction (will resume from checkpoints)
        task = asyncio.create_task(
            self._run_extraction_in_background(scan_id, object_types, credentials)
        )
        _running_tasks[scan_id] = task

        return {
            "scan_id": scan_id,
            "status": JobStatus.RESUMING.value,
            "message": "Scan resuming from last checkpoint",
        }

    def get_scan_status(self, scan_id: str) -> Dict[str, Any]:
        """Get the current status of a scan with checkpoint details."""
        job = self.job_service.get_job(scan_id)
        checkpoints = self.job_service.get_all_checkpoints(scan_id)

        checkpoint_info = {}
        for cp in checkpoints:
            checkpoint_info[cp.object_type] = {
                "records_processed": cp.records_processed,
                "has_more": cp.cursor is not None,
                "last_updated": cp.last_updated_at.isoformat() if cp.last_updated_at else None,
            }

        from app.utils.serialization import deep_serialize
        from app.utils.duration import calculate_duration

        return deep_serialize({
            "scan_id": job.scan_id,
            "organization_id": job.organization_id,
            "status": job.status,
            "object_types": job.object_types,
            "entity_record_counts": job.entity_record_counts,
            "checkpoints": checkpoint_info,
            "error_message": job.error_message,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "duration_seconds": calculate_duration(job.started_at, job.completed_at or datetime.utcnow()),
        })

    def get_scan_statistics(self) -> Dict[str, Any]:
        """Get aggregate scan statistics."""
        return self.job_service.get_statistics()

    def remove_scan(self, scan_id: str) -> Dict[str, Any]:
        """Remove a scan and its data."""
        self.job_service.remove_job(scan_id)

        # Clean up local data
        data_dir = self._get_scan_data_dir(scan_id)
        if os.path.exists(data_dir):
            import shutil
            shutil.rmtree(data_dir, ignore_errors=True)

        return {"scan_id": scan_id, "message": "Scan removed"}

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _get_scan_data_dir(self, scan_id: str) -> str:
        """Get the local data directory for a scan."""
        return os.path.join(self._settings.DATA_DIR, scan_id)

    def _save_raw_records(
        self, data_dir: str, object_type: str, records: List[Dict]
    ) -> None:
        """Save raw HubSpot records to a JSON file for later normalization."""
        filepath = os.path.join(data_dir, f"{object_type}_raw.json")
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(records, f, default=str, indent=2)
        logger.debug(f"Saved {len(records)} raw {object_type} records to {filepath}")
