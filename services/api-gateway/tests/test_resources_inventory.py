"""Tests for GET /api/v1/resources/inventory — flat resource listing.

Tests cover:
- list_resources route: success response shape with resources + resourceTypes
- ARG rows → response items mapping (id, name, type, location)
- resourceTypes derived from distinct type values sorted alphabetically
- Empty subscription list returns empty resources
- ARG failure returns 500
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")


@pytest.fixture()
def client():
    from services.api_gateway.main import app
    app.state.credential = MagicMock(name="DefaultAzureCredential")
    app.state.cosmos_client = None
    return TestClient(app)


def _arg_row(name: str, rtype: str, rg: str = "rg-prod", sub: str = "sub1", loc: str = "eastus") -> dict:
    return {
        "id": f"/subscriptions/{sub}/resourceGroups/{rg}/providers/{rtype}/{name}",
        "name": name,
        "type": rtype,
        "resourceGroup": rg,
        "subscriptionId": sub,
        "location": loc,
    }


def test_list_resources_success(client):
    rows = [
        _arg_row("vm-001", "microsoft.compute/virtualmachines"),
        _arg_row("kv-001", "microsoft.keyvault/vaults"),
        _arg_row("vm-002", "microsoft.compute/virtualmachines"),
    ]
    with patch(
        "services.api_gateway.resources_inventory.run_arg_query",
        return_value=rows,
    ):
        resp = client.get("/api/v1/resources/inventory?subscriptions=sub1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["resources"]) == 3
    assert data["total"] == 3


def test_list_resources_response_shape(client):
    rows = [_arg_row("vm-001", "microsoft.compute/virtualmachines")]
    with patch(
        "services.api_gateway.resources_inventory.run_arg_query",
        return_value=rows,
    ):
        resp = client.get("/api/v1/resources/inventory?subscriptions=sub1")
    item = resp.json()["resources"][0]
    assert "id" in item
    assert "name" in item
    assert "type" in item
    assert "location" in item


def test_list_resources_types_sorted(client):
    rows = [
        _arg_row("kv-001", "microsoft.keyvault/vaults"),
        _arg_row("vm-001", "microsoft.compute/virtualmachines"),
    ]
    with patch(
        "services.api_gateway.resources_inventory.run_arg_query",
        return_value=rows,
    ):
        resp = client.get("/api/v1/resources/inventory?subscriptions=sub1")
    types = resp.json()["resourceTypes"]
    assert types == sorted(types)
    assert "microsoft.compute/virtualmachines" in types
    assert "microsoft.keyvault/vaults" in types


def test_list_resources_empty_subscriptions(client):
    with patch(
        "services.api_gateway.resources_inventory.run_arg_query",
        return_value=[],
    ):
        resp = client.get("/api/v1/resources/inventory")
    assert resp.status_code == 200
    data = resp.json()
    assert data["resources"] == []
    assert data["total"] == 0
    assert data["resourceTypes"] == []


def test_list_resources_arg_failure_returns_500(client):
    with patch(
        "services.api_gateway.resources_inventory.run_arg_query",
        side_effect=Exception("ARG unavailable"),
    ):
        resp = client.get("/api/v1/resources/inventory?subscriptions=sub1")
    assert resp.status_code == 500
