"""Entry point for the Arc MCP Server container.

Usage (local):
    python -m arc_mcp_server

Usage (production container CMD):
    python -m arc_mcp_server

The MCP endpoint is served at: http://0.0.0.0:8080/mcp
"""
from arc_mcp_server.server import mcp

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8080)
