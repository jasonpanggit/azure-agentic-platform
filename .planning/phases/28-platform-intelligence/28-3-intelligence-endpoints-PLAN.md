---
plan: 28-3
phase: 28
wave: 2
depends_on: [28-1, 28-2]
requirements: [PLATINT-001, PLATINT-002, PLATINT-003, PLATINT-004]
files_modified:
  - services/api-gateway/main.py
  - services/api-gateway/tests/test_intelligence_endpoints.py
autonomous: true
---

## Objective

Wire the pattern analysis engine and platform health aggregation into the API gateway: add 5 endpoints (`GET /api/v1/intelligence/patterns`, `GET /api/v1/intelligence/platform-health`, `POST /api/v1/admin/business-tiers`, `GET /api/v1/admin/business-tiers`, `POST /api/v1/approvals/{approval_id}/approve` feedback passthrough), seed the default business tier on startup, start the background pattern analysis loop in the lifespan, and write comprehensive endpoint tests.

## Context

- `main.py` already has the lifespan function with background tasks: topology sync, forecast sweep, WAL stale monitor
- Pattern analysis loop follows the same pattern: `asyncio.create_task(run_pattern_analysis_loop(...))`
- Endpoints follow existing patterns: `@app.get(...)` with `Depends(verify_token)`, `Depends(get_cosmos_client)`, etc.
- The `approve_proposal` endpoint at line ~1226 already calls `process_approval_decision()` — needs `feedback_text` and `feedback_tags` passthrough
- The `reject_proposal` endpoint at line ~1262 also needs feedback passthrough
- Test files: `services/api-gateway/tests/test_intelligence_endpoints.py`
- Test client pattern: FastAPI `TestClient` with dependency overrides for `get_cosmos_client`, `verify_token`
- Environment variables for new containers: `COSMOS_PATTERN_ANALYSIS_CONTAINER` (default "pattern_analysis"), `COSMOS_BUSINESS_TIERS_CONTAINER` (default "business_tiers")
- Platform health aggregation reads from: incidents container (det- prefix lag), remediation_audit container (success rate, automation savings), slo_definitions PostgreSQL table (SLO compliance, error budgets)
- Business tier seeding: on startup, check if business_tiers container is empty; if so, seed `{"id": "default", "tier_name": "default", "monthly_revenue_usd": 0.0, "resource_tags": {}, "created_at": now, "updated_at": now}`

## Tasks

<task id="1">
<name>Add model imports to main.py</name>
<read_first>
- services/api-gateway/main.py (import section lines 50-103)
- services/api-gateway/models.py
</read_first>
<action>
Add the new model imports to the existing import block from `services.api_gateway.models` in `main.py`:

```python
from services.api_gateway.models import (
    # ... existing imports ...
    BusinessTier,
    BusinessTiersResponse,
    IncidentPattern,
    PatternAnalysisResult,
    PlatformHealth,
)
```

Add the pattern analyzer imports:

```python
from services.api_gateway.pattern_analyzer import (
    PATTERN_ANALYSIS_ENABLED,
    PATTERN_ANALYSIS_INTERVAL_SECONDS,
    analyze_patterns,
    run_pattern_analysis_loop,
)
```

Define container name constants at module level (after the logger definition):

```python
COSMOS_PATTERN_ANALYSIS_CONTAINER = os.environ.get(
    "COSMOS_PATTERN_ANALYSIS_CONTAINER", "pattern_analysis"
)
COSMOS_BUSINESS_TIERS_CONTAINER = os.environ.get(
    "COSMOS_BUSINESS_TIERS_CONTAINER", "business_tiers"
)
```
</action>
<acceptance_criteria>
- `grep 'from services.api_gateway.pattern_analyzer import' services/api-gateway/main.py` returns a match
- `grep 'BusinessTier' services/api-gateway/main.py` returns at least 1 match
- `grep 'PatternAnalysisResult' services/api-gateway/main.py` returns at least 1 match
- `grep 'PlatformHealth' services/api-gateway/main.py` returns at least 1 match
- `grep 'COSMOS_PATTERN_ANALYSIS_CONTAINER' services/api-gateway/main.py` returns at least 1 match
- `grep 'COSMOS_BUSINESS_TIERS_CONTAINER' services/api-gateway/main.py` returns at least 1 match
</acceptance_criteria>
</task>

<task id="2">
<name>Add startup seeding and background loop to lifespan</name>
<read_first>
- services/api-gateway/main.py (lifespan function, lines 246-370)
- services/api-gateway/forecaster.py (run_forecast_sweep_loop pattern)
</read_first>
<action>
Modify the `lifespan` function in `main.py`:

**1. After WAL stale monitor startup block (around line 340), add business tier seeding:**

```python
    # Seed default business tier if container is empty (PLATINT-004)
    if app.state.cosmos_client is not None:
        try:
            _bt_db = app.state.cosmos_client.get_database_client(
                os.environ.get("COSMOS_DATABASE", "aap")
            )
            _bt_container = _bt_db.get_container_client(COSMOS_BUSINESS_TIERS_CONTAINER)
            _bt_items = list(_bt_container.query_items(
                "SELECT c.id FROM c",
                enable_cross_partition_query=True,
                max_item_count=1,
            ))
            if not _bt_items:
                _now_iso = datetime.now(timezone.utc).isoformat()
                _bt_container.upsert_item({
                    "id": "default",
                    "tier_name": "default",
                    "monthly_revenue_usd": 0.0,
                    "resource_tags": {},
                    "created_at": _now_iso,
                    "updated_at": _now_iso,
                })
                logger.info("startup: seeded default business tier")
            else:
                logger.info("startup: business_tiers container already has %d item(s)", len(_bt_items))
        except Exception as exc:
            logger.warning("startup: business tier seeding failed (non-fatal) | error=%s", exc)
```

Note: import `datetime` and `timezone` from the `datetime` module at the top of the lifespan or use inline import. The `from datetime import datetime, timezone` is likely not imported at module level in main.py — check and add if needed:
```python
from datetime import datetime, timezone
```

**2. After business tier seeding, add pattern analysis loop:**

```python
    # Start pattern analysis background loop (PLATINT-001)
    _pattern_analysis_task: Optional[asyncio.Task] = None
    if app.state.cosmos_client is not None and PATTERN_ANALYSIS_ENABLED:
        _pattern_analysis_task = asyncio.create_task(
            run_pattern_analysis_loop(
                cosmos_client=app.state.cosmos_client,
                interval_seconds=PATTERN_ANALYSIS_INTERVAL_SECONDS,
            )
        )
        logger.info(
            "startup: pattern analysis loop started | interval=%ds",
            PATTERN_ANALYSIS_INTERVAL_SECONDS,
        )
    else:
        logger.warning(
            "startup: pattern analysis loop not started "
            "(COSMOS_ENDPOINT=%s, PATTERN_ANALYSIS_ENABLED=%s)",
            "set" if app.state.cosmos_client else "not_set",
            os.environ.get("PATTERN_ANALYSIS_ENABLED", "true"),
        )
```

**3. In the teardown section (after `yield`), cancel the pattern analysis task:**

```python
    # Cancel pattern analysis loop on shutdown
    if _pattern_analysis_task is not None and not _pattern_analysis_task.done():
        _pattern_analysis_task.cancel()
        try:
            await _pattern_analysis_task
        except asyncio.CancelledError:
            pass
        logger.info("shutdown: pattern analysis loop cancelled")
```
</action>
<acceptance_criteria>
- `grep 'seeded default business tier' services/api-gateway/main.py` returns a match
- `grep 'pattern analysis loop started' services/api-gateway/main.py` returns a match
- `grep 'pattern analysis loop cancelled' services/api-gateway/main.py` returns a match
- `grep 'run_pattern_analysis_loop' services/api-gateway/main.py` returns at least 1 match
- `grep 'COSMOS_BUSINESS_TIERS_CONTAINER' services/api-gateway/main.py` returns at least 2 matches (constant def + seed usage)
- `grep 'tier_name.*default' services/api-gateway/main.py` returns a match (the seed document)
</acceptance_criteria>
</task>

<task id="3">
<name>Add GET /api/v1/intelligence/patterns endpoint</name>
<read_first>
- services/api-gateway/main.py (existing endpoint patterns)
- services/api-gateway/pattern_analyzer.py
</read_first>
<action>
Add the patterns endpoint to `main.py` after the existing audit endpoints:

```python
@app.get(
    "/api/v1/intelligence/patterns",
    response_model=PatternAnalysisResult,
)
async def get_pattern_analysis(
    token: dict[str, Any] = Depends(verify_token),
    cosmos: Any = Depends(get_optional_cosmos_client),
) -> PatternAnalysisResult:
    """Get the most recent pattern analysis result (PLATINT-001).

    Returns the latest weekly analysis from the pattern_analysis container.
    Returns 404 if no analysis has been run yet.
    Returns 503 if Cosmos DB is not configured.

    Authentication: Entra ID Bearer token required.
    """
    if cosmos is None:
        raise HTTPException(status_code=503, detail="Pattern analysis store not configured")
    try:
        db = cosmos.get_database_client(os.environ.get("COSMOS_DATABASE", "aap"))
        container = db.get_container_client(COSMOS_PATTERN_ANALYSIS_CONTAINER)
        # Get the most recent analysis by ordering analysis_date descending
        items = list(container.query_items(
            "SELECT * FROM c ORDER BY c.analysis_date DESC OFFSET 0 LIMIT 1",
            enable_cross_partition_query=True,
        ))
        if not items:
            raise HTTPException(status_code=404, detail="No pattern analysis available yet")
        clean = {k: v for k, v in items[0].items() if not k.startswith("_")}
        return PatternAnalysisResult(**clean)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_pattern_analysis: error | error=%s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Pattern analysis retrieval failed")
```
</action>
<acceptance_criteria>
- `grep '/api/v1/intelligence/patterns' services/api-gateway/main.py` returns a match
- `grep 'async def get_pattern_analysis' services/api-gateway/main.py` returns a match
- `grep 'PLATINT-001' services/api-gateway/main.py` returns at least 1 match
- `grep 'PatternAnalysisResult' services/api-gateway/main.py` returns at least 2 matches (import + usage)
</acceptance_criteria>
</task>

<task id="4">
<name>Add GET /api/v1/intelligence/platform-health endpoint</name>
<read_first>
- services/api-gateway/main.py
- services/api-gateway/slo_tracker.py (list_slos function)
- services/api-gateway/models.py (PlatformHealth model)
</read_first>
<action>
Add the platform health endpoint to `main.py`:

```python
@app.get(
    "/api/v1/intelligence/platform-health",
    response_model=PlatformHealth,
)
async def get_platform_health(
    token: dict[str, Any] = Depends(verify_token),
    cosmos: Any = Depends(get_optional_cosmos_client),
) -> PlatformHealth:
    """Aggregate platform-wide health metrics (PLATINT-004).

    Computes from existing data sources:
    - detection_pipeline_lag_seconds: age of most recent det- incident
    - auto_remediation_success_rate: complete/(complete+failed) from remediation_audit last 7d
    - noise_reduction_pct: suppressed_cascade/total incidents last 24h
    - slo_compliance_pct: healthy SLOs / total SLOs
    - automation_savings_count: complete remediation executions last 30d
    - agent_p50_ms, agent_p95_ms: None (deferred — requires App Insights query)
    - error_budget_portfolio: [{slo_id, error_budget_pct}] from slo_definitions

    Authentication: Entra ID Bearer token required.
    """
    from datetime import datetime as _dt, timezone as _tz

    now = _dt.now(_tz.utc)
    now_iso = now.isoformat()

    detection_pipeline_lag_seconds: Optional[float] = None
    auto_remediation_success_rate: Optional[float] = None
    noise_reduction_pct: Optional[float] = None
    slo_compliance_pct: Optional[float] = None
    automation_savings_count: int = 0
    error_budget_portfolio: list[dict] = []

    if cosmos is not None:
        db_name = os.environ.get("COSMOS_DATABASE", "aap")
        db = cosmos.get_database_client(db_name)

        # 1. Detection pipeline lag: age of most recent det- incident
        try:
            incidents_container = db.get_container_client("incidents")
            det_items = list(incidents_container.query_items(
                "SELECT TOP 1 c.created_at FROM c WHERE STARTSWITH(c.incident_id, 'det-') ORDER BY c.created_at DESC",
                enable_cross_partition_query=True,
            ))
            if det_items and det_items[0].get("created_at"):
                last_det = _dt.fromisoformat(det_items[0]["created_at"])
                if last_det.tzinfo is None:
                    last_det = last_det.replace(tzinfo=_tz.utc)
                detection_pipeline_lag_seconds = (now - last_det).total_seconds()
        except Exception as exc:
            logger.debug("platform_health: detection lag query failed | error=%s", exc)

        # 2. Auto-remediation success rate (last 7 days)
        try:
            remediation_container = db.get_container_client("remediation_audit")
            cutoff_7d = (now - timedelta(days=7)).isoformat()
            rem_items = list(remediation_container.query_items(
                "SELECT c.status FROM c WHERE c.action_type = 'execute' AND c.executed_at >= @cutoff",
                parameters=[{"name": "@cutoff", "value": cutoff_7d}],
                enable_cross_partition_query=True,
            ))
            complete_count = sum(1 for r in rem_items if r.get("status") == "complete")
            failed_count = sum(1 for r in rem_items if r.get("status") == "failed")
            total_rem = complete_count + failed_count
            if total_rem > 0:
                auto_remediation_success_rate = round(complete_count / total_rem * 100, 1)
        except Exception as exc:
            logger.debug("platform_health: remediation rate query failed | error=%s", exc)

        # 3. Noise reduction percentage (last 24 hours)
        try:
            import time as _time_mod
            cutoff_ts = int(_time_mod.time()) - 86400
            noise_items = list(incidents_container.query_items(
                "SELECT c.status FROM c WHERE c._ts > @cutoff",
                parameters=[{"name": "@cutoff", "value": cutoff_ts}],
                enable_cross_partition_query=True,
            ))
            total_noise = len(noise_items)
            suppressed = sum(1 for i in noise_items if i.get("status") == "suppressed_cascade")
            if total_noise > 0:
                noise_reduction_pct = round(suppressed / total_noise * 100, 1)
        except Exception as exc:
            logger.debug("platform_health: noise reduction query failed | error=%s", exc)

        # 4. Automation savings count (last 30 days)
        try:
            cutoff_30d = (now - timedelta(days=30)).isoformat()
            savings_items = list(remediation_container.query_items(
                "SELECT c.id FROM c WHERE c.status = 'complete' AND c.action_type = 'execute' AND c.executed_at >= @cutoff",
                parameters=[{"name": "@cutoff", "value": cutoff_30d}],
                enable_cross_partition_query=True,
            ))
            automation_savings_count = len(savings_items)
        except Exception as exc:
            logger.debug("platform_health: automation savings query failed | error=%s", exc)

    # 5. SLO compliance + error budget portfolio (from PostgreSQL)
    try:
        slos = await list_slos()
        if slos:
            healthy_count = sum(1 for s in slos if s.get("status") == "healthy")
            slo_compliance_pct = round(healthy_count / len(slos) * 100, 1)
            error_budget_portfolio = [
                {"slo_id": s.get("id", ""), "error_budget_pct": s.get("error_budget_pct")}
                for s in slos
            ]
    except Exception as exc:
        logger.debug("platform_health: SLO compliance query failed | error=%s", exc)

    return PlatformHealth(
        detection_pipeline_lag_seconds=detection_pipeline_lag_seconds,
        auto_remediation_success_rate=auto_remediation_success_rate,
        noise_reduction_pct=noise_reduction_pct,
        slo_compliance_pct=slo_compliance_pct,
        automation_savings_count=automation_savings_count,
        agent_p50_ms=None,
        agent_p95_ms=None,
        error_budget_portfolio=error_budget_portfolio,
        generated_at=now_iso,
    )
```

Note: Add `from datetime import timedelta` if not already imported at module level. Check the existing imports — `timedelta` may need to be added alongside the existing datetime imports.
</action>
<acceptance_criteria>
- `grep '/api/v1/intelligence/platform-health' services/api-gateway/main.py` returns a match
- `grep 'async def get_platform_health' services/api-gateway/main.py` returns a match
- `grep 'detection_pipeline_lag_seconds' services/api-gateway/main.py` returns at least 1 match
- `grep 'auto_remediation_success_rate' services/api-gateway/main.py` returns at least 1 match
- `grep 'noise_reduction_pct' services/api-gateway/main.py` returns at least 1 match
- `grep 'slo_compliance_pct' services/api-gateway/main.py` returns at least 1 match
- `grep 'error_budget_portfolio' services/api-gateway/main.py` returns at least 1 match
- `grep "STARTSWITH(c.incident_id, 'det-')" services/api-gateway/main.py` returns a match
</acceptance_criteria>
</task>

<task id="5">
<name>Add POST and GET /api/v1/admin/business-tiers endpoints</name>
<read_first>
- services/api-gateway/main.py
- services/api-gateway/models.py (BusinessTier, BusinessTiersResponse)
</read_first>
<action>
Add the business tiers CRUD endpoints to `main.py`:

```python
@app.post(
    "/api/v1/admin/business-tiers",
    response_model=BusinessTier,
)
async def upsert_business_tier(
    payload: BusinessTier,
    token: dict[str, Any] = Depends(verify_token),
    cosmos: Any = Depends(get_optional_cosmos_client),
) -> BusinessTier:
    """Create or update a business tier for FinOps cost impact tracking (PLATINT-004).

    Upserts by tier_name (id == tier_name). Requires admin-level Entra token.

    Authentication: Entra ID Bearer token required.
    """
    if cosmos is None:
        raise HTTPException(status_code=503, detail="Business tier store not configured")
    try:
        from datetime import datetime as _dt, timezone as _tz
        now_iso = _dt.now(_tz.utc).isoformat()

        doc = payload.model_dump()
        doc["id"] = payload.tier_name  # Cosmos id = tier_name
        doc["updated_at"] = now_iso
        if not doc.get("created_at"):
            doc["created_at"] = now_iso

        db = cosmos.get_database_client(os.environ.get("COSMOS_DATABASE", "aap"))
        container = db.get_container_client(COSMOS_BUSINESS_TIERS_CONTAINER)
        container.upsert_item(doc)
        logger.info("business_tier: upserted | tier_name=%s", payload.tier_name)
        return BusinessTier(**doc)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("upsert_business_tier: error | error=%s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Business tier upsert failed")


@app.get(
    "/api/v1/admin/business-tiers",
    response_model=BusinessTiersResponse,
)
async def list_business_tiers(
    token: dict[str, Any] = Depends(verify_token),
    cosmos: Any = Depends(get_optional_cosmos_client),
) -> BusinessTiersResponse:
    """List all configured business tiers (PLATINT-004).

    Authentication: Entra ID Bearer token required.
    """
    if cosmos is None:
        raise HTTPException(status_code=503, detail="Business tier store not configured")
    try:
        db = cosmos.get_database_client(os.environ.get("COSMOS_DATABASE", "aap"))
        container = db.get_container_client(COSMOS_BUSINESS_TIERS_CONTAINER)
        items = list(container.query_items(
            "SELECT * FROM c",
            enable_cross_partition_query=True,
        ))
        tiers = [
            BusinessTier(**{k: v for k, v in item.items() if not k.startswith("_")})
            for item in items
        ]
        return BusinessTiersResponse(tiers=tiers)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("list_business_tiers: error | error=%s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Business tier retrieval failed")
```
</action>
<acceptance_criteria>
- `grep '/api/v1/admin/business-tiers' services/api-gateway/main.py` returns at least 2 matches (POST + GET)
- `grep 'async def upsert_business_tier' services/api-gateway/main.py` returns a match
- `grep 'async def list_business_tiers' services/api-gateway/main.py` returns a match
- `grep 'BusinessTiersResponse' services/api-gateway/main.py` returns at least 2 matches
- `grep 'PLATINT-004' services/api-gateway/main.py` returns at least 2 matches
</acceptance_criteria>
</task>

<task id="6">
<name>Pass feedback fields through approve/reject endpoints</name>
<read_first>
- services/api-gateway/main.py (approve_proposal and reject_proposal functions, lines ~1225-1293)
- services/api-gateway/approvals.py (process_approval_decision signature)
</read_first>
<action>
Modify the `approve_proposal` endpoint to pass feedback fields:

In the `process_approval_decision` call inside `approve_proposal`, add:
```python
        await process_approval_decision(
            approval_id=approval_id,
            thread_id=effective_thread_id,
            decision="approved",
            decided_by=payload.decided_by,
            scope_confirmed=payload.scope_confirmed,
            feedback_text=payload.feedback_text,
            feedback_tags=payload.feedback_tags,
            cosmos_client=cosmos_client,
        )
```

Modify the `reject_proposal` endpoint similarly:
```python
        await process_approval_decision(
            approval_id=approval_id,
            thread_id=effective_thread_id,
            decision="rejected",
            decided_by=payload.decided_by,
            feedback_text=payload.feedback_text,
            feedback_tags=payload.feedback_tags,
            cosmos_client=cosmos_client,
        )
```

This is a backward-compatible change — `feedback_text` and `feedback_tags` are Optional with default None on ApprovalAction, so existing callers that don't send these fields work identically.
</action>
<acceptance_criteria>
- `grep 'feedback_text=payload.feedback_text' services/api-gateway/main.py` returns at least 2 matches (approve + reject)
- `grep 'feedback_tags=payload.feedback_tags' services/api-gateway/main.py` returns at least 2 matches (approve + reject)
</acceptance_criteria>
</task>

<task id="7">
<name>Create test_intelligence_endpoints.py with 10+ tests</name>
<read_first>
- services/api-gateway/main.py (new endpoints)
- services/api-gateway/tests/test_forecast_endpoints.py (test pattern reference)
- services/api-gateway/tests/test_patch_endpoints.py (test pattern reference)
</read_first>
<action>
Create `services/api-gateway/tests/test_intelligence_endpoints.py` with 10+ tests:

```python
"""Unit tests for Platform Intelligence endpoints (PLATINT-001, PLATINT-002, PLATINT-003, PLATINT-004).

Tests cover:
- GET /api/v1/intelligence/patterns 200 with PatternAnalysisResult shape (test 1)
- GET /api/v1/intelligence/patterns 404 when no analysis exists (test 2)
- GET /api/v1/intelligence/patterns 503 when Cosmos not configured (test 3)
- GET /api/v1/intelligence/platform-health 200 (test 4)
- GET /api/v1/intelligence/platform-health 200 when Cosmos not available (test 5)
- POST /api/v1/admin/business-tiers 200 with upsert (test 6)
- GET /api/v1/admin/business-tiers 200 with list (test 7)
- POST /api/v1/admin/business-tiers 503 when Cosmos not configured (test 8)
- POST .../approve passes feedback_text (backward compat) (test 9)
- POST .../reject passes feedback_tags (backward compat) (test 10)
"""
```

**Test structure:**

Use FastAPI `TestClient` with dependency overrides:
```python
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient

# Override auth dependency
app.dependency_overrides[verify_token] = lambda: {"sub": "test-user"}
# Override cosmos dependency — create a mock that returns appropriate container clients
```

**Test 1: `test_get_patterns_200`**
- Mock Cosmos container `query_items` to return a single PatternAnalysisResult doc
- GET `/api/v1/intelligence/patterns` → 200
- Assert response has keys: `analysis_id`, `analysis_date`, `top_patterns`, `finops_summary`

**Test 2: `test_get_patterns_404_no_analysis`**
- Mock Cosmos container `query_items` to return empty list
- GET `/api/v1/intelligence/patterns` → 404

**Test 3: `test_get_patterns_503_no_cosmos`**
- Override `get_optional_cosmos_client` to return None
- GET `/api/v1/intelligence/patterns` → 503

**Test 4: `test_get_platform_health_200`**
- Mock Cosmos for incidents (det- incident), remediation_audit (complete records), SLO list
- GET `/api/v1/intelligence/platform-health` → 200
- Assert response has keys: `detection_pipeline_lag_seconds`, `auto_remediation_success_rate`, `generated_at`

**Test 5: `test_get_platform_health_200_no_cosmos`**
- Override `get_optional_cosmos_client` to return None
- GET `/api/v1/intelligence/platform-health` → 200
- Assert `detection_pipeline_lag_seconds` is None and `automation_savings_count` is 0

**Test 6: `test_post_business_tier_200`**
- Mock Cosmos container `upsert_item`
- POST `/api/v1/admin/business-tiers` with `{"id": "gold", "tier_name": "gold", "monthly_revenue_usd": 50000.0, "resource_tags": {"env": "prod"}, "created_at": "...", "updated_at": "..."}` → 200
- Assert response has `tier_name` == "gold"

**Test 7: `test_get_business_tiers_200`**
- Mock Cosmos container `query_items` to return list of tier docs
- GET `/api/v1/admin/business-tiers` → 200
- Assert response has `tiers` list

**Test 8: `test_post_business_tier_503_no_cosmos`**
- Override `get_optional_cosmos_client` to return None
- POST `/api/v1/admin/business-tiers` → 503

**Test 9: `test_approve_with_feedback_text`**
- Mock Cosmos for approval record read + replace
- POST `/api/v1/approvals/test-approval/approve?thread_id=test-thread` with `{"decided_by": "user@test.com", "feedback_text": "Good suggestion"}` → 200
- Verify the `process_approval_decision` call received `feedback_text="Good suggestion"`

**Test 10: `test_reject_with_feedback_tags`**
- Mock Cosmos for approval record read + replace
- POST `/api/v1/approvals/test-approval/reject?thread_id=test-thread` with `{"decided_by": "user@test.com", "feedback_tags": ["false_positive"]}` → 200
- Verify the `process_approval_decision` call received `feedback_tags=["false_positive"]`
</action>
<acceptance_criteria>
- File exists at `services/api-gateway/tests/test_intelligence_endpoints.py`
- `grep -c 'def test_' services/api-gateway/tests/test_intelligence_endpoints.py` returns >= 10
- `grep 'test_get_patterns_200' services/api-gateway/tests/test_intelligence_endpoints.py` returns a match
- `grep 'test_get_patterns_404' services/api-gateway/tests/test_intelligence_endpoints.py` returns a match
- `grep 'test_get_platform_health_200' services/api-gateway/tests/test_intelligence_endpoints.py` returns a match
- `grep 'test_post_business_tier_200' services/api-gateway/tests/test_intelligence_endpoints.py` returns a match
- `grep 'test_get_business_tiers_200' services/api-gateway/tests/test_intelligence_endpoints.py` returns a match
- `grep 'test_approve_with_feedback' services/api-gateway/tests/test_intelligence_endpoints.py` returns a match
- `grep 'test_reject_with_feedback' services/api-gateway/tests/test_intelligence_endpoints.py` returns a match
- `grep 'PLATINT' services/api-gateway/tests/test_intelligence_endpoints.py` returns at least 1 match
- Running `python -m pytest services/api-gateway/tests/test_intelligence_endpoints.py -v` passes all tests
</acceptance_criteria>
</task>

<task id="8">
<name>Verify all endpoints and tests pass</name>
<read_first>
- services/api-gateway/main.py
- services/api-gateway/tests/test_intelligence_endpoints.py
- services/api-gateway/tests/test_pattern_analyzer.py
</read_first>
<action>
Run the full test suite for api-gateway:

```bash
python -m pytest services/api-gateway/tests/ -v --tb=short
```

Verify:
1. All tests in `test_intelligence_endpoints.py` pass (10+ tests)
2. All tests in `test_pattern_analyzer.py` pass (12+ tests)
3. No regressions in existing tests (especially `test_approval_lifecycle.py`)
4. Total test count has increased by 22+ from pre-phase baseline

Also verify the app starts without import errors:
```bash
python -c "from services.api_gateway.main import app; print('App imported successfully')"
```
</action>
<acceptance_criteria>
- `python -m pytest services/api-gateway/tests/test_intelligence_endpoints.py -v` exits 0
- `python -m pytest services/api-gateway/tests/test_pattern_analyzer.py -v` exits 0
- `python -m pytest services/api-gateway/tests/ --tb=short` exits 0 (no regressions)
- `python -c "from services.api_gateway.main import app"` exits 0 (no import errors)
</acceptance_criteria>
</task>

## Verification Checklist

- [ ] `GET /api/v1/intelligence/patterns` endpoint exists and returns `PatternAnalysisResult`
- [ ] `GET /api/v1/intelligence/patterns` returns 404 when no analysis exists
- [ ] `GET /api/v1/intelligence/platform-health` endpoint exists and returns `PlatformHealth`
- [ ] `POST /api/v1/admin/business-tiers` endpoint upserts a tier
- [ ] `GET /api/v1/admin/business-tiers` endpoint returns `BusinessTiersResponse`
- [ ] Default business tier seeded on startup when container is empty
- [ ] Pattern analysis background loop starts in lifespan
- [ ] Pattern analysis background loop cancelled on shutdown
- [ ] `approve_proposal` passes `feedback_text` and `feedback_tags` to `process_approval_decision`
- [ ] `reject_proposal` passes `feedback_text` and `feedback_tags` to `process_approval_decision`
- [ ] 10+ endpoint tests in `test_intelligence_endpoints.py`
- [ ] All tests pass with no regressions

## must_haves

1. `GET /api/v1/intelligence/patterns` endpoint returns `PatternAnalysisResult` or 404
2. `GET /api/v1/intelligence/platform-health` endpoint returns `PlatformHealth` with all 8 fields
3. `POST /api/v1/admin/business-tiers` endpoint upserts and returns `BusinessTier`
4. `GET /api/v1/admin/business-tiers` endpoint returns `BusinessTiersResponse` with `tiers` list
5. Default business tier (`tier_name="default"`, `monthly_revenue_usd=0.0`) seeded on startup
6. `run_pattern_analysis_loop` started as asyncio task in lifespan
7. `approve_proposal` and `reject_proposal` pass `feedback_text` and `feedback_tags` through to `process_approval_decision`
8. 10+ endpoint tests in `test_intelligence_endpoints.py` all passing
9. No regressions in existing api-gateway tests
10. All 4 PLATINT requirements covered: PLATINT-001 (patterns endpoint + loop), PLATINT-002 (finops via patterns), PLATINT-003 (feedback passthrough), PLATINT-004 (business-tiers endpoints + default seed)
