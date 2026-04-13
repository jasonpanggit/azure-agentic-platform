# Lessons Learned

## Azure / Terraform

### 2026-03-28: Azure 403 errors can be network blocks, not permissions
When `publicNetworkAccess: Disabled` on a storage account, Azure returns `AuthorizationPermissionMismatch` (403), not a network error. Always check `publicNetworkAccess` and `networkRuleSet.defaultAction` before assuming RBAC is the issue.

### 2026-03-28: azurerm backend authenticates independently from provider
The `backend "azurerm" {}` block does NOT use `client_id`/`client_secret` from `provider "azurerm" {}`. Without `ARM_*` env vars, the backend falls back to Azure CLI auth. The identity running `terraform init` must have data-plane access (e.g., `Storage Blob Data Contributor`), not just control-plane `Contributor`.

### 2026-03-28: Terraform modules must declare non-HashiCorp providers
Modules using `azapi_resource` (or any non-`hashicorp/*` provider) MUST include a `required_providers` block with `source = "azure/azapi"`. Without it, Terraform assumes `hashicorp/azapi` and fails.

### 2026-03-28: Azure RBAC propagation takes up to 10 minutes
After `az role assignment create`, wait 5-10 minutes before testing. Immediate 403s after assignment are expected. Don't keep re-diagnosing the same issue.

### 2026-03-28: Bootstrap scripts should be explicit about defaults
Never rely on Azure defaults for security-sensitive settings. Always explicitly set `--public-network-access`, `--allow-shared-key-access`, etc. Subscription-level policies or Azure default changes can silently alter behavior.

### 2026-03-28: Env var names must match between Terraform and application code
When Terraform sets `FOUNDRY_ACCOUNT_ENDPOINT` but Python code reads `AZURE_PROJECT_ENDPOINT`, the app will fail at runtime even though the env var has a value. Always: (1) search the codebase for `os.environ.get("...")` before naming Terraform env blocks, (2) add fallback reads (`A or B`) for env vars that might have alternate names, (3) test the full call chain end-to-end after deployment, not just the health check.

### 2026-03-28: Health checks that don't exercise critical dependencies mask failures
`GET /health` returning 200 doesn't mean the service is functional. If the health check doesn't verify Foundry connectivity, missing env vars, or RBAC, the service appears healthy while all business endpoints fail. Consider adding a `/health/ready` endpoint that validates all required dependencies.

## Chat / SSE / Foundry

### 2026-03-29: Foundry runs.list() returns chronological order (oldest first)
`client.runs.list(thread_id=...)` returns runs oldest-first. Using `run_list[0]` to get the "latest" run is WRONG — it gets the oldest. Use `run_list[-1]` or (better) pass a specific `run_id` directly and use `client.runs.retrieve()`. Always verify list API ordering assumptions with multi-item tests.

### 2026-03-29: SSE dedup guards must reset between logical streams
When reusing an SSE hook across multiple runs (same thread, different runKey), the server starts seq at 0 for each new SSE connection. If the client retains lastSeqRef from the previous run, the dedup guard (`seq > lastSeqRef`) silently drops ALL events from the new stream. Reset sequence tracking when opening a new connection for a new run.

### 2026-03-29: Silent failures in event pipelines need defense-in-depth
Two independent bugs (wrong run selection + stale dedup guard) combined to produce complete silence with zero errors visible anywhere. When building event pipelines, add targeted polling (pass run_id through the full chain) rather than relying on "get latest" heuristics. Each layer should be independently correct.

### 2026-04-05: Foundry agent IDs must be consistent across orchestrator, env vars, and Terraform
When domain agent IDs in Container App env vars don't match the orchestrator's `connected_agent` IDs, the gateway's `_DOMAIN_AGENT_IDS` filter silently drops sub-run tool calls. The sub-run stays in `requires_action` forever and the chat hangs. **Always verify**: (1) `terraform.tfvars` agent IDs match what's actually in Foundry, (2) env vars on the Container App match the orchestrator's connected agents, (3) after re-provisioning agents, run `terraform apply` to propagate new IDs. A startup health check that validates each `*_AGENT_ID` env var exists in Foundry would catch this class of error early.

### 2026-04-05: Manual Azure resource changes drift from Terraform state
Updating Container App env vars via `az containerapp update` fixes the immediate issue but creates Terraform state drift. The next `terraform apply` may revert the fix. Always follow up manual fixes with a Terraform plan/apply to bring state back in sync. Better: fix the root cause in Terraform and apply, rather than patching around it.

### 2026-04-06: KQL `split()` is case-sensitive — always `tolower()` before splitting on ARM path segments
KQL's `split(string, delimiter)` uses case-sensitive matching. Azure Resource Graph returns the `id` field with casing that varies by resource provider — Azure VMs use `patchAssessmentResults` (camelCase) but Arc machines may use `patchassessmentresults` (lowercase). When deriving join keys by splitting ARM resource IDs on path segments, always apply `tolower(id)` BEFORE the split and use a lowercase delimiter: `split(tolower(id), '/patchassessmentresults/')`. Never assume consistent casing in ARM resource IDs across different providers.

### 2026-04-07: Env vars must be injected into the container that actually reads them, not the one that proxies to it
When the web-ui proxies requests to the api-gateway, env vars needed by the api-gateway endpoint must be set on the api-gateway container — NOT just on web-ui. The Terraform `dynamic "env"` block's `for_each` condition must include every container app key that reads `os.environ.get("VAR_NAME")`. In this case `LOG_ANALYTICS_WORKSPACE_ID` was only injected into `web-ui` but was read by `patch_endpoints.py` running in `api-gateway`, causing silent graceful degradation (empty results, no errors). **Rule**: When adding an env var, grep the entire codebase for `os.environ.get("VAR_NAME")` and ensure every service that reads it gets the injection.

### 2026-04-07: KQL ConfigurationData SoftwareType values depend on the data source
Azure Update Manager records installed patches with `SoftwareType == "Update"`, while traditional Change Tracking records use `"Package"`, `"Hotfix"`, `"WindowsFeatures"`, `"WindowsPackages"`. When querying `ConfigurationData` for installed software inventory, always include all known SoftwareType values in the filter: `"Package", "WindowsFeatures", "WindowsPackages", "Hotfix", "Update"`. Missing any value silently excludes patches from that data source.

### 2026-04-11: FastAPI wildcard path params swallow sibling fixed-path routes registered later
When two routers share the same prefix (e.g., `/api/v1/vms`) and one defines a wildcard `/{param}` while another defines a fixed path like `/cost-summary`, the wildcard route will match requests for the fixed path if registered first. **Rule**: Always register routers with fixed paths **before** routers with wildcard path params at the same prefix level. Add a comment explaining the ordering constraint so future developers don't accidentally reorder. Base64url-decoding a fixed path segment like `"cost-summary"` produces garbage bytes (including `0x8b`) that cause misleading UTF-8 decode errors.

### 2026-04-12: Terraform `-var-file` last-wins kills sensitive variables silently
When the CI workflow runs `terraform apply -var-file credentials.tfvars -var-file terraform.tfvars`, setting `pgvector_connection_string = ""` in `terraform.tfvars` overwrites the valid DSN from `credentials.tfvars`. The api-gateway gets no PostgreSQL env var, `_resolve_dsn()` throws, and the EOL endpoint silently returns all nulls. **Rule**: Never set sensitive variables to empty strings in `terraform.tfvars` when the actual value lives in `credentials.tfvars`. Omit the key entirely from `terraform.tfvars` so the earlier file's value flows through. For any secret managed in `credentials.tfvars`, add a comment in `terraform.tfvars` warning "DO NOT set here".

### 2026-04-12: Optional cache layers must not gate required functionality
The EOL endpoint's endoflife.date API call was inside a `try` block that required a successful PostgreSQL connection. When DB failed, the entire loop was skipped -- the public REST API (which needs no DB) was unreachable dead code. **Rule**: When a feature has an optional cache and a required data source, structure the code so cache failure degrades gracefully (skip cache, proceed to source) rather than aborting the entire operation. Test this by mocking the cache as unavailable and asserting the source is still called.

### 2026-04-13: Never deploy manually with az containerapp update :latest — always use GH workflow

**What happened:** During a debugging session, `az acr build ... --image api-gateway:latest` was used to build, then `az containerapp update --image ...:latest` to deploy. The second `update` call didn't create a new Container App revision because the image reference string (`...:latest`) hadn't changed, so Azure saw no diff. The old running revision kept serving traffic with the old code.

**Root cause:** Container Apps tracks revisions by image reference string. `:latest` is a mutable tag — pushing a new image to `:latest` doesn't change the string, so no revision rolls. The GH workflow uses `${{ github.sha }}` as the image tag, which changes on every commit and always forces a new revision.

**Rules:**
1. **Never** use `az containerapp update` with `:latest` to deploy code changes — it silently does nothing if already on `:latest`.
2. **Always** deploy via the GH workflow (`api-gateway-build.yml` on push to `main`). Commit your fix to main and let CI handle it.
3. If you need to verify manually: `az containerapp revision list` to check the latest revision's `createdTime` — if it's old, the deploy didn't take.
4. `az acr build` is fine for building, but the deploy step must use a SHA-tagged image reference.

---

### 2026-04-13: system_pod_health "unknown" — per-cluster omsagent workspace, not platform-wide env var

**What happened:** `system_pod_health` returned `"unknown"` for all AKS clusters even after deploying the `_fetch_system_pod_health_batch()` code. The list endpoint was querying `LOG_ANALYTICS_WORKSPACE_RESOURCE_ID` (platform-wide env var pointing to `workspace-agentic-aiops-demo`) for `KubePodInventory` data. But `aks-srelab` ships Container Insights to `log-srelab` — a different workspace stored in `properties.addonProfiles.omsagent.config.logAnalyticsWorkspaceResourceID`.

**Root cause:** The enrichment code used a single shared workspace for all clusters. In real deployments, each AKS cluster's omsagent is configured to send data to its own dedicated workspace, not a platform-wide one.

**Fix:** Extended the ARG KQL query to project `omsagent_workspace` and `omsagent_enabled` per cluster. The enrichment loop now groups clusters by their per-cluster workspace and queries each workspace independently. Falls back to `LOG_ANALYTICS_WORKSPACE_RESOURCE_ID` for clusters without an explicit omsagent workspace.

**Rule:** When enriching AKS list data from Log Analytics, always read the workspace from the cluster's `addonProfiles.omsagent.config.logAnalyticsWorkspaceResourceID` (via ARG), not a platform env var. The env var is only a fallback.

---

### 2026-04-13: system_pod_health may correctly return "unknown" — verify data before calling it a bug

**What happened:** After fixing the workspace resolution, `system_pod_health` still returned `"unknown"`. Spent time on more code fixes before directly querying the LA workspace to verify if `KubePodInventory` has any rows.

**Root cause:** `KubePodInventory` in `log-srelab` genuinely has no data — the omsagent is configured but Container Insights isn't actively shipping pod inventory data. This is a real limitation (no data), not a code bug. The `"unknown"` result is correct behavior.

**Rule:** Before assuming `"unknown"` / empty data is a code bug: directly query the Log Analytics workspace first:
```bash
az monitor log-analytics query -w <workspace-guid> \
  --analytics-query "KubePodInventory | where TimeGenerated > ago(4h) | summarize count() by ClusterName" \
  -o json
```
If this returns `[]`, the issue is data availability, not code. Don't spend time on further code fixes.

---

## Lesson: Always merge to main before starting a new phase

**Pattern:** Before starting research/planning for a new phase, always:
1. `git add` remaining untracked planning files
2. `git commit` any uncommitted changes  
3. `git push -u origin <branch>`
4. `gh pr create` + `gh pr merge --squash --delete-branch`
5. `git checkout main && git pull`

**Why:** Each phase should start from a clean main branch so the new phase branch has the full history of all prior work. Starting Phase N+1 before Phase N is merged means Phase N+1 is based on a stale main.

**Trigger:** Whenever the autonomous workflow completes phase execution + verification, before calling `gsd-plan-phase` for the next phase.
