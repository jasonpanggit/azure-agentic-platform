# Plan 26-3: Forecast API Endpoints + Lifespan Wiring

**Phase:** 26 — Predictive Operations
**Wave:** 3 (depends on 26-2: `forecaster.py` and `MetricForecast`/`ForecastResult` models must exist)
**Autonomous:** true
**Requirement:** INTEL-005 — `GET /api/v1/forecasts` endpoints, background sweep wired into lifespan

---

## Goal

Expose the forecaster as two REST endpoints and wire the background sweep loop into the FastAPI lifespan. Follows the exact same lifespan pattern established by the topology service in Phase 22.

---

## Files to Create / Modify

| File | Change |
|---|---|
| `services/api-gateway/forecast_endpoints.py` | **Create** — FastAPI router with two GET endpoints |
| `services/api-gateway/main.py` | **Modify** — init `ForecasterClient` + start sweep loop in lifespan; include router |
| `services/api-gateway/tests/test_forecast_endpoints.py` | **Create** — 10+ unit tests |

---

## Implementation

### 1. `services/api-gateway/forecast_endpoints.py`

New file. FastAPI router with two GET routes. No authentication dependency on `verify_token` — forecasts are read-only operational data, consistent with topology endpoints in `topology_endpoints.py`.

> **Check first**: Open `topology_endpoints.py` and confirm whether `verify_token` is applied there. If it is, apply the same pattern here for consistency.

```python
"""Forecast API endpoints — capacity exhaustion forecasts (INTEL-005).

Routes:
  GET /api/v1/forecasts?resource_id=<id>  → ForecastResult for one resource
  GET /api/v1/forecasts                   → list[ForecastResult] (breach_imminent only)
"""
from __future__ import annotations

import logging
import os
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from services.api_gateway.auth import verify_token
from services.api_gateway.forecaster import FORECAST_BREACH_ALERT_MINUTES
from services.api_gateway.models import ForecastResult, MetricForecast

logger = logging.getLogger(__name__)

router = APIRouter()
```

#### Route 1: `GET /api/v1/forecasts?resource_id=<id>`

When `resource_id` is provided, return all metric forecasts for that specific resource. Returns `404` if no baselines exist for the resource. Returns `503` if the forecaster is not initialized.

```python
@router.get(
    "/api/v1/forecasts",
    response_model=ForecastResult | list[ForecastResult],
)
async def get_forecasts(
    request: Request,
    resource_id: Optional[str] = None,
    token: dict = Depends(verify_token),
) -> ForecastResult | list[ForecastResult]:
    """Get capacity exhaustion forecasts.

    With resource_id:
        Returns a ForecastResult containing all metric forecasts for that resource.
        404 if no baselines exist for the resource yet.

    Without resource_id:
        Returns list[ForecastResult] for all resources with breach_imminent=True
        (time_to_breach_minutes < 60 minutes). Empty list if none.

    Authentication: Entra ID Bearer token required.
    """
```

**Implementation notes:**

- Get `forecaster_client` from `request.app.state.forecaster_client`. If `None`, raise `HTTP 503`.
- Call in executor: `await loop.run_in_executor(None, forecaster_client.get_forecasts, resource_id)` for single-resource path, or `get_all_imminent()` for the list path.
- Convert raw Cosmos docs to `ForecastResult` objects:
  - For each baseline doc, construct a `MetricForecast`:
    - `current_value` ← `doc["level"]`
    - `trend_per_interval` ← `doc["trend"]`
    - `breach_imminent` ← `doc["time_to_breach_minutes"] is not None and doc["time_to_breach_minutes"] < FORECAST_BREACH_ALERT_MINUTES`
    - All other fields map directly from doc keys.
  - Group `MetricForecast` objects by `resource_id` + `resource_type` into a single `ForecastResult`.
  - `has_imminent_breach` ← `any(f.breach_imminent for f in result.forecasts)`.

**Split the handler into two separate route functions** for clarity (one per query shape):

```python
@router.get("/api/v1/forecasts", response_model=ForecastResult)
async def get_resource_forecasts(
    request: Request,
    resource_id: str,
    token: dict = Depends(verify_token),
) -> ForecastResult:
    """Get all capacity forecasts for a specific resource.
    404 if resource has no baselines yet. 503 if forecaster not initialized.
    """
    ...

@router.get("/api/v1/forecasts/imminent", response_model=list[ForecastResult])
async def get_imminent_forecasts(
    request: Request,
    token: dict = Depends(verify_token),
) -> list[ForecastResult]:
    """Get all resources with at least one metric breach expected within 60 minutes.
    Returns empty list if none. 503 if forecaster not initialized.
    """
    ...
```

> **Route naming decision**: Use `/api/v1/forecasts` (with required `resource_id` query param) and `/api/v1/forecasts/imminent` (no param, list of breach-imminent resources). This avoids the FastAPI ambiguity of an optional query param that changes the response model type. Keep it as two distinct routes.

**Helper: `_docs_to_forecast_result`**

Extract a shared helper to convert a list of Cosmos baseline docs for one resource into a `ForecastResult`:

```python
def _docs_to_forecast_result(docs: list[dict]) -> ForecastResult:
    """Convert Cosmos baseline docs for one resource into a ForecastResult."""
    if not docs:
        raise ValueError("No docs to convert")
    resource_id = docs[0]["resource_id"]
    resource_type = docs[0].get("resource_type", "")
    forecasts = []
    for doc in docs:
        ttb = doc.get("time_to_breach_minutes")
        forecasts.append(MetricForecast(
            metric_name=doc["metric_name"],
            current_value=doc["level"],
            threshold=doc["threshold"],
            trend_per_interval=doc["trend"],
            time_to_breach_minutes=ttb,
            confidence=doc.get("confidence", "low"),
            mape=doc.get("mape", 0.0),
            last_updated=doc["last_updated"],
            breach_imminent=(
                ttb is not None and ttb < FORECAST_BREACH_ALERT_MINUTES
            ),
        ))
    has_imminent = any(f.breach_imminent for f in forecasts)
    return ForecastResult(
        resource_id=resource_id,
        resource_type=resource_type,
        forecasts=forecasts,
        has_imminent_breach=has_imminent,
    )
```

**Helper: `_group_docs_by_resource`**

For the `/imminent` endpoint, group cross-resource docs into per-resource `ForecastResult` objects:

```python
def _group_docs_by_resource(docs: list[dict]) -> list[ForecastResult]:
    """Group Cosmos baseline docs by resource_id and convert to ForecastResult list."""
    grouped: dict[str, list[dict]] = {}
    for doc in docs:
        rid = doc.get("resource_id", "")
        if rid not in grouped:
            grouped[rid] = []
        grouped[rid].append(doc)
    results = []
    for resource_docs in grouped.values():
        try:
            results.append(_docs_to_forecast_result(resource_docs))
        except Exception as exc:
            logger.warning("forecasts: group_docs conversion failed | error=%s", exc)
    return results
```

---

### 2. `services/api-gateway/main.py`

Three targeted changes. Read the file before editing. Make minimal, surgical additions:

#### Change A: New import at top of file

Add to the existing import block (near the topology imports at the bottom of the imports section):

```python
from services.api_gateway.forecaster import ForecasterClient, run_forecast_sweep_loop
from services.api_gateway.forecast_endpoints import router as forecast_router
```

#### Change B: Lifespan — init ForecasterClient and start sweep loop

Inside the `lifespan` async context manager, **after** the topology sync task is started (after `logger.info("startup: topology sync loop started | interval=900s")`), add:

```python
    # Initialize ForecasterClient and start background sweep (INTEL-005)
    _forecast_sweep_task = None
    if app.state.cosmos_client is not None and FORECAST_ENABLED:
        from services.api_gateway.forecaster import FORECAST_ENABLED as _FORECAST_ENABLED
        if _FORECAST_ENABLED:
            app.state.forecaster_client = ForecasterClient(
                cosmos_client=app.state.cosmos_client,
                credential=app.state.credential,
            )
            _forecast_sweep_task = asyncio.create_task(
                run_forecast_sweep_loop(
                    cosmos_client=app.state.cosmos_client,
                    credential=app.state.credential,
                    topology_client=app.state.topology_client,
                )
            )
            logger.info("startup: forecast sweep loop started | interval=%ds", FORECAST_SWEEP_INTERVAL_SECONDS)
        else:
            app.state.forecaster_client = None
            logger.info("startup: forecast sweep disabled (FORECAST_ENABLED=false)")
    else:
        app.state.forecaster_client = None
        logger.warning(
            "startup: forecaster_client not initialized "
            "(COSMOS_ENDPOINT=%s, FORECAST_ENABLED=%s)",
            "set" if app.state.cosmos_client else "not_set",
            os.environ.get("FORECAST_ENABLED", "true"),
        )
```

> **Important**: Import `FORECAST_SWEEP_INTERVAL_SECONDS` from `forecaster` at the top of the file (alongside the `ForecasterClient` import), not inline.

In the **teardown section** of lifespan (after the topology task cancel), add:

```python
    # Cancel forecast sweep loop on shutdown
    if _forecast_sweep_task is not None and not _forecast_sweep_task.done():
        _forecast_sweep_task.cancel()
        try:
            await _forecast_sweep_task
        except asyncio.CancelledError:
            pass
        logger.info("shutdown: forecast sweep loop cancelled")
```

#### Change C: Include forecast router

Add to the `app.include_router(...)` block (after `app.include_router(topology_router)`):

```python
app.include_router(forecast_router)
```

---

### 3. `services/api-gateway/tests/test_forecast_endpoints.py`

Write 10+ tests. Use `TestClient` from `fastapi.testclient` with mocked `app.state.forecaster_client`. Follow the pattern from `test_topology_endpoints.py`.

#### Required test cases (10 minimum):

1. `test_get_resource_forecasts_503_when_forecaster_none` — `app.state.forecaster_client = None` → 503
2. `test_get_resource_forecasts_404_when_no_baselines` — forecaster returns `[]` → 404
3. `test_get_resource_forecasts_200_single_metric` — one baseline doc → 200 with valid `ForecastResult`
4. `test_get_resource_forecasts_200_multiple_metrics` — three baseline docs → 200 with three `MetricForecast` entries
5. `test_get_resource_forecasts_breach_imminent_true` — `time_to_breach_minutes=30` → `breach_imminent=True`, `has_imminent_breach=True`
6. `test_get_resource_forecasts_breach_imminent_false` — `time_to_breach_minutes=None` → `breach_imminent=False`
7. `test_get_imminent_forecasts_empty_list` — `get_all_imminent()` returns `[]` → 200 with `[]`
8. `test_get_imminent_forecasts_groups_by_resource` — two docs for resource A, one for resource B → two `ForecastResult` objects
9. `test_get_imminent_forecasts_503_when_forecaster_none` — 503 when `forecaster_client` is None
10. `test_docs_to_forecast_result_correct_fields` — verify helper maps `level` → `current_value`, `trend` → `trend_per_interval`

#### Test file header:

```python
"""Unit tests for forecast API endpoints (INTEL-005).

Tests cover:
- GET /api/v1/forecasts?resource_id= (tests 1–6)
- GET /api/v1/forecasts/imminent (tests 7–9)
- _docs_to_forecast_result helper (test 10)
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
```

#### Sample fixture pattern:

```python
@pytest.fixture()
def mock_forecaster():
    """ForecasterClient mock with controllable return values."""
    client = MagicMock()
    client.get_forecasts.return_value = []
    client.get_all_imminent.return_value = []
    return client


@pytest.fixture()
def test_app(mock_forecaster):
    """FastAPI test app with forecast router and mocked state."""
    from services.api_gateway.forecast_endpoints import router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    app.state.forecaster_client = mock_forecaster
    return TestClient(app)
```

For auth, mock `verify_token` to return `{"sub": "test-user"}` using `app.dependency_overrides`:

```python
from services.api_gateway.auth import verify_token

def _mock_token():
    return {"sub": "test-user"}

app.dependency_overrides[verify_token] = _mock_token
```

#### Sample baseline doc for tests:

```python
def _make_baseline_doc(**overrides):
    """Return a minimal Cosmos baseline doc dict for testing."""
    base = {
        "id": "/sub/rg/vm1:Percentage CPU",
        "resource_id": "/subscriptions/sub-1/resourceGroups/rg/providers/microsoft.compute/virtualmachines/vm1",
        "resource_type": "microsoft.compute/virtualmachines",
        "metric_name": "Percentage CPU",
        "level": 72.5,
        "trend": 1.2,
        "threshold": 90.0,
        "invert": False,
        "time_to_breach_minutes": 73.0,
        "confidence": "medium",
        "mape": 18.5,
        "last_updated": "2026-04-03T10:00:00Z",
    }
    base.update(overrides)
    return base
```

---

## Verification Steps

```bash
# 1. Import check — no circular imports or missing modules
python -c "from services.api_gateway.forecast_endpoints import router"
python -c "from services.api_gateway.main import app"

# 2. Run new endpoint tests
python -m pytest services/api-gateway/tests/test_forecast_endpoints.py -v

# 3. Full test suite — verify no regressions
python -m pytest services/api-gateway/tests/ -v --tb=short

# 4. Verify routes are registered in the app
python -c "
from services.api_gateway.main import app
routes = [r.path for r in app.routes]
assert any('/api/v1/forecasts' in r for r in routes), 'forecast route missing'
print('Routes OK:', [r for r in routes if 'forecast' in r])
"

# 5. Startup log check (dev mode, no Azure credentials needed)
FORECAST_ENABLED=false python -c "
import asyncio, os
os.environ['FORECAST_ENABLED'] = 'false'
# Import triggers logger.warning — verify no crash
from services.api_gateway.forecaster import FORECAST_ENABLED
assert FORECAST_ENABLED == False
print('FORECAST_ENABLED=false handled correctly')
"
```

---

## Acceptance Criteria

- [ ] `forecast_endpoints.py` created with `GET /api/v1/forecasts` and `GET /api/v1/forecasts/imminent` routes
- [ ] Both routes return 503 when `forecaster_client` is `None` on `app.state`
- [ ] `GET /api/v1/forecasts` returns 404 when no baselines exist for the resource
- [ ] `GET /api/v1/forecasts/imminent` returns empty list (not 404) when no imminent breaches
- [ ] `_docs_to_forecast_result` maps `level` → `current_value`, `trend` → `trend_per_interval`
- [ ] `breach_imminent=True` when `time_to_breach_minutes < 60`
- [ ] Lifespan starts `ForecasterClient` and `run_forecast_sweep_loop` task when Cosmos is configured
- [ ] Lifespan cancels sweep task cleanly on shutdown (logs "forecast sweep loop cancelled")
- [ ] `FORECAST_ENABLED=false` prevents sweep task creation
- [ ] `app.include_router(forecast_router)` added to `main.py`
- [ ] All 10+ endpoint tests pass
- [ ] Zero regressions in existing test suite

---

## Notes

- **Lifespan variable scoping**: The `_forecast_sweep_task` local variable must be declared before the `yield` and referenced in the teardown section below it — same pattern as `_topology_sync_task` already in `main.py`. Initialize it to `None` before the conditional block.
- **`FORECAST_ENABLED` import**: Import the constant at the module level in `main.py` (alongside other forecaster imports), not inside the lifespan function, to keep the lifespan readable.
- **`app.state.forecaster_client`**: Always set — either to a `ForecasterClient` instance or `None`. Endpoint handlers check `if forecaster_client is None: raise 503`. This matches the topology pattern with `app.state.topology_client`.
- **No circular imports**: `forecast_endpoints.py` imports from `forecaster.py` and `models.py` only. `main.py` imports from `forecast_endpoints.py`. `forecaster.py` does not import from `main.py`. No circular dependency.
- **Run-in-executor for Cosmos calls**: Both endpoint handlers must call `await loop.run_in_executor(None, forecaster_client.get_forecasts, resource_id)` — not call the synchronous method directly in the async route handler. The executor is obtained via `asyncio.get_running_loop()`.
