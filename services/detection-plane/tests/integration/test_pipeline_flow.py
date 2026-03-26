"""Integration test: Event Hub -> Eventhouse pipeline flow (DETECT-002, SC-1).

This test sends a synthetic alert to Event Hub and verifies it flows through
the three-table KQL pipeline (RawAlerts -> EnrichedAlerts -> DetectionResults).

Requires:
- Live Event Hub namespace with 'raw-alerts' hub
- Live Fabric Eventhouse with KQL tables and update policies
- Environment variables: EVENTHUB_CONNECTION_STRING, EVENTHOUSE_URI, KQL_DATABASE

Run with: pytest tests/integration/test_pipeline_flow.py -v -m integration
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="Requires live Fabric + Event Hub infrastructure (Phase 4 deployment)")
class TestDetectionPipelineFlow:
    """End-to-end pipeline: Event Hub -> RawAlerts -> EnrichedAlerts -> DetectionResults."""

    def test_alert_reaches_raw_alerts_within_30s(self) -> None:
        """SC-1: Alert appears in RawAlerts within 30 seconds of firing."""
        # TODO: Implement after Fabric infrastructure is deployed
        # 1. Send Common Alert Schema payload to Event Hub
        # 2. Poll RawAlerts table via KQL query for up to 30 seconds
        # 3. Assert record exists with matching alert_id
        pass

    def test_enrichment_update_policy_fires(self) -> None:
        """DETECT-002: RawAlerts -> EnrichedAlerts update policy produces enriched record."""
        # TODO: After alert lands in RawAlerts, verify EnrichedAlerts record
        pass

    def test_classification_update_policy_fires(self) -> None:
        """DETECT-002: EnrichedAlerts -> DetectionResults with non-null domain."""
        # TODO: Verify DetectionResults record with domain field populated
        pass

    def test_sre_fallback_for_unknown_resource_type(self) -> None:
        """DETECT-002 + D-06: Unknown resource type classified as 'sre'."""
        # TODO: Send alert with unknown resource type, verify domain='sre'
        pass
