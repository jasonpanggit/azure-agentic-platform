# Services

The core runtime services of the Azure Agentic Platform (AAP). Each service runs as an Azure Container App and communicates internally — no service is exposed directly to the public internet.

## Tech Stack
- Python (FastAPI) for backend agents and API gateway
- TypeScript (New Teams SDK) for the Teams bot
- Next.js 15 (App Router) for the web UI
- Azure Container Apps for hosting all services
- Azure AI Foundry for agent threads and LLM backends

## Services

| Directory | Purpose |
|-----------|---------|
| [`api-gateway/`](api-gateway/) | FastAPI thin router — routes chat and operational requests to domain agents |
| [`arc-mcp-server/`](arc-mcp-server/) | Custom MCP server bridging the Azure MCP Server gap for Arc-enabled resources |
| [`azure-mcp-server/`](azure-mcp-server/) | Lightweight proxy/configuration wrapper for the Azure MCP Server (`@azure/mcp`) |
| [`detection-plane/`](detection-plane/) | Azure Monitor → Event Hub → Fabric Activator alert detection pipeline |
| [`teams-bot/`](teams-bot/) | TypeScript Teams bot with Adaptive Card approval flows and proactive alerts |
| [`web-ui/`](web-ui/) | Next.js 15 dashboard — 7 operational tabs + conversational chat panel |

## Internal Networking

All services run behind internal Container Apps ingress (`external_enabled = false`). The web UI is the only service with public ingress. Service-to-service calls use Container Apps internal DNS.
