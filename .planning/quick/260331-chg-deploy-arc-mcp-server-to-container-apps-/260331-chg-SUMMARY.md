# Quick Task Summary: Deploy Arc MCP Server to Container Apps

**ID:** 260331-chg
**Status:** code complete, operator steps pending
**Branch:** `quick/260331-chg-deploy-arc-mcp-server`
**Date:** 2026-03-31

---

## What Was Done (Code Changes)

### Commit: `90f2bf8` — feat: enable arc MCP server deployment with ACR auth and AcrPull RBAC

**Files modified:**

| File | Change |
|------|--------|
| `terraform/modules/arc-mcp-server/main.tf` | Added `registry` block (identity = "system") for ACR image pull auth; added `azurerm_role_assignment.arc_mcp_acr_pull` for AcrPull RBAC; added `lifecycle { ignore_changes }` for image (CI/CD-owned) |
| `terraform/modules/arc-mcp-server/variables.tf` | Added `acr_id` variable (default = "") for AcrPull RBAC scope |
| `terraform/envs/prod/main.tf` | Flipped `enable_arc_mcp_server = true`; wired `acr_id = module.compute_env.acr_id` into module call |
| `terraform/envs/dev/main.tf` | Wired `acr_id = module.compute_env.acr_id` into module call (consistency) |
| `terraform/envs/staging/main.tf` | Wired `acr_id = module.compute_env.acr_id` into module call (consistency) |

### Key Discovery: Missing ACR Auth (Fixed)

The arc-mcp-server module was missing two things that would have caused image pull failure:

1. **No `registry` block** — the Container App referenced `${acr_login_server}/services/arc-mcp-server:latest` but had no authentication configured to pull from ACR
2. **No AcrPull RBAC** — the system-assigned managed identity had no permission to pull from ACR

Both are now fixed, matching the proven pattern from the `agent-apps` module.

### Verification

- [x] `terraform fmt -check` passes on all 5 modified directories
- [x] No changes to application code — purely infrastructure

---

## Operator Steps Required

### Step 1: Build and push Arc MCP Server image to ACR

**Option A: Via GitHub Actions (recommended)**

```bash
# Trigger the "Deploy All Images" workflow from GitHub Actions UI
# Go to: Actions > Deploy All Images > Run workflow
# Set image_tag to "latest" (or leave blank for git SHA)
```

**Option B: Local build + push**

```bash
# Get ACR login server from Terraform state or Azure portal
ACR_LOGIN_SERVER="<your-acr>.azurecr.io"

# Login to ACR
az acr login --name "${ACR_LOGIN_SERVER%%.azurecr.io}"

# Build and push
docker build --platform linux/amd64 \
  -t "$ACR_LOGIN_SERVER/services/arc-mcp-server:latest" \
  services/arc-mcp-server/

docker push "$ACR_LOGIN_SERVER/services/arc-mcp-server:latest"
```

### Step 2: Apply Terraform

```bash
cd terraform/envs/prod

# Plan first — review the changes
terraform plan -out=tfplan

# Expected resources created:
#   + azurerm_container_app.arc_mcp_server            (ca-arc-mcp-server-prod)
#   + azurerm_role_assignment.arc_mcp_reader["<sub>"]  (Reader on Arc subscription)
#   + azurerm_role_assignment.arc_mcp_acr_pull[0]      (AcrPull on ACR)
#
# Expected resource updated:
#   ~ azurerm_container_app.agents["arc"]  (ARC_MCP_SERVER_URL env var added)

terraform apply tfplan
```

### Step 3: Verify deployment

```bash
# 1. Check Container App is running
az containerapp show \
  -n ca-arc-mcp-server-prod \
  -g rg-aap-prod \
  --query "properties.runningStatus"

# 2. Check ARC_MCP_SERVER_URL is set on the arc agent
az containerapp show \
  -n ca-arc-prod \
  -g rg-aap-prod \
  --query "properties.template.containers[0].env[?name=='ARC_MCP_SERVER_URL']"

# 3. Test arc listing via chat (requires Foundry RBAC F-01 to be resolved)
curl -X POST https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/api/v1/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"message": "list my arc enabled servers"}'
```

### Step 4: RBAC propagation wait

- AcrPull and Reader role assignments take ~5 minutes to propagate
- If the Container App fails to pull the image on first attempt, wait 5 minutes and trigger a new revision:

```bash
az containerapp revision restart \
  -n ca-arc-mcp-server-prod \
  -g rg-aap-prod \
  --revision $(az containerapp revision list -n ca-arc-mcp-server-prod -g rg-aap-prod --query "[0].name" -o tsv)
```

---

## Definition of Done Checklist

- [x] `enable_arc_mcp_server = true` in prod Terraform
- [x] Arc MCP Server module has ACR registry block for image pull auth
- [x] Arc MCP Server module has AcrPull RBAC assignment
- [x] `terraform fmt -check` passes
- [ ] Arc MCP Server image is in ACR (`services/arc-mcp-server:latest`) — **operator step**
- [ ] `terraform apply` run successfully — **operator step**
- [ ] `ca-arc-mcp-server-prod` Container App is running — **operator step**
- [ ] `ARC_MCP_SERVER_URL` env var is set on `ca-arc-prod` — **operator step**
- [ ] "list my arc enabled servers" query returns actual Arc data — **operator step** (also requires F-01 Foundry RBAC resolved)

---

## Notes

- The HANDOFF.json remaining task #6 ("Deploy Arc MCP Server") is addressed by this work
- After successful deployment, the Arc agent will be able to call arc_servers_list, arc_extensions_list, arc_k8s_list, etc. via the internal MCP URL
- The `lifecycle { ignore_changes = [image] }` block was added to prevent Terraform drift when CI/CD updates the image tag independently
- Dev and staging envs also received the `acr_id` wiring for consistency (they were already missing it)
