from __future__ import annotations
"""Unit tests for cross-subscription topology edges (VNet peering, Private Endpoints)."""

from services.api_gateway.topology import _extract_relationships


class TestVNetPeeringEdges:
    def _make_peering_row(self, peering_state: str, remote_vnet_id: str) -> dict:
        return {
            "id": "/subscriptions/sub-a/resourceGroups/rg-a/providers/Microsoft.Network/virtualNetworks/vnet-a/virtualNetworkPeerings/peer-to-b",
            "type": "microsoft.network/virtualnetworkpeerings",
            "resourceGroup": "rg-a",
            "subscriptionId": "sub-a",
            "name": "peer-to-b",
            "properties": {
                "peeringState": peering_state,
                "remoteVirtualNetwork": {"id": remote_vnet_id},
            },
            "tags": {},
        }

    def test_connected_peering_produces_vnet_peering_edge(self):
        remote_vnet = "/subscriptions/sub-b/resourceGroups/rg-b/providers/Microsoft.Network/virtualNetworks/vnet-b"
        row = self._make_peering_row("Connected", remote_vnet)
        rels = _extract_relationships(row)
        peering_edges = [r for r in rels if r["rel_type"] == "vnet_peering"]
        assert len(peering_edges) == 1
        assert peering_edges[0]["target_id"] == remote_vnet.lower()
        assert peering_edges[0]["direction"] == "outbound"

    def test_disconnected_peering_does_not_produce_vnet_peering_edge(self):
        remote_vnet = "/subscriptions/sub-b/resourceGroups/rg-b/providers/Microsoft.Network/virtualNetworks/vnet-b"
        row = self._make_peering_row("Disconnected", remote_vnet)
        rels = _extract_relationships(row)
        peering_edges = [r for r in rels if r["rel_type"] == "vnet_peering"]
        assert len(peering_edges) == 0

    def test_connected_peering_also_produces_parent_vnet_edge(self):
        remote_vnet = "/subscriptions/sub-b/resourceGroups/rg-b/providers/Microsoft.Network/virtualNetworks/vnet-b"
        row = self._make_peering_row("Connected", remote_vnet)
        rels = _extract_relationships(row)
        vnet_of_edges = [r for r in rels if r["rel_type"] == "vnet_of"]
        assert len(vnet_of_edges) == 1
        # Parent VNet derived by stripping /virtualNetworkPeerings/{name}
        assert "vnet-a" in vnet_of_edges[0]["target_id"]

    def test_disconnected_peering_still_produces_parent_vnet_edge(self):
        remote_vnet = "/subscriptions/sub-b/resourceGroups/rg-b/providers/Microsoft.Network/virtualNetworks/vnet-b"
        row = self._make_peering_row("Disconnected", remote_vnet)
        rels = _extract_relationships(row)
        vnet_of_edges = [r for r in rels if r["rel_type"] == "vnet_of"]
        assert len(vnet_of_edges) == 1
        assert "vnet-a" in vnet_of_edges[0]["target_id"]

    def test_cross_subscription_peering_target_id_contains_sub_b(self):
        remote_vnet = "/subscriptions/sub-b/resourceGroups/rg-b/providers/Microsoft.Network/virtualNetworks/vnet-b"
        row = self._make_peering_row("Connected", remote_vnet)
        rels = _extract_relationships(row)
        peering_edges = [r for r in rels if r["rel_type"] == "vnet_peering"]
        assert "sub-b" in peering_edges[0]["target_id"]

    def test_initiated_peering_does_not_produce_vnet_peering_edge(self):
        remote_vnet = "/subscriptions/sub-b/resourceGroups/rg-b/providers/Microsoft.Network/virtualNetworks/vnet-b"
        row = self._make_peering_row("Initiated", remote_vnet)
        rels = _extract_relationships(row)
        peering_edges = [r for r in rels if r["rel_type"] == "vnet_peering"]
        assert len(peering_edges) == 0

    def test_peering_with_empty_remote_vnet_produces_no_peering_edge(self):
        row = self._make_peering_row("Connected", "")
        rels = _extract_relationships(row)
        peering_edges = [r for r in rels if r["rel_type"] == "vnet_peering"]
        assert len(peering_edges) == 0

    def test_peering_resource_group_member_edge_always_produced(self):
        remote_vnet = "/subscriptions/sub-b/resourceGroups/rg-b/providers/Microsoft.Network/virtualNetworks/vnet-b"
        row = self._make_peering_row("Connected", remote_vnet)
        rels = _extract_relationships(row)
        rg_edges = [r for r in rels if r["rel_type"] == "resource_group_member"]
        assert len(rg_edges) == 1
        assert "rg-a" in rg_edges[0]["target_id"]


class TestPrivateEndpointEdges:
    def _make_pe_row(self, target_service_id: str, subnet_id: str) -> dict:
        return {
            "id": "/subscriptions/sub-a/resourceGroups/rg-a/providers/Microsoft.Network/privateEndpoints/pe-cosmos",
            "type": "microsoft.network/privateendpoints",
            "resourceGroup": "rg-a",
            "subscriptionId": "sub-a",
            "name": "pe-cosmos",
            "properties": {
                "subnet": {"id": subnet_id},
                "privateLinkServiceConnections": [
                    {
                        "properties": {
                            "privateLinkServiceId": target_service_id,
                            "privateLinkServiceConnectionState": {"status": "Approved"},
                        }
                    }
                ],
            },
            "tags": {},
        }

    def test_pe_produces_private_endpoint_target_edge(self):
        target = "/subscriptions/sub-b/resourceGroups/rg-b/providers/Microsoft.DocumentDB/databaseAccounts/cosmos-prod"
        subnet = "/subscriptions/sub-a/resourceGroups/rg-a/providers/Microsoft.Network/virtualNetworks/vnet-a/subnets/snet-pe"
        row = self._make_pe_row(target, subnet)
        rels = _extract_relationships(row)
        pe_edges = [r for r in rels if r["rel_type"] == "private_endpoint_target"]
        assert len(pe_edges) == 1
        assert pe_edges[0]["target_id"] == target.lower()

    def test_pe_produces_subnet_of_edge(self):
        target = "/subscriptions/sub-b/resourceGroups/rg-b/providers/Microsoft.DocumentDB/databaseAccounts/cosmos-prod"
        subnet = "/subscriptions/sub-a/resourceGroups/rg-a/providers/Microsoft.Network/virtualNetworks/vnet-a/subnets/snet-pe"
        row = self._make_pe_row(target, subnet)
        rels = _extract_relationships(row)
        subnet_edges = [r for r in rels if r["rel_type"] == "subnet_of"]
        assert len(subnet_edges) == 1
        assert "snet-pe" in subnet_edges[0]["target_id"]

    def test_pe_cross_subscription_target(self):
        target = "/subscriptions/sub-b/resourceGroups/rg-b/providers/Microsoft.DocumentDB/databaseAccounts/cosmos-prod"
        subnet = "/subscriptions/sub-a/resourceGroups/rg-a/providers/Microsoft.Network/virtualNetworks/vnet-a/subnets/snet-pe"
        row = self._make_pe_row(target, subnet)
        rels = _extract_relationships(row)
        pe_edges = [r for r in rels if r["rel_type"] == "private_endpoint_target"]
        assert "sub-b" in pe_edges[0]["target_id"]

    def test_pe_with_multiple_connections_produces_multiple_target_edges(self):
        subnet = "/subscriptions/sub-a/resourceGroups/rg-a/providers/Microsoft.Network/virtualNetworks/vnet-a/subnets/snet-pe"
        row = {
            "id": "/subscriptions/sub-a/resourceGroups/rg-a/providers/Microsoft.Network/privateEndpoints/pe-multi",
            "type": "microsoft.network/privateendpoints",
            "resourceGroup": "rg-a",
            "subscriptionId": "sub-a",
            "name": "pe-multi",
            "properties": {
                "subnet": {"id": subnet},
                "privateLinkServiceConnections": [
                    {"properties": {"privateLinkServiceId": "/subscriptions/sub-b/resourceGroups/rg-b/providers/Microsoft.Storage/storageAccounts/storage1"}},
                    {"properties": {"privateLinkServiceId": "/subscriptions/sub-c/resourceGroups/rg-c/providers/Microsoft.KeyVault/vaults/kv1"}},
                ],
            },
            "tags": {},
        }
        rels = _extract_relationships(row)
        pe_edges = [r for r in rels if r["rel_type"] == "private_endpoint_target"]
        assert len(pe_edges) == 2
        targets = {e["target_id"] for e in pe_edges}
        assert any("storage1" in t for t in targets)
        assert any("kv1" in t for t in targets)

    def test_pe_without_subnet_produces_no_subnet_of_edge(self):
        target = "/subscriptions/sub-b/resourceGroups/rg-b/providers/Microsoft.DocumentDB/databaseAccounts/cosmos-prod"
        row = {
            "id": "/subscriptions/sub-a/resourceGroups/rg-a/providers/Microsoft.Network/privateEndpoints/pe-no-subnet",
            "type": "microsoft.network/privateendpoints",
            "resourceGroup": "rg-a",
            "subscriptionId": "sub-a",
            "name": "pe-no-subnet",
            "properties": {
                "subnet": {},
                "privateLinkServiceConnections": [
                    {"properties": {"privateLinkServiceId": target}}
                ],
            },
            "tags": {},
        }
        rels = _extract_relationships(row)
        subnet_edges = [r for r in rels if r["rel_type"] == "subnet_of"]
        assert len(subnet_edges) == 0
