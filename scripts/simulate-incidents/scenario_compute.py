#!/usr/bin/env python3
"""Scenario 1: Compute — VM High CPU on vm-prod-01."""
import sys
from common import run_scenario, setup_logging

PAYLOAD = {
    "incident_id": "sim-compute-001",
    "severity": "Sev2",
    "domain": "compute",
    "affected_resources": [{
        "resource_id": "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.Compute/virtualMachines/vm-prod-01",
        "subscription_id": "4c727b88-12f4-4c91-9c2b-372aab3bbae9",
        "resource_type": "Microsoft.Compute/virtualMachines",
    }],
    "detection_rule": "HighCPUThreshold",
    "kql_evidence": "Perf | where ObjectName == 'Processor' | where CounterName == '% Processor Time' | where CounterValue > 95 | summarize avg(CounterValue) by bin(TimeGenerated, 5m), Computer",
    "title": "VM High CPU: vm-prod-01 sustained >95% for 15 minutes",
    "description": "Sustained CPU utilization above 95% threshold for 15 consecutive minutes.",
}

if __name__ == "__main__":
    setup_logging()
    result = run_scenario("compute", PAYLOAD)
    sys.exit(0 if result.success else 1)
