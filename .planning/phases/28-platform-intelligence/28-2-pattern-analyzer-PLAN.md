---
plan: 28-2
phase: 28
wave: 1
depends_on: []
requirements: [PLATINT-001, PLATINT-002, PLATINT-003]
files_modified:
  - services/api-gateway/pattern_analyzer.py
  - services/api-gateway/models.py
  - services/api-gateway/approvals.py
  - services/api-gateway/tests/test_pattern_analyzer.py
autonomous: true
---

## Objective

Create the pattern analysis engine (`pattern_analyzer.py`) that groups incidents by `(domain, resource_type, detection_rule)` tuples, scores patterns, computes FinOps estimates, and integrates operator feedback from approval records. Extend the `ApprovalAction` model and `process_approval_decision()` to capture feedback. All pure Python — no numpy, sklearn, or external ML packages.

## Context

- Pattern analysis algorithm: tuple grouping on `(domain, resource_type, detection_rule)`, NOT k-means. Pure Python using `collections.Counter` and `collections.defaultdict`.
- Severity scoring: Sev0=4.0, Sev1=3.0, Sev2=2.0, Sev3=1.0, unknown=1.5
- FinOps: two estimates (no external API calls): `wasted_compute_usd` and `automation_savings_usd`
- Feedback capture: extend `ApprovalAction` with `feedback_text` and `feedback_tags`; extend `process_approval_decision()` to write them to Cosmos
- Background task pattern: `async def run_pattern_analysis_loop(cosmos_client, interval_seconds=604800)` — mirrors `run_forecast_sweep_loop` in `forecaster.py`
- Cosmos query pattern: `cosmos_client.get_database_client("aap").get_container_client("incidents")` + `query_items(..., enable_cross_partition_query=True)`
- Existing models in `services/api-gateway/models.py`: `ApprovalAction`, `IncidentPayload`, etc.
- Existing approvals in `services/api-gateway/approvals.py`: `process_approval_decision()` function
- Test location: `services/api-gateway/tests/test_pattern_analyzer.py`
- Test pattern: see `test_forecaster.py` — class-based test groups, pytest, `MagicMock` for Cosmos

## Tasks

<task id="1">
<name>Extend ApprovalAction model with feedback fields</name>
<read_first>
- services/api-gateway/models.py
</read_first>
<action>
Add two new optional fields to the `ApprovalAction` class in `models.py`:

```python
class ApprovalAction(BaseModel):
    """Payload for approve/reject actions (D-09, TEAMS-003, PLATINT-003)."""

    decided_by: str = Field(..., description="UPN or object ID of the operator")
    scope_confirmed: Optional[bool] = Field(
        default=None, description="Required True for prod subscriptions (REMEDI-006)"
    )
    thread_id: Optional[str] = Field(
        default=None, description="Thread ID from card data (TEAMS-003 Action.Execute)"
    )
    feedback_text: Optional[str] = Field(
        default=None, description="Free-text operator feedback on the proposal quality (PLATINT-003)"
    )
    feedback_tags: Optional[list[str]] = Field(
        default=None, description="Structured feedback tags, e.g. ['false_positive', 'not_useful'] (PLATINT-003)"
    )
```

Important: `feedback_tags` default is `None` (NOT `[]`) — Pydantic mutable default trap.
</action>
<acceptance_criteria>
- `grep 'feedback_text' services/api-gateway/models.py` returns a match
- `grep 'feedback_tags' services/api-gateway/models.py` returns a match
- `grep 'PLATINT-003' services/api-gateway/models.py` returns at least 1 match
- Existing fields (`decided_by`, `scope_confirmed`, `thread_id`) are unchanged
</acceptance_criteria>
</task>

<task id="2">
<name>Extend process_approval_decision to capture feedback</name>
<read_first>
- services/api-gateway/approvals.py
- services/api-gateway/models.py
</read_first>
<action>
Modify `process_approval_decision()` in `approvals.py`:

1. Add two new parameters after `scope_confirmed`:
   ```python
   async def process_approval_decision(
       approval_id: str,
       thread_id: str,
       decision: str,
       decided_by: str,
       scope_confirmed: Optional[bool] = None,
       feedback_text: Optional[str] = None,
       feedback_tags: Optional[list[str]] = None,
       cosmos_client: Optional[CosmosClient] = None,
   ) -> dict:
   ```

2. In the `updated_record` dict construction (around line 160), add feedback fields:
   ```python
   updated_record = {
       **record,
       "status": decision,
       "decided_at": now,
       "decided_by": decided_by,
   }
   if feedback_text is not None:
       updated_record["feedback_text"] = feedback_text
   if feedback_tags is not None:
       updated_record["feedback_tags"] = feedback_tags
   ```

This is a backward-compatible change — existing callers that don't pass feedback fields will work identically.
</action>
<acceptance_criteria>
- `grep 'feedback_text' services/api-gateway/approvals.py` returns at least 2 matches (parameter + dict write)
- `grep 'feedback_tags' services/api-gateway/approvals.py` returns at least 2 matches (parameter + dict write)
- The function signature still starts with `async def process_approval_decision(`
- No existing behavior changed — `decided_by`, `scope_confirmed`, `cosmos_client` params unchanged
</acceptance_criteria>
</task>

<task id="3">
<name>Add Pydantic models for pattern analysis</name>
<read_first>
- services/api-gateway/models.py
</read_first>
<action>
Add the following models to the END of `models.py` (after `RemediationResult`):

```python
class BusinessTier(BaseModel):
    """Operator-configured revenue tier for FinOps cost impact tracking (PLATINT-004)."""

    id: str
    tier_name: str
    monthly_revenue_usd: float
    resource_tags: dict
    created_at: str
    updated_at: str


class IncidentPattern(BaseModel):
    """A single recurring incident pattern identified by the pattern analyzer (PLATINT-001)."""

    pattern_id: str
    domain: str
    resource_type: Optional[str] = None
    detection_rule: Optional[str] = None
    incident_count: int
    frequency_per_week: float
    avg_severity_score: float
    top_title_words: list[str]
    first_seen: str
    last_seen: str
    operator_flagged: bool = False
    common_feedback: list[str] = []


class PatternAnalysisResult(BaseModel):
    """Weekly pattern analysis output stored in Cosmos pattern_analysis container (PLATINT-001)."""

    analysis_id: str
    analysis_date: str
    period_days: int
    total_incidents_analyzed: int
    top_patterns: list[IncidentPattern]
    finops_summary: dict
    generated_at: str


class PlatformHealth(BaseModel):
    """Platform-wide health metrics aggregated from existing data sources (PLATINT-004)."""

    detection_pipeline_lag_seconds: Optional[float] = None
    auto_remediation_success_rate: Optional[float] = None
    noise_reduction_pct: Optional[float] = None
    slo_compliance_pct: Optional[float] = None
    automation_savings_count: int = 0
    agent_p50_ms: Optional[float] = None
    agent_p95_ms: Optional[float] = None
    error_budget_portfolio: list[dict] = []
    generated_at: str


class BusinessTiersResponse(BaseModel):
    """Response wrapper for GET /api/v1/admin/business-tiers (PLATINT-004)."""

    tiers: list[BusinessTier]
```
</action>
<acceptance_criteria>
- `grep 'class BusinessTier' services/api-gateway/models.py` returns 1 match
- `grep 'class IncidentPattern' services/api-gateway/models.py` returns 1 match
- `grep 'class PatternAnalysisResult' services/api-gateway/models.py` returns 1 match
- `grep 'class PlatformHealth' services/api-gateway/models.py` returns 1 match
- `grep 'class BusinessTiersResponse' services/api-gateway/models.py` returns 1 match
- `grep 'PLATINT-001' services/api-gateway/models.py` returns at least 2 matches
- `grep 'PLATINT-004' services/api-gateway/models.py` returns at least 2 matches
</acceptance_criteria>
</task>

<task id="4">
<name>Create pattern_analyzer.py</name>
<read_first>
- services/api-gateway/forecaster.py (background loop pattern, env var pattern)
- services/api-gateway/approvals.py (Cosmos query pattern)
- services/api-gateway/models.py (IncidentPattern, PatternAnalysisResult)
</read_first>
<action>
Create `services/api-gateway/pattern_analyzer.py` with the following structure:

```python
"""Platform-wide incident pattern analysis — pure Python (PLATINT-001, PLATINT-002, PLATINT-003).

Groups incidents by (domain, resource_type, detection_rule) tuples.
Scores by count * avg_severity. Tracks FinOps estimates. Captures operator feedback.

Architecture:
- Pure functions: _severity_score, _group_incidents_by_pattern, _score_pattern,
  _extract_top_words, _compute_finops_summary, _aggregate_feedback
- analyze_patterns: orchestrates full analysis and writes to Cosmos
- run_pattern_analysis_loop: asyncio background task (mirrors forecaster.py)
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PATTERN_ANALYSIS_ENABLED: bool = os.environ.get("PATTERN_ANALYSIS_ENABLED", "true").lower() == "true"
PATTERN_ANALYSIS_INTERVAL_SECONDS: int = int(
    os.environ.get("PATTERN_ANALYSIS_INTERVAL_SECONDS", "604800")
)
PATTERN_ANALYSIS_LOOKBACK_DAYS: int = int(
    os.environ.get("PATTERN_ANALYSIS_LOOKBACK_DAYS", "30")
)
FINOPS_SAVINGS_PER_REMEDIATION_MINUTES: float = float(
    os.environ.get("FINOPS_SAVINGS_PER_REMEDIATION_MINUTES", "30")
)
FINOPS_HOURLY_RATE_USD: float = float(
    os.environ.get("FINOPS_HOURLY_RATE_USD", "0.10")
)
COSMOS_DATABASE: str = os.environ.get("COSMOS_DATABASE", "aap")
COSMOS_PATTERN_ANALYSIS_CONTAINER: str = os.environ.get(
    "COSMOS_PATTERN_ANALYSIS_CONTAINER", "pattern_analysis"
)

SEVERITY_SCORES: Dict[str, float] = {
    "Sev0": 4.0,
    "Sev1": 3.0,
    "Sev2": 2.0,
    "Sev3": 1.0,
}
DEFAULT_SEVERITY_SCORE: float = 1.5
```

Then implement these pure functions:

**`_severity_score(severity: str) -> float`**
- Return `SEVERITY_SCORES.get(severity, DEFAULT_SEVERITY_SCORE)`

**`_group_incidents_by_pattern(incidents: List[Dict[str, Any]]) -> Dict[tuple, List[Dict[str, Any]]]`**
- Group incidents by `(inc.get("domain", ""), inc.get("resource_type", ""), inc.get("detection_rule", ""))` tuple
- Use `defaultdict(list)` — iterate once, append to groups

**`_score_pattern(incidents: List[Dict[str, Any]]) -> float`**
- Return `len(incidents) * avg_severity_score`
- Where `avg_severity_score = sum(_severity_score(i.get("severity", "")) for i in incidents) / len(incidents)`

**`_extract_top_words(incidents: List[Dict[str, Any]], top_n: int = 5) -> List[str]`**
- Concatenate all `title` fields, lowercase, split on whitespace
- Filter out words with len < 4 (stop words)
- Use `Counter.most_common(top_n)` — return just the word strings

**`_compute_finops_summary(incidents: List[Dict[str, Any]], remediation_records: List[Dict[str, Any]]) -> Dict[str, Any]`**
- `wasted_compute_usd`: count of compute-domain incidents lasting >30 min. For each, get affected_resources count. Multiply: `count * FINOPS_HOURLY_RATE_USD * (0.5) * affected_count`. Duration check: `created_at` to `decided_at` or `resolved_at` or now, > 30 min.
  - Simplified: count compute incidents × 0.5h × FINOPS_HOURLY_RATE_USD × avg affected_resources
- `automation_savings_usd`: count of `status="complete"` records in `remediation_records` × `FINOPS_SAVINGS_PER_REMEDIATION_MINUTES / 60` × `FINOPS_HOURLY_RATE_USD`
- Return: `{"wasted_compute_usd": round(wasted, 2), "automation_savings_usd": round(savings, 2), "complete_remediations": complete_count, "compute_incidents_30min": compute_count}`

**`_aggregate_feedback(approval_records: List[Dict[str, Any]], pattern_key: tuple) -> tuple[bool, List[str]]`**
- Filter approvals where incident domain+resource_type+detection_rule matches pattern_key
- Collect all `feedback_tags` lists from matching approvals
- `operator_flagged = True` if >= 2 approvals have `"false_positive"` or `"not_useful"` in tags
- `common_feedback` = top-3 most frequent tags from Counter
- Return `(operator_flagged, common_feedback)`

**`async def analyze_patterns(cosmos_client: Any) -> Optional[Dict[str, Any]]`**
- Read incidents from last `PATTERN_ANALYSIS_LOOKBACK_DAYS` days from Cosmos `incidents` container
- Read remediation records from Cosmos `remediation_audit` container (last 30 days, `action_type="execute"`)
- Read approval records from Cosmos `approvals` container (last 30 days)
- Group incidents by pattern, score each, take top-5 by score descending
- For each top pattern, aggregate feedback from approvals
- Compute FinOps summary
- Build and upsert `PatternAnalysisResult` doc to Cosmos `pattern_analysis` container:
  ```python
  doc = {
      "id": f"pattern-{analysis_date}",
      "analysis_date": analysis_date,
      "analysis_id": f"pattern-{analysis_date}",
      "period_days": PATTERN_ANALYSIS_LOOKBACK_DAYS,
      "total_incidents_analyzed": len(incidents),
      "top_patterns": [...],  # list of IncidentPattern dicts
      "finops_summary": finops_dict,
      "generated_at": datetime.now(timezone.utc).isoformat(),
  }
  ```
- Return the doc dict, or None on error

**`async def run_pattern_analysis_loop(cosmos_client: Any, interval_seconds: int = PATTERN_ANALYSIS_INTERVAL_SECONDS) -> None`**
- If not `PATTERN_ANALYSIS_ENABLED`, log and return
- `while True: await asyncio.sleep(interval_seconds); await analyze_patterns(cosmos_client)`
- Handle CancelledError (re-raise), log other exceptions and continue

Key: All Cosmos operations use `loop.run_in_executor(None, _sync_fn)` pattern from forecaster.py. Tool functions never raise — return None on error.
</action>
<acceptance_criteria>
- File exists at `services/api-gateway/pattern_analyzer.py`
- `grep 'SEVERITY_SCORES' services/api-gateway/pattern_analyzer.py` returns a match
- `grep 'def _severity_score' services/api-gateway/pattern_analyzer.py` returns a match
- `grep 'def _group_incidents_by_pattern' services/api-gateway/pattern_analyzer.py` returns a match
- `grep 'def _score_pattern' services/api-gateway/pattern_analyzer.py` returns a match
- `grep 'def _extract_top_words' services/api-gateway/pattern_analyzer.py` returns a match
- `grep 'def _compute_finops_summary' services/api-gateway/pattern_analyzer.py` returns a match
- `grep 'def _aggregate_feedback' services/api-gateway/pattern_analyzer.py` returns a match
- `grep 'async def analyze_patterns' services/api-gateway/pattern_analyzer.py` returns a match
- `grep 'async def run_pattern_analysis_loop' services/api-gateway/pattern_analyzer.py` returns a match
- `grep 'PATTERN_ANALYSIS_ENABLED' services/api-gateway/pattern_analyzer.py` returns a match
- `grep 'PATTERN_ANALYSIS_INTERVAL_SECONDS' services/api-gateway/pattern_analyzer.py` returns a match
- `grep 'FINOPS_HOURLY_RATE_USD' services/api-gateway/pattern_analyzer.py` returns a match
- `grep 'FINOPS_SAVINGS_PER_REMEDIATION_MINUTES' services/api-gateway/pattern_analyzer.py` returns a match
- `grep 'defaultdict' services/api-gateway/pattern_analyzer.py` returns a match
- `grep 'Counter' services/api-gateway/pattern_analyzer.py` returns a match
- `grep 'from __future__ import annotations' services/api-gateway/pattern_analyzer.py` returns a match
- No `import numpy`, `import sklearn`, or `import scipy` in the file
</acceptance_criteria>
</task>

<task id="5">
<name>Create test_pattern_analyzer.py with 12+ tests</name>
<read_first>
- services/api-gateway/pattern_analyzer.py
- services/api-gateway/tests/test_forecaster.py (test pattern reference)
</read_first>
<action>
Create `services/api-gateway/tests/test_pattern_analyzer.py` with 12+ tests organized in test classes:

```python
"""Unit tests for the Pattern Analyzer (PLATINT-001, PLATINT-002, PLATINT-003).

Tests cover:
- _severity_score mapping (tests 1–4)
- _group_incidents_by_pattern grouping (tests 5–6)
- _score_pattern scoring math (test 7)
- _extract_top_words returns list of strings (test 8)
- _compute_finops_summary returns dict with expected keys (tests 9–10)
- analyze_patterns returns PatternAnalysisResult with top_patterns <= 5 (test 11)
- Feedback tag aggregation: operator_flagged=True when >= 2 false_positive (test 12)
"""
```

**Class TestSeverityScore (tests 1–4):**
1. `test_sev0_returns_4_0` — `_severity_score("Sev0") == 4.0`
2. `test_sev1_returns_3_0` — `_severity_score("Sev1") == 3.0`
3. `test_sev2_returns_2_0` — `_severity_score("Sev2") == 2.0`
4. `test_sev3_returns_1_0` — `_severity_score("Sev3") == 1.0`
5. (bonus) `test_unknown_returns_1_5` — `_severity_score("unknown") == 1.5`

**Class TestGroupIncidents (tests 5–6):**
5. `test_groups_by_tuple` — 3 incidents (2 compute/vm/cpu_alert, 1 network/lb/lb_alert) produces 2 groups
6. `test_empty_list` — empty list returns empty dict

**Class TestScorePattern (test 7):**
7. `test_score_pattern_math` — 3 Sev1 incidents: score = 3 * 3.0 = 9.0

**Class TestExtractTopWords (test 8):**
8. `test_extracts_words` — incidents with titles ["High CPU on vm-prod-01", "High CPU on vm-prod-02"] returns list containing "high" and "cpu" (after lowercasing)

**Class TestComputeFinopsSummary (tests 9–10):**
9. `test_returns_expected_keys` — result has keys `wasted_compute_usd` and `automation_savings_usd`
10. `test_automation_savings_math` — 2 complete remediations × (30/60) × 0.10 = 0.10 USD

**Class TestAnalyzePatterns (test 11):**
11. `test_analyze_patterns_returns_result_with_max_5_patterns` — Mock Cosmos to return 10 incidents across 7 different patterns. Verify `len(result["top_patterns"]) <= 5`

**Class TestFeedbackAggregation (test 12):**
12. `test_operator_flagged_on_false_positive` — Pass approval records where 2+ have `feedback_tags: ["false_positive"]` for a pattern key. Verify `operator_flagged is True` and `"false_positive"` in `common_feedback`.

All tests should import from `services.api_gateway.pattern_analyzer` and use `MagicMock` for Cosmos client where needed.
</action>
<acceptance_criteria>
- File exists at `services/api-gateway/tests/test_pattern_analyzer.py`
- `grep -c 'def test_' services/api-gateway/tests/test_pattern_analyzer.py` returns >= 12
- `grep 'test_sev0_returns_4_0' services/api-gateway/tests/test_pattern_analyzer.py` returns a match
- `grep 'test_sev1_returns_3_0' services/api-gateway/tests/test_pattern_analyzer.py` returns a match
- `grep 'test_sev2_returns_2_0' services/api-gateway/tests/test_pattern_analyzer.py` returns a match
- `grep 'test_sev3_returns_1_0' services/api-gateway/tests/test_pattern_analyzer.py` returns a match
- `grep 'test_groups_by_tuple' services/api-gateway/tests/test_pattern_analyzer.py` returns a match
- `grep 'test_score_pattern_math' services/api-gateway/tests/test_pattern_analyzer.py` returns a match
- `grep 'test_extracts_words' services/api-gateway/tests/test_pattern_analyzer.py` returns a match
- `grep 'test_returns_expected_keys' services/api-gateway/tests/test_pattern_analyzer.py` returns a match
- `grep 'test_automation_savings_math' services/api-gateway/tests/test_pattern_analyzer.py` returns a match
- `grep 'test_analyze_patterns' services/api-gateway/tests/test_pattern_analyzer.py` returns a match
- `grep 'test_operator_flagged' services/api-gateway/tests/test_pattern_analyzer.py` returns a match
- `grep 'PLATINT-001' services/api-gateway/tests/test_pattern_analyzer.py` returns a match
- Running `python -m pytest services/api-gateway/tests/test_pattern_analyzer.py -v` passes all tests
</acceptance_criteria>
</task>

## Verification Checklist

- [ ] `models.py` ApprovalAction has `feedback_text` and `feedback_tags` fields
- [ ] `models.py` has all 5 new model classes (BusinessTier, IncidentPattern, PatternAnalysisResult, PlatformHealth, BusinessTiersResponse)
- [ ] `approvals.py` process_approval_decision accepts `feedback_text` and `feedback_tags` params
- [ ] `approvals.py` writes feedback fields to Cosmos record when provided
- [ ] `pattern_analyzer.py` exists with all 8 functions listed
- [ ] `pattern_analyzer.py` uses only stdlib (collections, datetime, etc.) — no numpy/sklearn/scipy
- [ ] `SEVERITY_SCORES` dict maps Sev0=4.0, Sev1=3.0, Sev2=2.0, Sev3=1.0
- [ ] All 7 env vars defined in module-level constants
- [ ] `test_pattern_analyzer.py` has 12+ tests
- [ ] All tests pass: `python -m pytest services/api-gateway/tests/test_pattern_analyzer.py -v`

## must_haves

1. `ApprovalAction.feedback_text` field exists in `models.py` with type `Optional[str]`
2. `ApprovalAction.feedback_tags` field exists in `models.py` with type `Optional[list[str]]`
3. `process_approval_decision()` in `approvals.py` accepts and persists `feedback_text` and `feedback_tags`
4. `pattern_analyzer.py` exists with `_severity_score`, `_group_incidents_by_pattern`, `_score_pattern`, `_extract_top_words`, `_compute_finops_summary`, `_aggregate_feedback`, `analyze_patterns`, `run_pattern_analysis_loop`
5. Severity map: Sev0=4.0, Sev1=3.0, Sev2=2.0, Sev3=1.0, default=1.5
6. FinOps summary returns dict with `wasted_compute_usd` and `automation_savings_usd` keys
7. Top patterns capped at 5
8. `operator_flagged=True` when >= 2 false_positive feedback tags
9. All 5 new Pydantic models in `models.py`: `BusinessTier`, `IncidentPattern`, `PatternAnalysisResult`, `PlatformHealth`, `BusinessTiersResponse`
10. 12+ tests in `test_pattern_analyzer.py` all passing
