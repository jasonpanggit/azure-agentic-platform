# Azure MCP Server

Lightweight proxy wrapper that runs the official Azure MCP Server (`@azure/mcp` v2.0.0) as a Container Apps sidecar. Exposes the Azure MCP Server's 61 namespace-level intent tools (ARM, Compute, Storage, Databases, Monitoring, Security, Messaging, and more) to the platform's domain agents over internal HTTP.

## Tech Stack
- Node.js / JavaScript
- `@azure/mcp` npm package (v2.0.0, GA)
- `DefaultAzureCredential` (managed identity in Container Apps)
- Docker (Container Apps deployment, internal ingress only)

## Key Files / Directories

- `proxy.js` — Entry point; spawns `npx @azure/mcp@latest start` and forwards MCP protocol traffic
- `Dockerfile` — Container image definition (Node.js base)

## Running Locally

```bash
cd services/azure-mcp-server
node proxy.js
```

> Requires valid Azure credentials (`az login` for local dev). The Azure MCP Server uses `DefaultAzureCredential` automatically.

## Coverage Notes

The Azure MCP Server v2 covers ARM, Compute, Storage, Databases, Networking (partial), Monitoring, Security, Messaging, and Containers. **Arc-enabled resources are not covered** — see [`arc-mcp-server/`](../arc-mcp-server/) for that gap.
