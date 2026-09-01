"""
Per-object normalizers package.

Each normalizer flattens raw HubSpot records into clean relational tables.
"""

from app.services.normalizers.contacts import ContactNormalizer
from app.services.normalizers.companies import CompanyNormalizer
from app.services.normalizers.deals import DealNormalizer
from app.services.normalizers.tickets import TicketNormalizer
from app.services.normalizers.owners import OwnerNormalizer

# Registry mapping object types to their normalizer classes
NORMALIZER_REGISTRY = {
    "contacts": ContactNormalizer,
    "companies": CompanyNormalizer,
    "deals": DealNormalizer,
    "tickets": TicketNormalizer,
    "owners": OwnerNormalizer,
}

__all__ = [
    "ContactNormalizer",
    "CompanyNormalizer",
    "DealNormalizer",
    "TicketNormalizer",
    "OwnerNormalizer",
    "NORMALIZER_REGISTRY",
]
