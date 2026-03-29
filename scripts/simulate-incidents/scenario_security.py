#!/usr/bin/env python3
"""Scenario 4: Security — Defender Suspicious Login."""
import sys
from common import run_scenario, setup_logging

PAYLOAD = {
    "incident_id": "sim-security-001",
    "severity": "Sev1",
    "domain": "security",
    "affected_resources": [{
        "resource_id": "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.Security/alerts/suspicious-login-001",
        "subscription_id": "4c727b88-12f4-4c91-9c2b-372aab3bbae9",
        "resource_type": "Microsoft.Security/alerts",
    }],
    "detection_rule": "DefenderSuspiciousLogin",
    "kql_evidence": "SecurityAlert | where AlertType == 'SIMULATED_BRUTE_FORCE' | where TimeGenerated > ago(1h)",
    "title": "Defender alert: suspicious login pattern from unusual geography",
    "description": "Multiple failed login attempts from IP 203.0.113.42 (unrecognized geography) followed by successful authentication.",
}

if __name__ == "__main__":
    setup_logging()
    result = run_scenario("security", PAYLOAD)
    sys.exit(0 if result.success else 1)
