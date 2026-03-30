"""Entra ID Bearer token validation for the API Gateway (D-10).

Uses fastapi-azure-auth for production-grade Entra token validation.
Callers must obtain a Bearer token from Entra and pass it in the
Authorization header. No API keys or shared secrets.

Local bypass is available only when explicitly enabled with
API_GATEWAY_AUTH_MODE=disabled.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_security_scheme = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)

AUTH_MODE_DISABLED = "disabled"
AUTH_MODE_ENTRA = "entra"


class EntraTokenValidator:
    """Validates Entra ID Bearer tokens.

    Default behavior is fail-closed: requests require valid Entra
    configuration and a Bearer token unless auth is explicitly disabled.
    """

    def __init__(self) -> None:
        self._auth_mode = _read_auth_mode()
        self._client_id = os.environ.get("AZURE_CLIENT_ID")
        self._tenant_id = os.environ.get("AZURE_TENANT_ID")
        self._validator = None
        self._configuration_error: Optional[str] = None

        if self._auth_mode == AUTH_MODE_DISABLED:
            logger.warning(
                "AUTH DISABLED: API_GATEWAY_AUTH_MODE=disabled. "
                "Requests are allowed without Entra validation."
            )
            return

        if self._auth_mode != AUTH_MODE_ENTRA:
            self._configuration_error = (
                "Unsupported API_GATEWAY_AUTH_MODE. Use 'entra' or 'disabled'."
            )
            return

        if not self._client_id or not self._tenant_id:
            self._configuration_error = (
                "Entra auth is enabled but AZURE_CLIENT_ID and AZURE_TENANT_ID "
                "are not fully configured. Set API_GATEWAY_AUTH_MODE=disabled "
                "only for local mock development."
            )
            return

        try:
            from fastapi_azure_auth import SingleTenantAzureAuthorizationCodeBearer

            self._validator = SingleTenantAzureAuthorizationCodeBearer(
                app_client_id=self._client_id,
                tenant_id=self._tenant_id,
                scopes={
                    f"api://{self._client_id}/incidents.write": "Write incidents"
                },
            )
        except ImportError:
            self._configuration_error = (
                "fastapi-azure-auth is not installed. "
                "Install it or set API_GATEWAY_AUTH_MODE=disabled for local mock use."
            )

    async def validate(
        self,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security_scheme),
    ) -> dict[str, Any]:
        """Validate the Bearer token from the Authorization header.

        Returns:
            Decoded token claims dict.

        Raises:
            HTTPException: 401 if token is missing or invalid.
        """
        if self._auth_mode == AUTH_MODE_DISABLED:
            return {
                "sub": "dev-user",
                "name": "Development User",
                # Included so tests can assert the bypass path explicitly.
                "auth_mode": AUTH_MODE_DISABLED,
            }

        if self._configuration_error is not None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=self._configuration_error,
            )

        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing Bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return await self._validator(credentials)


def _read_auth_mode() -> str:
    """Return the configured auth mode for the gateway.

    Defaults to fail-closed Entra validation. Local bypass must be explicit.
    """
    raw_mode = os.environ.get("API_GATEWAY_AUTH_MODE", AUTH_MODE_ENTRA)
    return raw_mode.strip().lower()


# Singleton instance
_token_validator = EntraTokenValidator()


async def verify_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security_scheme),
) -> dict[str, Any]:
    """FastAPI dependency for Entra token validation.

    Usage:
        @app.post("/api/v1/incidents")
        async def create_incident(token: dict = Depends(verify_token)):
            ...
    """
    return await _token_validator.validate(credentials)
