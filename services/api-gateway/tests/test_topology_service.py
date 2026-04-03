"""Unit tests for topology service core (topology.py).

Tests cover:
- _extract_relationships: VM/NIC/subnet/VNet/resource-group relationship extraction
- TopologyDocument: Pydantic model validation
- TopologyClient.get_blast_radius: BFS with mock Cosmos reads
- TopologyClient.get_path: bidirectional BFS path finding
- TopologyClient.get_snapshot: single document read
- TopologyClient._row_to_document: ARG row → Cosmos document conversion
"""
from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from services.api_gateway.topology import (
    TopologyClient,
    TopologyDocument,
    TopologyRelationship,
    _build_bootstrap_kql,
    _build_incremental_kql,
    _extract_relationships,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_vm_row(
    vm_id: str = "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm1",
) -> Dict[str, Any]:
    return {
        "id": vm_id.lower(),
        "type": "microsoft.compute/virtualmachines",
        "resourceGroup": "rg1",
        "subscriptionId": "s1",
        "name": "vm1",
        "tags": {"env": "prod"},
        "properties": {
            "networkProfile": {
                "networkInterfaces": [
                    {
                        "id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.network/networkinterfaces/nic1"
                    }
                ]
            },
            "storageProfile": {
                "osDisk": {
                    "managedDisk": {
                        "id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/disks/osdisk1"
                    }
                },
                "dataDisks": [
                    {
                        "managedDisk": {
                            "id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/disks/datadisk1"
                        }
                    }
                ],
            },
        },
    }


def _make_nic_row() -> Dict[str, Any]:
    return {
        "id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.network/networkinterfaces/nic1",
        "type": "microsoft.network/networkinterfaces",
        "resourceGroup": "rg1",
        "subscriptionId": "s1",
        "name": "nic1",
        "tags": {},
        "properties": {
            "ipConfigurations": [
                {
                    "properties": {
                        "subnet": {
                            "id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.network/virtualnetworks/vnet1/subnets/default"
                        }
                    }
                }
            ]
        },
    }


def _make_subnet_row() -> Dict[str, Any]:
    return {
        "id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.network/virtualnetworks/vnet1/subnets/default",
        "type": "microsoft.network/subnets",
        "resourceGroup": "rg1",
        "subscriptionId": "s1",
        "name": "default",
        "tags": {},
        "properties": {},
    }


def _make_topology_client() -> TopologyClient:
    cosmos_mock = MagicMock()
    credential_mock = MagicMock()
    return TopologyClient(
        cosmos_client=cosmos_mock,
        credential=credential_mock,
        subscription_ids=["s1"],
    )


# ---------------------------------------------------------------------------
# _extract_relationships tests
# ---------------------------------------------------------------------------


class TestExtractRelationships:
    def test_vm_nic_relationship(self):
        row = _make_vm_row()
        rels = _extract_relationships(row)
        nic_rels = [r for r in rels if r["rel_type"] == "nic_of"]
        assert len(nic_rels) == 1
        assert "nic1" in nic_rels[0]["target_id"]
        assert nic_rels[0]["direction"] == "outbound"

    def test_vm_os_disk_relationship(self):
        row = _make_vm_row()
        rels = _extract_relationships(row)
        disk_rels = [r for r in rels if r["rel_type"] == "disk_of"]
        assert any("osdisk1" in r["target_id"] for r in disk_rels)

    def test_vm_data_disk_relationship(self):
        row = _make_vm_row()
        rels = _extract_relationships(row)
        disk_rels = [r for r in rels if r["rel_type"] == "disk_of"]
        assert any("datadisk1" in r["target_id"] for r in disk_rels)

    def test_vm_resource_group_member(self):
        row = _make_vm_row()
        rels = _extract_relationships(row)
        rg_rels = [r for r in rels if r["rel_type"] == "resource_group_member"]
        assert len(rg_rels) == 1
        assert "rg1" in rg_rels[0]["target_id"]

    def test_nic_subnet_relationship(self):
        row = _make_nic_row()
        rels = _extract_relationships(row)
        subnet_rels = [r for r in rels if r["rel_type"] == "subnet_of"]
        assert len(subnet_rels) == 1
        assert "default" in subnet_rels[0]["target_id"]

    def test_subnet_vnet_relationship(self):
        row = _make_subnet_row()
        rels = _extract_relationships(row)
        vnet_rels = [r for r in rels if r["rel_type"] == "vnet_of"]
        assert len(vnet_rels) == 1
        assert "vnet1" in vnet_rels[0]["target_id"]

    def test_empty_properties_no_crash(self):
        row = {
            "id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm2",
            "type": "microsoft.compute/virtualmachines",
            "resourceGroup": "rg1",
            "subscriptionId": "s1",
            "name": "vm2",
            "tags": {},
            "properties": {},
        }
        rels = _extract_relationships(row)
        # Should still produce resource_group_member
        assert any(r["rel_type"] == "resource_group_member" for r in rels)

    def test_missing_properties_no_crash(self):
        row = {
            "id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.storage/storageaccounts/sa1",
            "type": "microsoft.storage/storageaccounts",
            "resourceGroup": "rg1",
            "subscriptionId": "s1",
            "name": "sa1",
            "tags": {},
        }
        rels = _extract_relationships(row)
        assert isinstance(rels, list)

    def test_vm_multiple_nics(self):
        """VM with 2 NICs produces 2 nic_of relationships."""
        row = {
            "id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm-multi",
            "type": "microsoft.compute/virtualmachines",
            "resourceGroup": "rg1",
            "subscriptionId": "s1",
            "name": "vm-multi",
            "tags": {},
            "properties": {
                "networkProfile": {
                    "networkInterfaces": [
                        {"id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.network/networkinterfaces/nic1"},
                        {"id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.network/networkinterfaces/nic2"},
                    ]
                },
                "storageProfile": {"osDisk": {}, "dataDisks": []},
            },
        }
        rels = _extract_relationships(row)
        nic_rels = [r for r in rels if r["rel_type"] == "nic_of"]
        assert len(nic_rels) == 2

    def test_nic_only_first_subnet_extracted(self):
        """NIC with multiple IP configs — only first subnet relationship extracted."""
        row = {
            "id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.network/networkinterfaces/nic-multi",
            "type": "microsoft.network/networkinterfaces",
            "resourceGroup": "rg1",
            "subscriptionId": "s1",
            "name": "nic-multi",
            "tags": {},
            "properties": {
                "ipConfigurations": [
                    {"properties": {"subnet": {"id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.network/virtualnetworks/vnet1/subnets/subnet-a"}}},
                    {"properties": {"subnet": {"id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.network/virtualnetworks/vnet1/subnets/subnet-b"}}},
                ]
            },
        }
        rels = _extract_relationships(row)
        subnet_rels = [r for r in rels if r["rel_type"] == "subnet_of"]
        assert len(subnet_rels) == 1
        assert "subnet-a" in subnet_rels[0]["target_id"]

    def test_subnet_with_invalid_id_no_crash(self):
        """Subnet row with malformed ID should not crash."""
        row = {
            "id": "not-a-valid-arm-id",
            "type": "microsoft.network/subnets",
            "resourceGroup": "rg1",
            "subscriptionId": "s1",
            "name": "bad-subnet",
            "tags": {},
            "properties": {},
        }
        rels = _extract_relationships(row)
        vnet_rels = [r for r in rels if r["rel_type"] == "vnet_of"]
        assert len(vnet_rels) == 0


# ---------------------------------------------------------------------------
# TopologyDocument model tests
# ---------------------------------------------------------------------------


class TestTopologyDocument:
    def test_valid_document(self):
        doc = TopologyDocument(
            id="/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm1",
            resource_id="/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm1",
            resource_type="microsoft.compute/virtualmachines",
            resource_group="rg1",
            subscription_id="s1",
            name="vm1",
            tags={"env": "prod"},
            relationships=[
                TopologyRelationship(
                    target_id="/subscriptions/s1/resourcegroups/rg1/providers/microsoft.network/networkinterfaces/nic1",
                    rel_type="nic_of",
                    direction="outbound",
                )
            ],
            last_synced_at="2026-04-03T10:00:00+00:00",
        )
        assert doc.resource_type == "microsoft.compute/virtualmachines"
        assert len(doc.relationships) == 1

    def test_empty_relationships_default(self):
        doc = TopologyDocument(
            id="test-id",
            resource_id="test-id",
            resource_type="microsoft.compute/virtualmachines",
            resource_group="rg",
            subscription_id="s1",
            name="vm1",
            last_synced_at="2026-04-03T10:00:00+00:00",
        )
        assert doc.relationships == []
        assert doc.tags == {}

    def test_topology_relationship_fields(self):
        rel = TopologyRelationship(
            target_id="/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/disks/disk1",
            rel_type="disk_of",
            direction="outbound",
        )
        assert rel.rel_type == "disk_of"
        assert rel.direction == "outbound"


# ---------------------------------------------------------------------------
# TopologyClient._row_to_document tests
# ---------------------------------------------------------------------------


class TestRowToDocument:
    def test_vm_row_conversion(self):
        client = _make_topology_client()
        row = _make_vm_row()
        doc = client._row_to_document(row, "2026-04-03T10:00:00+00:00")
        assert doc["id"] == row["id"].lower()
        assert doc["resource_id"] == doc["id"]
        assert doc["resource_type"] == "microsoft.compute/virtualmachines"
        assert doc["resource_group"] == "rg1"
        assert doc["subscription_id"] == "s1"
        assert doc["name"] == "vm1"
        assert doc["last_synced_at"] == "2026-04-03T10:00:00+00:00"
        assert isinstance(doc["relationships"], list)
        assert len(doc["relationships"]) > 0

    def test_tags_string_parsed_as_json(self):
        """Tags returned as JSON string from ARG should be parsed to dict."""
        import json

        client = _make_topology_client()
        row = {
            "id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.storage/storageaccounts/sa1",
            "type": "microsoft.storage/storageaccounts",
            "resourceGroup": "rg1",
            "subscriptionId": "s1",
            "name": "sa1",
            "tags": json.dumps({"env": "prod", "team": "ops"}),
            "properties": {},
        }
        doc = client._row_to_document(row, "2026-04-03T10:00:00+00:00")
        assert doc["tags"] == {"env": "prod", "team": "ops"}

    def test_tags_none_becomes_empty_dict(self):
        client = _make_topology_client()
        row = {
            "id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.storage/storageaccounts/sa1",
            "type": "microsoft.storage/storageaccounts",
            "resourceGroup": "rg1",
            "subscriptionId": "s1",
            "name": "sa1",
            "tags": None,
            "properties": {},
        }
        doc = client._row_to_document(row, "2026-04-03T10:00:00+00:00")
        assert doc["tags"] == {}

    def test_id_lowercased(self):
        """Resource IDs should always be lowercased in the output document."""
        client = _make_topology_client()
        row = {
            "id": "/subscriptions/S1/resourceGroups/RG1/providers/Microsoft.Compute/virtualMachines/VM1",
            "type": "Microsoft.Compute/virtualMachines",
            "resourceGroup": "RG1",
            "subscriptionId": "S1",
            "name": "VM1",
            "tags": {},
            "properties": {},
        }
        doc = client._row_to_document(row, "2026-04-03T10:00:00+00:00")
        assert doc["id"] == doc["id"].lower()
        assert doc["resource_type"] == "microsoft.compute/virtualmachines"
        assert doc["resource_group"] == "rg1"


# ---------------------------------------------------------------------------
# TopologyClient.get_snapshot tests
# ---------------------------------------------------------------------------


class TestGetSnapshot:
    def test_returns_document_on_hit(self):
        client = _make_topology_client()
        mock_container = MagicMock()
        mock_doc = {
            "id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm1",
            "resource_id": "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm1",
            "resource_type": "microsoft.compute/virtualmachines",
            "resource_group": "rg1",
            "subscription_id": "s1",
            "name": "vm1",
            "tags": {},
            "relationships": [],
            "last_synced_at": "2026-04-03T10:00:00+00:00",
            "_rid": "cosmos-internal",
            "_etag": '"etag-001"',
        }
        mock_container.read_item.return_value = mock_doc
        client._container = mock_container

        result = client.get_snapshot(
            "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm1"
        )
        assert result is not None
        assert "_rid" not in result
        assert "_etag" not in result
        assert result["name"] == "vm1"

    def test_returns_none_on_miss(self):
        client = _make_topology_client()
        mock_container = MagicMock()
        mock_container.read_item.side_effect = Exception("NotFound")
        client._container = mock_container

        result = client.get_snapshot(
            "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/missing"
        )
        assert result is None

    def test_lowercases_resource_id_for_lookup(self):
        """Snapshot lookup should lowercase the resource_id before querying Cosmos."""
        client = _make_topology_client()
        mock_container = MagicMock()
        mock_container.read_item.return_value = {"id": "test", "name": "test"}
        client._container = mock_container

        client.get_snapshot("/subscriptions/S1/resourceGroups/RG1/providers/Microsoft.Compute/virtualMachines/VM1")
        call_args = mock_container.read_item.call_args
        assert call_args[1]["item"] == "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm1"


# ---------------------------------------------------------------------------
# TopologyClient.get_blast_radius tests
# ---------------------------------------------------------------------------


class TestGetBlastRadius:
    def _make_doc(self, rid: str, neighbors: list) -> Dict[str, Any]:
        return {
            "id": rid,
            "resource_id": rid,
            "resource_type": "microsoft.compute/virtualmachines",
            "resource_group": "rg1",
            "subscription_id": "s1",
            "name": rid.split("/")[-1],
            "tags": {},
            "relationships": [
                {"target_id": n, "rel_type": "nic_of", "direction": "outbound"}
                for n in neighbors
            ],
            "last_synced_at": "2026-04-03T10:00:00+00:00",
        }

    def test_blast_radius_single_hop(self):
        """Origin → NIC1 (1 hop)."""
        client = _make_topology_client()
        mock_container = MagicMock()

        origin = "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm1"
        nic = "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.network/networkinterfaces/nic1"

        docs = {
            origin: self._make_doc(origin, [nic]),
            nic: self._make_doc(nic, []),
        }

        def read_item(item, partition_key):
            rid = item.lower()
            if rid in docs:
                return docs[rid]
            raise Exception(f"NotFound: {rid}")

        mock_container.read_item.side_effect = read_item
        client._container = mock_container

        result = client.get_blast_radius(origin, max_depth=3)
        assert result["resource_id"] == origin
        assert result["total_affected"] == 1
        affected_ids = [r["resource_id"] for r in result["affected_resources"]]
        assert nic in affected_ids

    def test_blast_radius_respects_max_depth(self):
        """With max_depth=1, should not traverse beyond direct neighbors."""
        client = _make_topology_client()
        mock_container = MagicMock()

        origin = "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/vm1"
        nic = "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.network/networkinterfaces/nic1"
        subnet = "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.network/virtualnetworks/vnet1/subnets/default"

        docs = {
            origin: self._make_doc(origin, [nic]),
            nic: self._make_doc(nic, [subnet]),
            subnet: self._make_doc(subnet, []),
        }

        def read_item(item, partition_key):
            rid = item.lower()
            if rid in docs:
                return docs[rid]
            raise Exception("NotFound")

        mock_container.read_item.side_effect = read_item
        client._container = mock_container

        result = client.get_blast_radius(origin, max_depth=1)
        affected_ids = [r["resource_id"] for r in result["affected_resources"]]
        assert nic in affected_ids
        assert subnet not in affected_ids

    def test_blast_radius_origin_not_found(self):
        """Returns empty result when origin node is not in Cosmos."""
        client = _make_topology_client()
        mock_container = MagicMock()
        mock_container.read_item.side_effect = Exception("NotFound")
        client._container = mock_container

        result = client.get_blast_radius(
            "/subscriptions/s1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/missing"
        )
        assert result["total_affected"] == 0
        assert result["affected_resources"] == []

    def test_blast_radius_hop_counts_populated(self):
        """hop_counts should reflect BFS distance from origin."""
        client = _make_topology_client()
        mock_container = MagicMock()

        origin = "node-origin"
        hop1 = "node-hop1"
        hop2 = "node-hop2"

        docs = {
            origin: self._make_doc(origin, [hop1]),
            hop1: self._make_doc(hop1, [hop2]),
            hop2: self._make_doc(hop2, []),
        }

        def read_item(item, partition_key):
            rid = item.lower()
            if rid in docs:
                return docs[rid]
            raise Exception("NotFound")

        mock_container.read_item.side_effect = read_item
        client._container = mock_container

        result = client.get_blast_radius(origin, max_depth=3)
        assert result["hop_counts"].get(hop1) == 1
        assert result["hop_counts"].get(hop2) == 2
        # Origin should not appear in hop_counts
        assert origin not in result["hop_counts"]

    def test_blast_radius_no_cycles(self):
        """BFS should not loop when there are cycles in the graph."""
        client = _make_topology_client()
        mock_container = MagicMock()

        a = "node-a"
        b = "node-b"
        c = "node-c"

        # Cycle: a → b → c → a
        docs = {
            a: self._make_doc(a, [b]),
            b: self._make_doc(b, [c]),
            c: self._make_doc(c, [a]),
        }

        def read_item(item, partition_key):
            rid = item.lower()
            if rid in docs:
                return docs[rid]
            raise Exception("NotFound")

        mock_container.read_item.side_effect = read_item
        client._container = mock_container

        # Should complete without infinite loop
        result = client.get_blast_radius(a, max_depth=5)
        assert result["total_affected"] == 2
        affected_ids = [r["resource_id"] for r in result["affected_resources"]]
        assert b in affected_ids
        assert c in affected_ids


# ---------------------------------------------------------------------------
# TopologyClient.get_path tests
# ---------------------------------------------------------------------------


class TestGetPath:
    def test_path_same_node(self):
        client = _make_topology_client()
        result = client.get_path("resource-a", "resource-a")
        assert result["found"] is True
        assert result["hops"] == 0
        assert result["path"] == ["resource-a"]

    def test_path_direct_neighbor(self):
        client = _make_topology_client()
        mock_container = MagicMock()

        source = "node-a"
        target = "node-b"

        def read_item(item, partition_key):
            if item == "node-a":
                return {"relationships": [{"target_id": "node-b"}]}
            if item == "node-b":
                return {"relationships": []}
            raise Exception("NotFound")

        mock_container.read_item.side_effect = read_item
        client._container = mock_container

        result = client.get_path(source, target)
        assert result["found"] is True
        assert result["hops"] == 1

    def test_path_not_found(self):
        client = _make_topology_client()
        mock_container = MagicMock()
        mock_container.read_item.side_effect = Exception("NotFound")
        client._container = mock_container

        result = client.get_path("isolated-a", "isolated-b")
        assert result["found"] is False
        assert result["hops"] == -1

    def test_path_two_hops(self):
        """source → middle → target via two hops."""
        client = _make_topology_client()
        mock_container = MagicMock()

        source = "node-src"
        middle = "node-mid"
        target = "node-tgt"

        def read_item(item, partition_key):
            if item == source:
                return {"relationships": [{"target_id": middle}]}
            if item == middle:
                return {"relationships": [{"target_id": target}]}
            if item == target:
                return {"relationships": []}
            raise Exception("NotFound")

        mock_container.read_item.side_effect = read_item
        client._container = mock_container

        result = client.get_path(source, target)
        assert result["found"] is True
        assert result["hops"] == 2
        assert source in result["path"]
        assert target in result["path"]


# ---------------------------------------------------------------------------
# KQL builder tests
# ---------------------------------------------------------------------------


class TestKQLBuilders:
    def test_bootstrap_kql_contains_resource_types(self):
        kql = _build_bootstrap_kql()
        assert "microsoft.compute/virtualmachines" in kql
        assert "microsoft.network/networkinterfaces" in kql
        assert "microsoft.storage/storageaccounts" in kql

    def test_incremental_kql_contains_interval(self):
        kql = _build_incremental_kql(interval_minutes=20)
        assert "ago(20m)" in kql

    def test_bootstrap_kql_projects_required_fields(self):
        kql = _build_bootstrap_kql()
        for field in ["id", "type", "resourceGroup", "subscriptionId", "name", "tags", "properties"]:
            assert field in kql

    def test_incremental_kql_default_interval(self):
        """Default interval should be 16 minutes (slightly over 15-min sync)."""
        kql = _build_incremental_kql()
        assert "ago(16m)" in kql
