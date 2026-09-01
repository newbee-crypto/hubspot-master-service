"""
Duration calculation utility (§10.10).
ISO datetime diff in seconds for job duration reporting.
"""

from datetime import datetime
from typing import Optional


def calculate_duration(start: Optional[datetime], end: Optional[datetime]) -> Optional[float]:
    """
    Calculate duration in seconds between two datetimes.

    Returns None if either timestamp is missing.
    """
    if start is None or end is None:
        return None
    delta = end - start
    return round(delta.total_seconds(), 2)


def format_duration(seconds: Optional[float]) -> Optional[str]:
    """
    Format a duration in seconds into a human-readable string.

    Examples: "2m 30s", "1h 15m 0s", "45s"
    """
    if seconds is None:
        return None

    seconds = int(seconds)
    if seconds < 0:
        return "0s"

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0 or hours > 0:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")

    return " ".join(parts)
