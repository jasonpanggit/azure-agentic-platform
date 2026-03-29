"""Azure tools endpoint — calls @azure/mcp via stdio subprocess.

Follows the gcc-demo pattern (azure_mcp_client.py) where the API gateway
acts as the MCP client using stdio transport, completely bypassing Foundry's
broken HTTP MCP client.

The Foundry orchestrator calls this as a regular OpenAI function tool:
  POST /api/v1/azure-tools
  {"tool_name": "compute", "arguments": {"intent": "...", "command": "...", "parameters": {...}}}
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Module-level singleton
_mcp_client: Optional["AzureMCPClient"] = None
_client_lock = asyncio.Lock()


class AzureToolRequest(BaseModel):
    """Request body for POST /api/v1/azure-tools."""

    tool_name: str = Field(..., description="MCP tool name (e.g. 'compute')")
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="Tool arguments"
    )


class AzureToolResponse(BaseModel):
    """Response from POST /api/v1/azure-tools."""

    success: bool
    content: str
    is_error: bool = False


class AzureMCPClient:
    """Singleton MCP client that communicates with @azure/mcp via stdio subprocess."""

    def __init__(self) -> None:
        self._session = None
        self._stdio_ctx = None
        self._session_ctx = None
        self._tool_name_map: dict[str, str] = {}
        self._ready = False

    def _get_mcp_env(self) -> dict[str, str]:
        """Build env vars for the MCP subprocess.

        Reads Azure credentials from MCP_AZURE_* prefixed env vars to avoid
        conflicting with the API gateway's own AZURE_CLIENT_ID / AZURE_TENANT_ID
        vars (which trigger fastapi-azure-auth Entra validation).
        """
        env = dict(os.environ)
        # Map MCP_AZURE_* → AZURE_* for the subprocess
        for short_key in ("CLIENT_ID", "CLIENT_SECRET", "TENANT_ID"):
            val = os.environ.get(f"MCP_AZURE_{short_key}")
            if val:
                env[f"AZURE_{short_key}"] = val
        return env

    async def initialize(self) -> None:
        """Start the @azure/mcp subprocess and initialize the MCP session."""
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:
            raise RuntimeError(
                "mcp package not installed. Add 'mcp[cli]>=1.26.0' to requirements."
            ) from exc

        env = self._get_mcp_env()

        server_params = StdioServerParameters(
            command="npx",
            args=["-y", "@azure/mcp@2.0.0-beta.34", "server", "start"],
            env=env,
        )

        logger.info("Starting @azure/mcp via stdio...")
        self._stdio_ctx = stdio_client(server_params)
        read, write = await self._stdio_ctx.__aenter__()

        self._session_ctx = ClientSession(read, write)
        self._session = await self._session_ctx.__aenter__()
        await self._session.initialize()

        # Discover and cache tools
        tools_result = await self._session.list_tools()
        for tool in tools_result.tools:
            safe_name = re.sub(r"[^0-9a-zA-Z_-]", "_", tool.name)
            self._tool_name_map[safe_name] = tool.name
            self._tool_name_map[tool.name] = tool.name  # identity mapping too

        self._ready = True
        logger.info(
            "MCP client ready. Tools: %s",
            list(self._tool_name_map.values()),
        )

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> AzureToolResponse:
        """Call an MCP tool and return a normalized response."""
        if not self._ready or self._session is None:
            raise RuntimeError("MCP client not initialized")

        # Resolve tool name (handle safe-name mapping)
        resolved = self._tool_name_map.get(tool_name, tool_name)

        try:
            result = await self._session.call_tool(resolved, arguments)
        except Exception as exc:
            logger.error("MCP tool call failed: %s", exc)
            return AzureToolResponse(
                success=False,
                content=f"Tool call failed: {exc}",
                is_error=True,
            )

        # Normalize result
        content_parts = []
        is_error = getattr(result, "isError", False)

        for item in getattr(result, "content", []):
            if hasattr(item, "text"):
                content_parts.append(item.text)
            elif hasattr(item, "data"):
                content_parts.append(str(item.data))

        content = "\n".join(content_parts) if content_parts else "(no content)"
        return AzureToolResponse(
            success=not is_error,
            content=content,
            is_error=is_error,
        )

    async def close(self) -> None:
        """Shut down the MCP subprocess."""
        self._ready = False
        if self._session_ctx:
            try:
                await self._session_ctx.__aexit__(None, None, None)
            except Exception:
                pass
        if self._stdio_ctx:
            try:
                await self._stdio_ctx.__aexit__(None, None, None)
            except Exception:
                pass


async def get_mcp_client() -> AzureMCPClient:
    """Return the singleton MCP client, initializing it on first call."""
    global _mcp_client
    async with _client_lock:
        if _mcp_client is None or not _mcp_client._ready:
            client = AzureMCPClient()
            await client.initialize()
            _mcp_client = client
    return _mcp_client


async def call_azure_tool(request: AzureToolRequest) -> AzureToolResponse:
    """Call an Azure MCP tool via stdio subprocess."""
    try:
        client = await get_mcp_client()
        return await client.call_tool(request.tool_name, request.arguments)
    except Exception as exc:
        logger.error("Azure tool call error: %s", exc)
        # Re-initialize client on next call
        global _mcp_client
        _mcp_client = None
        return AzureToolResponse(
            success=False,
            content=f"Error: {exc}",
            is_error=True,
        )
