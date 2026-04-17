from __future__ import annotations
"""Tests for GET /api/v1/topology/tree — hierarchical resource tree.

Tests cover:
- tree response shape: nodes list + edges list
- subscription/resourceGroup/resource node kinds
- parentId linking (sub → rg → resource)
- resourceCount on resourceGroup nodes equals actual child count
- ARG failure returns 500
- Empty subscriptions returns empty nodes/edges
"""
import os

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


def _arg_row(
    name: str,
    rtype: str,
    rg: str,
    sub: str,
    loc: str = "eastus",
) -> dict:
    return {
        "id": f"/subscriptions/{sub}/resourceGroups/{rg}/providers/{rtype}/{name}",
        "name": name,
        "type": rtype,
        "resourceGroup": rg,
        "subscriptionId": sub,
        "location": loc,
    }


def _sub_row(sub_id: str, display_name: str) -> dict:
    return {"subscriptionId": sub_id, "displayName": display_name}


def test_tree_response_has_nodes_and_edges(client):
    rows = [_arg_row("vm-001", "microsoft.compute/virtualmachines", "rg-prod", "sub1")]
    sub_rows = [_sub_row("sub1", "My Sub")]
    with patch("services.api_gateway.topology_tree.run_arg_query", side_effect=[sub_rows, rows]):
        resp = client.get("/api/v1/topology/tree?subscriptions=sub1")
    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data
    assert "edges" in data


def test_tree_has_subscription_node(client):
    rows = [_arg_row("vm-001", "microsoft.compute/virtualmachines", "rg-prod", "sub1")]
    sub_rows = [_sub_row("sub1", "My Sub")]
    with patch("services.api_gateway.topology_tree.run_arg_query", side_effect=[sub_rows, rows]):
        resp = client.get("/api/v1/topology/tree?subscriptions=sub1")
    nodes = resp.json()["nodes"]
    sub_nodes = [n for n in nodes if n["kind"] == "subscription"]
    assert len(sub_nodes) == 1
    assert sub_nodes[0]["label"] == "My Sub"
    assert sub_nodes[0]["parentId"] is None


def test_tree_has_resource_group_node(client):
    rows = [_arg_row("vm-001", "microsoft.compute/virtualmachines", "rg-prod", "sub1")]
    sub_rows = [_sub_row("sub1", "My Sub")]
    with patch("services.api_gateway.topology_tree.run_arg_query", side_effect=[sub_rows, rows]):
        resp = client.get("/api/v1/topology/tree?subscriptions=sub1")
    nodes = resp.json()["nodes"]
    rg_nodes = [n for n in nodes if n["kind"] == "resourceGroup"]
    assert len(rg_nodes) == 1
    assert rg_nodes[0]["label"] == "rg-prod"
    assert rg_nodes[0]["resourceCount"] == 1


def test_tree_has_resource_node(client):
    rows = [_arg_row("vm-001", "microsoft.compute/virtualmachines", "rg-prod", "sub1")]
    sub_rows = [_sub_row("sub1", "My Sub")]
    with patch("services.api_gateway.topology_tree.run_arg_query", side_effect=[sub_rows, rows]):
        resp = client.get("/api/v1/topology/tree?subscriptions=sub1")
    nodes = resp.json()["nodes"]
    res_nodes = [n for n in nodes if n["kind"] == "resource"]
    assert len(res_nodes) == 1
    assert res_nodes[0]["label"] == "vm-001"
    assert res_nodes[0]["type"] == "microsoft.compute/virtualmachines"


def test_tree_edges_link_sub_to_rg_to_resource(client):
    rows = [_arg_row("vm-001", "microsoft.compute/virtualmachines", "rg-prod", "sub1")]
    sub_rows = [_sub_row("sub1", "My Sub")]
    with patch("services.api_gateway.topology_tree.run_arg_query", side_effect=[sub_rows, rows]):
        resp = client.get("/api/v1/topology/tree?subscriptions=sub1")
    data = resp.json()
    edges = data["edges"]
    sub_node = next(n for n in data["nodes"] if n["kind"] == "subscription")
    rg_node = next(n for n in data["nodes"] if n["kind"] == "resourceGroup")
    res_node = next(n for n in data["nodes"] if n["kind"] == "resource")
    assert {"source": sub_node["id"], "target": rg_node["id"]} in edges
    assert {"source": rg_node["id"], "target": res_node["id"]} in edges
    assert rg_node["parentId"] == sub_node["id"]
    assert res_node["parentId"] == rg_node["id"]


def test_tree_resource_count_matches_children(client):
    rows = [
        _arg_row("vm-001", "microsoft.compute/virtualmachines", "rg-prod", "sub1"),
        _arg_row("vm-002", "microsoft.compute/virtualmachines", "rg-prod", "sub1"),
        _arg_row("kv-001", "microsoft.keyvault/vaults", "rg-prod", "sub1"),
    ]
    sub_rows = [_sub_row("sub1", "My Sub")]
    with patch("services.api_gateway.topology_tree.run_arg_query", side_effect=[sub_rows, rows]):
        resp = client.get("/api/v1/topology/tree?subscriptions=sub1")
    nodes = resp.json()["nodes"]
    rg_node = next(n for n in nodes if n["kind"] == "resourceGroup")
    resource_nodes = [n for n in nodes if n["kind"] == "resource"]
    assert rg_node["resourceCount"] == len(resource_nodes)


def test_tree_arg_failure_returns_500(client):
    sub_rows = [_sub_row("sub1", "My Sub")]
    with patch(
        "services.api_gateway.topology_tree.run_arg_query",
        side_effect=[sub_rows, Exception("ARG down")],
    ):
        resp = client.get("/api/v1/topology/tree?subscriptions=sub1")
    assert resp.status_code == 500


def test_tree_empty_subscriptions_returns_empty(client):
    with patch(
        "services.api_gateway.topology_tree.run_arg_query",
        side_effect=[[], []],
    ):
        resp = client.get("/api/v1/topology/tree")
    assert resp.status_code == 200
    data = resp.json()
    assert data["nodes"] == []
    assert data["edges"] == []
