"""
Deep serialization utility (§10.10).
Recursively converts Decimals, UUIDs, Enums, datetimes, and other
non-JSON-native types into JSON-safe structures for API responses.
"""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def deep_serialize(obj: Any) -> Any:
    """
    Recursively convert an object into a JSON-serializable structure.

    Handles: Decimal, UUID, Enum, datetime, date, sets, SQLAlchemy-style
    objects with __dict__, and nested dicts/lists.
    """
    if obj is None:
        return None

    if isinstance(obj, (str, int, float, bool)):
        return obj

    if isinstance(obj, Decimal):
        # Preserve precision for financial data
        if obj == obj.to_integral_value():
            return int(obj)
        return float(obj)

    if isinstance(obj, uuid.UUID):
        return str(obj)

    if isinstance(obj, enum.Enum):
        return obj.value

    if isinstance(obj, datetime):
        return obj.isoformat()

    if isinstance(obj, date):
        return obj.isoformat()

    if isinstance(obj, (set, frozenset)):
        return [deep_serialize(item) for item in obj]

    if isinstance(obj, (list, tuple)):
        return [deep_serialize(item) for item in obj]

    if isinstance(obj, dict):
        return {str(k): deep_serialize(v) for k, v in obj.items()}

    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")

    # Handle objects with __dict__ (e.g., SQLAlchemy models)
    if hasattr(obj, "__dict__"):
        result = {}
        for key, value in obj.__dict__.items():
            if not key.startswith("_"):
                result[key] = deep_serialize(value)
        return result

    # Fallback
    return str(obj)
