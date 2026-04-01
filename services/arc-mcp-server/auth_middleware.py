"""Entra JWT authentication middleware for the Arc MCP Server (14-12).

Validates the ``Authorization: Bearer <token>`` header on all incoming MCP
requests.  Performs lightweight claim-only validation (issuer, audience,
expiry) — no JWKS signature verification, which avoids an outbound network
call from inside the VNet while still preventing obviously invalid or expired
tokens.

Environment variables
----------------------
ARC_MCP_AUTH_DISABLED : str
    Set to ``"true"`` to skip authentication entirely (local dev / CI).
    Default: ``"false"`` (auth enabled).
AZURE_TENANT_ID : str
    Expected Entra tenant ID.  When set, the ``iss`` claim must contain this
    value.  If empty, issuer is not validated.
ARC_MCP_EXPECTED_AUDIENCE : str
    Expected ``aud`` claim value (e.g. the app-registration client ID of this
    service).  When empty, audience is not validated.

Paths that bypass auth
-----------------------
``/`` and ``/health`` are always allowed without a token (readiness probes and
the Container Apps health check configured in the Dockerfile).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (read once at import time — immutable after startup)
# ---------------------------------------------------------------------------

_AUTH_DISABLED: bool = os.environ.get("ARC_MCP_AUTH_DISABLED", "false").lower() == "true"
_TENANT_ID: str = os.environ.get("AZURE_TENANT_ID", "")
_EXPECTED_AUDIENCE: str = os.environ.get("ARC_MCP_EXPECTED_AUDIENCE", "")

# Paths that never require a token (health / liveness probes)
_EXEMPT_PATHS: frozenset[str] = frozenset({"/", "/health"})


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class EntraAuthMiddleware(BaseHTTPMiddleware):
    """Validate Entra Bearer tokens on incoming MCP requests.

    Accepts the request when:
    - ``ARC_MCP_AUTH_DISABLED=true`` (local dev mode), OR
    - The path is in ``_EXEMPT_PATHS``, OR
    - The ``Authorization: Bearer <token>`` header carries a JWT whose
      ``iss``, ``aud``, and ``exp`` claims pass lightweight validation.

    Returns HTTP 401 for any other case.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Always allow health / readiness probes through
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        if _AUTH_DISABLED:
            logger.debug("arc-mcp-auth: disabled via ARC_MCP_AUTH_DISABLED=true")
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            logger.warning(
                "arc-mcp-auth: missing Bearer token on %s %s",
                request.method,
                request.url.path,
            )
            return JSONResponse(
                {"error": "Unauthorized", "detail": "Bearer token required"},
                status_code=401,
            )

        token = auth_header[7:]
        try:
            _validate_token_claims(token)
        except _TokenValidationError as exc:
            logger.warning("arc-mcp-auth: token validation failed — %s", exc)
            return JSONResponse(
                {"error": "Unauthorized", "detail": "Invalid token"},
                status_code=401,
            )

        return await call_next(request)


# ---------------------------------------------------------------------------
# Token claim validation (no signature verification — VNet-safe)
# ---------------------------------------------------------------------------


class _TokenValidationError(Exception):
    """Raised when a JWT claim check fails."""


def _validate_token_claims(token: str) -> None:
    """Validate Entra JWT claims without signature verification.

    Signature verification requires outbound HTTPS to the JWKS endpoint which
    may not be reachable from inside a private VNet.  Claim validation catches
    expired tokens and tokens issued by a different tenant/audience, which
    covers the primary threat model for an internal service.

    Args:
        token: Raw JWT string (header.payload.signature).

    Raises:
        _TokenValidationError: If any required claim check fails.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise _TokenValidationError("Not a valid JWT (expected 3 parts)")

    # Decode payload — add padding so base64 doesn't choke on truncated strings
    payload_b64 = parts[1]
    padding = (4 - len(payload_b64) % 4) % 4
    try:
        raw = base64.urlsafe_b64decode(payload_b64 + "=" * padding)
        payload: dict = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise _TokenValidationError(f"Cannot decode JWT payload: {exc}") from exc

    # 1. Expiry
    exp = payload.get("exp")
    if exp is None:
        raise _TokenValidationError("JWT missing 'exp' claim")
    if not isinstance(exp, (int, float)):
        raise _TokenValidationError(f"JWT 'exp' claim is not a number: {exp!r}")
    if exp < time.time():
        raise _TokenValidationError(f"JWT expired at {exp} (now {time.time():.0f})")

    # 2. Issuer — must contain the configured tenant ID (if set)
    if _TENANT_ID:
        iss = payload.get("iss", "")
        if _TENANT_ID not in iss:
            raise _TokenValidationError(
                f"JWT issuer '{iss}' does not contain expected tenant '{_TENANT_ID}'"
            )

    # 3. Audience — must match exactly (if configured)
    if _EXPECTED_AUDIENCE:
        aud = payload.get("aud", "")
        if isinstance(aud, list):
            if _EXPECTED_AUDIENCE not in aud:
                raise _TokenValidationError(
                    f"JWT audience list {aud} does not contain '{_EXPECTED_AUDIENCE}'"
                )
        elif aud != _EXPECTED_AUDIENCE:
            raise _TokenValidationError(
                f"JWT audience '{aud}' != expected '{_EXPECTED_AUDIENCE}'"
            )
