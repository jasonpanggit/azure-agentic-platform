---
wave: 2
depends_on:
  - 35-1-verification-feedback-loop-PLAN.md
files_modified:
  - services/api-gateway/pattern_analyzer.py
  - services/api-gateway/models.py
  - services/api-gateway/main.py
  - services/api-gateway/remediation_executor.py
  - services/api-gateway/tests/test_pattern_analyzer.py
autonomous: true
---

# Plan 35-2: MTTR Tracking and Intelligence

## Goal

Add Mean Time To Resolution (MTTR) tracking per issue type (domain, detection_rule, severity). Compute MTTR P50/P95/mean in the weekly pattern analysis. Surface MTTR stats in the `GET /api/v1/intelligence/platform-health` endpoint. Auto-set `resolved_at` on incidents when verification classifies RESOLVED.

## Derived Requirements

- **LOOP-003:** MTTR tracked per (domain, detection_rule, severity) tuple; P50/P95/mean computed in weekly pattern analysis; surfaced in platform-health endpoint.

<threat_model>

### Authentication/Authorization Risks
- **NONE:** No new endpoints. Extends existing `GET /api/v1/intelligence/platform-health` which is already behind Entra auth (`verify_token` dependency).

### Input Validation Risks
- **NONE:** MTTR computation is a pure server-side function consuming Cosmos data. No user input involved.

### Data Exposure Risks
- **LOW:** MTTR stats are aggregate metrics (P50, P95, mean minutes per issue type). No PII or resource-specific data is exposed beyond what `platform-health` already returns.

### High-Severity Threats
- **NONE.**

**Verdict:** No threats. Pure data aggregation extension.

</threat_model>

## Tasks

<task id="35-2-1">
<title>Auto-set resolved_at when verification returns RESOLVED</title>
<read_first>
- services/api-gateway/remediation_executor.py (_verify_remediation and _inject_verification_result — need to add auto-resolve logic)
- services/api-gateway/main.py (resolve_incident endpoint at line 1050 — shows the Cosmos patch pattern for resolved_at)
</read_first>
<action>
In `_inject_verification_result` in `remediation_executor.py`, after the `patch_item` call that increments `re_diagnosis_count`, add auto-resolution for RESOLVED verification results:

```python
# Auto-set resolved_at when verification_result is RESOLVED
if verification_result == "RESOLVED" and cosmos_client is not None:
    try:
        resolved_at = datetime.now(timezone.utc).isoformat()
        incidents_container.patch_item(
            item=incident_id,
            partition_key=incident_id,
            patch_operations=[
                {"op": "add", "path": "/status", "value": "resolved"},
                {"op": "add", "path": "/resolved_at", "value": resolved_at},
                {"op": "add", "path": "/auto_resolved", "value": True},
                {"op": "add", "path": "/resolution", "value": f"Auto-resolved: {proposed_action} verified as RESOLVED"},
            ],
        )
        logger.info(
            "_inject_verification_result: auto-resolved incident | incident_id=%s resolved_at=%s",
            incident_id, resolved_at,
        )
    except Exception as exc:
        logger.warning(
            "_inject_verification_result: failed to auto-resolve incident | incident_id=%s error=%s",
            incident_id, exc,
        )
```

This ensures MTTR can be computed from `created_at` to `resolved_at` for auto-resolved incidents.
</action>
<acceptance_criteria>
- grep "auto_resolved" services/api-gateway/remediation_executor.py returns at least 1 match
- grep "Auto-resolved" services/api-gateway/remediation_executor.py returns 1 match
- grep "resolved_at.*resolved_at" services/api-gateway/remediation_executor.py returns at least 1 match in the patch_operations
</acceptance_criteria>
</task>

<task id="35-2-2">
<title>Add compute_mttr_by_issue_type to pattern_analyzer.py</title>
<read_first>
- services/api-gateway/pattern_analyzer.py (full file — understand _group_incidents_by_pattern, _run_analysis_sync structure, existing imports at top of file)
- services/api-gateway/models.py (PatternAnalysisResult, PlatformHealth models)
</read_first>
<action>
1. **Add `from collections import defaultdict` to the import block** at the top of `pattern_analyzer.py` (if not already present).

2. Add `compute_mttr_by_issue_type` function to `pattern_analyzer.py` after `_aggregate_feedback`:

```python
def compute_mttr_by_issue_type(
    incidents: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Compute MTTR (Mean Time To Resolution) statistics grouped by issue type.

    Groups resolved incidents by (domain, detection_rule, severity) and computes
    P50, P95, and mean MTTR in minutes.

    Only includes incidents where both created_at and resolved_at are present.

    Args:
        incidents: List of incident documents from Cosmos.

    Returns:
        Dict mapping "domain:detection_rule:severity" → {
            "count": int,
            "p50_min": float,
            "p95_min": float,
            "mean_min": float,
        }
    """
    from datetime import datetime as _dt

    groups: Dict[str, List[float]] = defaultdict(list)

    for inc in incidents:
        created_at = inc.get("created_at")
        resolved_at = inc.get("resolved_at")
        if not created_at or not resolved_at:
            continue
        if inc.get("status") != "resolved":
            continue

        try:
            created = _dt.fromisoformat(created_at.replace("Z", "+00:00"))
            resolved = _dt.fromisoformat(resolved_at.replace("Z", "+00:00"))
            mttr_minutes = (resolved - created).total_seconds() / 60.0
            if mttr_minutes < 0:
                continue
        except (ValueError, TypeError):
            continue

        domain = inc.get("domain", "unknown")
        detection_rule = inc.get("detection_rule", "unknown")
        severity = inc.get("severity", "unknown")
        key = f"{domain}:{detection_rule}:{severity}"
        groups[key].append(mttr_minutes)

    result: Dict[str, Dict[str, Any]] = {}
    for key, times in groups.items():
        if not times:
            continue
        sorted_times = sorted(times)
        n = len(sorted_times)
        p50_idx = int(n * 0.50)
        p95_idx = min(int(n * 0.95), n - 1)
        result[key] = {
            "count": n,
            "p50_min": round(sorted_times[p50_idx], 1),
            "p95_min": round(sorted_times[p95_idx], 1),
            "mean_min": round(sum(sorted_times) / n, 1),
        }

    return result
```
</action>
<acceptance_criteria>
- grep "def compute_mttr_by_issue_type" services/api-gateway/pattern_analyzer.py returns 1 match
- grep "from collections import defaultdict" services/api-gateway/pattern_analyzer.py returns 1 match
- grep "p50_min" services/api-gateway/pattern_analyzer.py returns at least 1 match
- grep "p95_min" services/api-gateway/pattern_analyzer.py returns at least 1 match
- grep "mean_min" services/api-gateway/pattern_analyzer.py returns at least 1 match
- grep "domain:detection_rule:severity" services/api-gateway/pattern_analyzer.py returns 1 match (in docstring)
</acceptance_criteria>
</task>

<task id="35-2-3">
<title>Add mttr_summary to PatternAnalysisResult and wire into _run_analysis_sync</title>
<read_first>
- services/api-gateway/models.py (PatternAnalysisResult model — lines 509-519)
- services/api-gateway/pattern_analyzer.py (_run_analysis_sync function — lines 279-397)
</read_first>
<action>
1. **In `models.py`**, add `mttr_summary` field to `PatternAnalysisResult`:

```python
class PatternAnalysisResult(BaseModel):
    """Weekly pattern analysis output stored in Cosmos pattern_analysis container (PLATINT-001)."""

    analysis_id: str
    analysis_date: str
    period_days: int
    total_incidents_analyzed: int
    top_patterns: list[IncidentPattern]
    finops_summary: dict
    mttr_summary: dict = Field(
        default_factory=dict,
        description=(
            "MTTR statistics grouped by 'domain:detection_rule:severity' key. "
            "Each value contains count, p50_min, p95_min, mean_min (LOOP-003)."
        ),
    )
    generated_at: str
```

2. **In `pattern_analyzer.py`**, in `_run_analysis_sync`, after the FinOps summary computation (line 374) and before the result doc build (line 377), add:

```python
# --- MTTR summary ---
mttr_dict = compute_mttr_by_issue_type(incidents)
```

3. **In `_run_analysis_sync`**, add `"mttr_summary": mttr_dict,` to the result doc dict (after `"finops_summary": finops_dict,`):

```python
doc = {
    "id": f"pattern-{analysis_date}",
    "analysis_date": analysis_date,
    "analysis_id": f"pattern-{analysis_date}",
    "period_days": PATTERN_ANALYSIS_LOOKBACK_DAYS,
    "total_incidents_analyzed": len(incidents),
    "top_patterns": top_patterns,
    "finops_summary": finops_dict,
    "mttr_summary": mttr_dict,  # NEW
    "generated_at": now.isoformat(),
}
```
</action>
<acceptance_criteria>
- grep "mttr_summary" services/api-gateway/models.py returns at least 1 match
- grep "LOOP-003" services/api-gateway/models.py returns 1 match
- grep "mttr_summary" services/api-gateway/pattern_analyzer.py returns at least 2 matches (computation + doc insertion)
- grep "compute_mttr_by_issue_type" services/api-gateway/pattern_analyzer.py returns at least 2 matches (definition + call)
</acceptance_criteria>
</task>

<task id="35-2-4">
<title>Add MTTR fields to PlatformHealth model and platform-health endpoint</title>
<read_first>
- services/api-gateway/models.py (PlatformHealth model — lines 521-533)
- services/api-gateway/main.py (platform-health endpoint — search for "platform_health" or "PlatformHealth" to find the endpoint around line 1752; **specifically verify that `latest_analysis` variable exists in scope from a Cosmos query of the `pattern_analysis` container**)
</read_first>
<action>
1. **First, read the platform-health handler in main.py and confirm the variable `latest_analysis` exists in scope from a Cosmos query of the `pattern_analysis` container.** If it does not exist, add the query before the MTTR computation following the existing pattern in that handler:

```python
# Query latest pattern analysis from Cosmos (if not already present)
latest_results = list(
    pattern_analysis_container.query_items(
        query="SELECT TOP 1 * FROM c ORDER BY c.generated_at DESC",
        enable_cross_partition_query=True,
    )
)
latest_analysis = latest_results[0] if latest_results else {}
```

2. **In `models.py`**, add MTTR fields to `PlatformHealth`:

```python
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
    mttr_p50_minutes: Optional[float] = Field(
        default=None,
        description="P50 MTTR across all resolved incidents in the last 30 days (LOOP-003).",
    )
    mttr_p95_minutes: Optional[float] = Field(
        default=None,
        description="P95 MTTR across all resolved incidents in the last 30 days (LOOP-003).",
    )
    mttr_by_issue_type: dict = Field(
        default_factory=dict,
        description="MTTR breakdown by 'domain:detection_rule:severity' key (LOOP-003).",
    )
    generated_at: str
```

3. **In `main.py`**, in the platform-health endpoint handler, after confirming `latest_analysis` is in scope (step 1), add MTTR computation before returning the PlatformHealth object:

```python
# MTTR from latest pattern analysis (LOOP-003)
mttr_p50 = None
mttr_p95 = None
mttr_by_type = {}
if latest_analysis:
    mttr_summary = latest_analysis.get("mttr_summary", {})
    mttr_by_type = mttr_summary
    # Compute aggregate P50/P95 across all issue types
    # approximation: mean of per-issue-type P50s, not true population P50
    all_p50s = [v.get("p50_min", 0) for v in mttr_summary.values() if v.get("count", 0) > 0]
    all_p95s = [v.get("p95_min", 0) for v in mttr_summary.values() if v.get("count", 0) > 0]
    if all_p50s:
        mttr_p50 = round(sum(all_p50s) / len(all_p50s), 1)
    if all_p95s:
        mttr_p95 = round(max(all_p95s), 1)
```

Then include in the PlatformHealth constructor:
```python
mttr_p50_minutes=mttr_p50,
mttr_p95_minutes=mttr_p95,
mttr_by_issue_type=mttr_by_type,
```
</action>
<acceptance_criteria>
- grep "mttr_p50_minutes" services/api-gateway/models.py returns at least 1 match
- grep "mttr_p95_minutes" services/api-gateway/models.py returns at least 1 match
- grep "mttr_by_issue_type" services/api-gateway/models.py returns at least 1 match
- grep "LOOP-003" services/api-gateway/models.py returns at least 3 matches (one per new field)
- grep "mttr_p50_minutes" services/api-gateway/main.py returns at least 1 match
- grep "mttr_summary" services/api-gateway/main.py returns at least 1 match
- grep "latest_analysis" services/api-gateway/main.py returns at least 1 match in the platform-health handler context (either pre-existing or added by this task)
- grep "approximation.*mean of per-issue-type P50s" services/api-gateway/main.py returns 1 match (comment documenting the approximation)
</acceptance_criteria>
</task>

<task id="35-2-5">
<title>Unit tests for MTTR tracking</title>
<read_first>
- services/api-gateway/tests/test_pattern_analyzer.py (existing tests — understand test patterns, imports)
- services/api-gateway/pattern_analyzer.py (compute_mttr_by_issue_type function)
</read_first>
<action>
Add the following tests to `services/api-gateway/tests/test_pattern_analyzer.py`:

1. **`test_compute_mttr_empty_incidents`** — asserts `compute_mttr_by_issue_type([])` returns `{}`

2. **`test_compute_mttr_no_resolved_incidents`** — pass 3 incidents with status="new" (no resolved_at), asserts result is `{}`

3. **`test_compute_mttr_single_resolved`** — pass 1 resolved incident with `created_at="2026-04-01T10:00:00+00:00"` and `resolved_at="2026-04-01T10:30:00+00:00"`, domain="compute", detection_rule="HighCPU", severity="Sev1". Assert result has key `"compute:HighCPU:Sev1"` with `count=1`, `p50_min=30.0`, `p95_min=30.0`, `mean_min=30.0`

4. **`test_compute_mttr_multiple_resolved`** — pass 4 resolved incidents (same domain/rule/severity) with MTTR of 10, 20, 30, 60 minutes. Assert `count=4`, `p50_min=20.0` (index 2 of sorted [10,20,30,60]), `p95_min=60.0` (index 3), `mean_min=30.0`

5. **`test_compute_mttr_groups_by_issue_type`** — pass 2 resolved incidents in domain="compute" and 1 in domain="network". Assert result has 2 keys.

6. **`test_compute_mttr_skips_negative_mttr`** — pass 1 incident where resolved_at < created_at. Assert result is `{}`.

7. **`test_auto_resolve_sets_resolved_at`** — in the remediation executor test file, mock Cosmos `patch_item`, call `_inject_verification_result` with `verification_result="RESOLVED"`, assert `patch_item` was called with ops containing `"path": "/resolved_at"` and `"path": "/auto_resolved"`.
</action>
<acceptance_criteria>
- grep -c "def test_compute_mttr" services/api-gateway/tests/test_pattern_analyzer.py returns at least 5
- grep "test_compute_mttr_empty_incidents" services/api-gateway/tests/test_pattern_analyzer.py returns 1 match
- grep "test_compute_mttr_multiple_resolved" services/api-gateway/tests/test_pattern_analyzer.py returns 1 match
- grep "test_auto_resolve_sets_resolved_at" services/api-gateway/tests/test_remediation_executor.py returns 1 match
- Running `cd /Users/jasonmba/workspace/azure-agentic-platform && python -m pytest services/api-gateway/tests/test_pattern_analyzer.py -x -q -k "mttr"` exits 0
</acceptance_criteria>
</task>

## Verification

```bash
# 1. MTTR function exists
grep "def compute_mttr_by_issue_type" services/api-gateway/pattern_analyzer.py

# 2. defaultdict import present
grep "from collections import defaultdict" services/api-gateway/pattern_analyzer.py

# 3. mttr_summary in models
grep "mttr_summary\|mttr_p50_minutes\|mttr_p95_minutes\|mttr_by_issue_type" services/api-gateway/models.py

# 4. MTTR wired into _run_analysis_sync
grep "mttr_dict\|mttr_summary" services/api-gateway/pattern_analyzer.py

# 5. MTTR surfaced in platform-health endpoint
grep "mttr_p50\|mttr_p95\|mttr_by_type" services/api-gateway/main.py

# 6. MTTR approximation comment present
grep "approximation" services/api-gateway/main.py

# 7. Auto-resolve on RESOLVED
grep "auto_resolved" services/api-gateway/remediation_executor.py

# 8. Tests pass
cd /Users/jasonmba/workspace/azure-agentic-platform && python -m pytest services/api-gateway/tests/test_pattern_analyzer.py services/api-gateway/tests/test_remediation_executor.py -x -q
```

## must_haves

- [ ] `compute_mttr_by_issue_type()` function exists in `pattern_analyzer.py` and returns P50/P95/mean grouped by issue type
- [ ] `from collections import defaultdict` is in the import block of `pattern_analyzer.py`
- [ ] `mttr_summary` field added to `PatternAnalysisResult` model
- [ ] `mttr_p50_minutes`, `mttr_p95_minutes`, `mttr_by_issue_type` fields added to `PlatformHealth` model
- [ ] `GET /api/v1/intelligence/platform-health` returns MTTR metrics
- [ ] `latest_analysis` variable is confirmed in scope (from Cosmos query) before MTTR computation in platform-health handler
- [ ] `mttr_p50_minutes` field has code comment: `# approximation: mean of per-issue-type P50s, not true population P50`
- [ ] Auto-resolve logic sets `resolved_at` and `auto_resolved=True` when verification returns RESOLVED
- [ ] 7 new unit tests pass covering MTTR computation and auto-resolve
