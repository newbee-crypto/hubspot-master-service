"""Tests for normalizers."""

from app.services.normalizers.contacts import ContactNormalizer
from app.services.normalizers.companies import CompanyNormalizer
from app.services.normalizers.deals import DealNormalizer
from app.services.normalizers.tickets import TicketNormalizer
from app.services.normalizers.owners import OwnerNormalizer


class TestContactNormalizer:
    def test_normalize_contacts(self, sample_hubspot_contacts):
        normalizer = ContactNormalizer()
        result = normalizer.normalize(sample_hubspot_contacts)
        assert "contacts" in result
        assert len(result["contacts"]) == 2
        assert result["contacts"][0]["id"] == "101"
        assert result["contacts"][0]["email"] == "john@example.com"
        assert result["contacts"][1]["firstname"] == "Jane"

    def test_normalize_empty(self):
        normalizer = ContactNormalizer()
        result = normalizer.normalize([])
        assert result == {"contacts": []}


class TestCompanyNormalizer:
    def test_normalize_companies(self):
        records = [{
            "id": "301",
            "createdAt": "2024-01-01T00:00:00Z",
            "updatedAt": "2024-06-01T00:00:00Z",
            "properties": {
                "name": "Acme Inc",
                "domain": "acme.com",
                "industry": "Technology",
                "numberofemployees": "100",
                "annualrevenue": "10000000",
                "city": "SF",
                "state": "CA",
                "country": "US",
                "phone": "555-0000",
                "createdate": "2024-01-01T00:00:00Z",
                "lastmodifieddate": "2024-06-01T00:00:00Z",
            },
        }]
        normalizer = CompanyNormalizer()
        result = normalizer.normalize(records)
        assert len(result["companies"]) == 1
        assert result["companies"][0]["name"] == "Acme Inc"
        assert result["companies"][0]["domain"] == "acme.com"


class TestDealNormalizer:
    def test_normalize_deals_with_associations(self, sample_hubspot_deals):
        normalizer = DealNormalizer()
        result = normalizer.normalize(sample_hubspot_deals)
        assert "deals" in result
        assert "deal_associations" in result
        assert "deal_line_items" in result
        assert len(result["deals"]) == 1
        assert result["deals"][0]["dealname"] == "Big Deal"
        assert result["deals"][0]["amount"] == "50000"
        # Associations
        assert len(result["deal_associations"]) == 2
        assert result["deal_associations"][0]["to_object_type"] == "contacts"
        assert result["deal_associations"][1]["to_object_type"] == "companies"


class TestTicketNormalizer:
    def test_normalize_tickets(self):
        records = [{
            "id": "401",
            "createdAt": "2024-04-01T00:00:00Z",
            "updatedAt": "2024-09-01T00:00:00Z",
            "properties": {
                "subject": "Login issue",
                "content": "Cannot login",
                "hs_pipeline": "support",
                "hs_pipeline_stage": "open",
                "hs_ticket_priority": "HIGH",
                "hs_ticket_category": "bug",
                "createdate": "2024-04-01T00:00:00Z",
                "lastmodifieddate": "2024-09-01T00:00:00Z",
            },
        }]
        normalizer = TicketNormalizer()
        result = normalizer.normalize(records)
        assert len(result["tickets"]) == 1
        assert result["tickets"][0]["subject"] == "Login issue"
        assert result["tickets"][0]["hs_ticket_priority"] == "HIGH"


class TestOwnerNormalizer:
    def test_normalize_owners(self, sample_hubspot_owners):
        normalizer = OwnerNormalizer()
        result = normalizer.normalize(sample_hubspot_owners)
        assert len(result["owners"]) == 1
        owner = result["owners"][0]
        assert owner["email"] == "owner@example.com"
        assert owner["first_name"] == "Alice"
        assert owner["team_ids"] == "1"
        assert owner["team_names"] == "Sales"

    def test_normalize_owner_no_teams(self):
        records = [{"id": "502", "email": "solo@example.com", "firstName": "Bob",
                     "lastName": "Solo", "userId": 99, "createdAt": "2024-01-01",
                     "updatedAt": "2024-01-01", "archived": False}]
        normalizer = OwnerNormalizer()
        result = normalizer.normalize(records)
        assert result["owners"][0]["team_ids"] is None
