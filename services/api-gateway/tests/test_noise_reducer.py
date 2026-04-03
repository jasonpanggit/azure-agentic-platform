"""Unit tests for noise_reducer.py (INTEL-001).

Covers:
- Group 1: compute_composite_severity scoring math (5 tests)
- Group 2: check_causal_suppression logic (5 tests)
- Group 3: check_temporal_topological_correlation logic (5 tests)
"""
from __future__ import annotations

import asyncio
import math
import pytest
from typing import Optional
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_cosmos_with_items(items: list[dict]) -> MagicMock:
    """Return a mock cosmos_client whose incidents container yields `items`."""
    container = MagicMock()
    container.query_items.return_value = items

    db = MagicMock()
    db.get_container_client.return_value = container

    client = MagicMock()
    client.get_database_client.return_value = db
    return client


def _make_topology_client(neighbor_ids: Optional[list] = None) -> MagicMock:
    """Return a mock topology_client whose _get_topology_node returns neighbors."""
    client = MagicMock()
    if neighbor_ids is None:
        client._get_topology_node.return_value = None
    else:
        client._get_topology_node.return_value = {
            "relationships": [{"target_id": rid} for rid in neighbor_ids]
        }
    return client


# ---------------------------------------------------------------------------
# Group 1: compute_composite_severity — scoring math
# ---------------------------------------------------------------------------


def test_composite_severity_sev0_security_large_blast():
    """security domain + Sev1 + blast_radius=50 → score >= 0.9 → Sev0."""
    from services.api_gateway.noise_reducer import compute_composite_severity, _blast_radius_score

    # Verify formula: 0.8 + 0.3 * _blast_radius_score(50) + 0.2 * 1.0
    expected_score = 0.8 + 0.3 * _blast_radius_score(50) + 0.2 * 1.0
    assert expected_score >= 0.9, f"Pre-condition failed: score={expected_score}"

    result = compute_composite_severity("Sev1", 50, "security")
    assert result == "Sev0"


def test_composite_severity_sev3_small_blast_patch():
    """patch domain + Sev3 + blast_radius=0 → score < 0.5 → Sev3."""
    from services.api_gateway.noise_reducer import compute_composite_severity

    # 0.4 + 0.3 * 0.0 + 0.2 * 0.4 = 0.48 → Sev3
    result = compute_composite_severity("Sev3", 0, "patch")
    assert result == "Sev3"


def test_composite_severity_no_blast_radius():
    """blast_radius=0 contributes 0.0 to the score."""
    from services.api_gateway.noise_reducer import compute_composite_severity, _blast_radius_score

    assert _blast_radius_score(0) == 0.0
    # compute domain=compute, severity=Sev3: 0.4 + 0.3*0.0 + 0.2*0.9 = 0.58 → Sev2
    result = compute_composite_severity("Sev3", 0, "compute")
    expected_score = 0.4 + 0.0 + 0.2 * 0.9  # = 0.58
    assert expected_score >= 0.5
    assert result == "Sev2"


def test_composite_severity_exact_threshold_sev1():
    """Craft inputs so score lands in [0.7, 0.9) → Sev1."""
    from services.api_gateway.noise_reducer import compute_composite_severity, _blast_radius_score

    # Sev2 base=0.6, blast_radius=0 → 0.0, domain=network (0.85)
    # score = 0.6 + 0.0 + 0.2*0.85 = 0.77 → Sev1
    score = 0.6 + 0.0 + 0.2 * 0.85
    assert 0.7 <= score < 0.9, f"Pre-condition failed: score={score}"

    result = compute_composite_severity("Sev2", 0, "network")
    assert result == "Sev1"


def test_composite_severity_unknown_domain_uses_default():
    """domain='unknown' uses _DOMAIN_SLO_RISK_DEFAULT=0.5, does not raise."""
    from services.api_gateway.noise_reducer import (
        compute_composite_severity,
        _DOMAIN_SLO_RISK_DEFAULT,
    )

    # Just verify no exception is raised and result is a valid severity label
    result = compute_composite_severity("Sev2", 5, "unknown")
    assert result in ("Sev0", "Sev1", "Sev2", "Sev3")

    # Verify the default weight is used: 0.6 + 0.3*_blast(5) + 0.2*0.5
    from services.api_gateway.noise_reducer import _blast_radius_score
    expected_score = 0.6 + 0.3 * _blast_radius_score(5) + 0.2 * _DOMAIN_SLO_RISK_DEFAULT
    if expected_score >= 0.9:
        assert result == "Sev0"
    elif expected_score >= 0.7:
        assert result == "Sev1"
    elif expected_score >= 0.5:
        assert result == "Sev2"
    else:
        assert result == "Sev3"


# ---------------------------------------------------------------------------
# Group 2: check_causal_suppression — suppression logic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suppression_disabled_returns_none():
    """NOISE_SUPPRESSION_ENABLED=false → None immediately, no Cosmos call."""
    cosmos = _build_cosmos_with_items([])
    topo = _make_topology_client()

    import services.api_gateway.noise_reducer as nr

    original = nr.SUPPRESSION_ENABLED
    nr.SUPPRESSION_ENABLED = False
    try:
        result = await nr.check_causal_suppression(
            resource_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
            topology_client=topo,
            cosmos_client=cosmos,
        )
    finally:
        nr.SUPPRESSION_ENABLED = original

    assert result is None
    # Cosmos should never have been touched
    cosmos.get_database_client.assert_not_called()


@pytest.mark.asyncio
async def test_suppression_no_cosmos_returns_none():
    """cosmos_client=None → None without error."""
    import services.api_gateway.noise_reducer as nr

    result = await nr.check_causal_suppression(
        resource_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
        topology_client=_make_topology_client(),
        cosmos_client=None,
    )
    assert result is None


@pytest.mark.asyncio
async def test_suppression_hit_resource_in_blast_radius():
    """Active incident with blast_radius_summary containing resource_id → returns parent incident_id."""
    resource_id = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1"
    parent_id = "inc-parent-001"

    incident_doc = {
        "incident_id": parent_id,
        "status": "active",
        "blast_radius_summary": {
            "affected_resources": [resource_id],
        },
    }
    cosmos = _build_cosmos_with_items([incident_doc])
    topo = _make_topology_client()

    import services.api_gateway.noise_reducer as nr

    original = nr.SUPPRESSION_ENABLED
    nr.SUPPRESSION_ENABLED = True
    try:
        result = await nr.check_causal_suppression(
            resource_id=resource_id,
            topology_client=topo,
            cosmos_client=cosmos,
        )
    finally:
        nr.SUPPRESSION_ENABLED = original

    assert result == parent_id


@pytest.mark.asyncio
async def test_suppression_miss_resource_not_in_blast_radius():
    """Active incident exists but resource_id NOT in blast_radius → returns None."""
    resource_id = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1"
    other_resource = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-other"

    incident_doc = {
        "incident_id": "inc-other-001",
        "status": "active",
        "blast_radius_summary": {
            "affected_resources": [other_resource],
        },
    }
    cosmos = _build_cosmos_with_items([incident_doc])
    topo = _make_topology_client()

    import services.api_gateway.noise_reducer as nr

    original = nr.SUPPRESSION_ENABLED
    nr.SUPPRESSION_ENABLED = True
    try:
        result = await nr.check_causal_suppression(
            resource_id=resource_id,
            topology_client=topo,
            cosmos_client=cosmos,
        )
    finally:
        nr.SUPPRESSION_ENABLED = original

    assert result is None


@pytest.mark.asyncio
async def test_suppression_cosmos_error_returns_none():
    """Cosmos query raises Exception → logs warning, returns None."""
    cosmos = MagicMock()
    db = MagicMock()
    container = MagicMock()
    container.query_items.side_effect = Exception("Cosmos unavailable")
    db.get_container_client.return_value = container
    cosmos.get_database_client.return_value = db

    import services.api_gateway.noise_reducer as nr

    original = nr.SUPPRESSION_ENABLED
    nr.SUPPRESSION_ENABLED = True
    try:
        result = await nr.check_causal_suppression(
            resource_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
            topology_client=_make_topology_client(),
            cosmos_client=cosmos,
        )
    finally:
        nr.SUPPRESSION_ENABLED = original

    assert result is None


# ---------------------------------------------------------------------------
# Group 3: check_temporal_topological_correlation — correlation logic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_correlation_disabled_returns_none():
    """NOISE_SUPPRESSION_ENABLED=false → None immediately."""
    cosmos = _build_cosmos_with_items([])
    topo = _make_topology_client()

    import services.api_gateway.noise_reducer as nr

    original = nr.SUPPRESSION_ENABLED
    nr.SUPPRESSION_ENABLED = False
    try:
        result = await nr.check_temporal_topological_correlation(
            resource_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
            domain="compute",
            topology_client=topo,
            cosmos_client=cosmos,
        )
    finally:
        nr.SUPPRESSION_ENABLED = original

    assert result is None
    cosmos.get_database_client.assert_not_called()


@pytest.mark.asyncio
async def test_correlation_no_topology_client_returns_none():
    """topology_client=None → None without error."""
    import services.api_gateway.noise_reducer as nr

    result = await nr.check_temporal_topological_correlation(
        resource_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
        domain="compute",
        topology_client=None,
        cosmos_client=_build_cosmos_with_items([]),
    )
    assert result is None


@pytest.mark.asyncio
async def test_correlation_hit_neighbor_resource():
    """Topology returns a neighbor that matches an existing incident resource_id → returns incident_id."""
    neighbor_id = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Network/networkInterfaces/nic-1"
    incident_id = "inc-neighbor-001"

    incident_doc = {
        "incident_id": incident_id,
        "resource_id": neighbor_id,
        "domain": "compute",
        "blast_radius_summary": None,
    }
    cosmos = _build_cosmos_with_items([incident_doc])
    # topology returns neighbor_id as a neighbor of the primary resource
    topo = _make_topology_client(neighbor_ids=[neighbor_id])

    import services.api_gateway.noise_reducer as nr

    original = nr.SUPPRESSION_ENABLED
    nr.SUPPRESSION_ENABLED = True
    try:
        result = await nr.check_temporal_topological_correlation(
            resource_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
            domain="compute",
            topology_client=topo,
            cosmos_client=cosmos,
        )
    finally:
        nr.SUPPRESSION_ENABLED = original

    assert result == incident_id


@pytest.mark.asyncio
async def test_correlation_miss_no_overlap():
    """Topology neighbors don't overlap with any active incident → None."""
    incident_doc = {
        "incident_id": "inc-unrelated-001",
        "resource_id": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-unrelated",
        "domain": "compute",
        "blast_radius_summary": None,
    }
    cosmos = _build_cosmos_with_items([incident_doc])
    # topology returns a neighbor that is different from the incident resource
    topo = _make_topology_client(neighbor_ids=[
        "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Network/networkInterfaces/nic-different"
    ])

    import services.api_gateway.noise_reducer as nr

    original = nr.SUPPRESSION_ENABLED
    nr.SUPPRESSION_ENABLED = True
    try:
        result = await nr.check_temporal_topological_correlation(
            resource_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
            domain="compute",
            topology_client=topo,
            cosmos_client=cosmos,
        )
    finally:
        nr.SUPPRESSION_ENABLED = original

    assert result is None


@pytest.mark.asyncio
async def test_correlation_topology_fetch_error_falls_back_to_single_node():
    """topology._get_topology_node raises → graceful fallback, still checks resource_id itself."""
    resource_id = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1"
    incident_id = "inc-same-resource-001"

    # Incident on the same resource_id as the incoming alert
    incident_doc = {
        "incident_id": incident_id,
        "resource_id": resource_id,
        "domain": "compute",
        "blast_radius_summary": None,
    }
    cosmos = _build_cosmos_with_items([incident_doc])

    # Topology client raises on _get_topology_node
    topo = MagicMock()
    topo._get_topology_node.side_effect = Exception("Topology service down")

    import services.api_gateway.noise_reducer as nr

    original = nr.SUPPRESSION_ENABLED
    nr.SUPPRESSION_ENABLED = True
    try:
        result = await nr.check_temporal_topological_correlation(
            resource_id=resource_id,
            domain="compute",
            topology_client=topo,
            cosmos_client=cosmos,
        )
    finally:
        nr.SUPPRESSION_ENABLED = original

    # Even with topology down, the fallback single-node check finds the same-resource incident
    assert result == incident_id
