# Quick Task 260406-ahq: E2E Real Incident Simulation Walkthrough

**Type:** Exploration + Small Fixes
**Estimated effort:** ~30% context
**Branch:** `gsd/quick-260406-ahq-real-incident-sim`

---

## Current State Analysis

After reading the full codebase, here is the current wiring status for each step of the E2E flow:

### What's Already Wired

| Step | Component | Status |
|------|-----------|--------|
| 1. POST incident | `POST /api/v1/incidents` in `main.py` | Fully wired. Accepts `IncidentPayload`, creates Foundry thread, queues `run_diagnostic_pipeline` as BackgroundTask |
| 2. Diagnostic pipeline | `diagnostic_pipeline.py` | Fully wired. Collects activity log, resource health, metrics (CPU/memory/disk/network), log analytics. Writes to Cosmos `evidence` container. Updates incident `investigation_status = evidence_ready` |
| 3. Evidence in UI | `VMDetailPanel.tsx` | Fully wired. Fetches `/api/proxy/incidents/{id}/evidence`, polls until ready, renders metric anomalies, recent changes, log errors |
| 4. VM metrics in UI | `vm_detail.py` | Fully wired. Real Azure Monitor metrics via `MonitorManagementClient`, sparkline charts in VMDetailPanel |
| 5. Chat investigation | `vm_chat.py` + `VMDetailPanel.tsx` | Fully wired. POST to compute agent with evidence context injection, polling, inline chat bubbles |
| 6. Approval creation | `agents/shared/approval_manager.py` | Fully wired. `create_approval_record()` writes to Cosmos `approvals` container with pending status, 30-min expiry |
| 7. Approval in Chat UI | `ChatDrawer.tsx` + `ProposalCard.tsx` | Fully wired. SSE `approval_gate` trace event renders ProposalCard with Approve/Reject buttons + countdown timer |
| 8. Approve/Reject API | `POST /api/v1/approvals/{id}/approve\|reject` | Fully wired. ETag concurrency, expiry check, resumes Foundry thread on approval |
| 9. Approve/Reject proxy | `app/api/proxy/approvals/[approvalId]/approve\|reject/route.ts` | Fully wired. Proxies to API gateway |
| 10. Execute remediation | `POST /api/v1/approvals/{id}/execute` | Fully wired (Phase 27). WAL, blast-radius pre-flight, 10-min verification, auto-rollback |

### Gaps Identified

| # | Gap | Severity | Description |
|---|-----|----------|-------------|
| G-1 | **No `GET /api/proxy/approvals` list route in web-ui** | LOW | Pending approvals are only visible in the chat SSE stream (ProposalCard). There's no standalone "Approvals" view in the dashboard. The Observability tab shows `pending` count but doesn't link to individual approvals. This means: for the demo, approvals MUST be discovered via the chat flow. |
| G-2 | **Approval creation requires agent LLM to decide** | MEDIUM | The approval record is created by `agents/shared/approval_manager.py` which is called by the Foundry agent during its run. The agent must autonomously decide to propose remediation. There's no guaranteed way to force the LLM to propose a specific action. The simulation depends on the agent's reasoning. |
| G-3 | **Jumphost resource ID needed** | INFO | The jumphost VM is in `aml-rg` (not `rg-aap-prod`). Need to discover its full ARM resource ID for the incident payload. |
| G-4 | **Incident partition key is `incident_id`** | INFO | The dedup module writes the incident with `incident_id` as partition key, but the diagnostic pipeline tries to read it with `resource_id` as partition key. This is a known quirk (pipeline falls back gracefully with a warning). |

### Key Insight: The "Approval" Step is Agent-Driven

The approval flow is **fully wired** end-to-end. However, the approval is created by the Foundry agent (LLM) as part of its reasoning, not by the API gateway. This means:

1. POST incident -> Foundry thread created -> Orchestrator routes to Compute agent
2. Compute agent investigates using its tools (metrics, activity log, resource health)
3. If the agent decides a remediation is needed, it calls `create_approval_record()`
4. The approval surfaces in the chat via SSE `approval_gate` event
5. User clicks Approve in the ProposalCard

For a deterministic demo, we can:
- **Option A:** Use the chat to explicitly ask "Propose restarting the stress-ng process" after evidence is collected
- **Option B:** Inject a synthetic approval directly into Cosmos (bypasses agent reasoning but guarantees UI visibility)
- **Recommended:** Do both. Start with Option A (real flow), fall back to Option B if the agent doesn't propose.

---

## Tasks

### Task 1: Produce End-to-End Walkthrough Script
**Goal:** Create `scripts/ops/simulate-real-incident.sh` that walks an operator through the full demo

**Steps:**
1. Discover the jumphost VM's full ARM resource ID using `az vm show`
2. SSH to jumphost and run `stress-ng --cpu $(nproc) --timeout 300s` (5 min CPU stress)
3. Wait ~2 minutes for Azure Monitor to ingest the CPU spike
4. POST a crafted incident to the API gateway pointing at the jumphost resource ID
5. Poll the evidence endpoint until `pipeline_status = complete`
6. Open the web UI -> Alerts tab -> click the incident -> VMDetailPanel shows real metrics
7. Click "Investigate with AI" -> Compute agent runs investigation with real evidence
8. The agent proposes remediation -> ProposalCard appears in chat
9. Click Approve -> thread resumes, remediation executes

**Script contents:**
- `# Step 0: Prerequisites` - check az login, jumphost reachable
- `# Step 1: Stress the VM` - SSH + stress-ng (or provide curl for cloud-init)
- `# Step 2: Wait for metrics` - sleep or poll Azure Monitor
- `# Step 3: Inject incident` - curl POST with real jumphost resource ID
- `# Step 4: Verify evidence` - curl GET evidence endpoint, show summary
- `# Step 5: Open Web UI` - instructions for browser navigation
- `# Step 6: Chat investigation` - instructions for "Investigate with AI"
- `# Step 7: Approval flow` - instructions for approve/reject
- `# Step 8: Cleanup` - kill stress-ng, optionally delete Cosmos records
- `# Fallback: Inject synthetic approval` - for deterministic demos

**Acceptance criteria:**
- [ ] Script is self-contained and runnable by an operator
- [ ] Uses real jumphost resource ID (discovered via `az vm show`)
- [ ] POST payload uses correct `IncidentPayload` schema
- [ ] Includes fallback for synthetic approval injection
- [ ] Includes cleanup step

### Task 2: Create Synthetic Approval Injection Script
**Goal:** Create `scripts/ops/inject-approval.py` for deterministic demo of the approval UI

When the agent doesn't propose a remediation (e.g., it just reports findings), we need a way to create a synthetic approval record in Cosmos so the ProposalCard renders in the web UI.

**Steps:**
1. Accept `--incident-id` and `--thread-id` from the walkthrough script output
2. Call `create_approval_record()` (or equivalent Cosmos upsert) with a realistic proposal: "Restart stress-ng process on jumphost to reduce CPU utilization"
3. Print the approval_id for manual approve/reject via curl

**Acceptance criteria:**
- [ ] Creates a realistic approval record in Cosmos `approvals` container
- [ ] Approval has correct schema (proposal, risk_level, expires_at, resource_snapshot)
- [ ] Prints approval_id and curl commands for approve/reject
- [ ] Works with `API_GATEWAY_AUTH_MODE=disabled` (current prod config)

### Task 3: Document Gaps and Demo Limitations
**Goal:** Add a "Known Limitations" section to the walkthrough script documenting:

1. **Approval is agent-driven**: The LLM may or may not propose remediation. Use fallback injection script.
2. **No standalone Approvals tab**: Approvals only visible in chat stream. Observability tab shows queue count.
3. **Evidence timing**: Diagnostic pipeline runs as BackgroundTask (~15-30s). Azure Monitor metrics lag ~2-3 minutes from VM.
4. **Stress-ng dependency**: Must be installed on jumphost (`sudo apt-get install stress-ng`).
5. **Auth disabled**: Current prod API gateway has `API_GATEWAY_AUTH_MODE=disabled`. No bearer token needed for curl commands.

**Acceptance criteria:**
- [ ] All gaps documented in the walkthrough script header
- [ ] Fallback paths clearly marked

---

## Verification

- [ ] `scripts/ops/simulate-real-incident.sh` exists and is executable
- [ ] `scripts/ops/inject-approval.py` exists and is executable
- [ ] Walkthrough covers all 7 steps from the task goal (stress VM, POST incident, evidence in UI, investigation, approval, approve)
- [ ] Jumphost resource ID discovery command is correct
- [ ] Incident payload matches `IncidentPayload` Pydantic model schema
- [ ] Approval injection matches `create_approval_record()` schema
