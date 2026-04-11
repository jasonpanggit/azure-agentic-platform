---
title: "AKS — Pod CrashLoopBackOff"
version: "1.0"
domain: compute
scenario_tags:
  - aks
  - pod
  - crashloop
  - restart
severity_threshold: P2
resource_types:
  - Microsoft.ContainerService/managedClusters
is_generic: false
author: platform-team
last_updated: 2026-04-11
---

## Description
Covers AKS scenarios where pods enter CrashLoopBackOff state, indicating application
crash, misconfiguration, or resource limit exhaustion.

## Pre-conditions
- Pod in CrashLoopBackOff state for >3 restart cycles
- Alert: Container restart count exceeds threshold

## Triage Steps

1. **[DIAGNOSTIC]** Call `query_aks_diagnostics` for pod events, container logs, and
   restart reasons.
   - *Expected signal:* Pod running with 0 restarts.
   - *Abnormal signal:* OOMKilled, Error exit code, liveness probe failure.

2. **[DIAGNOSTIC]** Call `query_aks_node_pools` to verify node health and resource availability.
   - *Abnormal signal:* Node under resource pressure → pods evicted.

3. **[DIAGNOSTIC]** Call `query_activity_log` (2h look-back).
   - *Abnormal signal:* Recent deployment or config change correlating with crash start.

4. **[NOTIFY]** Notify operator:
   > "Incident {incident_id}: AKS cluster {resource_name} pod {pod_name} in CrashLoopBackOff.
   >  Restart count: {restart_count}. Last exit reason: {exit_reason}."
   - *Channels:* teams, email
   - *Severity:* warning

5. **[DECISION]** Root cause:
   - Cause A: OOMKilled → container memory limits too low
   - Cause B: Application error → bad config or code regression
   - Cause C: Node resource pressure → scheduling issue

## Remediation Steps

6. **[REMEDIATION:MEDIUM]** If Cause C: propose node pool scale-up.
   - Call `propose_aks_node_pool_scale` with reason="Add capacity for pod scheduling"
   - *Reversibility:* reversible
   - *Approval message:* "Approve scaling node pool to relieve resource pressure?"

## Escalation
- If Cause A or B: escalate to application team (platform cannot fix application code)
- Provide container logs and restart history in escalation

## Rollback
- Node pool scale: scale back to original count

## References
- KB: https://learn.microsoft.com/en-us/azure/aks/troubleshoot-common-issues
