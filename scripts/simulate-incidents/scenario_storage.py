#!/usr/bin/env python3
"""Scenario 3: Storage — Account Quota Approaching Limit."""
import sys
from common import run_scenario, setup_logging

PAYLOAD = {
    "incident_id": "sim-storage-001",
    "severity": "Sev2",
    "domain": "storage",
    "affected_resources": [{
        "resource_id": "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.Storage/storageAccounts/aapstorageprod",
        "subscription_id": "4c727b88-12f4-4c91-9c2b-372aab3bbae9",
        "resource_type": "Microsoft.Storage/storageAccounts",
    }],
    "detection_rule": "StorageQuotaThreshold",
    "kql_evidence": "StorageBlobLogs | summarize TotalBytes=sum(RequestBodySize) | where TotalBytes > 4000000000000",
    "title": "Storage account approaching 5TB quota limit (80% utilization)",
    "description": "Blob storage usage at 4.1TB of 5TB limit. Approaching quota boundary.",
}

if __name__ == "__main__":
    setup_logging()
    result = run_scenario("storage", PAYLOAD)
    sys.exit(0 if result.success else 1)
