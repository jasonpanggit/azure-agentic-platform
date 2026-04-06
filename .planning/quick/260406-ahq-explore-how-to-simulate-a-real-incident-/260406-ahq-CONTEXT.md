# Quick Task 260406-ahq: Simulate Real Incident with Evidence + Remediation - Context

**Gathered:** 2026-04-05
**Status:** Ready for planning

<domain>
## Task Boundary

Explore how to simulate a realistic end-to-end incident in the Azure Agentic Platform:
1. Trigger a high-CPU incident on a real Azure VM (the jumphost)
2. Have the Compute agent investigate and collect real evidence (CPU/memory metrics + activity logs)
3. The agent proposes a remediation action (restart offending process/service)
4. The remediation appears as a pending approval in the Web UI
5. User approves/rejects via the Web UI approval flow

This is an exploration task — the output should be a working end-to-end demo walkthrough,
identifying any gaps in the current implementation and producing scripts/steps needed to run it.

</domain>

<decisions>
## Implementation Decisions

### Incident type
- High CPU on the real jumphost VM (real Azure VM, real resource ID)
- Stress the VM with `stress-ng` or similar to generate genuine Azure Monitor metrics

### Evidence content
- CPU/memory metrics from Azure Monitor (real time-series data)
- Recent ARM activity logs for the VM resource
- Investigation should surface what's consuming CPU

### Remediation flow
- Agent proposes to restart the offending process/service
- Approval surfaces in the Web UI as a pending approval card
- User clicks Approve or Reject in the UI to complete the flow

### Claude's Discretion
- Whether to use `stress-ng` vs a CPU-spin script on the VM
- The exact threshold/duration to trigger detection vs just generate metrics
- Which Azure Monitor metrics to poll (CPU percentage, available memory bytes)
- How to structure the approval payload for a process-restart action

</decisions>

<specifics>
## Specific Ideas

- Jumphost VM is in `aml-rg` resource group (known from prod-ops memory)
- Need to verify: does the approval endpoint exist in the API gateway? Does the UI render it?
- Remediation approval flow exists in Cosmos `approvals` container — need to check if it's wired to the UI
- The investigation produces evidence stored in Cosmos `evidence` container
- Detection plane fires on Azure Monitor alerts → but for this sim, may need to POST incident directly

</specifics>

<canonical_refs>
## Canonical References

- `services/api-gateway/main.py` — approval endpoints
- `services/web-ui/components/VMDetailPanel.tsx` — evidence + approval UI
- `services/api-gateway/vm_detail.py` — VM detail / metrics endpoints
- `.planning/memory/prod-ops.md` — jumphost VM ID, subscription info
</canonical_refs>
