"""Authentication helpers for AAP agents (AGENT-008).

All agents authenticate via DefaultAzureCredential resolving
system-assigned managed identity. No service principal secrets
or credentials are stored in code or environment variables.
"""
from __future__ import annotations

import os
from functools import lru_cache

from azure.identity import DefaultAzureCredential
from azure.ai.agents import AgentsClient


@lru_cache(maxsize=1)
def get_credential() -> DefaultAzureCredential:
    """Return a cached DefaultAzureCredential instance.

    In Azure Container Apps, this resolves the system-assigned
    managed identity via IMDS. Locally, it falls back to
    Azure CLI / VS Code / environment credentials.

    Returns:
        DefaultAzureCredential instance (cached, thread-safe).
    """
    return DefaultAzureCredential()


def get_foundry_client() -> AgentsClient:
    """Create an AgentsClient connected to the Foundry project.

    Reads AZURE_PROJECT_ENDPOINT from environment, falling back to
    FOUNDRY_ACCOUNT_ENDPOINT. Uses azure-ai-agents (AgentsClient) which
    exposes .threads, .messages, and .runs sub-operation groups.
    azure-ai-projects 2.x no longer provides these agent operations.

    Returns:
        AgentsClient configured for the platform's Foundry project.

    Raises:
        ValueError: If AZURE_PROJECT_ENDPOINT is not set.
    """
    endpoint = os.environ.get("AZURE_PROJECT_ENDPOINT") or os.environ.get(
        "FOUNDRY_ACCOUNT_ENDPOINT"
    )
    if not endpoint:
        raise ValueError(
            "AZURE_PROJECT_ENDPOINT (or FOUNDRY_ACCOUNT_ENDPOINT) "
            "environment variable is required. "
            "This should be set by the agent-apps Terraform module."
        )

    return AgentsClient(
        endpoint=endpoint,
        credential=get_credential(),
    )


def _resolve_principal_id_from_token() -> str | None:
    """Resolve the managed identity principal_id (oid) from an ARM access token.

    Uses DefaultAzureCredential to obtain a token for Azure Resource Manager,
    then decodes the JWT payload (without signature verification — we only need
    the `oid` claim for attribution, not auth) to extract the principal's
    object ID.

    Returns:
        The `oid` claim string, or None if extraction fails.
    """
    import base64
    import json
    import logging

    logger = logging.getLogger(__name__)
    try:
        token = get_credential().get_token("https://management.azure.com/.default")
        # JWT is header.payload.signature — we need the payload
        payload_segment = token.token.split(".")[1]
        # Add padding if needed for base64 decoding
        padding = 4 - len(payload_segment) % 4
        if padding != 4:
            payload_segment += "=" * padding
        claims = json.loads(base64.urlsafe_b64decode(payload_segment))
        oid = claims.get("oid")
        if oid:
            logger.info("Resolved agent identity from token: oid=%s", oid)
            return oid
        logger.warning("Token claims missing 'oid' field")
    except Exception:
        logger.warning("Failed to resolve agent identity from access token", exc_info=True)
    return None


def get_agent_identity() -> str:
    """Return the current agent's Entra object ID for AUDIT-005 attribution.

    Resolution order:
    1. AGENT_ENTRA_ID environment variable (set via `az containerapp update`
       post-deployment or CI/CD pipeline).
    2. Auto-discovery from the managed identity access token's `oid` claim.
       This eliminates the need for Terraform to inject the value at
       creation time (which caused self-referential / dependency cycle errors).

    Returns:
        Entra Agent ID object ID string.

    Raises:
        ValueError: If identity cannot be resolved from env or token.
    """
    agent_id = os.environ.get("AGENT_ENTRA_ID")
    if agent_id:
        return agent_id

    # Fallback: resolve from managed identity token
    agent_id = _resolve_principal_id_from_token()
    if agent_id:
        return agent_id

    raise ValueError(
        "AGENT_ENTRA_ID could not be resolved. "
        "Set the AGENT_ENTRA_ID environment variable or ensure the "
        "container app has a system-assigned managed identity."
    )
