# Quick Plan: Deploy Arc MCP Server to Container Apps

**ID:** 260331-chg
**Type:** change (infrastructure + deploy)
**Created:** 2026-03-31
**Status:** planned

---

## Goal

Deploy the Arc MCP Server (`services/arc-mcp-server/`) as a Container App (`ca-arc-mcp-prod`) and wire `ARC_MCP_SERVER_URL` env var on the arc agent Container App so it can call Arc-specific tools (arc_servers_list, arc_extensions_list, arc_k8s_list, etc.).

## Current State

- Arc MCP Server source code exists at `services/arc-mcp-server/` with Dockerfile, FastMCP server, and 9 tools
- Terraform module exists at `terraform/modules/arc-mcp-server/` with Container App, internal ingress (port 8080), and RBAC (Reader on Arc subscriptions)
- CI job `build-arc-mcp-server` exists in `deploy-all-images.yml` (pushes `services/arc-mcp-server` to ACR)
- `terraform/envs/prod/main.tf` has the `arc_mcp_server` module **gated by** `enable_arc_mcp_server = false`
- `agent-apps` module already has the `arc_mcp_server_url` variable and dynamic env block to inject `ARC_MCP_SERVER_URL` into the `arc` Container App
- The image may or may not be in ACR already (CI workflow is manual dispatch)

## What's Needed

Everything is already wired in Terraform and CI. The only changes are:

1. Flip `enable_arc_mcp_server = true` in prod main.tf
2. Run CI to build+push the Arc MCP Server image (if not already in ACR)
3. Run `terraform apply` (or do it manually with `az` CLI as a faster path)

---

## Tasks

### Task 1: Enable Arc MCP Server in Terraform prod config

**Files to change:**
- `terraform/envs/prod/main.tf` — change `enable_arc_mcp_server = false` to `true`

**What this does:**
- Enables the `arc_mcp_server` module (count = 1 instead of 0)
- Creates `ca-arc-mcp-server-prod` Container App with internal ingress on port 8080
- Grants Reader RBAC on all subscription IDs to the Arc MCP Server managed identity
- Passes `arc_mcp_server_url` (e.g., `http://ca-arc-mcp-server-prod.internal.{domain}/mcp`) to the `agent_apps` module
- The `agent_apps` module injects `ARC_MCP_SERVER_URL` env var into the `arc` Container App

**Verification:**
- [ ] `terraform fmt -check` passes on `terraform/envs/prod/`
- [ ] `terraform plan` shows the new Container App, RBAC assignments, and updated env var on `ca-arc-prod`

### Task 2: Build Arc MCP Server image and deploy

**This is an operator task** (requires Azure credentials):

1. **Ensure image is in ACR** — either:
   - Trigger `Deploy All Images` workflow from GitHub Actions (workflow_dispatch), OR
   - Build locally: `docker build --platform linux/amd64 -t <acr>/services/arc-mcp-server:latest services/arc-mcp-server/ && docker push <acr>/services/arc-mcp-server:latest`

2. **Apply Terraform** — from `terraform/envs/prod/`:
   ```bash
   terraform plan -out=tfplan
   terraform apply tfplan
   ```

3. **Verify deployment:**
   ```bash
   # Check Container App is running
   az containerapp show -n ca-arc-mcp-server-prod -g rg-aap-prod --query "properties.runningStatus"

   # Check ARC_MCP_SERVER_URL is set on arc agent
   az containerapp show -n ca-arc-prod -g rg-aap-prod --query "properties.template.containers[0].env[?name=='ARC_MCP_SERVER_URL']"

   # Test arc listing via chat
   curl -X POST https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/api/v1/chat \
     -H "Content-Type: application/json" \
     -d '{"message": "list my arc enabled servers"}'
   ```

### Task 3: Grant ACR pull permission to Arc MCP Server identity

**Important:** The Arc MCP Server Container App uses `identity = "system"` for ACR pulls (same as agent-apps pattern). However, the `arc-mcp-server` module's Terraform does NOT include a `registry` block with `identity = "system"`.

**Action needed:** After the Container App is created, either:
- Add a `registry` block to `terraform/modules/arc-mcp-server/main.tf`, OR
- Grant `AcrPull` role to the Arc MCP Server managed identity on the ACR, OR
- Verify the module works with the placeholder image first, then update the image manually

**Check:** Review if the module already handles ACR auth — if the image reference uses the ACR login server, the Container App needs ACR pull permission.

---

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| ACR pull fails (no registry block) | HIGH | Add `registry { server = var.acr_login_server; identity = "system" }` to arc-mcp-server module |
| Arc MCP Server image not in ACR | MEDIUM | Trigger CI workflow first, or use `use_placeholder_image` pattern temporarily |
| RBAC propagation delay | LOW | Reader role takes ~5min to propagate; retry after delay |

## Key Discovery: Missing ACR Registry Block

The `terraform/modules/arc-mcp-server/main.tf` Container App resource does NOT have a `registry` block, but it references `${var.acr_login_server}/services/arc-mcp-server:${var.image_tag}`. This means the Container App will fail to pull the image from ACR because it has no authentication configured.

**Fix required in Task 1:** Add a `registry` block to the arc-mcp-server module matching the pattern used in agent-apps:
```hcl
registry {
  server   = var.acr_login_server
  identity = "system"
}
```

And grant `AcrPull` on the ACR to the Arc MCP Server's managed identity (same as the RBAC module does for agent-apps).

---

## Definition of Done

- [ ] `enable_arc_mcp_server = true` in prod Terraform
- [ ] Arc MCP Server module has ACR registry block for image pull auth
- [ ] `terraform fmt -check` passes
- [ ] Arc MCP Server image is in ACR (`services/arc-mcp-server:latest`)
- [ ] `ca-arc-mcp-server-prod` Container App is running
- [ ] `ARC_MCP_SERVER_URL` env var is set on `ca-arc-prod`
- [ ] "list my arc enabled servers" query returns actual Arc data (not "no direct access")
