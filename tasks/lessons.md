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
