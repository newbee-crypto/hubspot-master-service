"""
Initial migration — create jobs, job_checkpoints, audit_logs, failed_external_calls tables.

Revision ID: 001
Revises: None
Create Date: 2024-01-01 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers
revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create job_status enum type
    job_status_enum = sa.Enum(
        "PENDING", "RUNNING", "PAUSED", "RESUMING", "NORMALIZING",
        "UPLOADING_TO_MINIO", "COMPLETED", "FAILED", "CANCELLED", "CRASHED",
        name="job_status",
    )
    job_status_enum.create(op.get_bind(), checkfirst=True)

    # --- jobs table ---
    op.create_table(
        "jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("scan_id", sa.String(255), unique=True, nullable=False, index=True),
        sa.Column("organization_id", sa.String(255), nullable=False, index=True),
        sa.Column("status", job_status_enum, nullable=False, server_default="PENDING"),
        sa.Column("object_types", JSONB, nullable=False, server_default="[]"),
        sa.Column("configuration", JSONB, nullable=True),
        sa.Column("entity_record_counts", JSONB, nullable=True, server_default="{}"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("completed_at", sa.DateTime, nullable=True),
        sa.Column("failed_at", sa.DateTime, nullable=True),
        sa.Column("normalized_at", sa.DateTime, nullable=True),
        sa.Column("minio_uploaded_at", sa.DateTime, nullable=True),
        sa.Column("last_heartbeat", sa.DateTime, nullable=True),
    )

    # --- job_checkpoints table ---
    op.create_table(
        "job_checkpoints",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("object_type", sa.String(100), nullable=False),
        sa.Column("cursor", sa.String(500), nullable=True),
        sa.Column("records_processed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("job_id", "object_type", name="uq_job_checkpoint_object_type"),
    )

    # --- audit_logs table ---
    op.create_table(
        "audit_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("event_category", sa.String(100), nullable=False, index=True),
        sa.Column("event_type", sa.String(100), nullable=False, index=True),
        sa.Column("actor_client_id", sa.String(255), nullable=True),
        sa.Column("actor_role", sa.String(50), nullable=True),
        sa.Column("organization_id", sa.String(255), nullable=True, index=True),
        sa.Column("entity_type", sa.String(100), nullable=True),
        sa.Column("resource_type", sa.String(100), nullable=True),
        sa.Column("resource_id", sa.String(255), nullable=True),
        sa.Column("http_method", sa.String(10), nullable=True),
        sa.Column("endpoint", sa.String(500), nullable=True),
        sa.Column("request_ip", sa.String(45), nullable=True),
        sa.Column("status_code", sa.Integer, nullable=True),
        sa.Column("outcome", sa.String(50), nullable=False, index=True),
        sa.Column("severity", sa.String(20), nullable=False, server_default="INFO"),
        sa.Column("error_detail", sa.Text, nullable=True),
        sa.Column("extra_metadata", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now(), index=True),
    )

    # --- failed_external_calls table ---
    op.create_table(
        "failed_external_calls",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("target_service", sa.String(100), nullable=False, index=True),
        sa.Column("operation", sa.String(255), nullable=False),
        sa.Column("organization_id", sa.String(255), nullable=True, index=True),
        sa.Column("scan_id", sa.String(255), nullable=True, index=True),
        sa.Column("payload", JSONB, nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="failed"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now(), index=True),
    )


def downgrade() -> None:
    op.drop_table("failed_external_calls")
    op.drop_table("audit_logs")
    op.drop_table("job_checkpoints")
    op.drop_table("jobs")
    sa.Enum(name="job_status").drop(op.get_bind(), checkfirst=True)
