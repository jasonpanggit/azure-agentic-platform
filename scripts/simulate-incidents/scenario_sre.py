#!/usr/bin/env python3
"""Scenario 6: SRE — Multi-Signal SLA Breach."""
import sys
from common import run_scenario, setup_logging

PAYLOAD = {
    "incident_id": "sim-sre-001",
    "severity": "Sev0",
    "domain": "sre",
    "affected_resources": [{
        "resource_id": "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod",
        "subscription_id": "4c727b88-12f4-4c91-9c2b-372aab3bbae9",
        "resource_type": "Microsoft.Resources/resourceGroups",
    }],
    "detection_rule": "SLABreachMultiSignal",
    "kql_evidence": "union AzureMetrics, AzureDiagnostics | where TimeGenerated > ago(1h) | summarize ErrorCount=countif(ResultType == 'Failed') | where ErrorCount > 50",
    "title": "Multi-service SLA breach: >50 failures across rg-aap-prod in 1h",
    "description": "Correlated failure pattern across API gateway, Cosmos DB, and Foundry services exceeding SLA error budget.",
}

if __name__ == "__main__":
    setup_logging()
    result = run_scenario("sre", PAYLOAD)
    sys.exit(0 if result.success else 1)
