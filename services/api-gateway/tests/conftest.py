"""Shared pytest fixtures for Phase 5 api-gateway tests.

Fixtures:
- client: FastAPI TestClient for the api-gateway
- mock_foundry_client: Mocked AIProjectClient (agents.create_thread, create_message, create_run)
- mock_cosmos_approvals: Mocked Cosmos DB approvals container (read_item, replace_item, create_item, query_items)
- mock_cosmos_incidents: Mocked Cosmos DB incidents container
- mock_teams_notifier: Mocked Teams card poster (post_card, update_card)
- mock_arm_client: Mocked ARM resource client for Resource Identity Certainty
- sample_approval_record: Pre-built approval record dict matching the D-12 schema
- sample_remediation_proposal: Pre-built RemediationProposal for testing
- pre_seeded_embeddings: 3 pre-computed 1536-dim float vectors for runbook RAG testing (no Azure OpenAI call)
"""
import os

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")

from services.api_gateway.main import app


@pytest.fixture()
def client():
    """FastAPI TestClient for the api-gateway."""
    return TestClient(app)


@pytest.fixture()
def mock_foundry_client():
    """Mocked AIProjectClient with agents sub-client."""
    client = MagicMock()
    client.agents.create_thread.return_value = MagicMock(id="thread-test-001")
    client.agents.create_message.return_value = MagicMock(id="msg-test-001")
    client.agents.create_run.return_value = MagicMock(id="run-test-001")
    return client


@pytest.fixture()
def mock_cosmos_approvals():
    """Mocked Cosmos DB approvals container."""
    container = MagicMock()
    container.read_item.return_value = {
        "id": "appr_test-001",
        "action_id": "act_test-001",
        "thread_id": "thread-test-001",
        "incident_id": "inc-test-001",
        "agent_name": "compute",
        "status": "pending",
        "risk_level": "high",
        "proposed_at": "2026-03-27T14:30:00Z",
        "expires_at": "2026-03-27T15:00:00Z",
        "decided_at": None,
        "decided_by": None,
        "executed_at": None,
        "abort_reason": None,
        "resource_snapshot": {
            "resource_id": "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-prod-01",
            "provisioning_state": "Succeeded",
            "tags": {"environment": "production"},
            "resource_health": "Available",
            "snapshot_hash": "a" * 64,
        },
        "proposal": {
            "description": "Restart VM vm-prod-01",
            "target_resources": ["/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-prod-01"],
            "estimated_impact": "~2 min downtime",
            "risk_level": "high",
            "reversibility": "reversible",
            "action_type": "restart",
        },
        "_etag": '"etag-test-001"',
    }
    container.replace_item.return_value = container.read_item.return_value
    container.create_item.return_value = container.read_item.return_value
    container.query_items.return_value = iter([])
    return container


@pytest.fixture()
def mock_cosmos_incidents():
    """Mocked Cosmos DB incidents container."""
    container = MagicMock()
    container.query_items.return_value = iter([
        {
            "id": "inc-test-001",
            "incident_id": "inc-test-001",
            "severity": "Sev1",
            "domain": "compute",
            "status": "new",
            "created_at": "2026-03-27T14:00:00Z",
            "resource_id": "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-prod-01",
        }
    ])
    return container


@pytest.fixture()
def mock_teams_notifier():
    """Mocked Teams outbound card poster."""
    notifier = AsyncMock()
    notifier.post_card.return_value = {"message_id": "teams-msg-001"}
    notifier.update_card.return_value = {"message_id": "teams-msg-001"}
    return notifier


@pytest.fixture()
def mock_arm_client():
    """Mocked ARM resource client for Resource Identity Certainty."""
    client = MagicMock()
    client.resources.get_by_id.return_value = MagicMock(
        id="/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-prod-01",
        properties={"provisioningState": "Succeeded"},
        tags={"environment": "production"},
    )
    return client


@pytest.fixture()
def sample_approval_record():
    """Pre-built approval record dict matching D-12 schema."""
    return {
        "id": "appr_test-001",
        "action_id": "act_test-001",
        "thread_id": "thread-test-001",
        "incident_id": "inc-test-001",
        "agent_name": "compute",
        "status": "pending",
        "risk_level": "high",
        "proposed_at": "2026-03-27T14:30:00Z",
        "expires_at": "2026-03-27T15:00:00Z",
        "decided_at": None,
        "decided_by": None,
        "executed_at": None,
        "abort_reason": None,
        "resource_snapshot": {
            "resource_id": "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-prod-01",
            "provisioning_state": "Succeeded",
            "tags": {"environment": "production"},
            "resource_health": "Available",
            "snapshot_hash": "a" * 64,
        },
        "proposal": {
            "description": "Restart VM vm-prod-01",
            "target_resources": ["/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-prod-01"],
            "estimated_impact": "~2 min downtime",
            "risk_level": "high",
            "reversibility": "reversible",
            "action_type": "restart",
        },
    }


@pytest.fixture()
def sample_remediation_proposal():
    """Pre-built RemediationProposal for testing."""
    from agents.shared.triage import RemediationProposal
    return RemediationProposal(
        description="Restart VM vm-prod-01",
        target_resources=["/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-prod-01"],
        estimated_impact="~2 min downtime",
        risk_level="high",
        reversibility="reversible",
        action_type="restart",
    )


@pytest.fixture()
def pre_seeded_embeddings():
    """3 pre-computed 1536-dim float vectors for runbook RAG testing.

    These are deterministic vectors — no Azure OpenAI call needed.
    Vector 0: "VM high CPU" topic (mostly 0.1 with peaks at positions 0-50)
    Vector 1: "NSG misconfiguration" topic (mostly 0.1 with peaks at 100-150)
    Vector 2: "Storage throttling" topic (mostly 0.1 with peaks at 200-250)
    """
    import random
    random.seed(42)
    vectors = []
    for offset in [0, 100, 200]:
        v = [0.1] * 1536
        for i in range(offset, offset + 50):
            v[i] = random.uniform(0.7, 1.0)
        # Normalize to unit vector
        magnitude = sum(x**2 for x in v) ** 0.5
        v = [x / magnitude for x in v]
        vectors.append(v)
    return vectors
