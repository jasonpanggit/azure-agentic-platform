from __future__ import annotations
"""FastAPI dependency providers for shared service clients (CONCERNS 4.4).

Clients are initialized once in main.py lifespan and stored on app.state.
These Depends() providers read from app.state — no per-request instantiation.

Usage in route handlers:
    from services.api_gateway.dependencies import get_credential, get_cosmos_client
    from fastapi import Depends

    @app.get("/api/v1/something")
    async def handler(
        credential = Depends(get_credential),
        cosmos_client = Depends(get_cosmos_client),
    ):
        ...
"""

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
    """
    client: Optional[CosmosClient] = request.app.state.cosmos_client
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="Cosmos DB not configured (COSMOS_ENDPOINT not set)",
        )
    return client


def get_optional_cosmos_client(request: Request) -> Optional[CosmosClient]:
    """Return the shared CosmosClient from app.state, or None if not configured.

    Use this dependency when the route can proceed without Cosmos DB
    (e.g., the diagnostic pipeline which gracefully degrades without persistence).
    """
    return request.app.state.cosmos_client
