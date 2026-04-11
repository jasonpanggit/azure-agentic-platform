---
title: "AKS — Node Not Ready"
version: "1.0"
domain: compute
scenario_tags:
  - aks
  - node
  - not-ready
  - kubelet
severity_threshold: P2
resource_types:
  - Microsoft.ContainerService/managedClusters
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers AKS scenarios where one or more nodes report NotReady status, indicating
kubelet failure, resource pressure (CPU/memory/disk), or VM-level issues.

## Pre-conditions
- AKS cluster node in NotReady state
- Alert: Node condition NotReady for >5 minutes

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_aks_node_pools` to list node pools with health, VM size,
   and resource pressure indicators.
   - *Expected signal:* All nodes Ready with no pressure conditions.
   - *Abnormal signal:* Node(s) in NotReady with MemoryPressure/DiskPressure/PIDPressure.

2. **[DIAGNOSTIC]** Call `query_aks_diagnostics` for control plane logs.
   - *Abnormal signal:* Kubelet crash loops, certificate expiry, or API server connectivity loss.

3. **[DIAGNOSTIC]** Call `query_resource_health` for the AKS cluster.
   - *Abnormal signal:* Degraded → platform-level issue.

4. **[DIAGNOSTIC]** Call `query_activity_log` (2h look-back).
   - *Abnormal signal:* Recent node pool scaling or upgrade event.

5. **[NOTIFY]** Notify operator:
   > "Incident {incident_id}: AKS cluster {resource_name} has nodes in NotReady state.
   >  Affected node pool: {node_pool_name}."
   - *Channels:* teams, email
   - *Severity:* warning

6. **[DECISION]** Root cause:
   - Cause A: Resource pressure (memory/disk/PID) on node
   - Cause B: Kubelet service failure or certificate issue
   - Cause C: VM-level failure (underlying VMSS instance)

## Remediation Steps

7. **[REMEDIATION:MEDIUM]** If Cause A or C: propose node pool scale-up to add capacity.
   - Call `propose_aks_node_pool_scale` with target_count and reason="Add nodes to compensate for NotReady nodes"
   - *Reversibility:* reversible (scale back down)
   - *Approval message:* "Approve scaling node pool {node_pool_name} to {target_count} nodes?"

## Escalation
- If control plane issue (Cause B): escalate to SRE agent for AKS support case
- If >50% nodes affected: P1 escalation

## Rollback
- Node pool scale: scale back to original count

## References
- KB: https://learn.microsoft.com/en-us/azure/aks/troubleshoot-node-not-ready
