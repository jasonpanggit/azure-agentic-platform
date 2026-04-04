# Summary: Add Reader and Monitoring Reader RBAC for API Gateway

**ID:** 260404-vm9
**Status:** COMPLETE
**Branch:** `quick/260404-vm9-api-gateway-rbac`
**Date:** 2026-04-04

---

## What Changed

**File:** `terraform/modules/rbac/main.tf` (+21 lines)

Added a new `merge()` block granting the API gateway managed identity two RBAC roles across all in-scope subscriptions (`var.all_subscription_ids`):

1. **Reader** - enables `Microsoft.ResourceHealth/availabilityStatuses/read` for `_collect_resource_health()` in `diagnostic_pipeline.py`
2. **Monitoring Reader** - enables `Microsoft.Insights/metrics/read` for `_collect_metrics()` in `diagnostic_pipeline.py`

The new block follows the exact same pattern used by the SRE and Patch agent blocks (nested `merge()` with `for_each` over `var.all_subscription_ids`, keys prefixed with `api-gateway-reader-*` and `api-gateway-monreader-*`).

## Verification

- [x] `terraform fmt -check` passes on `terraform/modules/rbac/main.tf`
- [x] Key prefixes `api-gateway-reader-*` and `api-gateway-monreader-*` are unique (no collisions with existing keys)
- [x] Additive-only change - no existing resources modified
- [x] No new variables needed - uses existing `var.all_subscription_ids` and `var.agent_principal_ids["api-gateway"]`

## Operator Action Required

Run `terraform apply` to create the role assignments in Azure:

```bash
cd terraform/envs/prod
terraform plan   # Verify only new role assignments are shown
terraform apply  # Create the RBAC assignments
```

## Commits

| Commit | Description |
|--------|-------------|
| `11108ce` | feat: add Reader + Monitoring Reader RBAC for api-gateway across all subscriptions |
