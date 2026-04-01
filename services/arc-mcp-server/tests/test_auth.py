"""Unit tests for EntraAuthMiddleware (14-12).

Tests cover:
- No Authorization header → 401
- Malformed (non-Bearer) header → 401
- Non-JWT Bearer token → 401
- Expired JWT → 401
- Wrong tenant in issuer → 401
- Wrong audience → 401
- Valid-structure token (correct claims) → passes through
- ARC_MCP_AUTH_DISABLED=true → bypasses all checks
- Exempt paths (/health, /) → always pass through

Note: Signature verification is intentionally not performed (VNet-safe design),
so tests exercise claim validation only.
"""
from __future__ import annotations

import base64
import json
import time
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_jwt(payload: dict[str, Any]) -> str:
    """Encode a JWT with a dummy header and signature (no real signing)."""
    header = base64.urlsafe_b64encode(b'{"alg":"RS256","typ":"JWT"}').rstrip(b"=").decode()
    payload_b64 = (
        base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    )
    return f"{header}.{payload_b64}.fakesignature"


def _valid_payload(
    *,
    tenant_id: str = "test-tenant-id",
    audience: str = "api://arc-mcp-server",
    exp_offset: int = 3600,
) -> dict[str, Any]:
    """Return a payload dict that passes all configured validations."""
    return {
        "iss": f"https://sts.windows.net/{tenant_id}/",
        "aud": audience,
        "exp": int(time.time()) + exp_offset,
        "sub": "arc-agent-identity",
    }


def _make_app(*, auth_disabled: bool = False, tenant_id: str = "test-tenant-id", audience: str = "api://arc-mcp-server") -> Starlette:
    """Build a minimal Starlette app with EntraAuthMiddleware applied."""
    # Patch env vars before importing the module so module-level constants refresh
    env = {
        "ARC_MCP_AUTH_DISABLED": "true" if auth_disabled else "false",
        "AZURE_TENANT_ID": tenant_id,
        "ARC_MCP_EXPECTED_AUDIENCE": audience,
    }
    with patch.dict("os.environ", env, clear=False):
        # Re-import to pick up patched env (module caches constants at import)
        import importlib
        import arc_mcp_server.auth_middleware as auth_mod
        importlib.reload(auth_mod)
        from arc_mcp_server.auth_middleware import EntraAuthMiddleware as _Mw  # noqa: PLC0415

    async def _ok(request: Request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[
        Route("/mcp", _ok, methods=["POST", "GET"]),
        Route("/health", _ok),
        Route("/", _ok),
    ])
    app.add_middleware(_Mw)
    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client() -> TestClient:
    """Test client with auth enabled, matching tenant + audience."""
    return TestClient(_make_app(), raise_server_exceptions=True)


@pytest.fixture()
def client_no_auth() -> TestClient:
    """Test client with ARC_MCP_AUTH_DISABLED=true."""
    return TestClient(_make_app(auth_disabled=True), raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# 401 cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_auth_header_returns_401(client: TestClient):
    """Missing Authorization header on /mcp → 401."""
    resp = client.post("/mcp", content=b"{}")
    assert resp.status_code == 401
    assert resp.json()["error"] == "Unauthorized"


@pytest.mark.unit
def test_non_bearer_header_returns_401(client: TestClient):
    """Basic auth header (not Bearer) → 401."""
    resp = client.post("/mcp", content=b"{}", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert resp.status_code == 401


@pytest.mark.unit
def test_non_jwt_bearer_returns_401(client: TestClient):
    """Bearer token that is not a JWT → 401."""
    resp = client.post("/mcp", content=b"{}", headers={"Authorization": "Bearer notajwtatall"})
    assert resp.status_code == 401


@pytest.mark.unit
def test_expired_token_returns_401(client: TestClient):
    """JWT with exp in the past → 401."""
    payload = _valid_payload(exp_offset=-3600)  # expired 1 hour ago
    token = _make_jwt(payload)
    resp = client.post("/mcp", content=b"{}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


@pytest.mark.unit
def test_wrong_tenant_returns_401(client: TestClient):
    """JWT with a different tenant in iss → 401."""
    payload = _valid_payload(tenant_id="other-tenant-id")
    token = _make_jwt(payload)
    resp = client.post("/mcp", content=b"{}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


@pytest.mark.unit
def test_wrong_audience_string_returns_401(client: TestClient):
    """JWT with wrong string aud claim → 401."""
    payload = _valid_payload(audience="api://wrong-service")
    token = _make_jwt(payload)
    resp = client.post("/mcp", content=b"{}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


@pytest.mark.unit
def test_wrong_audience_list_returns_401(client: TestClient):
    """JWT with aud as a list that doesn't include expected audience → 401."""
    payload = _valid_payload()
    payload["aud"] = ["api://other-1", "api://other-2"]
    token = _make_jwt(payload)
    resp = client.post("/mcp", content=b"{}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


@pytest.mark.unit
def test_missing_exp_claim_returns_401(client: TestClient):
    """JWT missing exp claim → 401."""
    payload = _valid_payload()
    del payload["exp"]
    token = _make_jwt(payload)
    resp = client.post("/mcp", content=b"{}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 200 cases — valid tokens
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_valid_token_passes(client: TestClient):
    """Valid JWT with correct claims → request passes through (200)."""
    token = _make_jwt(_valid_payload())
    resp = client.post("/mcp", content=b"{}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


@pytest.mark.unit
def test_valid_audience_as_list_passes():
    """JWT where aud is a list containing the expected audience → 200."""
    app = _make_app()
    client = TestClient(app)
    payload = _valid_payload()
    payload["aud"] = ["api://arc-mcp-server", "api://other"]
    token = _make_jwt(payload)
    resp = client.post("/mcp", content=b"{}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# ARC_MCP_AUTH_DISABLED=true
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_auth_disabled_no_header_passes(client_no_auth: TestClient):
    """ARC_MCP_AUTH_DISABLED=true — no Authorization header → 200 (auth bypassed)."""
    resp = client_no_auth.post("/mcp", content=b"{}")
    assert resp.status_code == 200


@pytest.mark.unit
def test_auth_disabled_expired_token_passes(client_no_auth: TestClient):
    """ARC_MCP_AUTH_DISABLED=true — even an expired token passes (auth not checked)."""
    token = _make_jwt(_valid_payload(exp_offset=-3600))
    resp = client_no_auth.post(
        "/mcp", content=b"{}", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Exempt paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_health_path_exempt(client: TestClient):
    """/health is exempt from auth — no token needed."""
    resp = client.get("/health")
    assert resp.status_code == 200


@pytest.mark.unit
def test_root_path_exempt(client: TestClient):
    """/ is exempt from auth — no token needed."""
    resp = client.get("/")
    assert resp.status_code == 200
