# services/arc-mcp-server/tests/conftest.py
"""Shared pytest fixtures for Arc MCP Server unit tests."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest


def _make_machine(
    index: int,
    status: str = "Connected",
    last_status_change: datetime | None = None,
    resource_group: str = "rg-arc-test",
    subscription_id: str = "sub-test-001",
) -> MagicMock:
    """Create a mock HybridCompute Machine object for testing."""
    machine = MagicMock()
    machine.name = f"arc-server-{index:04d}"
    machine.id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.HybridCompute/machines/arc-server-{index:04d}"
    )
    machine.location = "eastus"
    machine.status = status
    machine.last_status_change = last_status_change or datetime(
        2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc
    )
    machine.agent_version = "1.37.02905.009"
    machine.os_name = "Ubuntu 22.04.3 LTS"
    machine.os_type = "linux"
    machine.os_version = "22.04"
    machine.kind = None
    machine.provisioning_state = "Succeeded"
    return machine


def _make_cluster(
    index: int,
    connectivity_status: str = "Connected",
    resource_group: str = "rg-arc-k8s-test",
    subscription_id: str = "sub-test-001",
) -> MagicMock:
    """Create a mock ConnectedCluster object for testing."""
    cluster = MagicMock()
    cluster.name = f"arc-cluster-{index:04d}"
    cluster.id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.Kubernetes/connectedClusters/arc-cluster-{index:04d}"
    )
    cluster.location = "eastus"
    # Mock properties sub-object
    props = MagicMock()
    props.connectivity_status = connectivity_status
    props.last_connectivity_time = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    props.kubernetes_version = "1.28.5"
    props.distribution = "k3s"
    props.total_node_count = 3
    props.total_core_count = 6
    props.agent_version = "1.14.0"
    props.provisioning_state = "Succeeded"
    cluster.properties = props
    return cluster


def _make_extension(
    name: str,
    publisher: str = "Microsoft.Azure.Monitor",
    ext_type: str = "AzureMonitorLinuxAgent",
    provisioning_state: str = "Succeeded",
    status_level: str = "Info",
) -> MagicMock:
    """Create a mock MachineExtension object for testing."""
    ext = MagicMock()
    ext.name = name
    props = MagicMock()
    props.publisher = publisher
    props.type = ext_type
    props.provisioning_state = provisioning_state
    props.type_handler_version = "1.21.0"
    props.enable_automatic_upgrade = True
    instance_view = MagicMock()
    status = MagicMock()
    status.code = f"ProvisioningState/{provisioning_state.lower()}"
    status.level = status_level
    status.display_status = f"Provisioning {provisioning_state}"
    status.message = ""
    instance_view.status = status
    props.instance_view = instance_view
    ext.properties = props
    return ext


@pytest.fixture
def sample_machines_120():
    """120 mock Arc machines — used in pagination tests (AGENT-006)."""
    return [_make_machine(i) for i in range(120)]


@pytest.fixture
def sample_clusters_105():
    """105 mock Arc K8s clusters — used in K8s pagination tests (AGENT-006)."""
    return [_make_cluster(i) for i in range(105)]
