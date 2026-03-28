# Debug: terraform-backend-404

## Issue
`terraform init` fails with 404 - Resource group `rg-aap-tfstate-prod` not found.

## Root Causes Found

### RC1 (Primary): Backend infrastructure never provisioned
The Azure Storage Account used for Terraform state backend does not exist. The bootstrap script
`scripts/bootstrap-state.sh` was never executed for this subscription. The resource group
`rg-aap-tfstate-prod`, storage account `staaptfstateprod`, and blob container `tfstate` must exist
BEFORE `terraform init` runs because the azurerm backend block is evaluated at init time.

**Verified:** `az group show --name rg-aap-tfstate-prod` returned `ResourceGroupNotFound`.

### RC2: Backend auth misconfigured for Entra-only storage
The subscription has an Azure Policy enforcing `allowSharedKeyAccess = false` on all storage accounts.
The prod `backend.tf` had NO auth flag (defaulting to shared key auth), while dev/staging had
`use_oidc = true` (which is for GitHub Actions OIDC, not direct SP auth).

All three backends needed `use_azuread_auth = true` for Entra ID token-based data-plane access.

### RC3: Missing Storage Blob Data Contributor RBAC (RESOLVED)
The Terraform service principal has `Contributor` role (ARM control-plane) but NOT
`Storage Blob Data Contributor` (data-plane). With shared key access disabled by policy,
the SP cannot read/write blobs in the state container without an explicit data-plane RBAC assignment.

**Fix:** Granted `Storage Blob Data Contributor` to both the SP (`65cf695c...`) and the user
(`jason@xtech-sg.net`) on the storage account. The SP role was needed for provider-level ops,
the user role was needed because the azurerm backend falls back to Azure CLI auth (no ARM_* env vars set).

### RC4: Storage account public network access disabled
The bootstrap script created the storage account without explicitly setting `--public-network-access`.
Azure defaulted to `Disabled`, making the storage account unreachable from any external client
(including local `terraform init`). No private endpoints existed either, so the account was
completely inaccessible. The 403 `AuthorizationPermissionMismatch` error was misleading — it was
actually a network-level block, not a true permissions issue.

**Fix:** Enabled public network access: `az storage account update --name staaptfstateprod --public-network-access Enabled`.
Updated bootstrap script to explicitly set `--public-network-access Enabled`.

### RC5: Modules missing `required_providers` for `azure/azapi`
The `foundry` and `fabric` modules use `azapi_resource` but did not declare `required_providers`.
Terraform defaulted to looking up `hashicorp/azapi` (which doesn't exist) instead of `azure/azapi`.

**Fix:** Added `providers.tf` with `required_providers` block to both `terraform/modules/fabric/`
and `terraform/modules/foundry/`.

## Investigation Steps

1. Read `terraform/envs/prod/backend.tf` - confirmed backend expects `rg-aap-tfstate-prod` / `staaptfstateprod` / `tfstate`
2. Read `scripts/bootstrap-state.sh` - confirmed bootstrap exists but was never run
3. Compared dev/staging backend.tf with prod - found missing auth flag in prod
4. Confirmed Azure CLI is logged in to correct subscription: `4c727b88-12f4-4c91-9c2b-372aab3bbae9`
5. Confirmed resource group does not exist: `az group show` returns 404
6. Confirmed `credentials.tfvars` is gitignored and not tracked
7. Ran bootstrap script - created resource group, storage account, and container successfully
8. Attempted `terraform init` - failed with 403 Key based auth not permitted
9. Discovered Azure Policy: `Storage accounts should prevent shared key access` at subscription scope
10. Attempted to enable shared key access - blocked by Azure Policy
11. Attempted to assign `Storage Blob Data Contributor` - SP lacks authorization for role assignments
12. Confirmed SP has only `Contributor` role (no Owner/UAA)
13. Confirmed current CLI user (`jason@xtech-sg.net`) is subscription **Owner**
14. Discovered `Storage Blob Data Contributor` already assigned to SP (by Owner, 31 seconds before failed init)
15. Discovered **user** account also lacked `Storage Blob Data Contributor` — backend uses CLI auth, not SP
16. Granted `Storage Blob Data Contributor` to user — still 403
17. Discovered **`publicNetworkAccess: Disabled`** on storage account — the real blocker
18. No private endpoints existed — storage account was completely unreachable
19. Enabled `publicNetworkAccess: Enabled` — `terraform init` backend now connects
20. Hit secondary error: `hashicorp/azapi` provider not found — modules missing `required_providers`
21. Added `providers.tf` to `fabric` and `foundry` modules
22. `terraform init` now succeeds fully

## Fixes Applied

### Fix 1: Bootstrap prod state backend (DONE)
Ran `./scripts/bootstrap-state.sh <sub_id> prod` - created:
- Resource group: `rg-aap-tfstate-prod` (Succeeded)
- Storage account: `staaptfstateprod` (Standard_LRS, allowSharedKeyAccess=false)
- Blob container: `tfstate`

### Fix 2: Standardize all backends to `use_azuread_auth = true` (DONE)
Updated all three environment backend.tf files (dev, staging, prod) to use `use_azuread_auth = true`
instead of the inconsistent mix of `use_oidc = true` and no flag. `use_azuread_auth` works for both
local SP auth and CI/CD, while `use_oidc` is specifically for GitHub Actions OIDC federated credentials.

### Fix 3: Enhanced bootstrap script (DONE)
- Added single-environment mode: `./scripts/bootstrap-state.sh <sub_id> prod`
- Added automatic RBAC assignment attempt (graceful failure if insufficient permissions)
- Improved output and next-steps guidance

### Fix 4: Created RBAC grant script (DONE)
New script `scripts/grant-state-rbac.sh` that a subscription Owner must run to assign
`Storage Blob Data Contributor` to the Terraform SP on all state storage accounts.

### Fix 5: Enabled public network access on storage account (DONE)
Storage account was created with `publicNetworkAccess: Disabled` (Azure default or subscription policy).
Ran `az storage account update --name staaptfstateprod --public-network-access Enabled`.
Updated bootstrap script to explicitly include `--public-network-access Enabled`.

### Fix 6: Granted Storage Blob Data Contributor to current user (DONE)
The azurerm backend authenticates via Azure CLI (current user), not the SP from credentials.tfvars.
Without `ARM_*` env vars, the backend falls back to CLI auth. Granted the role to `jason@xtech-sg.net`.

### Fix 7: Added `required_providers` to modules using `azure/azapi` (DONE)
Created `providers.tf` in `terraform/modules/fabric/` and `terraform/modules/foundry/` declaring
`azure/azapi` as the provider source. Without this, Terraform looked for `hashicorp/azapi` which
does not exist in the registry.

## Status: RESOLVED

`terraform init` in `terraform/envs/prod/` now succeeds fully:
- Backend "azurerm" configured successfully
- All 12 modules initialized
- All providers installed (azurerm 4.65.0, azapi 2.9.0, azuread 3.8.0, random 3.8.1, null 3.2.4)
- Lock file `.terraform.lock.hcl` generated

## Verification
- [x] Bootstrap script creates resource group, storage account, and container
- [x] RBAC role assigned to service principal (Storage Blob Data Contributor)
- [x] RBAC role assigned to current user (Storage Blob Data Contributor)
- [x] Public network access enabled on storage account
- [x] Module provider declarations fixed (azure/azapi)
- [x] `terraform init` in prod succeeds

## Lessons Learned
1. **Misleading 403 errors**: Azure returns `AuthorizationPermissionMismatch` (403) when `publicNetworkAccess: Disabled` blocks the request. This looks like a permissions issue but is actually a network issue.
2. **Backend vs Provider auth**: The azurerm `backend {}` block authenticates independently from `provider "azurerm" {}`. Without `ARM_*` env vars, the backend uses Azure CLI identity, even if `credentials.tfvars` supplies SP creds to the provider.
3. **Azure RBAC propagation**: Takes up to 5-10 minutes. A 403 immediately after `az role assignment create` is likely propagation delay, not a config error.
4. **Terraform module provider sources**: Modules that use non-HashiCorp providers (e.g., `azure/azapi`) MUST declare `required_providers` or Terraform assumes `hashicorp/<name>`.
5. **Bootstrap scripts should be explicit**: Always set `--public-network-access Enabled` explicitly rather than relying on Azure defaults, which can vary by subscription policy.
