"""Tests for health endpoint."""

import os
os.environ["DATABASE_URL"] = "sqlite:///test.db"
os.environ["HMAC_ENABLED"] = "false"

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_root():
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert "service" in data
    assert data["service"] == "HubSpot Master Service"


def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "components" in data
    assert "timestamp" in data
