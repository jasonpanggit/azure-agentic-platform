#!/usr/bin/env python3
"""Scenario 2: Network — NSG Rule Blocking Port 443."""
import sys
from common import run_scenario, setup_logging

PAYLOAD = {
    "incident_id": "sim-network-001",
    "severity": "Sev1",
    "domain": "network",
    "affected_resources": [{
        "resource_id": "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.Network/networkSecurityGroups/nsg-app-tier",
        "subscription_id": "4c727b88-12f4-4c91-9c2b-372aab3bbae9",
        "resource_type": "Microsoft.Network/networkSecurityGroups",
    }],
    "detection_rule": "NSGBlockedTraffic",
    "kql_evidence": "AzureNetworkAnalytics_CL | where FlowStatus_s == 'D' | where DestPort_d == 443",
    "title": "NSG Deny Rule blocking HTTPS to app tier",
    "description": "NSG effective rule denying inbound TCP/443 traffic to application tier subnet.",
}

if __name__ == "__main__":
    setup_logging()
    result = run_scenario("network", PAYLOAD)
    sys.exit(0 if result.success else 1)
