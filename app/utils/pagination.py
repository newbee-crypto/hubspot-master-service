"""
Pagination utility (§10.10).
Standard pagination envelope for list endpoints.
"""

import math
from typing import Any, Dict, List, Optional


def build_pagination_info(
    page: int,
    page_size: int,
    total: int,
) -> Dict[str, Any]:
    """
    Build a standard pagination info envelope.

    Args:
        page: Current page number (1-indexed).
        page_size: Number of items per page.
        total: Total number of items.

    Returns:
        Dict with pagination metadata.
    """
    total_pages = math.ceil(total / page_size) if page_size > 0 else 0
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_previous": page > 1,
    }


def paginate_list(
    items: List[Any],
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """
    Paginate a list of items in-memory.

    Returns dict with 'items' and 'pagination' keys.
    """
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    total = len(items)

    start = (page - 1) * page_size
    end = start + page_size

    return {
        "items": items[start:end],
        "pagination": build_pagination_info(page, page_size, total),
    }
