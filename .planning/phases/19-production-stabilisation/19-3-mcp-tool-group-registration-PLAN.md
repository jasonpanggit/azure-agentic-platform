---
phase: 19
plan: 3
title: "MCP Tool Group Registration"
objective: "Register the Network, Security, Arc, and SRE MCP tool surfaces on the Foundry project so all 8 domain agents can invoke their domain-specific tools in production."
wave: 2
estimated_tasks: 9
gap_closure: false
---

# Plan 19-3: MCP Tool Group Registration

## Objective

Resolve **PROD-003 / F-09 / F-10 / F-11**: Network, Security, Arc, and SRE agents currently return "tool group was not found" errors in production and fall back to the compute tool surface. This plan registers the missing MCP tool groups on the Foundry project using `azapi_resource` Terraform blocks and scripted REST verification, then runs integration tests to confirm each domain agent can successfully invoke its domain-specific tools.

## Context

**Current state (verified from research):**

- Azure MCP Server is deployed as `ca-azure-mcp-prod` (after Plan 1 it will be internal-only)
- The orchestrator's 8 `connected_agent` tools are registered (done in quick task 260331-ize)
- Azure MCP Server holds `Reader` role on the subscription (already configured)
- **Missing:** MCP tool group connections on the Foundry project for `Microsoft.Network`, `Microsoft.Security`, and Arc MCP Server
- SRE agent cross-domain access (monitor + Log Analytics) is satisfied by registering those tool groups on the Foundry project

**Key research finding:** Tool group registration is at the **Foundry project level**, not per-agent. Once `Microsoft.Network` is registered on the project, ALL agents in that project can invoke Network tools.

**Dependency on Wave 1:** This plan depends on Plan 1 (Azure MCP Server Security Hardening) completing first:
- The Azure MCP Server's internal FQDN changes when `external_enabled` switches to `false`
- MCP connections must point to the internal FQDN, not the public URL
- Registering connections before Plan 1 completes would require re-registering them with the updated URL

**PROD requirement:** PROD-003 — All 8 domain agent MCP tool groups registered in Foundry; each exercises domain tools in integration test.

---

## Tasks

### Task 1: Verify Arc MCP Server real image is running

Before registering the Arc MCP connection, verify the real image is deployed and the health endpoint responds:

```bash
# Check which image is running
az containerapp show \
  --name ca-arc-mcp-server-prod \
  --resource-group rg-aap-prod \
  --query "properties.template.containers[0].image" -o tsv

# Expected: aapcrprodjgmjti.azurecr.io/services/arc-mcp-server:latest
# NOT expected: mcr.microsoft.com/azuredocs/containerapps-helloworld:latest
```

If the placeholder image is still running, build and push the real image:

```bash
az acr login --name aapcrprodjgmjti
docker build -t aapcrprodjgmjti.azurecr.io/services/arc-mcp-server:latest \
  --platform linux/amd64 \
  -f services/arc-mcp-server/Dockerfile \
  services/arc-mcp-server/

docker push aapcrprodjgmjti.azurecr.io/services/arc-mcp-server:latest

az containerapp update \
  --name ca-arc-mcp-server-prod \
  --resource-group rg-aap-prod \
  --image aapcrprodjgmjti.azurecr.io/services/arc-mcp-server:latest

# Wait for revision to become active
az containerapp revision list \
  --name ca-arc-mcp-server-prod \
  --resource-group rg-aap-prod \
  --query "[0].{name: name, active: properties.active, running: properties.runningState}"
```

### Task 2: Get internal FQDNs for MCP connections

Retrieve the internal FQDNs for both MCP servers (after Plan 1 has applied internal-only ingress):

```bash
# Azure MCP Server internal FQDN (from Plan 1 Terraform output)
AZURE_MCP_FQDN=$(az containerapp show \
  --name ca-azure-mcp-prod \
  --resource-group rg-aap-prod \
  --query "properties.configuration.ingress.fqdn" -o tsv)
echo "Azure MCP internal FQDN: $AZURE_MCP_FQDN"

# Arc MCP Server internal FQDN
ARC_MCP_FQDN=$(az containerapp show \
  --name ca-arc-mcp-server-prod \
  --resource-group rg-aap-prod \
  --query "properties.configuration.ingress.fqdn" -o tsv)
echo "Arc MCP internal FQDN: $ARC_MCP_FQDN"
```

Save these values for use in Tasks 3–5.

### Task 3: Add Terraform `azapi_resource` blocks for MCP connections

Create a new file `terraform/envs/prod/mcp-connections.tf` with `azapi_resource` blocks for each MCP connection on the Foundry project.

**File:** `terraform/envs/prod/mcp-connections.tf`

```hcl
# MCP Connections — Foundry Project Tool Surfaces (PROD-003)
#
# Each connection registers an MCP server on the Foundry project.
# All agents in the project can then invoke tools from that server.
# api-version 2026-01-01-preview is confirmed working (scripts/deploy-azure-mcp-server.sh:104)

locals {
  foundry_project_id = module.foundry.project_id
}

# Azure MCP Server — primary tool surface (replaces ad-hoc script registration)
resource "azapi_resource" "mcp_connection_azure" {
  type      = "Microsoft.CognitiveServices/accounts/projects/connections@2026-01-01-preview"
  name      = "azure-mcp-connection"
  parent_id = local.foundry_project_id

  body = jsonencode({
    properties = {
      category = "MCP"
      target   = "http://${module.azure_mcp_server.internal_fqdn}"
      authType = "None"  # Internal VNet — no token needed, network boundary is sufficient
      metadata = {
        description = "Azure MCP Server — ARM, Monitor, Log Analytics, Advisor, Policy, Resource Health"
      }
    }
  })

  response_export_values = ["*"]
  ignore_missing_property = true
}

# Arc MCP Server — custom Arc tool surface (AGENT-005)
resource "azapi_resource" "mcp_connection_arc" {
  type      = "Microsoft.CognitiveServices/accounts/projects/connections@2026-01-01-preview"
  name      = "arc-mcp-connection"
  parent_id = local.foundry_project_id

  body = jsonencode({
    properties = {
      category = "MCP"
      target   = "http://${module.arc_mcp_server.internal_fqdn}"
      authType = "None"  # Internal VNet — Arc MCP server has ARC_MCP_AUTH_DISABLED=false for Entra JWT validation
      metadata = {
        description = "Arc MCP Server — Arc Servers, Arc K8s, Arc Data Services"
      }
    }
  })

  response_export_values = ["*"]
  ignore_missing_property = true

  count = local.enable_arc_mcp_server ? 1 : 0
}
```

> **Note on `module.foundry.project_id`:** Verify this output exists in `terraform/modules/foundry/outputs.tf`. If not, add: `output "project_id" { value = azurerm_cognitive_account_project.main.id }`.

> **Note on `module.arc_mcp_server`:** This references the existing `arc-mcp-server` module in `terraform/envs/prod/main.tf`. Verify the output `internal_fqdn` exists in `terraform/modules/arc-mcp-server/outputs.tf`. If not, add it.

### Task 4: Add `azapi` provider to `terraform/envs/prod/versions.tf`

Verify that the `azapi` provider is configured. Check `terraform/envs/prod/versions.tf` or the existing providers configuration. If `azapi` is not already present, add:

```hcl
terraform {
  required_providers {
    azapi = {
      source  = "azure/azapi"
      version = "~> 2.9.0"
    }
  }
}

provider "azapi" {
  # Inherits subscription/tenant from ARM_* environment variables
  # Same credential chain as azurerm provider
}
```

Run `terraform init -upgrade` to download the `azapi` provider if newly added.

### Task 5: Create `scripts/ops/19-3-register-mcp-connections.sh`

Create a verification script that tests each MCP tool group is reachable and the Foundry connections are registered. This is the operator runbook for post-Terraform verification:

```bash
#!/usr/bin/env bash
# Phase 19 Plan 3: MCP Tool Group Registration Verification
#
# Prerequisites:
#   - Plan 1 (Azure MCP Server internal ingress) must be applied first
#   - Plan 2 (Auth enablement) must be applied first (for Bearer token)
#   - terraform apply on terraform/envs/prod/ must be complete

set -euo pipefail

RESOURCE_GROUP="rg-aap-prod"
FOUNDRY_PROJECT="aap-project-prod"
SUBSCRIPTION="4c727b88-e6f3-4c73-8d8a-e73ff8d3b91c"

echo "=== MCP Connection Verification ==="

# List all MCP connections on the Foundry project
echo "Foundry project MCP connections:"
az rest \
  --method GET \
  --url "https://management.azure.com/subscriptions/${SUBSCRIPTION}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.CognitiveServices/accounts/aap-foundry-prod/projects/${FOUNDRY_PROJECT}/connections?api-version=2026-01-01-preview" \
  --query "value[?properties.category=='MCP'].{name: name, target: properties.target, auth: properties.authType}" \
  -o table

echo ""
echo "=== Domain Agent Tool Group Verification ==="
echo "Testing via API gateway chat endpoint (requires auth token)..."

# Get auth token (requires E2E_CLIENT_ID/SECRET to be set)
if [[ -z "${E2E_CLIENT_ID:-}" ]]; then
  echo "WARNING: E2E_CLIENT_ID not set. Skipping authenticated tool tests."
  echo "Set E2E_CLIENT_ID, E2E_CLIENT_SECRET, E2E_API_AUDIENCE env vars to run authenticated tests."
  exit 0
fi

TOKEN=$(curl -s -X POST \
  "https://login.microsoftonline.com/abbdca26-d233-4a1e-9d8c-c4eebbc16e50/oauth2/v2.0/token" \
  -d "grant_type=client_credentials&client_id=${E2E_CLIENT_ID}&client_secret=${E2E_CLIENT_SECRET}&scope=${E2E_API_AUDIENCE}/.default" \
  | jq -r '.access_token')

API_URL="https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"

echo ""
echo "--- Test 1: Network Agent (Microsoft.Network tool group) ---"
curl -s -X POST "${API_URL}/api/v1/chat" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"message": "List NSG rules in the prod subscription", "domain": "network"}' \
  | jq '{status: .status, has_tool_call: (.trace // [] | length > 0)}'

echo ""
echo "--- Test 2: Security Agent (Microsoft.Security tool group) ---"
curl -s -X POST "${API_URL}/api/v1/chat" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the Defender for Cloud secure score?", "domain": "security"}' \
  | jq '{status: .status, has_tool_call: (.trace // [] | length > 0)}'

echo ""
echo "--- Test 3: Arc Agent (Arc MCP Server tool group) ---"
curl -s -X POST "${API_URL}/api/v1/chat" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"message": "List all Arc-enabled servers", "domain": "arc"}' \
  | jq '{status: .status, has_tool_call: (.trace // [] | length > 0)}'

echo ""
echo "--- Test 4: SRE Agent (Monitor + Log Analytics tool groups) ---"
curl -s -X POST "${API_URL}/api/v1/chat" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"message": "Show Azure Service Health events in the last 24 hours", "domain": "sre"}' \
  | jq '{status: .status, has_tool_call: (.trace // [] | length > 0)}'

echo ""
echo "=== Verification complete ==="
```

### Task 6: Verify `module.foundry` outputs expose `project_id`

Check `terraform/modules/foundry/outputs.tf`:

```bash
grep -n "project_id\|project_resource_id" terraform/modules/foundry/outputs.tf
```

If `project_id` is not exposed, add it to `terraform/modules/foundry/outputs.tf`:

```hcl
output "project_id" {
  description = "Resource ID of the Foundry project (used for MCP connection parent_id)"
  value       = azurerm_cognitive_account_project.main.id
}
```

### Task 7: Verify `module.arc_mcp_server` exposes `internal_fqdn`

Check `terraform/modules/arc-mcp-server/outputs.tf`:

```bash
cat terraform/modules/arc-mcp-server/outputs.tf
```

If `internal_fqdn` is not exposed, add it:

```hcl
output "internal_fqdn" {
  description = "Internal FQDN for Arc MCP Server (internal ingress — no external access)"
  value       = azurerm_container_app.arc_mcp_server.ingress[0].fqdn
}
```

### Task 8: Run `terraform plan` and apply MCP connections

```bash
cd terraform/envs/prod

# Initialize (downloads azapi provider if newly added)
terraform init -upgrade

# Plan — review MCP connection creates
terraform plan -out=plan-19-3.tfplan

# Expected: 2 azapi_resource creates (azure-mcp-connection, arc-mcp-connection)
# Review output carefully before applying

terraform apply plan-19-3.tfplan
```

### Task 9: Run verification script and confirm tool invocations

Execute the verification script from Task 5 against prod:

```bash
export E2E_CLIENT_ID="<value from GitHub Actions secrets>"
export E2E_CLIENT_SECRET="<value from GitHub Actions secrets>"
export E2E_API_AUDIENCE="api://505df1d3-3bd3-4151-ae87-6e5974b72a44"

bash scripts/ops/19-3-register-mcp-connections.sh
```

For each domain test:
- Confirm the response does NOT contain "tool group was not found"
- Confirm `has_tool_call: true` (at least one MCP tool was invoked)
- Check Application Insights for `mcp.outcome: success` spans from network/security/arc/sre agents

Application Insights query to verify:
```kql
dependencies
| where cloud_RoleName in ("ca-network-prod", "ca-security-prod", "ca-arc-prod", "ca-sre-prod")
| where name startswith "mcp."
| where timestamp > ago(1h)
| summarize count() by cloud_RoleName, name, success
| order by cloud_RoleName, name
```

---

## Success Criteria

1. `az rest GET .../connections?api-version=2026-01-01-preview` on the Foundry project lists at least 2 MCP connections: `azure-mcp-connection` and `arc-mcp-connection`
2. `terraform plan` on `terraform/envs/prod/` shows zero diff after `terraform apply` completes (connections owned by Terraform)
3. Network agent successfully invokes at least one `Microsoft.Network` MCP tool in response to a NSG query (confirmed by Application Insights trace or API response)
4. Security agent successfully invokes at least one `Microsoft.Security` MCP tool in response to a Defender query (confirmed by Application Insights trace or API response)
5. Arc agent successfully invokes `arc_servers_list` via the Arc MCP Server (confirmed by Application Insights trace or API response containing Arc server data)
6. SRE agent successfully invokes Monitor/Log Analytics tools in response to a Service Health query
7. No agent returns "tool group was not found" error in its response

---

## Files Touched

### Created
- `terraform/envs/prod/mcp-connections.tf` — `azapi_resource` blocks for Azure MCP and Arc MCP connections
- `scripts/ops/19-3-register-mcp-connections.sh` — verification script for MCP tool group testing

### Modified
- `terraform/modules/foundry/outputs.tf` — add `project_id` output (if missing)
- `terraform/modules/arc-mcp-server/outputs.tf` — add `internal_fqdn` output (if missing)
- `terraform/envs/prod/versions.tf` — add `azapi` provider (if not already present)
