# Arc MCP Server

Custom MCP (Model Context Protocol) server that fills the gap in the Azure MCP Server's Arc coverage. Provides LLM-callable tools for Arc-enabled servers, Arc-enabled Kubernetes clusters, and Arc-enabled data services — none of which are covered by the official `@azure/mcp` package.

## Tech Stack
- Python / FastMCP (`mcp[cli]` — `mcp.server.fastmcp`)
- Azure SDK: `azure-mgmt-hybridcompute`, `azure-mgmt-hybridkubernetes`, `azure-mgmt-resourcegraph`
- `DefaultAzureCredential` for Entra ID authentication
- Streamable HTTP transport (production)
- Docker (Container Apps deployment, internal ingress only)

## Key Files / Directories

- `server.py` — FastMCP server entry point; registers all tools and starts Streamable HTTP transport
- `__main__.py` — CLI entry point (`python -m arc_mcp_server`)
- `tools/arc_servers.py` — Tools for Arc-enabled servers (`Microsoft.HybridCompute/machines`): list, get, connectivity status, extensions
- `tools/arc_k8s.py` — Tools for Arc-enabled Kubernetes (`Microsoft.Kubernetes/connectedClusters`): list, get, node status, namespaces
- `tools/arc_data.py` — Tools for Arc-enabled data services (SQL Managed Instance, PostgreSQL): list, get, health
- `models.py` — Pydantic models for tool inputs and outputs
- `auth.py` — Azure credential factory with MSI/service principal fallback
- `auth_middleware.py` — MCP transport-level auth middleware
- `conftest.py` — Pytest fixtures shared across test modules
- `Dockerfile` — Container image definition
- `requirements.txt` — Python dependencies
- `tests/` — Pytest unit tests for all tool modules

## Running Locally

```bash
cd services/arc-mcp-server
pip install -r requirements.txt
python -m arc_mcp_server
# Server starts on http://localhost:8088 (Streamable HTTP)
```

> Requires `AZURE_SUBSCRIPTION_ID` and valid Azure credentials (`DefaultAzureCredential` — local az login works for development).
