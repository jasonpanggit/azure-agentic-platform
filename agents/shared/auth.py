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


def get_agent_identity() -> str:
    """Return the current agent's Entra object ID for AUDIT-005 attribution.

    Reads AGENT_ENTRA_ID from environment, set by the agent-apps
    Terraform module from the Container App's system-assigned identity
    principal_id.

    Returns:
        Entra Agent ID object ID string.

    Raises:
        ValueError: If AGENT_ENTRA_ID is not set.
    """
    agent_id = os.environ.get("AGENT_ENTRA_ID")
    if not agent_id:
        raise ValueError(
            "AGENT_ENTRA_ID environment variable is required. "
            "This must be the system-assigned managed identity principal_id."
        )
    return agent_id
