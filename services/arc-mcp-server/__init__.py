"""Arc MCP Server — custom FastMCP server for Azure Arc resources (AGENT-005).

Exposes Arc-specific ARM tools that the Azure MCP Server does not cover:
  - Arc Servers (Microsoft.HybridCompute/machines)
  - Arc Kubernetes (Microsoft.Kubernetes/connectedClusters)
  - Arc Data Services (Microsoft.HybridData / AzureArcData)

Built with FastMCP (mcp[cli]==1.26.0), deployed as an internal-only
Container App. Authentication via DefaultAzureCredential (system-assigned
managed identity in production; Azure CLI locally).
"""
