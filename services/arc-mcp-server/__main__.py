"""Entry point for the Arc MCP Server container.

Usage (local):
    python -m arc_mcp_server

Usage (production container CMD):
    python -m arc_mcp_server

The MCP endpoint is served at: http://0.0.0.0:8080/mcp

Authentication (14-12)
-----------------------
EntraAuthMiddleware is added to the Starlette app before uvicorn starts.
Set ARC_MCP_AUTH_DISABLED=true to bypass auth in local dev / CI.
"""
import anyio
import uvicorn

from arc_mcp_server.auth_middleware import EntraAuthMiddleware
from arc_mcp_server.server import mcp


async def _serve() -> None:
    """Build the Starlette app, attach auth middleware, then run uvicorn."""
    app = mcp.streamable_http_app()
    app.add_middleware(EntraAuthMiddleware)

    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=8080,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    anyio.run(_serve)
