"""Integration test: Bidirectional Azure Monitor state sync (SC-4).

Verifies that alert state transitions in Cosmos DB are synced back to
Azure Monitor, and that Azure Monitor state changes are reflected
in the platform.

Requires:
- Live Azure subscription with fired alerts
- Live Cosmos DB with incidents container
- Azure Monitor AlertsManagement API access
- Environment variables: COSMOS_ENDPOINT, COSMOS_DATABASE_NAME,
  SUBSCRIPTION_ID, AZURE_CLIENT_ID

Run with: pytest tests/integration/test_state_sync.py -v -m integration
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="Requires live Azure Monitor + Cosmos DB (SC-4 state sync)")
class TestBidirectionalStateSync:
    """Alert state bidirectional sync between Cosmos DB and Azure Monitor."""

    def test_acknowledge_syncs_to_azure_monitor(self) -> None:
        """SC-4: Transitioning Cosmos DB status to 'acknowledged' syncs to Azure Monitor."""
        # TODO: Implement after Phase 4 deployment
        # 1. Fire alert -> create incident in Cosmos DB
        # 2. Transition Cosmos DB status to 'acknowledged'
        # 3. Query Azure Monitor alert state via ARM API
        # 4. Assert Azure Monitor alert state == 'Acknowledged'
        pass

    def test_close_syncs_to_azure_monitor(self) -> None:
        """SC-4: Transitioning Cosmos DB status to 'closed' syncs to Azure Monitor."""
        # TODO: Implement after Phase 4 deployment
        # 1. Transition Cosmos DB status to 'closed'
        # 2. Query Azure Monitor alert state via ARM API
        # 3. Assert Azure Monitor alert state == 'Closed'
        pass

    def test_sync_failure_does_not_block_transition(self) -> None:
        """SC-4: Azure Monitor sync failure must not block platform state transition."""
        # TODO: Test with unreachable Azure Monitor endpoint
        # Assert: Cosmos DB transition succeeds, sync error is logged
        pass
