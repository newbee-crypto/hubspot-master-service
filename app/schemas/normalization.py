"""
Pydantic schemas for normalization endpoints.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class NormalizeRequest(BaseModel):
    """Request body for POST /normalization/{scan_id}/normalize."""
    format: str = Field(
        default="parquet",
        description="Output format: 'parquet' or 'json'",
    )
    save_to_disk: bool = Field(
        default=True,
        description="Whether to save normalized files to local disk",
    )
    upload_to_minio: bool = Field(
        default=True,
        description="Whether to upload normalized files to MinIO",
    )


class NormalizeResponse(BaseModel):
    """Response for POST /normalization/{scan_id}/normalize."""
    scan_id: str
    status: str
    tables_produced: List[str] = []
    record_counts: Dict[str, int] = {}
    output_format: str = "parquet"
    uploaded_to_minio: bool = False
    message: str = ""


class TableInfo(BaseModel):
    """Info about a single normalized table file."""
    table_name: str
    file_path: str
    file_size_bytes: Optional[int] = None
    record_count: Optional[int] = None


class NormalizedTablesResponse(BaseModel):
    """Response for GET /normalization/{scan_id}/tables."""
    scan_id: str
    tables: List[TableInfo] = []


class ObjectTableMapping(BaseModel):
    """Mapping of a HubSpot object type to its output tables."""
    object_type: str
    output_tables: List[str]
    description: str = ""


class SupportedObjectsResponse(BaseModel):
    """Response for GET /normalization/supported-objects."""
    supported_objects: List[ObjectTableMapping]
