---
plan: 28-1
phase: 28
wave: 1
depends_on: []
requirements: [PLATINT-001, PLATINT-004]
files_modified:
  - terraform/modules/databases/cosmos.tf
  - terraform/modules/databases/outputs.tf
autonomous: true
---

## Objective

Add two new Cosmos DB SQL containers (`pattern_analysis` and `business_tiers`) to the databases Terraform module. These containers store weekly pattern analysis results (PLATINT-001) and operator-configured business tiers (PLATINT-004). The containers follow the same pattern as the existing `baselines` and `remediation_audit` containers — partition keys aligned to access patterns, no TTL (compliance retention), and standard indexing.

## Context

- Existing Cosmos containers defined in `terraform/modules/databases/cosmos.tf`: incidents, approvals, sessions, topology, baselines, remediation_audit (6 total)
- Outputs for container names in `terraform/modules/databases/outputs.tf`
- Each container follows the same Terraform pattern: `azurerm_cosmosdb_sql_container` resource with `partition_key_paths`, `partition_key_version = 2`, and `indexing_policy`
- Database name: `aap` (from `azurerm_cosmosdb_sql_database.main.name`)
- Account: `azurerm_cosmosdb_account.main`
- Resource group: `var.resource_group_name`

## Tasks

<task id="1">
<name>Add pattern_analysis Cosmos container</name>
<read_first>
- terraform/modules/databases/cosmos.tf
</read_first>
<action>
Append a new `azurerm_cosmosdb_sql_container` resource block named `pattern_analysis` to `cosmos.tf` after the `remediation_audit` container. Configuration:

```hcl
resource "azurerm_cosmosdb_sql_container" "pattern_analysis" {
  name                  = "pattern_analysis"
  resource_group_name   = var.resource_group_name
  account_name          = azurerm_cosmosdb_account.main.name
  database_name         = azurerm_cosmosdb_sql_database.main.name
  partition_key_paths   = ["/analysis_date"]
  partition_key_version = 2

  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }

    excluded_path {
      path = "/top_patterns/[]/*"
    }

    excluded_path {
      path = "/_etag/?"
    }
  }
}
```

Key decisions:
- Partition key `/analysis_date` (e.g. "2026-04-07") — one document per weekly run
- Exclude `/top_patterns/[]/*` from indexing (nested pattern arrays are large and read by full-doc fetch, not queried individually)
- No TTL — compliance requirement (same as remediation_audit)
- No composite index needed — access pattern is single-partition read by analysis_date
</action>
<acceptance_criteria>
- `grep -c 'azurerm_cosmosdb_sql_container.*pattern_analysis' terraform/modules/databases/cosmos.tf` returns 1
- `grep '/analysis_date' terraform/modules/databases/cosmos.tf` returns a match
- `grep 'partition_key_version = 2' terraform/modules/databases/cosmos.tf` returns at least 7 matches (6 existing + 1 new)
- `terraform fmt -check terraform/modules/databases/cosmos.tf` exits 0
</acceptance_criteria>
</task>

<task id="2">
<name>Add business_tiers Cosmos container</name>
<read_first>
- terraform/modules/databases/cosmos.tf
</read_first>
<action>
Append a new `azurerm_cosmosdb_sql_container` resource block named `business_tiers` to `cosmos.tf` after the `pattern_analysis` container. Configuration:

```hcl
resource "azurerm_cosmosdb_sql_container" "business_tiers" {
  name                  = "business_tiers"
  resource_group_name   = var.resource_group_name
  account_name          = azurerm_cosmosdb_account.main.name
  database_name         = azurerm_cosmosdb_sql_database.main.name
  partition_key_paths   = ["/tier_name"]
  partition_key_version = 2

  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }

    excluded_path {
      path = "/_etag/?"
    }
  }
}
```

Key decisions:
- Partition key `/tier_name` — each tier is a single document, accessed by tier_name
- No TTL — business tiers are operator-managed configuration
- Standard indexing — small container, no need for composite indexes
</action>
<acceptance_criteria>
- `grep -c 'azurerm_cosmosdb_sql_container.*business_tiers' terraform/modules/databases/cosmos.tf` returns 1
- `grep '/tier_name' terraform/modules/databases/cosmos.tf` returns a match
- `terraform fmt -check terraform/modules/databases/cosmos.tf` exits 0
</acceptance_criteria>
</task>

<task id="3">
<name>Add Terraform outputs for new containers</name>
<read_first>
- terraform/modules/databases/outputs.tf
</read_first>
<action>
Add two new output blocks to `outputs.tf` following the existing pattern (e.g. `cosmos_baselines_container_name`, `cosmos_remediation_audit_container_name`):

```hcl
output "cosmos_pattern_analysis_container_name" {
  description = "Name of the Cosmos DB pattern_analysis container for platform intelligence (PLATINT-001)"
  value       = azurerm_cosmosdb_sql_container.pattern_analysis.name
}

output "cosmos_business_tiers_container_name" {
  description = "Name of the Cosmos DB business_tiers container for FinOps tier configuration (PLATINT-004)"
  value       = azurerm_cosmosdb_sql_container.business_tiers.name
}
```
</action>
<acceptance_criteria>
- `grep 'cosmos_pattern_analysis_container_name' terraform/modules/databases/outputs.tf` returns a match
- `grep 'cosmos_business_tiers_container_name' terraform/modules/databases/outputs.tf` returns a match
- `grep 'PLATINT-001' terraform/modules/databases/outputs.tf` returns a match
- `grep 'PLATINT-004' terraform/modules/databases/outputs.tf` returns a match
- `terraform fmt -check terraform/modules/databases/outputs.tf` exits 0
</acceptance_criteria>
</task>

<task id="4">
<name>Validate Terraform formatting</name>
<read_first>
- terraform/modules/databases/cosmos.tf
- terraform/modules/databases/outputs.tf
</read_first>
<action>
Run `terraform fmt -check terraform/modules/databases/` to verify all files pass formatting. If any fail, run `terraform fmt terraform/modules/databases/` to fix. Verify the total container count in cosmos.tf is 8 (incidents, approvals, sessions, topology, baselines, remediation_audit, pattern_analysis, business_tiers).
</action>
<acceptance_criteria>
- `terraform fmt -check terraform/modules/databases/` exits 0
- `grep -c 'azurerm_cosmosdb_sql_container' terraform/modules/databases/cosmos.tf` returns 8
</acceptance_criteria>
</task>

## Verification Checklist

- [ ] `terraform fmt -check terraform/modules/databases/` exits 0
- [ ] cosmos.tf contains exactly 8 `azurerm_cosmosdb_sql_container` resources
- [ ] `pattern_analysis` container has partition key `/analysis_date`
- [ ] `business_tiers` container has partition key `/tier_name`
- [ ] outputs.tf has outputs for both new container names
- [ ] No existing container definitions modified

## must_haves

1. `azurerm_cosmosdb_sql_container.pattern_analysis` exists in `terraform/modules/databases/cosmos.tf` with partition key `/analysis_date`
2. `azurerm_cosmosdb_sql_container.business_tiers` exists in `terraform/modules/databases/cosmos.tf` with partition key `/tier_name`
3. `cosmos_pattern_analysis_container_name` output exists in `terraform/modules/databases/outputs.tf`
4. `cosmos_business_tiers_container_name` output exists in `terraform/modules/databases/outputs.tf`
5. All Terraform files pass `terraform fmt -check`
