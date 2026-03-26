"""Integration test: Activity Log OneLake mirror (AUDIT-003, SC-6).

Verifies that Azure Activity Log events are exported to Log Analytics
and mirrored to Fabric OneLake within 5 minutes.

Requires:
- Azure subscription with Activity Log diagnostic settings
- Log Analytics workspace receiving Activity Log
- Fabric OneLake with Activity Log mirror configured
- Environment variables: SUBSCRIPTION_ID, LOG_ANALYTICS_WORKSPACE_ID

Run with: pytest tests/integration/test_activity_log.py -v -m integration
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="Requires live Azure subscription + OneLake mirror (Phase 4 deployment)")
class TestActivityLogExport:
    """Activity Log export to Log Analytics and OneLake mirror."""

    def test_activity_log_reaches_log_analytics(self) -> None:
        """AUDIT-003: Activity Log events appear in Log Analytics."""
        # TODO: Generate activity log event (create temp resource group)
        # Query Log Analytics for the event
        # Assert: event found within 5 minutes
        pass

    def test_activity_log_mirrored_to_onelake(self) -> None:
        """AUDIT-003 + SC-6: Activity Log events in OneLake within 5 minutes."""
        # TODO: After Log Analytics confirms event, query OneLake
        # Assert: event found with timestamp within 5 minutes of source
        pass
