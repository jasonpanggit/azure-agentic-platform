# Phase 12: Reliability Hardening Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix correctness gaps that silently mask failures — health endpoint always returns OK, 500s that should be 404s, missing env vars, connection pool exhaustion under load.

**Architecture:** Four tasks targeting the Python API gateway. Tasks 12-01 and 12-04 both modify `main.py` lifespan — implement 12-04 first or carefully merge both changes in `main.py`. Tasks 12-02 modifies `approvals.py`. Task 12-03 modifies Terraform. All Python tasks use pytest + FastAPI TestClient.

**Tech Stack:** FastAPI (Python), pytest, Azure Cosmos DB SDK (`azure-cosmos`), Azure Identity SDK (`azure-identity`), Terraform (HCL)

---

## File Structure

### New files
- `services/api-gateway/health.py` — readiness check logic (dependency-injectable)
- `services/api-gateway/dependencies.py` — shared FastAPI `Depends()` providers for credential/cosmos singletons
- `services/api-gateway/tests/test_health_ready.py` — unit tests for `/health/ready`
- `services/api-gateway/tests/test_approvals_404.py` — unit tests for approvals 404 fix
- `services/api-gateway/tests/test_dependencies.py` — unit tests for singleton initialization

### Modified files
- `services/api-gateway/main.py` — add `/health/ready` route, add lifespan credential init, wire `dependencies.py`
- `services/api-gateway/approvals.py` — catch `CosmosResourceNotFoundError` in `get_approval` and `process_approval_decision`
- `services/api-gateway/incidents_list.py` — replace per-request credential with `Depends(get_cosmos_client)`
- `services/api-gateway/foundry.py` — replace per-request credential with `Depends(get_credential)`
- `services/api-gateway/audit.py` — replace per-request credential with `Depends(get_credential)` (if applicable)
- `terraform/modules/agent-apps/main.tf` — add `AGENT_ENTRA_ID` env var, address `ignore_changes` conflict

---

## Chunk 1: Readiness Health Endpoint (Task 12-01)

### Task 12-01: Implement `/health/ready` Endpoint

**Files:**
- Create: `services/api-gateway/health.py`
- Create: `services/api-gateway/tests/test_health_ready.py`
- Modify: `services/api-gateway/main.py`

**Context:** The existing `/health` returns `{"status": "ok"}` unconditionally (liveness probe). We add a separate `/health/ready` (readiness probe) that checks three config dependencies. This is the pattern that would have caught the Phase 8 ORCHESTRATOR_AGENT_ID missing incident.

- [ ] **Step 1: Write failing tests for `/health/ready`**

```python
# services/api-gateway/tests/test_health_ready.py
"""Tests for GET /health/ready readiness endpoint (CONCERNS 5.1)."""
import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock


class TestHealthReady:
    """Tests for /health/ready readiness probe."""

    def _get_test_client(self, env_overrides: dict) -> TestClient:
        """Build a test client with specific env vars patched."""
        import importlib
        # Patch env before importing to control module-level behavior
        with patch.dict(os.environ, env_overrides, clear=False):
            # Re-import to pick up env changes
            import services.api_gateway.health as health_module
            importlib.reload(health_module)
            from fastapi import FastAPI
            app = FastAPI()
            app.include_router(health_module.router)
            return TestClient(app)

    def test_returns_503_when_orchestrator_agent_id_missing(self):
        env = {
            "COSMOS_ENDPOINT": "https://cosmos.example.com",
            "AZURE_PROJECT_ENDPOINT": "https://foundry.example.com",
        }
        # Remove ORCHESTRATOR_AGENT_ID
        with patch.dict(os.environ, env):
            os.environ.pop("ORCHESTRATOR_AGENT_ID", None)
            import importlib
            import services.api_gateway.health as health_module
            importlib.reload(health_module)
            from fastapi import FastAPI
            app = FastAPI()
            app.include_router(health_module.router)
            client = TestClient(app)
            response = client.get("/health/ready")
            assert response.status_code == 503
            body = response.json()
            assert body["status"] == "not_ready"
            assert body["checks"]["orchestrator_agent_id"] is False

    def test_returns_503_when_cosmos_endpoint_missing(self):
        with patch.dict(os.environ, {
            "ORCHESTRATOR_AGENT_ID": "asst_test123",
            "AZURE_PROJECT_ENDPOINT": "https://foundry.example.com",
        }):
            os.environ.pop("COSMOS_ENDPOINT", None)
            import importlib
            import services.api_gateway.health as health_module
            importlib.reload(health_module)
            from fastapi import FastAPI
            app = FastAPI()
            app.include_router(health_module.router)
            client = TestClient(app)
            response = client.get("/health/ready")
            assert response.status_code == 503
            body = response.json()
            assert body["checks"]["cosmos"] is False

    def test_returns_503_when_foundry_endpoint_missing(self):
        with patch.dict(os.environ, {
            "ORCHESTRATOR_AGENT_ID": "asst_test123",
            "COSMOS_ENDPOINT": "https://cosmos.example.com",
        }):
            os.environ.pop("AZURE_PROJECT_ENDPOINT", None)
            os.environ.pop("FOUNDRY_ACCOUNT_ENDPOINT", None)
            import importlib
            import services.api_gateway.health as health_module
            importlib.reload(health_module)
            from fastapi import FastAPI
            app = FastAPI()
            app.include_router(health_module.router)
            client = TestClient(app)
            response = client.get("/health/ready")
            assert response.status_code == 503
            body = response.json()
            assert body["checks"]["foundry"] is False

    def test_returns_200_when_all_deps_configured(self):
        with patch.dict(os.environ, {
            "ORCHESTRATOR_AGENT_ID": "asst_test123",
            "COSMOS_ENDPOINT": "https://cosmos.example.com",
            "AZURE_PROJECT_ENDPOINT": "https://foundry.example.com",
        }):
            import importlib
            import services.api_gateway.health as health_module
            importlib.reload(health_module)
            from fastapi import FastAPI
            app = FastAPI()
            app.include_router(health_module.router)
            client = TestClient(app)
            response = client.get("/health/ready")
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "ready"
            assert body["checks"]["orchestrator_agent_id"] is True
            assert body["checks"]["cosmos"] is True
            assert body["checks"]["foundry"] is True

    def test_existing_liveness_health_unaffected(self):
        """GET /health (liveness) must still return 200 regardless of readiness."""
        from services.api_gateway.main import app
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest services/api-gateway/tests/test_health_ready.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'services.api_gateway.health'`

- [ ] **Step 3: Implement `health.py`**

```python
# services/api-gateway/health.py
"""Readiness health check for the API gateway (CONCERNS 5.1).

GET /health/ready — checks three required config dependencies:
  1. ORCHESTRATOR_AGENT_ID env var is set
  2. COSMOS_ENDPOINT env var is set (validates Cosmos connectivity config)
  3. AZURE_PROJECT_ENDPOINT (or FOUNDRY_ACCOUNT_ENDPOINT) is set

Returns 200 {"status": "ready", "checks": {...}} if all pass.
Returns 503 {"status": "not_ready", "checks": {...}} if any fail.

The existing /health (liveness) remains unchanged in main.py.
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


def _run_readiness_checks() -> tuple[bool, dict[str, bool]]:
    """Run all readiness checks. Returns (all_passed, checks_dict)."""
    checks: dict[str, bool] = {}

    # Check 1: ORCHESTRATOR_AGENT_ID
    orchestrator_id = os.environ.get("ORCHESTRATOR_AGENT_ID", "").strip()
    checks["orchestrator_agent_id"] = bool(orchestrator_id)

    # Check 2: COSMOS_ENDPOINT
    cosmos_endpoint = os.environ.get("COSMOS_ENDPOINT", "").strip()
    checks["cosmos"] = bool(cosmos_endpoint)

    # Check 3: Foundry endpoint (either name accepted)
    foundry_endpoint = (
        os.environ.get("AZURE_PROJECT_ENDPOINT", "").strip()
        or os.environ.get("FOUNDRY_ACCOUNT_ENDPOINT", "").strip()
    )
    checks["foundry"] = bool(foundry_endpoint)

    all_passed = all(checks.values())
    return all_passed, checks


@router.get("/health/ready")
async def health_ready() -> Any:
    """Readiness probe — checks required config deps are present.

    Returns 200 when all dependencies are configured.
    Returns 503 when any dependency is missing, with details.
    """
    all_passed, checks = _run_readiness_checks()

    status_str = "ready" if all_passed else "not_ready"
    status_code = 200 if all_passed else 503

    return JSONResponse(
        {"status": status_str, "checks": checks},
        status_code=status_code,
    )
```

- [ ] **Step 4: Register `health.py` router in `main.py`**

Add after the existing imports in `main.py`:

```python
from services.api_gateway.health import router as health_router
```

Add after `app = FastAPI(...)` and before the middleware setup:

```python
app.include_router(health_router)
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
python -m pytest services/api-gateway/tests/test_health_ready.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 6: Run full gateway test suite**

```bash
python -m pytest services/api-gateway/tests/ -v --timeout=30
```

Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
git add services/api-gateway/health.py \
        services/api-gateway/tests/test_health_ready.py \
        services/api-gateway/main.py
git commit -m "feat(api-gateway): add /health/ready readiness probe checking ORCHESTRATOR_AGENT_ID, COSMOS_ENDPOINT, and Foundry endpoint (CONCERNS 5.1)"
```

---

## Chunk 2: Approvals 500 → 404 (Task 12-02)

### Task 12-02: Fix Approvals Return 404 Instead of 500

**Files:**
- Modify: `services/api-gateway/approvals.py`
- Create: `services/api-gateway/tests/test_approvals_404.py`

**Context:** `get_approval()` and `process_approval_decision()` both call `container.read_item(item=approval_id, partition_key=thread_id)`. When the record doesn't exist, the Cosmos SDK raises `azure.cosmos.exceptions.CosmosResourceNotFoundError` — it does NOT return `None`. The exception propagates up to FastAPI, which returns a 500. We catch it at the `approvals.py` level and raise `HTTPException(404)`.

**Note:** `process_approval_decision()` calls `_get_approvals_container()` which creates a new `CosmosClient` per call. Task 12-04 will address that separately — for this task, focus only on the 404 fix.

- [ ] **Step 1: Write failing tests**

```python
# services/api-gateway/tests/test_approvals_404.py
"""Tests for approvals endpoints returning 404 on missing records (CONCERNS 5.7)."""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from azure.cosmos.exceptions import CosmosResourceNotFoundError


class TestApprovals404:
    """Approval endpoints must return 404, not 500, when record not found."""

    @pytest.fixture
    def client(self):
        from services.api_gateway.main import app
        return TestClient(app, raise_server_exceptions=False)

    @pytest.fixture
    def mock_cosmos_not_found(self):
        """Mock the approvals container to raise CosmosResourceNotFoundError."""
        mock_container = MagicMock()
        not_found_error = CosmosResourceNotFoundError(
            message="Resource Not Found",
            response=MagicMock(status_code=404, headers={}, text="Not Found"),
        )
        mock_container.read_item.side_effect = not_found_error
        return mock_container

    def test_approve_nonexistent_returns_404(self, client, mock_cosmos_not_found):
        with patch(
            "services.api_gateway.approvals._get_approvals_container",
            return_value=mock_cosmos_not_found,
        ):
            resp = client.post(
                "/api/v1/approvals/nonexistent-id/approve",
                json={"decided_by": "operator@example.com", "thread_id": "th_123"},
                headers={"Authorization": "Bearer test"},
            )
            assert resp.status_code == 404
            body = resp.json()
            assert "not found" in body["detail"].lower()

    def test_reject_nonexistent_returns_404(self, client, mock_cosmos_not_found):
        with patch(
            "services.api_gateway.approvals._get_approvals_container",
            return_value=mock_cosmos_not_found,
        ):
            resp = client.post(
                "/api/v1/approvals/nonexistent-id/reject",
                json={"decided_by": "operator@example.com", "thread_id": "th_123"},
                headers={"Authorization": "Bearer test"},
            )
            assert resp.status_code == 404

    def test_approve_existing_record_still_works(self, client):
        """Confirm that a found record continues to flow through normally."""
        mock_container = MagicMock()
        from datetime import datetime, timezone, timedelta
        future = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        mock_record = {
            "id": "approval-123",
            "thread_id": "th_abc",
            "status": "pending",
            "expires_at": future,
            "proposal": {},
            "_etag": "etag_1",
        }
        mock_container.read_item.return_value = mock_record
        mock_container.replace_item.return_value = {**mock_record, "status": "approved"}

        with patch("services.api_gateway.approvals._get_approvals_container",
                   return_value=mock_container):
            with patch("services.api_gateway.approvals._resume_foundry_thread"):
                with patch("services.api_gateway.approvals.log_remediation_event"):
                    resp = client.post(
                        "/api/v1/approvals/approval-123/approve",
                        json={
                            "decided_by": "operator@example.com",
                            "thread_id": "th_abc",
                        },
                        headers={"Authorization": "Bearer test"},
                    )
                    assert resp.status_code == 200
                    assert resp.json()["status"] == "approved"

    def test_get_approval_status_nonexistent_returns_404(self, client, mock_cosmos_not_found):
        """GET /api/v1/approvals/{id} must also return 404, not 500, when record not found."""
        with patch(
            "services.api_gateway.approvals._get_approvals_container",
            return_value=mock_cosmos_not_found,
        ):
            resp = client.get(
                "/api/v1/approvals/nonexistent-id",
                params={"thread_id": "th_123"},
                headers={"Authorization": "Bearer test"},
            )
            assert resp.status_code == 404
            body = resp.json()
            assert "not found" in body["detail"].lower()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest services/api-gateway/tests/test_approvals_404.py -v 2>&1 | head -40
```

Expected: Tests for 404 fail — response is currently 500.

- [ ] **Step 3: Fix `approvals.py` — catch `CosmosResourceNotFoundError`**

Add imports at top of `approvals.py` (module level, not inside functions):

```python
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from fastapi import HTTPException
```

Modify `get_approval()` (lines 46-49):

```python
async def get_approval(approval_id: str, thread_id: str) -> dict:
    """Read an approval record from Cosmos DB."""
    container = _get_approvals_container()
    try:
        return container.read_item(item=approval_id, partition_key=thread_id)
    except CosmosResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Approval not found")
```

Modify `process_approval_decision()` — wrap the `container.read_item()` call at line 95:

```python
async def process_approval_decision(
    approval_id: str,
    thread_id: str,
    decision: str,
    decided_by: str,
    scope_confirmed: Optional[bool] = None,
) -> dict:
    """..."""
    container = _get_approvals_container()
    try:
        record = container.read_item(item=approval_id, partition_key=thread_id)
    except CosmosResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Approval not found")
    etag = record["_etag"]
    # ... rest of function unchanged
```

**Note on exception contract:** After this change, `process_approval_decision()` raises both `ValueError` (for expiry/status/scope_confirmation) and `HTTPException` (for not-found). The callers in `main.py` have `except ValueError` blocks — these correctly continue to handle `ValueError` cases. The `HTTPException(404)` propagates through FastAPI's exception handling directly (it is not caught by `except ValueError`). No changes to `main.py` callers are needed for the 404 case. This mixed pattern is deliberate: `ValueError` is a domain error handled by the caller; `HTTPException(404)` is a "record doesn't exist" condition that should bypass domain logic entirely.

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python -m pytest services/api-gateway/tests/test_approvals_404.py -v
```

Expected: All 3 tests PASS.

- [ ] **Step 5: Run full gateway test suite**

```bash
python -m pytest services/api-gateway/tests/ -v --timeout=30
```

Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add services/api-gateway/approvals.py \
        services/api-gateway/tests/test_approvals_404.py
git commit -m "fix(api-gateway): return 404 instead of 500 when approval record not found in Cosmos (CONCERNS 5.7, closes BACKLOG F-07)"
```

---

## Chunk 3: AGENT_ENTRA_ID Terraform (Task 12-03)

### Task 12-03: Add `AGENT_ENTRA_ID` to Agent Apps Terraform Module

**Files:**
- Modify: `terraform/modules/agent-apps/main.tf`

**Context:** `agents/shared/auth.py` reads `AGENT_ENTRA_ID` and raises `ValueError` if missing. The env var must be the Container App's own system-assigned managed identity `principal_id`. The `terraform/modules/agent-apps/main.tf` has a `lifecycle { ignore_changes = [template[0].container[0].env, ...] }` block which will silently skip new env var additions for existing Container Apps. This must be addressed.

- [ ] **Step 1: Read the current Terraform module**

```bash
cat terraform/modules/agent-apps/main.tf
```

Identify:
- The `lifecycle` block and what it contains for `ignore_changes`
- The `env` block structure inside `template[0].container[0]`
- The `identity` block — confirm `type = "SystemAssigned"` exists

- [ ] **Step 2: Inspect auth.py to confirm the exact env var name**

```bash
grep -n "AGENT_ENTRA_ID" agents/shared/auth.py
```

Confirm: `os.environ.get("AGENT_ENTRA_ID")` or `os.environ["AGENT_ENTRA_ID"]`

- [ ] **Step 3: Add `AGENT_ENTRA_ID` env var to Terraform module**

In `terraform/modules/agent-apps/main.tf`, locate the `template` block's `container` env section. Add:

```hcl
env {
  name  = "AGENT_ENTRA_ID"
  value = azurerm_container_app.agent.identity[0].principal_id
}
```

**IMPORTANT — address the `ignore_changes` conflict:**

If `lifecycle { ignore_changes = [template[0].container[0].env] }` exists, either:

**Option A (recommended):** Remove `template[0].container[0].env` from `ignore_changes`. Add a comment:

```hcl
lifecycle {
  # IMPORTANT: env is intentionally NOT in ignore_changes so that new required
  # env vars (like AGENT_ENTRA_ID) propagate on apply.
  # If you need to preserve manually-set env vars, use az containerapp update --set-env-vars instead.
  ignore_changes = [
    # Remove template[0].container[0].env from here
  ]
}
```

**Option B (if removing env from ignore_changes is too risky):** Keep `ignore_changes` as-is but add a `null_resource` with a local-exec that runs `az containerapp update`:

```hcl
resource "null_resource" "set_agent_entra_id" {
  triggers = {
    container_app_id  = azurerm_container_app.agent.id
    principal_id      = azurerm_container_app.agent.identity[0].principal_id
  }

  provisioner "local-exec" {
    command = <<-EOT
      az containerapp update \
        --name ${azurerm_container_app.agent.name} \
        --resource-group ${var.resource_group_name} \
        --set-env-vars "AGENT_ENTRA_ID=${azurerm_container_app.agent.identity[0].principal_id}"
    EOT
  }
}
```

Choose the option that fits the actual `lifecycle` block content found in Step 1.

- [ ] **Step 4: Add module output for traceability**

Add to `terraform/modules/agent-apps/outputs.tf` (create file if it doesn't exist):

```hcl
output "agent_entra_id" {
  description = "System-assigned managed identity principal ID for this agent Container App."
  value       = azurerm_container_app.agent.identity[0].principal_id
}
```

- [ ] **Step 5: Validate Terraform syntax**

```bash
cd terraform/modules/agent-apps
terraform init -backend=false 2>&1 | tail -5
terraform validate
```

Expected: `Success! The configuration is valid.`

- [ ] **Step 6: Run `terraform plan` in a dev environment (if available)**

```bash
cd terraform/environments/dev
terraform plan -out=tfplan 2>&1 | grep "AGENT_ENTRA_ID"
```

Expected: Shows `AGENT_ENTRA_ID` in the diff for agent Container Apps.

**Note:** Container Apps will require a revision cycle (redeploy) to pick up the new env var. This is expected behavior — Terraform will trigger a new revision when the template changes.

- [ ] **Step 7: Commit**

```bash
git add terraform/modules/agent-apps/main.tf \
        terraform/modules/agent-apps/outputs.tf
git commit -m "feat(terraform): add AGENT_ENTRA_ID env var to agent Container Apps via system-assigned identity principal_id (CONCERNS 3.6)"
```

---

## Chunk 4: Credential Singleton Caching (Task 12-04)

### Task 12-04: Cache `DefaultAzureCredential` and `CosmosClient` as App Singletons

**Files:**
- Create: `services/api-gateway/dependencies.py`
- Create: `services/api-gateway/tests/test_dependencies.py`
- Modify: `services/api-gateway/main.py` — extend lifespan to initialize singletons
- Modify: `services/api-gateway/approvals.py` — use `Depends(get_cosmos_client)`
- Modify: `services/api-gateway/incidents_list.py` — use `Depends(get_cosmos_client)`
- Modify: `services/api-gateway/foundry.py` — use `Depends(get_credential)`

**Context:** Currently `DefaultAzureCredential()` and `CosmosClient()` are created fresh per request. This causes IMDS HTTP calls on every request and Cosmos TCP connection exhaustion under load. The fix initializes them once in the `lifespan` startup event and stores them on `app.state`. Module functions that currently call `_get_approvals_container()` / `_get_incidents_container()` directly must accept the injected client via `Depends()`.

**Important:** FastAPI `Depends()` only works with route handler parameters. The internal helper functions `_get_approvals_container()` and `_get_incidents_container()` are called from within async functions. The refactor moves the credential/client out of those helpers into the top-level route handlers (in `main.py`), then passes them down.

- [ ] **Step 1: Write failing tests for `dependencies.py`**

```python
# services/api-gateway/tests/test_dependencies.py
"""Tests for FastAPI dependency providers (CONCERNS 4.4)."""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from contextlib import asynccontextmanager


class TestDependencies:
    """DefaultAzureCredential and CosmosClient initialized once per process."""

    def test_get_credential_reads_from_app_state(self):
        from services.api_gateway.dependencies import get_credential
        from fastapi import Request

        mock_cred = MagicMock(name="DefaultAzureCredential")
        mock_request = MagicMock(spec=Request)
        mock_request.app.state.credential = mock_cred

        result = get_credential(mock_request)
        assert result is mock_cred

    def test_get_cosmos_client_reads_from_app_state(self):
        from services.api_gateway.dependencies import get_cosmos_client
        from fastapi import Request

        mock_client = MagicMock(name="CosmosClient")
        mock_request = MagicMock(spec=Request)
        mock_request.app.state.cosmos_client = mock_client

        result = get_cosmos_client(mock_request)
        assert result is mock_client

    def test_credential_initialized_once_in_lifespan(self):
        """DefaultAzureCredential.__init__ called exactly once during app startup.

        NOTE: This test uses importlib.reload to ensure a fresh module state
        regardless of test execution order. Without reload, a previously-imported
        app module may skip lifespan on re-entry, making the call count unreliable.
        """
        import importlib
        import services.api_gateway.main as main_module

        with patch.object(main_module, "DefaultAzureCredential") as mock_cred_cls:
            with patch.object(main_module, "CosmosClient") as mock_cosmos_cls:
                with patch.object(main_module, "_run_startup_migrations", new_callable=AsyncMock):
                    mock_cred_cls.return_value = MagicMock()
                    mock_cosmos_cls.return_value = MagicMock()

                    # Reload the module to get a fresh app instance with fresh lifespan
                    importlib.reload(main_module)
                    fresh_app = main_module.app

                    with TestClient(fresh_app):
                        pass  # TestClient lifecycle runs lifespan

                    assert mock_cred_cls.call_count == 1, (
                        f"DefaultAzureCredential() called {mock_cred_cls.call_count} times, expected 1"
                    )
                    assert mock_cosmos_cls.call_count == 1, (
                        f"CosmosClient() called {mock_cosmos_cls.call_count} times, expected 1"
                    )
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest services/api-gateway/tests/test_dependencies.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'services.api_gateway.dependencies'`

- [ ] **Step 3: Create `dependencies.py`**

```python
# services/api-gateway/dependencies.py
"""FastAPI dependency providers for shared service clients (CONCERNS 4.4).

Clients are initialized once in main.py lifespan and stored on app.state.
These Depends() providers read from app.state — no per-request instantiation.

Usage in route handlers:
    from services.api_gateway.dependencies import get_credential, get_cosmos_client

    @app.get("/api/v1/something")
    async def handler(
        credential: DefaultAzureCredential = Depends(get_credential),
        cosmos_client: CosmosClient = Depends(get_cosmos_client),
    ):
        ...
"""
from __future__ import annotations

from typing import Optional

from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential
from fastapi import HTTPException, Request


def get_credential(request: Request) -> DefaultAzureCredential:
    """Return the shared DefaultAzureCredential from app.state."""
    return request.app.state.credential


def get_cosmos_client(request: Request) -> CosmosClient:
    """Return the shared CosmosClient from app.state.

    Raises HTTP 503 if COSMOS_ENDPOINT was not configured at startup.
    This provides a clear error message instead of AttributeError/NoneType.
    """
    client: Optional[CosmosClient] = request.app.state.cosmos_client
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="Cosmos DB not configured (COSMOS_ENDPOINT not set)",
        )
    return client
```

- [ ] **Step 4: Extend lifespan in `main.py` to initialize singletons**

Modify the `lifespan` function in `main.py`:

```python
# Add to imports at top of main.py
import os
from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: initialize shared clients, run migrations, then yield."""
    # Initialize shared credential and Cosmos client (CONCERNS 4.4)
    app.state.credential = DefaultAzureCredential()
    cosmos_endpoint = os.environ.get("COSMOS_ENDPOINT", "")
    if cosmos_endpoint:
        app.state.cosmos_client = CosmosClient(
            url=cosmos_endpoint, credential=app.state.credential
        )
    else:
        app.state.cosmos_client = None
        logger.warning("COSMOS_ENDPOINT not set — CosmosClient singleton not initialized")

    await _run_startup_migrations()
    yield
    # Teardown: close Cosmos client if it was initialized
    if app.state.cosmos_client is not None:
        app.state.cosmos_client.close()
```

- [ ] **Step 5: Refactor `incidents_list.py` to accept injected client**

Modify `list_incidents()` to accept an optional `cosmos_client` parameter (backward-compatible):

```python
async def list_incidents(
    since: Optional[str] = None,
    subscription_ids: Optional[list[str]] = None,
    severity: Optional[str] = None,
    domain: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    cosmos_client: Optional[CosmosClient] = None,  # injected from app.state
) -> list[dict]:
    """List incidents from Cosmos DB with optional filters."""
    if cosmos_client is None:
        # Fallback: create per-request (for backward compat with direct calls)
        endpoint = os.environ.get("COSMOS_ENDPOINT", "")
        if not endpoint:
            raise ValueError("COSMOS_ENDPOINT environment variable is required.")
        cosmos_client = CosmosClient(url=endpoint, credential=DefaultAzureCredential())

    database_name = os.environ.get("COSMOS_DATABASE_NAME", "aap")
    database = cosmos_client.get_database_client(database_name)
    container = database.get_container_client("incidents")
    # ... rest of function unchanged
```

Update the route handler in `main.py` to inject the client:

```python
from services.api_gateway.dependencies import get_cosmos_client

@app.get("/api/v1/incidents", response_model=list[IncidentSummary])
async def list_incidents_endpoint(
    since: Optional[str] = None,
    subscription: Optional[str] = None,
    severity: Optional[str] = None,
    domain: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    token: dict[str, Any] = Depends(verify_token),
    cosmos_client: CosmosClient = Depends(get_cosmos_client),
) -> list[IncidentSummary]:
    """..."""
    sub_ids = subscription.split(",") if subscription else None
    results = await list_incidents(
        since=since,
        subscription_ids=sub_ids,
        severity=severity,
        domain=domain,
        status=status,
        limit=limit,
        cosmos_client=cosmos_client,
    )
    return [
        IncidentSummary(**{k: v for k, v in r.items() if not k.startswith("_")})
        for r in results
    ]
```

- [ ] **Step 6: Apply same pattern to `approvals.py` and `foundry.py`**

**`approvals.py`:** Modify `_get_approvals_container()` to accept optional `cosmos_client`:

```python
def _get_approvals_container(cosmos_client: Optional[CosmosClient] = None) -> ContainerProxy:
    """Get the Cosmos DB approvals container."""
    if cosmos_client is None:
        endpoint = os.environ.get("COSMOS_ENDPOINT", "")
        if not endpoint:
            raise ValueError("COSMOS_ENDPOINT environment variable is required.")
        cosmos_client = CosmosClient(url=endpoint, credential=DefaultAzureCredential())
    database_name = os.environ.get("COSMOS_DATABASE_NAME", "aap")
    database = cosmos_client.get_database_client(database_name)
    return database.get_container_client("approvals")
```

Update approval route handlers in `main.py` to inject `cosmos_client: CosmosClient = Depends(get_cosmos_client)` and pass it to `process_approval_decision()` and `get_approval()`.

**`foundry.py`:** Modify `_get_foundry_client()` to accept optional `credential`:

```python
def _get_foundry_client(credential: Optional[DefaultAzureCredential] = None) -> AgentsClient:
    """Create an AgentsClient using DefaultAzureCredential."""
    if credential is None:
        credential = DefaultAzureCredential()
    endpoint = os.environ.get("AZURE_PROJECT_ENDPOINT") or os.environ.get(
        "FOUNDRY_ACCOUNT_ENDPOINT"
    )
    if not endpoint:
        raise ValueError(
            "AZURE_PROJECT_ENDPOINT (or FOUNDRY_ACCOUNT_ENDPOINT) "
            "environment variable is required."
        )
    return AgentsClient(endpoint=endpoint, credential=credential)
```

- [ ] **Step 7: Run tests to confirm they pass**

```bash
python -m pytest services/api-gateway/tests/test_dependencies.py -v
```

Expected: All 3 tests PASS.

- [ ] **Step 8: Run full gateway test suite**

```bash
python -m pytest services/api-gateway/tests/ -v --timeout=30
```

Expected: All tests pass.

- [ ] **Step 9: Commit**

```bash
git add services/api-gateway/dependencies.py \
        services/api-gateway/tests/test_dependencies.py \
        services/api-gateway/main.py \
        services/api-gateway/approvals.py \
        services/api-gateway/incidents_list.py \
        services/api-gateway/foundry.py
git commit -m "perf(api-gateway): cache DefaultAzureCredential and CosmosClient as app.state singletons via lifespan (CONCERNS 4.4)"
```

---

## Verification Checklist

- [ ] `python -m pytest services/api-gateway/tests/ -v` — all tests pass
- [ ] `GET /health/ready` returns 503 when any required env var is unset
- [ ] `GET /health/ready` returns 200 when all three deps configured
- [ ] `GET /health` still returns 200 (liveness unaffected)
- [ ] `POST /api/v1/approvals/nonexistent/approve` returns 404 (not 500)
- [ ] `POST /api/v1/approvals/nonexistent/reject` returns 404 (not 500)
- [ ] `terraform validate` passes on modified `agent-apps` module
- [ ] `DefaultAzureCredential.__init__` called exactly once per process (test verifies)
- [ ] `CosmosClient.__init__` called exactly once per process (test verifies)
