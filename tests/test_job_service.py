"""Tests for JobService — state machine, checkpoints, crash detection."""

import uuid
from datetime import datetime, timedelta
from app.services.job_service import JobService, InvalidTransitionError, JobNotFoundError
from app.models.job import Job, JobStatus, TERMINAL_STATES
import pytest


class TestJobServiceCRUD:
    def test_create_job(self, db_session):
        svc = JobService(db_session)
        job = svc.create_job("scan_001", "org_1", ["contacts", "deals"])
        assert job.scan_id == "scan_001"
        assert job.status == JobStatus.PENDING
        assert job.object_types == ["contacts", "deals"]

    def test_get_job(self, db_session):
        svc = JobService(db_session)
        svc.create_job("scan_002", "org_1", ["contacts"])
        job = svc.get_job("scan_002")
        assert job.scan_id == "scan_002"

    def test_get_job_not_found(self, db_session):
        svc = JobService(db_session)
        with pytest.raises(JobNotFoundError):
            svc.get_job("nonexistent")

    def test_scrub_configuration(self, db_session):
        svc = JobService(db_session)
        job = svc.create_job("scan_003", "org_1", ["contacts"],
                             configuration={"access_token": "secret", "page_size": 100})
        assert job.configuration["access_token"] == "[REDACTED]"
        assert job.configuration["page_size"] == 100


class TestStateMachine:
    def test_pending_to_running(self, db_session):
        svc = JobService(db_session)
        svc.create_job("scan_sm1", "org_1", ["contacts"])
        job = svc.update_job_status("scan_sm1", JobStatus.RUNNING)
        assert job.status == JobStatus.RUNNING
        assert job.started_at is not None

    def test_running_to_paused(self, db_session):
        svc = JobService(db_session)
        svc.create_job("scan_sm2", "org_1", ["contacts"])
        svc.update_job_status("scan_sm2", JobStatus.RUNNING)
        job = svc.pause_job("scan_sm2")
        assert job.status == JobStatus.PAUSED

    def test_paused_to_resuming(self, db_session):
        svc = JobService(db_session)
        svc.create_job("scan_sm3", "org_1", ["contacts"])
        svc.update_job_status("scan_sm3", JobStatus.RUNNING)
        svc.pause_job("scan_sm3")
        job = svc.resume_job("scan_sm3")
        assert job.status == JobStatus.RESUMING

    def test_cannot_transition_from_terminal(self, db_session):
        svc = JobService(db_session)
        svc.create_job("scan_sm4", "org_1", ["contacts"])
        svc.update_job_status("scan_sm4", JobStatus.RUNNING)
        svc.update_job_status("scan_sm4", JobStatus.NORMALIZING)
        svc.update_job_status("scan_sm4", JobStatus.UPLOADING_TO_MINIO)
        svc.complete_job("scan_sm4")
        with pytest.raises(InvalidTransitionError):
            svc.update_job_status("scan_sm4", JobStatus.RUNNING)

    def test_cancel_from_running(self, db_session):
        svc = JobService(db_session)
        svc.create_job("scan_sm5", "org_1", ["contacts"])
        svc.update_job_status("scan_sm5", JobStatus.RUNNING)
        job = svc.cancel_job("scan_sm5")
        assert job.status == JobStatus.CANCELLED

    def test_fail_job(self, db_session):
        svc = JobService(db_session)
        svc.create_job("scan_sm6", "org_1", ["contacts"])
        svc.update_job_status("scan_sm6", JobStatus.RUNNING)
        job = svc.fail_job("scan_sm6", "Something went wrong")
        assert job.status == JobStatus.FAILED
        assert "Something went wrong" in job.error_message


class TestCheckpoints:
    def test_save_and_get_checkpoint(self, db_session):
        svc = JobService(db_session)
        svc.create_job("scan_cp1", "org_1", ["contacts"])
        cp = svc.save_checkpoint("scan_cp1", "contacts", "cursor_abc", 100)
        assert cp.cursor == "cursor_abc"
        assert cp.records_processed == 100

        fetched = svc.get_latest_checkpoint("scan_cp1", "contacts")
        assert fetched.cursor == "cursor_abc"

    def test_update_checkpoint(self, db_session):
        svc = JobService(db_session)
        svc.create_job("scan_cp2", "org_1", ["contacts"])
        svc.save_checkpoint("scan_cp2", "contacts", "cursor_1", 50)
        svc.save_checkpoint("scan_cp2", "contacts", "cursor_2", 150)
        cp = svc.get_latest_checkpoint("scan_cp2", "contacts")
        assert cp.cursor == "cursor_2"
        assert cp.records_processed == 150


class TestCrashDetection:
    def test_detect_crashed_jobs(self, db_session):
        svc = JobService(db_session)
        job = svc.create_job("scan_crash1", "org_1", ["contacts"])
        svc.update_job_status("scan_crash1", JobStatus.RUNNING)
        # Simulate stale heartbeat
        job = svc.get_job("scan_crash1")
        job.last_heartbeat = datetime.utcnow() - timedelta(minutes=10)
        db_session.commit()
        crashed = svc.detect_crashed_jobs(timeout_minutes=5)
        assert len(crashed) == 1
        assert crashed[0].status == JobStatus.CRASHED


class TestStatistics:
    def test_get_statistics(self, db_session):
        svc = JobService(db_session)
        svc.create_job("scan_s1", "org_1", ["contacts"])
        svc.create_job("scan_s2", "org_1", ["deals"])
        svc.update_job_status("scan_s2", JobStatus.RUNNING)
        stats = svc.get_statistics()
        assert stats["PENDING"] == 1
        assert stats["RUNNING"] == 1
        assert stats["total"] == 2
