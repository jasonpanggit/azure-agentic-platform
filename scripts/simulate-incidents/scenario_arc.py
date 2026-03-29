#!/usr/bin/env python3
"""Scenario 5: Arc — Server Connectivity Loss."""
import sys
from common import run_scenario, setup_logging

PAYLOAD = {
    "incident_id": "sim-arc-001",
    "severity": "Sev2",
    "domain": "arc",
    "affected_resources": [{
        "resource_id": "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-arc-servers/providers/Microsoft.HybridCompute/machines/arc-server-prod-01",
        "subscription_id": "4c727b88-12f4-4c91-9c2b-372aab3bbae9",
        "resource_type": "Microsoft.HybridCompute/machines",
    }],
    "detection_rule": "ArcDisconnectedThreshold",
    "kql_evidence": "Heartbeat | where Computer == 'arc-server-prod-01' | summarize LastHeartbeat=max(TimeGenerated) | where LastHeartbeat < ago(30m)",
    "title": "Arc server disconnected: arc-server-prod-01 offline >30 minutes",
    "description": "Arc-enabled server has not sent heartbeat in over 30 minutes. Status: Disconnected.",
}

if __name__ == "__main__":
    setup_logging()
    result = run_scenario("arc", PAYLOAD)
    sys.exit(0 if result.success else 1)
