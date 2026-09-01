"""Tests for scan API endpoints."""

import os
os.environ["DATABASE_URL"] = "sqlite:///test.db"
os.environ["HMAC_ENABLED"] = "false"

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_list_scans():
    resp = client.get("/api/scan/list")
    assert resp.status_code == 200
    data = resp.json()
    assert "scans" in data
    assert "pagination" in data


def test_scan_statistics():
    resp = client.get("/api/scan/statistics")
    assert resp.status_code == 200
    data = resp.json()
    assert "statistics" in data


def test_get_scan_status_not_found():
    resp = client.get("/api/scan/nonexistent/status")
    assert resp.status_code == 404


def test_pause_scan_not_found():
    resp = client.post("/api/scan/nonexistent/pause")
    assert resp.status_code == 404


def test_cancel_scan_not_found():
    resp = client.post("/api/scan/nonexistent/cancel")
    assert resp.status_code == 404


def test_remove_scan_not_found():
    resp = client.delete("/api/scan/nonexistent/remove")
    assert resp.status_code == 404


def test_supported_objects():
    resp = client.get("/api/normalization/supported-objects")
    assert resp.status_code == 200
    data = resp.json()
    assert "supported_objects" in data
    types = [o["object_type"] for o in data["supported_objects"]]
    assert "contacts" in types
    assert "deals" in types
