"""Activity log integration test — requires live Azure subscription (AUDIT-003)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def skip_without_live_infra() -> None:
    pytest.skip(
        "requires live Azure subscription + Log Analytics + Fabric OneLake "
        "(Phase 4 deployment) — enable when SUBSCRIPTION_ID and "
        "LOG_ANALYTICS_WORKSPACE_ID are configured"
    )


class TestActivityLogExport:
    """Activity Log export to Log Analytics and OneLake mirror."""

    def test_activity_log_reaches_log_analytics(self) -> None:
        pass

    def test_activity_log_mirrored_to_onelake(self) -> None:
        pass
