"""Authentication helpers for the Arc MCP Server (AGENT-008).

Matches the pattern in agents/shared/auth.py — DefaultAzureCredential
cached via lru_cache, resolved from system-assigned managed identity in
Container Apps via IMDS. Falls back to Azure CLI / VS Code locally.
"""
from __future__ import annotations

from functools import lru_cache

from azure.identity import DefaultAzureCredential


@lru_cache(maxsize=1)
def get_credential() -> DefaultAzureCredential:
    """Return a cached DefaultAzureCredential instance.

    In Azure Container Apps, resolves the system-assigned managed identity
    via IMDS. Locally, falls back to Azure CLI / VS Code credentials.

    Returns:
        DefaultAzureCredential (cached, thread-safe via lru_cache).
    """
    return DefaultAzureCredential()
