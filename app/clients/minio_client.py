"""
MinIO storage client (§10.4).

Handles:
- Bucket existence checking and creation
- File upload
- Normalized data upload with path convention:
  hubspot/{table_name}/glynac_organization_id={org_id}/processing_date={date}/{table}.parquet

Credentials come from environment configuration, never hard-coded.
"""

import io
import logging
import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from minio import Minio
from minio.error import S3Error

from app.config import get_settings

logger = logging.getLogger(__name__)


class MinIOClient:
    """
    MinIO storage client for uploading normalized data.
    """

    def __init__(self):
        settings = get_settings()
        self._client = Minio(
            endpoint=settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        self._bucket = settings.MINIO_BUCKET

    def ensure_bucket_exists(self) -> bool:
        """
        Check if the configured bucket exists; create it if not.

        Returns True if bucket exists or was created successfully.
        """
        try:
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)
                logger.info(f"Created MinIO bucket: {self._bucket}")
            return True
        except S3Error as e:
            logger.error(f"Failed to ensure bucket exists: {e}")
            return False

    def upload_file(self, local_path: str, object_key: str) -> bool:
        """
        Upload a local file to MinIO.

        Args:
            local_path: Path to the local file.
            object_key: Destination key in the bucket.

        Returns:
            True on success, False on failure.
        """
        try:
            self.ensure_bucket_exists()
            file_size = os.path.getsize(local_path)

            with open(local_path, "rb") as f:
                self._client.put_object(
                    bucket_name=self._bucket,
                    object_name=object_key,
                    data=f,
                    length=file_size,
                )

            logger.info(f"Uploaded {local_path} → {self._bucket}/{object_key}")
            return True
        except Exception as e:
            logger.error(f"Failed to upload {local_path}: {e}")
            return False

    def upload_bytes(self, data: bytes, object_key: str, content_type: str = "application/octet-stream") -> bool:
        """
        Upload bytes data to MinIO.

        Args:
            data: The bytes to upload.
            object_key: Destination key in the bucket.
            content_type: MIME type of the data.

        Returns:
            True on success, False on failure.
        """
        try:
            self.ensure_bucket_exists()
            data_stream = io.BytesIO(data)

            self._client.put_object(
                bucket_name=self._bucket,
                object_name=object_key,
                data=data_stream,
                length=len(data),
                content_type=content_type,
            )

            logger.info(f"Uploaded {len(data)} bytes → {self._bucket}/{object_key}")
            return True
        except Exception as e:
            logger.error(f"Failed to upload bytes to {object_key}: {e}")
            return False

    def upload_normalized_data(
        self,
        scan_id: str,
        organization_id: str,
        processing_date: str,
        tables: Dict[str, bytes],
    ) -> Dict[str, bool]:
        """
        Upload normalized table data to MinIO following the path convention.

        Path convention per DESIGN.md:
        hubspot/{table_name}/glynac_organization_id={org_id}/processing_date={date}/{table}.parquet

        Args:
            scan_id: The scan identifier.
            organization_id: The organization identifier.
            processing_date: Processing date string (YYYY-MM-DD).
            tables: Dict mapping table_name → parquet bytes.

        Returns:
            Dict mapping table_name → success boolean.
        """
        results = {}

        for table_name, data in tables.items():
            object_key = (
                f"hubspot/{table_name}/"
                f"glynac_organization_id={organization_id}/"
                f"processing_date={processing_date}/"
                f"{table_name}.parquet"
            )
            results[table_name] = self.upload_bytes(
                data, object_key, content_type="application/octet-stream"
            )

        uploaded = sum(1 for v in results.values() if v)
        logger.info(
            f"Uploaded {uploaded}/{len(tables)} tables for scan {scan_id} "
            f"(org={organization_id}, date={processing_date})"
        )
        return results

    def check_health(self) -> bool:
        """Check MinIO connectivity for health endpoint."""
        try:
            self._client.list_buckets()
            return True
        except Exception:
            return False
