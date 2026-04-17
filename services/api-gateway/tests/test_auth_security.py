from __future__ import annotations
"""Security tests for API gateway auth mode handling.

These tests use `pytest.mark.anyio` because the local verification runner for
this repo exposes AnyIO but not pytest-asyncio.
"""

import importlib
import sys
import types

import pytest
from fastapi import HTTPException


AUTH_MODULE_NAME = "services.api_gateway.auth"


def _reload_auth_module(
    monkeypatch: pytest.MonkeyPatch,
    *,
    auth_mode: str | None,
    client_id: str | None,
    tenant_id: str | None,
    stub_fastapi_azure_auth: bool = False,
):
    if auth_mode is None:
        monkeypatch.delenv("API_GATEWAY_AUTH_MODE", raising=False)
    else:
        monkeypatch.setenv("API_GATEWAY_AUTH_MODE", auth_mode)

    if client_id is None:
        monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)
    else:
        monkeypatch.setenv("AZURE_CLIENT_ID", client_id)

    if tenant_id is None:
        monkeypatch.delenv("AZURE_TENANT_ID", raising=False)
    else:
        monkeypatch.setenv("AZURE_TENANT_ID", tenant_id)

    if stub_fastapi_azure_auth:
        stub = types.ModuleType("fastapi_azure_auth")

        class FakeBearer:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

            async def __call__(self, credentials):
                return {"sub": "entra-user", "credentials": credentials}

        stub.SingleTenantAzureAuthorizationCodeBearer = FakeBearer
        monkeypatch.setitem(sys.modules, "fastapi_azure_auth", stub)
    else:
        monkeypatch.delitem(sys.modules, "fastapi_azure_auth", raising=False)

    sys.modules.pop(AUTH_MODULE_NAME, None)
    module = importlib.import_module(AUTH_MODULE_NAME)
    return importlib.reload(module)


@pytest.mark.anyio
async def test_auth_rejects_requests_when_no_credentials_and_no_bypass(monkeypatch):
    auth = _reload_auth_module(
        monkeypatch,
        auth_mode=None,
        client_id=None,
        tenant_id=None,
    )

    with pytest.raises(HTTPException) as exc_info:
        await auth.verify_token(None)

    assert exc_info.value.status_code == 503
    assert "API_GATEWAY_AUTH_MODE=disabled" in exc_info.value.detail


@pytest.mark.anyio
async def test_auth_allows_requests_when_bypass_explicitly_enabled(monkeypatch):
    auth = _reload_auth_module(
        monkeypatch,
        auth_mode="disabled",
        client_id=None,
        tenant_id=None,
    )

    claims = await auth.verify_token(None)

    assert claims["sub"] == "dev-user"
    assert claims["auth_mode"] == "disabled"


@pytest.mark.anyio
async def test_auth_requires_bearer_token_when_entra_mode_is_configured(monkeypatch):
    auth = _reload_auth_module(
        monkeypatch,
        auth_mode="entra",
        client_id="client-id",
        tenant_id="tenant-id",
        stub_fastapi_azure_auth=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        await auth.verify_token(None)

    assert exc_info.value.status_code == 401
    assert exc_info.value.headers == {"WWW-Authenticate": "Bearer"}