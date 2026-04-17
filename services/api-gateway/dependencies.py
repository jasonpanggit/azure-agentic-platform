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
from fastapi import HTTPException, Query, Request


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


async def get_scoped_credential(
    subscription_id: str,
    request: Request,
) -> object:
    """Return the per-subscription credential from CredentialStore.

    FastAPI resolves subscription_id from the path parameter automatically.
    This dependency is safe to use on any endpoint with /{subscription_id}/ in its path.
    """
    store = request.app.state.credential_store
    return await store.get(subscription_id)


async def get_credential_for_subscriptions(
    subscriptions: Optional[str] = Query(default=None),
    request: Request = None,
) -> object:
    """Return a per-subscription credential for multi-subscription ARG endpoints.

    Reads the first subscription ID from the ?subscriptions= query param and
    resolves its SPN credential from CredentialStore.  Falls back to the shared
    DefaultAzureCredential (pod managed identity) when:
    - no subscriptions param is provided, or
    - the credential store lookup fails (e.g. subscription not onboarded yet).

    Use this dependency on endpoints that accept ?subscriptions=sub1,sub2 instead
    of a /{subscription_id}/ path parameter.
    """
    if subscriptions:
        first_sub = subscriptions.split(",")[0].strip()
        if first_sub:
            try:
                store = getattr(request.app.state, "credential_store", None)
                if store is not None:
                    cred = await store.get(first_sub)
                    if cred:
                        return cred
            except Exception:
                pass
    return request.app.state.credential
