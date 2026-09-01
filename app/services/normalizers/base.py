"""
Base normalizer interface (§10.4).

All per-object normalizers inherit from this base class and implement
the normalize() method, which transforms raw HubSpot records into
one or more clean relational tables.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class BaseNormalizer(ABC):
    """
    Abstract base class for HubSpot object normalizers.

    Each normalizer converts a list of raw HubSpot API records into
    a dict mapping table_name -> list of flat row dicts.
    """

    @abstractmethod
    def normalize(self, records: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Normalize raw HubSpot records into clean relational tables.

        Args:
            records: List of raw HubSpot API record dicts.

        Returns:
            Dict mapping table_name to a list of flat row dicts.
            e.g., {"contacts": [{"id": "1", "email": "a@b.com", ...}, ...]}
        """
        pass

    def _extract_properties(
        self,
        record: Dict[str, Any],
        property_keys: List[str],
    ) -> Dict[str, Any]:
        """
        Extract properties from a HubSpot record's 'properties' dict.

        HubSpot records nest data under record["properties"][key].
        This helper pulls them into a flat dict.
        """
        properties = record.get("properties", {})
        result = {}
        for key in property_keys:
            result[key] = properties.get(key)
        return result

    def _get_record_id(self, record: Dict[str, Any]) -> Optional[str]:
        """Extract the record ID from a HubSpot record."""
        return record.get("id")

    def _get_created_at(self, record: Dict[str, Any]) -> Optional[str]:
        """Extract createdAt from a HubSpot record."""
        return record.get("createdAt") or record.get("properties", {}).get("createdate")

    def _get_updated_at(self, record: Dict[str, Any]) -> Optional[str]:
        """Extract updatedAt from a HubSpot record."""
        return record.get("updatedAt") or record.get("properties", {}).get("lastmodifieddate")

    def _extract_associations(
        self, record: Dict[str, Any], association_type: str
    ) -> List[Dict[str, Any]]:
        """
        Extract association records from a HubSpot record.

        HubSpot stores associations under record["associations"][type]["results"].
        """
        associations = record.get("associations", {})
        type_data = associations.get(association_type, {})
        return type_data.get("results", [])
