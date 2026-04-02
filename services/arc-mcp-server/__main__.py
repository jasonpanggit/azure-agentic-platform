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
import logging
import os

import anyio
import uvicorn

from arc_mcp_server.auth_middleware import EntraAuthMiddleware
from arc_mcp_server.server import mcp

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OpenTelemetry auto-instrumentation (D-05)
# Must be called before uvicorn starts so hooks attach to HTTP requests.
# ---------------------------------------------------------------------------
_appinsights_conn = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "")
if _appinsights_conn:
    from azure.monitor.opentelemetry import configure_azure_monitor

    configure_azure_monitor(connection_string=_appinsights_conn)
    logger.info("Azure Monitor OpenTelemetry configured for arc-mcp-server")
else:
    logger.warning(
        "APPLICATIONINSIGHTS_CONNECTION_STRING not set — OTel disabled for arc-mcp-server"
    )


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
