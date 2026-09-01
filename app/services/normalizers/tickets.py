"""
Ticket normalizer (§10.4).

Flattens raw HubSpot Ticket records into a clean 'tickets' table.
"""

import logging
from typing import Any, Dict, List

from app.services.normalizers.base import BaseNormalizer

logger = logging.getLogger(__name__)

TICKET_PROPERTIES = [
    "subject",
    "content",
    "hs_pipeline",
    "hs_pipeline_stage",
    "hs_ticket_priority",
    "hs_ticket_category",
    "createdate",
    "lastmodifieddate",
]


class TicketNormalizer(BaseNormalizer):
    """Normalizes raw HubSpot Ticket records into the 'tickets' table."""

    def normalize(self, records: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Normalize Ticket records.

        Returns:
            {"tickets": [flat ticket rows]}
        """
        tickets = []
        for record in records:
            row = {
                "id": self._get_record_id(record),
                "created_at": self._get_created_at(record),
                "updated_at": self._get_updated_at(record),
            }
            row.update(self._extract_properties(record, TICKET_PROPERTIES))
            tickets.append(row)

        logger.info(f"Normalized {len(tickets)} tickets")
        return {"tickets": tickets}
