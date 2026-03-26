"""Entra ID Bearer token validation for the API Gateway (D-10).

Uses fastapi-azure-auth for production-grade Entra token validation.
Callers must obtain a Bearer token from Entra and pass it in the
Authorization header. No API keys or shared secrets.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# Use fastapi-azure-auth for production Entra validation
# Falls back to a permissive mode in development when AZURE_CLIENT_ID is not set
_security_scheme = HTTPBearer(auto_error=False)


class EntraTokenValidator:
    """Validates Entra ID Bearer tokens.

    In production (AZURE_CLIENT_ID set): validates JWT signature, audience,
    issuer, and expiration using the Entra JWKS endpoint.

    In development (AZURE_CLIENT_ID not set): logs a warning and allows
    requests through for local testing.
    """

    def __init__(self) -> None:
        self._client_id = os.environ.get("AZURE_CLIENT_ID")
        self._tenant_id = os.environ.get("AZURE_TENANT_ID")
        self._validator = None

        if self._client_id and self._tenant_id:
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
                import logging

                logging.getLogger(__name__).warning(
                    "fastapi-azure-auth not installed; token validation disabled"
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
        if self._validator is not None:
            if credentials is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Missing Bearer token",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            # Delegate to fastapi-azure-auth
            return await self._validator(credentials)

        # Development mode: no validation
        import logging

        logging.getLogger(__name__).warning(
            "AUTH DISABLED: AZURE_CLIENT_ID not configured. "
            "All requests are allowed in development mode."
        )
        return {"sub": "dev-user", "name": "Development User"}


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
