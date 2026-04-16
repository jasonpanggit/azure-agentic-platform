"""TenantScopeMiddleware — injects tenant context into every request.

Extracts operator_id from the Authorization header (JWT sub claim) or the
X-Operator-Id header, resolves the tenant via TenantManager, and injects
tenant_id + tenant_subscriptions into request.state.

Skipped for: /health, /api/v1/admin/* routes.
Returns 403 when operator is not assigned to any tenant.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Paths where tenant scoping is skipped
_SKIP_PREFIXES = (
    "/health",
    "/api/v1/admin/",
)


def _extract_operator_id(request: Request) -> Optional[str]:
    """Extract operator_id from X-Operator-Id header or Authorization JWT sub."""
    # Explicit header takes priority (for service-to-service calls or tests)
    explicit = request.headers.get("X-Operator-Id")
    if explicit:
        return explicit.strip()

    # Parse JWT sub from Authorization: Bearer <token>
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:]
        try:
            import base64
            import json as _json

            # Decode payload (middle segment) without signature verification
            # This is safe because auth is already verified by Depends(verify_token)
            parts = token.split(".")
            if len(parts) >= 2:
                padded = parts[1] + "=" * (-len(parts[1]) % 4)
                payload = _json.loads(base64.urlsafe_b64decode(padded))
                sub = payload.get("sub")
                if sub:
                    return str(sub)
        except Exception:
            pass  # Non-fatal — fall through to None

    return None


class TenantScopeMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that resolves tenant context for each request.

    Injects into request.state:
        - tenant_id: str | None
        - tenant_subscriptions: list[str]
        - tenant: Tenant | None

    Returns 403 JSON when operator is not found in any tenant AND the path
    requires tenant scoping (i.e. not on the skip list).

    To disable tenant enforcement entirely (e.g. during migration), set
    TENANT_SCOPE_ENABLED=false in the environment.
    """

    def __init__(self, app, tenant_manager=None) -> None:
        super().__init__(app)
        self._tenant_manager = tenant_manager

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        # Skip for excluded paths
        for prefix in _SKIP_PREFIXES:
            if path == prefix or path.startswith(prefix):
                return await call_next(request)

        # Attach defaults so request.state always has the attrs
        request.state.tenant_id = None
        request.state.tenant_subscriptions = []
        request.state.tenant = None

        # If the feature flag is off, just pass through
        if os.environ.get("TENANT_SCOPE_ENABLED", "true").lower() == "false":
            return await call_next(request)

        # No manager configured → pass through (non-blocking degraded mode)
        if self._tenant_manager is None:
            return await call_next(request)

        operator_id = _extract_operator_id(request)
        if operator_id is None:
            # No operator identity — let auth middleware handle it
            return await call_next(request)

        tenant = await self._tenant_manager.get_tenant_for_operator(operator_id)
        if tenant is None:
            logger.warning(
                "tenant_scope: operator not assigned to any tenant | operator=%s path=%s",
                operator_id, path,
            )
            return JSONResponse(
                {"error": "Operator not assigned to any tenant"},
                status_code=403,
            )

        request.state.tenant_id = tenant.tenant_id
        request.state.tenant_subscriptions = tenant.subscriptions
        request.state.tenant = tenant
        logger.debug(
            "tenant_scope: resolved | operator=%s tenant=%s subs=%d path=%s",
            operator_id, tenant.tenant_id, len(tenant.subscriptions), path,
        )
        return await call_next(request)
