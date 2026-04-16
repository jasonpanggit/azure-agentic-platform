# Phase 61-1: Multi-Agent Parallel Investigation — PLAN

## Goal
Replace sequential orchestrator handoff with parallel multi-domain fan-out for complex incidents, enabling simultaneous compute/network/security investigation with synthesised root cause narrative.

## Files to Create / Modify

| File | Action |
|------|--------|
| `agents/orchestrator/concurrent_orchestrator.py` | CREATE — ConcurrentOrchestrator with asyncio.gather fan-out |
| `agents/orchestrator/tools.py` | CREATE — `correlate_multi_domain` @ai_function synthesis tool |
| `services/api-gateway/chat.py` | MODIFY — add fan_out / domain_result / synthesis SSE events |
| `services/web-ui/components/ParallelInvestigationPanel.tsx` | CREATE — UI panel for parallel investigation status |
| `agents/orchestrator/tests/test_concurrent_orchestrator.py` | CREATE — ≥8 pytest tests |
| `agents/orchestrator/tests/__init__.py` | CREATE — empty init |

## Implementation Steps

- [ ] 1. Create `concurrent_orchestrator.py` with domain keyword selection + asyncio.gather + sequential fallback
- [ ] 2. Create `tools.py` with `correlate_multi_domain` @ai_function
- [ ] 3. Add SSE event types to `chat.py` (fan_out, domain_result, synthesis)
- [ ] 4. Create `ParallelInvestigationPanel.tsx` with per-agent spinners + duration display
- [ ] 5. Create tests (≥8) covering domain selection, parallel dispatch, synthesis, fallback, SSE
- [ ] 6. Run pytest and tsc, fix any errors

## Key Constraints
- Python lazy imports (try/except ImportError with None fallback)
- Tool functions never raise — return structured error dicts
- CSS semantic tokens only (var(--accent-*), no hardcoded Tailwind colors)
- asyncio.gather with asyncio.wait_for for timeout handling
