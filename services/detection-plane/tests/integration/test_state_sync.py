"""State sync integration test — requires live Azure Monitor + Cosmos DB (SC-4)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def skip_without_live_infra() -> None:
    pytest.skip(
        "requires live Azure Monitor + Cosmos DB (SC-4 state sync, Phase 4 deployment) — "
        "enable when COSMOS_ENDPOINT, SUBSCRIPTION_ID, and AZURE_CLIENT_ID are configured"
    )


class TestBidirectionalStateSync:
    """Alert state bidirectional sync between Cosmos DB and Azure Monitor."""

    def test_acknowledge_syncs_to_azure_monitor(self) -> None:
        pass

    def test_close_syncs_to_azure_monitor(self) -> None:
        pass

    def test_sync_failure_does_not_block_transition(self) -> None:
        pass
