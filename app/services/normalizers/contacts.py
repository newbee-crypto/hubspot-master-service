"""
Contact normalizer (§10.4).

Flattens raw HubSpot Contact records into a clean 'contacts' table.
"""

import logging
from typing import Any, Dict, List

from app.services.normalizers.base import BaseNormalizer

logger = logging.getLogger(__name__)

# Properties to extract from Contact records
CONTACT_PROPERTIES = [
    "firstname",
    "lastname",
    "email",
    "phone",
    "company",
    "jobtitle",
    "lifecyclestage",
    "hs_lead_status",
    "createdate",
    "lastmodifieddate",
]


class ContactNormalizer(BaseNormalizer):
    """Normalizes raw HubSpot Contact records into the 'contacts' table."""

    def normalize(self, records: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Normalize Contact records.

        Returns:
            {"contacts": [flat contact rows]}
        """
        contacts = []
        for record in records:
            row = {
                "id": self._get_record_id(record),
                "created_at": self._get_created_at(record),
                "updated_at": self._get_updated_at(record),
            }
            row.update(self._extract_properties(record, CONTACT_PROPERTIES))
            contacts.append(row)

        logger.info(f"Normalized {len(contacts)} contacts")
        return {"contacts": contacts}
