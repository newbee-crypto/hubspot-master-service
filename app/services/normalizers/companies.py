"""
Company normalizer (§10.4).

Flattens raw HubSpot Company records into a clean 'companies' table.
"""

import logging
from typing import Any, Dict, List

from app.services.normalizers.base import BaseNormalizer

logger = logging.getLogger(__name__)

COMPANY_PROPERTIES = [
    "name",
    "domain",
    "industry",
    "numberofemployees",
    "annualrevenue",
    "city",
    "state",
    "country",
    "phone",
    "createdate",
    "lastmodifieddate",
]


class CompanyNormalizer(BaseNormalizer):
    """Normalizes raw HubSpot Company records into the 'companies' table."""

    def normalize(self, records: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Normalize Company records.

        Returns:
            {"companies": [flat company rows]}
        """
        companies = []
        for record in records:
            row = {
                "id": self._get_record_id(record),
                "created_at": self._get_created_at(record),
                "updated_at": self._get_updated_at(record),
            }
            row.update(self._extract_properties(record, COMPANY_PROPERTIES))
            companies.append(row)

        logger.info(f"Normalized {len(companies)} companies")
        return {"companies": companies}
