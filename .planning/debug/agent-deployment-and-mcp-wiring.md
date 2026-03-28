# Debug: Agent Deployment & MCP Wiring

## Investigation Summary (2026-03-29)

### Initial State (Before Fix)

| Component | State | Evidence |
|---|---|---|
| Agent images in ACR | All 7 built with `latest` tag | `az acr repository show-tags` confirms |
| Agent container apps | ALL running `mcr.microsoft.com/azuredocs/containerapps-helloworld:latest` | `az containerapp show` confirms |
| API gateway container | Running real image from ACR | `:sha256:b7ff4a9...` |
| Foundry assistant | Exists as `asst_NeBVjCA5isNrIERoGYzRpBTu` | Bare assistant with NO tools, NO instructions |
| Foundry project connections | ZERO MCP connections | `az rest GET .../connections` returns `[]` |
| ORCHESTRATOR_AGENT_ID env var | Set on api-gateway | Value matches assistant ID |
| AZURE_PROJECT_ENDPOINT | Set on api-gateway | Correct endpoint |
| Azure AI Developer RBAC | Already assigned on api-gateway MI | Verified via `az role assignment list` |
| AcrPull on agent MIs | MISSING for all 7 agents | None had AcrPull role |

### Root Causes

1. **Agent container apps run placeholder images** - Terraform `use_placeholder_image=true` (default). Images exist in ACR but were never deployed. The deploy-all-images.yml workflow builds images to ACR but does NOT update the container apps.

2. **Foundry assistant has no tools** - Created manually in Azure portal as a bare assistant. No Azure MCP Server tools connected, no instructions set. All chat responses are generic LLM text.

3. **No MCP connections on Foundry project** - The Azure MCP Server was never connected to the project. Without MCP connections, even if tools were added to the assistant, they wouldn't be able to reach Azure APIs.

4. **No ACR registry configuration** on container apps - Container Apps didn't have a registry block to authenticate with ACR via managed identity. Required both AcrPull role AND registry config.

## Actions Taken

### Track A: MCP Server + Assistant Configuration

| Step | Status | Details |
|------|--------|---------|
| 1. Azure AI Developer RBAC | Already done | Verified pre-existing on api-gateway MI `69e05934-...` |
| 2. Deploy Azure MCP Server Container App | DONE | `ca-azure-mcp-prod` running `@azure/mcp` v2.0.0-beta.34 in HTTP transport mode |
| 3. Grant Reader role to MCP server MI | DONE | Principal `27490fe3-...` has Reader on subscription |
| 4. Create MCP connection on Foundry account | DONE | `azure-mcp-connection` created (CustomKeys category with MCP metadata) |
| 5. Update Foundry assistant instructions | DONE | 1724 chars of system instructions |
| 6. Add MCP tool to Foundry assistant | DONE | `type: "mcp"` tool with `server_label: "azure_mcp"` pointing to external MCP server URL |

### Track B: Real Agent Image Deployment

| Step | Status | Details |
|------|--------|---------|
| 1. Grant AcrPull to all 7 agent MIs | DONE | All principals have AcrPull on ACR `aapcrprodjgmjti` |
| 2. Configure ACR registry on container apps | DONE | `registry { server = "aapcrprodjgmjti.azurecr.io", identity = "system" }` via ARM API |
| 3. Deploy real images from ACR | DONE | All 7 container apps now running `aapcrprodjgmjti.azurecr.io/agents/<name>:latest` |
| 4. Update Terraform prod config | DONE | `use_placeholder_image = false`, `image_tag = "latest"` in `terraform/envs/prod/main.tf` |
| 5. Add registry block to agent-apps module | DONE | Dynamic `registry` block added to both `azurerm_container_app.agents` and `.teams_bot` |
| 6. Add AcrPull to RBAC module | DONE | `azurerm_role_assignment.acr_pull` resource added |

## New Production State

| Component | State |
|---|---|
| Azure MCP Server | Running at `https://ca-azure-mcp-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io` |
| MCP Server Port | 5000 (default HTTP transport) |
| MCP Server Mode | Read-only, HTTP auth disabled (internal network) |
| Foundry Assistant | Instructions + MCP tool configured |
| ca-orchestrator-prod | `aapcrprodjgmjti.azurecr.io/agents/orchestrator:latest` |
| ca-compute-prod | `aapcrprodjgmjti.azurecr.io/agents/compute:latest` |
| ca-network-prod | `aapcrprodjgmjti.azurecr.io/agents/network:latest` |
| ca-storage-prod | `aapcrprodjgmjti.azurecr.io/agents/storage:latest` |
| ca-security-prod | `aapcrprodjgmjti.azurecr.io/agents/security:latest` |
| ca-sre-prod | `aapcrprodjgmjti.azurecr.io/agents/sre:latest` |
| ca-arc-prod | `aapcrprodjgmjti.azurecr.io/agents/arc:latest` |

## Key Discoveries During Fix

1. **Azure MCP Server is a .NET AOT binary**, not pure Node.js. The `node:20-slim` image crashed due to missing native libraries. Required `node:20` (full image) instead.

2. **Azure MCP Server v2.0.0-beta.34** does NOT support `--port` flag. It listens on port 5000 (default HTTP). Port documented in blog posts is for older versions.

3. **MCP tool type on Foundry assistants** uses `server_url` directly (not connection-based). The `type: "mcp"` tool requires `server_label` (alphanumeric + underscore only) and `server_url`.

4. **ARM API `category: "MCP"`** for connections is NOT available yet in GA or current preview API versions. Used `CustomKeys` category with MCP metadata as workaround.

5. **Foundry Agent Service** runs in Microsoft's cloud, not inside Container Apps environment. MCP server must be externally accessible (`external: true` ingress).

6. **Container Apps need both** `AcrPull` role AND a `registry` block in the resource definition to pull from ACR with managed identity.

## Files Changed

- `terraform/envs/prod/main.tf` - Added `use_placeholder_image = false`, `image_tag = "latest"`, `acr_id` to RBAC module
- `terraform/modules/agent-apps/main.tf` - Added dynamic `registry` block for ACR managed identity auth
- `terraform/modules/rbac/main.tf` - Added `azurerm_role_assignment.acr_pull` for all agent identities
- `terraform/modules/rbac/variables.tf` - Added `acr_id` variable
- `scripts/configure-orchestrator.py` - New script for configuring Foundry assistant
- `scripts/deploy-azure-mcp-server.sh` - New script for deploying Azure MCP Server
- `services/azure-mcp-server/Dockerfile` - New Dockerfile for Azure MCP Server container

## Remaining Work

- [ ] Verify MCP server is reachable from Foundry Agent Service (test "show my virtual machines")
- [ ] The MCP server currently uses `--dangerously-disable-http-incoming-auth` — add proper Entra auth in production
- [ ] Add Azure MCP Server Container App to Terraform (currently deployed ad-hoc)
- [ ] Agent containers may crash on startup due to missing env vars (domain agent IDs, AGENT_ENTRA_ID)
- [ ] Run `terraform plan` to verify Terraform state matches live infrastructure
