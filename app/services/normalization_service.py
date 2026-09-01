"""
Normalization service (§10.4).

Orchestrates the normalization pipeline:
1. Lists raw fetched records per object type
2. Runs each per-object normalizer
3. Saves output as JSON or Parquet
4. Optionally uploads to MinIO
5. Cleans up local scan data on success
"""

import io
import json
import logging
import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.clients.minio_client import MinIOClient
from app.config import get_settings
from app.models.job import JobStatus
from app.services.job_service import JobService
from app.services.normalizers import NORMALIZER_REGISTRY

logger = logging.getLogger(__name__)

# Catalog of supported objects and their output tables
SUPPORTED_OBJECTS_CATALOG = [
    {
        "object_type": "contacts",
        "output_tables": ["contacts"],
        "description": "HubSpot CRM contacts — people associated with your business",
    },
    {
        "object_type": "companies",
        "output_tables": ["companies"],
        "description": "HubSpot CRM companies — organizations associated with your business",
    },
    {
        "object_type": "deals",
        "output_tables": ["deals", "deal_associations", "deal_line_items"],
        "description": "HubSpot CRM deals — revenue opportunities, plus their associations and line items",
    },
    {
        "object_type": "tickets",
        "output_tables": ["tickets"],
        "description": "HubSpot CRM tickets — customer support requests",
    },
    {
        "object_type": "owners",
        "output_tables": ["owners"],
        "description": "HubSpot owners — users/team members who own records",
    },
]


class NormalizationService:
    """
    Orchestrates normalization of raw HubSpot data into clean relational tables.
    """

    def __init__(self, db: Session):
        self.db = db
        self.job_service = JobService(db)
        self._settings = get_settings()

    def normalize_scan(
        self,
        scan_id: str,
        output_format: str = "parquet",
        save_to_disk: bool = True,
        upload_to_minio: bool = True,
    ) -> Dict[str, Any]:
        """
        Run the full normalization pipeline for a scan.

        1. Read raw records from disk
        2. Run per-object normalizers
        3. Save output as JSON or Parquet
        4. Optionally upload to MinIO
        5. Update job status

        Args:
            scan_id: The scan to normalize.
            output_format: 'parquet' or 'json'.
            save_to_disk: Whether to save normalized files locally.
            upload_to_minio: Whether to upload to MinIO.

        Returns:
            Dict with normalization results.
        """
        job = self.job_service.get_job(scan_id)
        data_dir = self._get_scan_data_dir(scan_id)
        normalized_dir = os.path.join(data_dir, "normalized")

        if save_to_disk:
            os.makedirs(normalized_dir, exist_ok=True)

        # Update status to NORMALIZING
        try:
            self.job_service.update_job_status(scan_id, JobStatus.NORMALIZING)
        except Exception:
            pass  # May already be in NORMALIZING

        all_tables: Dict[str, List[Dict[str, Any]]] = {}
        record_counts: Dict[str, int] = {}
        object_types = job.object_types or []

        # Process each object type
        for obj_type in object_types:
            raw_file = os.path.join(data_dir, f"{obj_type}_raw.json")
            if not os.path.exists(raw_file):
                logger.warning(f"[{scan_id}] No raw data file for {obj_type}: {raw_file}")
                continue

            # Load raw records
            with open(raw_file, "r", encoding="utf-8") as f:
                raw_records = json.load(f)

            # Get normalizer
            normalizer_class = NORMALIZER_REGISTRY.get(obj_type)
            if not normalizer_class:
                logger.warning(f"[{scan_id}] No normalizer for object type: {obj_type}")
                continue

            # Normalize
            normalizer = normalizer_class()
            tables = normalizer.normalize(raw_records)

            for table_name, rows in tables.items():
                all_tables[table_name] = rows
                record_counts[table_name] = len(rows)

                # Save to disk
                if save_to_disk:
                    self._save_table(normalized_dir, table_name, rows, output_format)

        # Update normalization timestamp
        job.normalized_at = datetime.utcnow()
        self.db.commit()

        # Upload to MinIO if requested
        uploaded = False
        if upload_to_minio and all_tables:
            try:
                self.job_service.update_job_status(scan_id, JobStatus.UPLOADING_TO_MINIO)
                uploaded = self._upload_tables(scan_id, job.organization_id, all_tables, output_format)
                job.minio_uploaded_at = datetime.utcnow()
                self.db.commit()
            except Exception as exc:
                logger.error(f"[{scan_id}] MinIO upload failed: {exc}")

        # Complete the job
        try:
            self.job_service.complete_job(scan_id, record_counts)
        except Exception as exc:
            logger.error(f"[{scan_id}] Failed to complete job: {exc}")

        return {
            "scan_id": scan_id,
            "status": "completed",
            "tables_produced": list(all_tables.keys()),
            "record_counts": record_counts,
            "output_format": output_format,
            "uploaded_to_minio": uploaded,
            "message": f"Normalized {len(all_tables)} tables with {sum(record_counts.values())} total records",
        }

    def list_normalized_tables(self, scan_id: str) -> List[Dict[str, Any]]:
        """
        List normalized table files for a scan.

        Returns list of dicts with table_name, file_path, file_size_bytes.
        """
        data_dir = self._get_scan_data_dir(scan_id)
        normalized_dir = os.path.join(data_dir, "normalized")

        tables = []
        if os.path.exists(normalized_dir):
            for filename in os.listdir(normalized_dir):
                filepath = os.path.join(normalized_dir, filename)
                if os.path.isfile(filepath):
                    table_name = os.path.splitext(filename)[0]
                    tables.append({
                        "table_name": table_name,
                        "file_path": filepath,
                        "file_size_bytes": os.path.getsize(filepath),
                    })

        return tables

    @staticmethod
    def get_supported_objects() -> List[Dict[str, Any]]:
        """Return the static catalog of supported HubSpot objects and their output tables."""
        return SUPPORTED_OBJECTS_CATALOG

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _get_scan_data_dir(self, scan_id: str) -> str:
        return os.path.join(self._settings.DATA_DIR, scan_id)

    def _save_table(
        self,
        output_dir: str,
        table_name: str,
        rows: List[Dict[str, Any]],
        output_format: str,
    ) -> str:
        """Save a normalized table to disk in the requested format."""
        if output_format == "parquet":
            return self._save_as_parquet(output_dir, table_name, rows)
        else:
            return self._save_as_json(output_dir, table_name, rows)

    def _save_as_json(
        self, output_dir: str, table_name: str, rows: List[Dict[str, Any]]
    ) -> str:
        """Save table as JSON file."""
        filepath = os.path.join(output_dir, f"{table_name}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(rows, f, default=str, indent=2)
        logger.debug(f"Saved {len(rows)} rows to {filepath}")
        return filepath

    def _save_as_parquet(
        self, output_dir: str, table_name: str, rows: List[Dict[str, Any]]
    ) -> str:
        """Save table as Parquet file using pandas + pyarrow."""
        import pandas as pd

        filepath = os.path.join(output_dir, f"{table_name}.parquet")
        df = pd.DataFrame(rows)
        df.to_parquet(filepath, engine="pyarrow", index=False)
        logger.debug(f"Saved {len(rows)} rows to {filepath}")
        return filepath

    def _upload_tables(
        self,
        scan_id: str,
        organization_id: str,
        tables: Dict[str, List[Dict[str, Any]]],
        output_format: str,
    ) -> bool:
        """Upload normalized tables to MinIO."""
        import pandas as pd

        minio_client = MinIOClient()
        processing_date = date.today().isoformat()

        table_bytes: Dict[str, bytes] = {}
        for table_name, rows in tables.items():
            if output_format == "parquet":
                df = pd.DataFrame(rows)
                buffer = io.BytesIO()
                df.to_parquet(buffer, engine="pyarrow", index=False)
                table_bytes[table_name] = buffer.getvalue()
            else:
                table_bytes[table_name] = json.dumps(rows, default=str).encode("utf-8")

        results = minio_client.upload_normalized_data(
            scan_id=scan_id,
            organization_id=organization_id,
            processing_date=processing_date,
            tables=table_bytes,
        )

        all_success = all(results.values())
        if all_success:
            logger.info(f"[{scan_id}] All tables uploaded to MinIO")
        else:
            failed = [k for k, v in results.items() if not v]
            logger.error(f"[{scan_id}] Failed to upload tables: {failed}")

        return all_success
