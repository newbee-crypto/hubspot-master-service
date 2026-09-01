"""
Deal normalizer (§10.4).

Flattens raw HubSpot Deal records into:
- 'deals' table (main deal properties)
- 'deal_associations' table (deal → contact/company associations)
- 'deal_line_items' table (line items associated with deals)
"""

import logging
from typing import Any, Dict, List

from app.services.normalizers.base import BaseNormalizer

logger = logging.getLogger(__name__)

DEAL_PROPERTIES = [
    "dealname",
    "dealstage",
    "pipeline",
    "amount",
    "closedate",
    "createdate",
    "lastmodifieddate",
    "hs_deal_stage_probability",
    "dealtype",
]


class DealNormalizer(BaseNormalizer):
    """Normalizes raw HubSpot Deal records into deals, associations, and line items tables."""

    def normalize(self, records: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Normalize Deal records.

        Returns:
            {
                "deals": [flat deal rows],
                "deal_associations": [association rows],
                "deal_line_items": [line item rows],
            }
        """
        deals = []
        associations = []
        line_items = []

        for record in records:
            deal_id = self._get_record_id(record)

            # Main deal row
            row = {
                "id": deal_id,
                "created_at": self._get_created_at(record),
                "updated_at": self._get_updated_at(record),
            }
            row.update(self._extract_properties(record, DEAL_PROPERTIES))
            deals.append(row)

            # Extract associations (contacts, companies)
            for assoc_type in ["contacts", "companies"]:
                assoc_records = self._extract_associations(record, assoc_type)
                for assoc in assoc_records:
                    associations.append({
                        "deal_id": deal_id,
                        "to_object_type": assoc_type,
                        "to_object_id": assoc.get("id"),
                        "association_type": assoc.get("type", ""),
                    })

            # Extract line items if present
            li_records = self._extract_associations(record, "line_items")
            for li in li_records:
                line_items.append({
                    "deal_id": deal_id,
                    "line_item_id": li.get("id"),
                    "association_type": li.get("type", ""),
                })

        logger.info(
            f"Normalized {len(deals)} deals, "
            f"{len(associations)} associations, "
            f"{len(line_items)} line items"
        )

        return {
            "deals": deals,
            "deal_associations": associations,
            "deal_line_items": line_items,
        }
