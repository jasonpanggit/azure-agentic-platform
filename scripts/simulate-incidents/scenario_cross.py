#!/usr/bin/env python3
"""Scenario 7: Cross-Domain — Disk Full (Compute + Storage).

The API only accepts one domain per payload, so this scenario injects
TWO incidents — one compute, one storage — with related resource context.
"""
import sys
from common import run_scenario, setup_logging, SimulationClient

PAYLOAD_COMPUTE = {
    "incident_id": "sim-cross-001a",
    "severity": "Sev1",
    "domain": "compute",
    "affected_resources": [{
        "resource_id": "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.Compute/virtualMachines/vm-prod-02",
        "subscription_id": "4c727b88-12f4-4c91-9c2b-372aab3bbae9",
        "resource_type": "Microsoft.Compute/virtualMachines",
    }],
    "detection_rule": "VMDiskFullCritical",
    "title": "VM disk full: vm-prod-02 OS disk at 98% capacity",
    "description": "OS disk utilization at 98% on vm-prod-02. Immediate risk of service disruption.",
}

PAYLOAD_STORAGE = {
    "incident_id": "sim-cross-001b",
    "severity": "Sev1",
    "domain": "storage",
    "affected_resources": [{
        "resource_id": "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/rg-aap-prod/providers/Microsoft.Compute/disks/vm-prod-02-osdisk",
        "subscription_id": "4c727b88-12f4-4c91-9c2b-372aab3bbae9",
        # Intentional: storage agent receives managed disk (Compute/disks) — this is the
        # storage perspective of the cross-domain disk-full scenario. The resource_type is
        # Microsoft.Compute/disks (not Microsoft.Storage/*) because managed disks are a
        # Compute resource type that the storage agent must also understand.
        "resource_type": "Microsoft.Compute/disks",
    }],
    "detection_rule": "ManagedDiskCapacityCritical",
    "title": "Managed disk critical: vm-prod-02-osdisk at 98% capacity",
    "description": "Managed disk vm-prod-02-osdisk at 98% capacity. Correlated with VM disk full alert.",
}

if __name__ == "__main__":
    setup_logging()
    client = SimulationClient()
    result_a = run_scenario("cross-compute", PAYLOAD_COMPUTE, client=client)
    result_b = run_scenario("cross-storage", PAYLOAD_STORAGE, client=client)
    success = result_a.success and result_b.success
    sys.exit(0 if success else 1)
