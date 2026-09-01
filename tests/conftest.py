"""
Shared test fixtures.

Uses SQLite in-memory for tests (no PostgreSQL dependency).
JSONB columns fall back to JSON type in SQLite.
"""

import os
import sys
import pytest

# Ensure app is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Override settings BEFORE any app imports
os.environ["DATABASE_URL"] = "sqlite:///test.db"
os.environ["HMAC_ENABLED"] = "false"
os.environ["APP_ENV"] = "development"
os.environ["MINIO_ENDPOINT"] = "localhost:9000"

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Job, JobCheckpoint, AuditLog, FailedExternalCall


# SQLite engine for tests
TEST_ENGINE = create_engine("sqlite:///test.db", echo=False)
TestSession = sessionmaker(bind=TEST_ENGINE, autocommit=False, autoflush=False)


@pytest.fixture(autouse=True)
def setup_db():
    """Create all tables before each test, drop after."""
    # SQLite doesn't support PostgreSQL JSONB — the models use generic JSON fallback
    Base.metadata.create_all(bind=TEST_ENGINE)
    yield
    Base.metadata.drop_all(bind=TEST_ENGINE)
    if os.path.exists("test.db"):
        try:
            os.remove("test.db")
        except Exception:
            pass


@pytest.fixture
def db_session():
    """Yield a test DB session."""
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def sample_hubspot_contacts():
    """Sample raw HubSpot contact records."""
    return [
        {
            "id": "101",
            "createdAt": "2024-01-01T00:00:00Z",
            "updatedAt": "2024-06-01T00:00:00Z",
            "properties": {
                "firstname": "John",
                "lastname": "Doe",
                "email": "john@example.com",
                "phone": "555-0100",
                "company": "Acme Inc",
                "jobtitle": "Engineer",
                "lifecyclestage": "lead",
                "hs_lead_status": "NEW",
                "createdate": "2024-01-01T00:00:00Z",
                "lastmodifieddate": "2024-06-01T00:00:00Z",
            },
        },
        {
            "id": "102",
            "createdAt": "2024-02-01T00:00:00Z",
            "updatedAt": "2024-07-01T00:00:00Z",
            "properties": {
                "firstname": "Jane",
                "lastname": "Smith",
                "email": "jane@example.com",
                "phone": None,
                "company": "Beta Corp",
                "jobtitle": "Manager",
                "lifecyclestage": "customer",
                "hs_lead_status": "CONNECTED",
                "createdate": "2024-02-01T00:00:00Z",
                "lastmodifieddate": "2024-07-01T00:00:00Z",
            },
        },
    ]


@pytest.fixture
def sample_hubspot_deals():
    """Sample raw HubSpot deal records with associations."""
    return [
        {
            "id": "201",
            "createdAt": "2024-03-01T00:00:00Z",
            "updatedAt": "2024-08-01T00:00:00Z",
            "properties": {
                "dealname": "Big Deal",
                "dealstage": "closedwon",
                "pipeline": "default",
                "amount": "50000",
                "closedate": "2024-07-15T00:00:00Z",
                "createdate": "2024-03-01T00:00:00Z",
                "lastmodifieddate": "2024-08-01T00:00:00Z",
                "hs_deal_stage_probability": "1.0",
                "dealtype": "newbusiness",
            },
            "associations": {
                "contacts": {
                    "results": [
                        {"id": "101", "type": "deal_to_contact"},
                    ]
                },
                "companies": {
                    "results": [
                        {"id": "301", "type": "deal_to_company"},
                    ]
                },
            },
        },
    ]


@pytest.fixture
def sample_hubspot_owners():
    """Sample raw HubSpot owner records (flat structure)."""
    return [
        {
            "id": "501",
            "email": "owner@example.com",
            "firstName": "Alice",
            "lastName": "Owner",
            "userId": 12345,
            "createdAt": "2024-01-01T00:00:00Z",
            "updatedAt": "2024-06-01T00:00:00Z",
            "archived": False,
            "teams": [{"id": 1, "name": "Sales"}],
        },
    ]
