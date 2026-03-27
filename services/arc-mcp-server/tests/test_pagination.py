"""Pagination exhaustion tests (AGENT-006).

Verifies that all Arc MCP Server list tools exhaust ALL nextLink pages and
return total_count == len(results). This is the unit-level proof of AGENT-006.

The Azure SDK ItemPaged is an iterator — in tests, mock it with a plain
Python iterator. The production code's `for item in paged:` loop correctly
exhausts it, proving nextLink behaviour.

Note: HTTP-level multi-page simulation (with actual nextLink URLs) is covered
in integration tests (03-04). These tests verify that the tool implementation
ALWAYS collects all items from the iterator.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from arc_mcp_server.tools.arc_servers import arc_servers_list_impl
from arc_mcp_server.tools.arc_k8s import arc_k8s_list_impl


# ---------------------------------------------------------------------------
# Arc Servers pagination (AGENT-006)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_arc_servers_list_120_total_count(sample_machines_120):
    """AGENT-006: arc_servers_list returns total_count == 120 for 120 seeded machines."""
    with patch(
        "arc_mcp_server.tools.arc_servers._get_hybridcompute_client"
    ) as mock_factory:
        mock_client = MagicMock()
        mock_client.machines.list_by_subscription.return_value = iter(sample_machines_120)
        mock_factory.return_value = mock_client

        result = await arc_servers_list_impl(subscription_id="sub-pagination-test")

    # AGENT-006: total_count MUST equal the number of items returned
    assert result.total_count == 120
    assert len(result.servers) == 120
    # No items lost — indices 0–119 all present
    names = {s.name for s in result.servers}
    assert "arc-server-0000" in names
    assert "arc-server-0119" in names
    assert len(names) == 120  # No duplicates


@pytest.mark.unit
@pytest.mark.asyncio
async def test_arc_servers_list_total_count_equals_len(sample_machines_120):
    """AGENT-006: total_count MUST always equal len(servers) — invariant check."""
    with patch(
        "arc_mcp_server.tools.arc_servers._get_hybridcompute_client"
    ) as mock_factory:
        mock_client = MagicMock()
        mock_client.machines.list_by_subscription.return_value = iter(sample_machines_120)
        mock_factory.return_value = mock_client

        result = await arc_servers_list_impl(subscription_id="sub-test")

    # This is the core AGENT-006 invariant
    assert result.total_count == len(result.servers), (
        f"AGENT-006 VIOLATION: total_count ({result.total_count}) "
        f"!= len(servers) ({len(result.servers)})"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_arc_servers_list_single_item():
    """arc_servers_list works correctly with exactly 1 machine."""
    from unittest.mock import MagicMock as MM

    machine = MM()
    machine.name = "arc-server-solo"
    machine.id = "/subscriptions/s1/resourceGroups/rg1/providers/Microsoft.HybridCompute/machines/arc-server-solo"
    machine.location = "westus"
    machine.status = "Connected"
    machine.last_status_change = datetime(2026, 3, 1, tzinfo=timezone.utc)
    machine.agent_version = "1.37.0"
    machine.os_name = "Windows Server 2022"
    machine.os_type = "windows"
    machine.os_version = "10.0"
    machine.kind = None
    machine.provisioning_state = "Succeeded"

    with patch(
        "arc_mcp_server.tools.arc_servers._get_hybridcompute_client"
    ) as mock_factory:
        mock_client = MagicMock()
        mock_client.machines.list_by_subscription.return_value = iter([machine])
        mock_factory.return_value = mock_client

        result = await arc_servers_list_impl(subscription_id="sub-solo")

    assert result.total_count == 1
    assert len(result.servers) == 1


# ---------------------------------------------------------------------------
# Arc K8s pagination (AGENT-006)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_arc_k8s_list_105_total_count(sample_clusters_105):
    """AGENT-006: arc_k8s_list returns total_count == 105 for 105 seeded clusters."""
    with patch(
        "arc_mcp_server.tools.arc_k8s._get_k8s_client"
    ) as mock_factory:
        mock_client = MagicMock()
        mock_client.connected_cluster.list_by_subscription.return_value = iter(
            sample_clusters_105
        )
        mock_factory.return_value = mock_client

        result = await arc_k8s_list_impl(
            subscription_id="sub-k8s-pagination-test",
            include_flux=False,
        )

    assert result.total_count == 105
    assert len(result.clusters) == 105


@pytest.mark.unit
@pytest.mark.asyncio
async def test_arc_k8s_list_total_count_equals_len(sample_clusters_105):
    """AGENT-006: K8s total_count MUST always equal len(clusters) — invariant."""
    with patch(
        "arc_mcp_server.tools.arc_k8s._get_k8s_client"
    ) as mock_factory:
        mock_client = MagicMock()
        mock_client.connected_cluster.list_by_subscription.return_value = iter(
            sample_clusters_105
        )
        mock_factory.return_value = mock_client

        result = await arc_k8s_list_impl(
            subscription_id="sub-test",
            include_flux=False,
        )

    assert result.total_count == len(result.clusters), (
        f"AGENT-006 VIOLATION: total_count ({result.total_count}) "
        f"!= len(clusters) ({len(result.clusters)})"
    )


# ---------------------------------------------------------------------------
# Cross-tool consistency: total_count invariant for all list tools
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_arc_k8s_list_single_cluster():
    """arc_k8s_list_impl handles exactly 1 cluster without error."""
    from unittest.mock import MagicMock as MM

    cluster = MM()
    cluster.name = "arc-cluster-solo"
    cluster.id = "/subscriptions/s1/resourceGroups/rg1/providers/Microsoft.Kubernetes/connectedClusters/arc-cluster-solo"
    cluster.location = "eastus"
    props = MM()
    props.connectivity_status = "Connected"
    props.last_connectivity_time = datetime(2026, 3, 1, tzinfo=timezone.utc)
    props.kubernetes_version = "1.28.5"
    props.distribution = "k3s"
    props.total_node_count = 1
    props.total_core_count = 2
    props.agent_version = "1.14.0"
    props.provisioning_state = "Succeeded"
    cluster.properties = props

    with patch(
        "arc_mcp_server.tools.arc_k8s._get_k8s_client"
    ) as mock_factory:
        mock_client = MagicMock()
        mock_client.connected_cluster.list_by_subscription.return_value = iter([cluster])
        mock_factory.return_value = mock_client

        result = await arc_k8s_list_impl(subscription_id="sub-solo", include_flux=False)

    assert result.total_count == 1
    assert len(result.clusters) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_arc_k8s_list_empty_equals_len():
    """arc_k8s_list_impl: total_count == len(clusters) == 0 for empty subscription."""
    with patch(
        "arc_mcp_server.tools.arc_k8s._get_k8s_client"
    ) as mock_factory:
        mock_client = MagicMock()
        mock_client.connected_cluster.list_by_subscription.return_value = iter([])
        mock_factory.return_value = mock_client

        result = await arc_k8s_list_impl(subscription_id="sub-empty", include_flux=False)

    assert result.total_count == 0
    assert result.total_count == len(result.clusters)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 1, 50, 101, 500])
async def test_arc_servers_list_total_count_parametrized(count):
    """AGENT-006: total_count == len(servers) for various estate sizes."""
    from unittest.mock import MagicMock as MM

    def _m(i):
        m = MM()
        m.name = f"arc-server-{i}"
        m.id = f"/subscriptions/s1/resourceGroups/rg1/providers/Microsoft.HybridCompute/machines/arc-server-{i}"
        m.location = "eastus"
        m.status = "Connected"
        m.last_status_change = datetime(2026, 1, 1, tzinfo=timezone.utc)
        m.agent_version = "1.37.0"
        m.os_name = "Ubuntu 22.04"
        m.os_type = "linux"
        m.os_version = "22.04"
        m.kind = None
        m.provisioning_state = "Succeeded"
        return m

    machines = [_m(i) for i in range(count)]

    with patch(
        "arc_mcp_server.tools.arc_servers._get_hybridcompute_client"
    ) as mock_factory:
        mock_client = MagicMock()
        mock_client.machines.list_by_subscription.return_value = iter(machines)
        mock_factory.return_value = mock_client

        result = await arc_servers_list_impl(subscription_id="sub-test")

    assert result.total_count == count
    assert result.total_count == len(result.servers)
