"""Deduplication load test — requires live Cosmos DB and API gateway (DETECT-005)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def skip_without_live_infra() -> None:
    pytest.skip(
        "requires live Cosmos DB + API gateway (Phase 4 deployment) — "
        "enable when COSMOS_ENDPOINT and API_GATEWAY_URL are configured"
    )


class TestDedupLoad:
    """Load test for two-layer deduplication."""

    def test_10_identical_alerts_collapse_into_1_incident(self) -> None:
        pass

    def test_distinct_alert_correlates_to_open_incident(self) -> None:
        pass

    def test_closed_incident_does_not_correlate(self) -> None:
        pass
