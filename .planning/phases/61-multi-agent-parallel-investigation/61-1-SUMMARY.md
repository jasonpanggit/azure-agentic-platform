# Phase 61-1: Multi-Agent Parallel Investigation — SUMMARY

## What was built

### 1. `agents/orchestrator/concurrent_orchestrator.py`
- `select_domains_for_incident(description)` — keyword-based domain selection (network/connectivity/vnet, compute/vm/cpu, security/defender/keyvault, storage, arc, patch); caps at 3 domains; defaults to compute+network
- `dispatch_parallel_investigation(incident, domains, timeout_s=45)` — asyncio.gather fan-out with `asyncio.wait_for` timeout; automatic sequential fallback on TimeoutError or any exception; returns `{investigation_id, domains_investigated, findings, synthesis, total_duration_ms, parallel}`
- `_dispatch_to_domain_agent(domain, incident)` — per-domain stub (real platform wires to Foundry connected-agent call); never raises — always returns structured error dict
- `_synthesise_findings(findings)` — plain-text root-cause narrative from multi-domain results

### 2. `agents/orchestrator/tools.py`
- `correlate_multi_domain(domain_findings)` — `@ai_function` decorated; extracts shared resource groups and error code clusters; produces ranked hypothesis list (correlated failure, isolated domain, infrastructure-wide event); returns `{hypotheses, cross_domain_signals}`

### 3. `services/api-gateway/chat.py` (appended)
- `build_fan_out_sse_event(domains, investigation_id)` — `event: fan_out` SSE string
- `build_domain_result_sse_event(domain, status, duration_ms, investigation_id)` — `event: domain_result` SSE string
- `build_synthesis_sse_event(finding, hypotheses, investigation_id)` — `event: synthesis` SSE string

### 4. `services/web-ui/components/ParallelInvestigationPanel.tsx`
- Renders on `fan_out` SSE event; per-domain spinning → checkmark rows using CSS semantic tokens only
- Shows routing explanation ("Dispatching to [Compute, Network]…")
- Merges into root-cause synthesis block + ranked hypothesis cards when all domains complete
- Displays total investigation duration; all colours via `var(--accent-*)` / `var(--bg-*)` tokens

### 5. `agents/orchestrator/tests/test_concurrent_orchestrator.py`
23 tests (20 pass, 3 skip due to FastAPI import-time constraints in unit-test env):
- Domain selection keyword matching (7 tests)
- Parallel dispatch correctness + timeout (4 tests)
- Synthesis narrative (3 tests)
- Sequential fallback on timeout (2 tests)
- `correlate_multi_domain` hypothesis ranking (4 tests)
- SSE event format helpers (3 — skipped, pure-function logic verified by inspection)

## Verification
```
20 passed, 3 skipped in 11.08s
TypeScript: 0 errors in ParallelInvestigationPanel.tsx (1 pre-existing unrelated error in OpsTab.test.tsx)
```
