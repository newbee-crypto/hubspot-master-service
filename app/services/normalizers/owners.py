"""
Owner normalizer (§10.4).

Flattens raw HubSpot Owner records into a clean 'owners' table.
Owners have a slightly different structure than other CRM objects.
"""

import logging
from typing import Any, Dict, List

from app.services.normalizers.base import BaseNormalizer

logger = logging.getLogger(__name__)


class OwnerNormalizer(BaseNormalizer):
    """Normalizes raw HubSpot Owner records into the 'owners' table."""

    def normalize(self, records: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Normalize Owner records.

        Owners have a flat structure (not nested under 'properties'
        like other CRM objects), so we handle them directly.

        Returns:
            {"owners": [flat owner rows]}
        """
        owners = []
        for record in records:
            # Owners are flat — fields are top-level, not under 'properties'
            row = {
                "id": record.get("id"),
                "email": record.get("email"),
                "first_name": record.get("firstName"),
                "last_name": record.get("lastName"),
                "user_id": record.get("userId"),
                "created_at": record.get("createdAt"),
                "updated_at": record.get("updatedAt"),
                "archived": record.get("archived", False),
            }

            # Some owner records also have teams
            teams = record.get("teams", [])
            if teams:
                row["team_ids"] = ",".join(str(t.get("id", "")) for t in teams)
                row["team_names"] = ",".join(t.get("name", "") for t in teams)
            else:
                row["team_ids"] = None
                row["team_names"] = None

            owners.append(row)

        logger.info(f"Normalized {len(owners)} owners")
        return {"owners": owners}
