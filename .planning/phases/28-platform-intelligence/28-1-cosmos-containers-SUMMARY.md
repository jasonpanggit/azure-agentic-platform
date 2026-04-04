---
plan: 28-1
phase: 28
status: complete
completed_at: "2026-04-04"
commits:
  - 41f44cc  # feat: add pattern_analysis and business_tiers Cosmos containers
  - 0e0213c  # feat: add Terraform outputs for pattern_analysis and business_tiers containers
---

# Plan 28-1 Summary: Cosmos DB Containers for Platform Intelligence

## Objective

Add two new Cosmos DB SQL containers (`pattern_analysis` and `business_tiers`) to the databases Terraform module, satisfying requirements PLATINT-001 and PLATINT-004.

## What Was Done

### Task 1 + 2: New Containers in cosmos.tf

Added two `azurerm_cosmosdb_sql_container` resource blocks after `remediation_audit` in `terraform/modules/databases/cosmos.tf`:

**`pattern_analysis`** (PLATINT-001 — weekly pattern analysis results)
- Partition key: `/analysis_date` — one document per weekly run, accessed by date
- Excludes `/top_patterns/[]/*` from indexing — large nested arrays are read by full-doc fetch, not individually queried; excluding reduces index storage and write overhead
- No TTL — compliance retention requirement (same as `remediation_audit`)

**`business_tiers`** (PLATINT-004 — operator-configured FinOps tiers)
- Partition key: `/tier_name` — each tier is a single document, accessed by name
- Standard `/*` indexing — small container, no composite indexes needed
- No TTL — operator-managed configuration that must not expire

Both containers follow the established pattern: `partition_key_version = 2`, `indexing_mode = "consistent"`, `/_etag/?` excluded.

### Task 3: Outputs in outputs.tf

Added two output blocks to `terraform/modules/databases/outputs.tf`:
- `cosmos_pattern_analysis_container_name` — references PLATINT-001
- `cosmos_business_tiers_container_name` — references PLATINT-004

Follows the existing naming convention (`cosmos_<name>_container_name`).

### Task 4: Format Validation

- `terraform fmt -check terraform/modules/databases/` exits 0 ✅
- Total `azurerm_cosmosdb_sql_container` count: 8 (6 existing + 2 new) ✅

## Verification Results

| Check | Result |
|---|---|
| `terraform fmt -check terraform/modules/databases/` | ✅ Exits 0 |
| Container count = 8 | ✅ Confirmed |
| `pattern_analysis` partition key `/analysis_date` | ✅ Present |
| `business_tiers` partition key `/tier_name` | ✅ Present |
| Both outputs in outputs.tf | ✅ Present |
| All 6 original containers unmodified | ✅ Confirmed |
| PLATINT-001 reference in outputs | ✅ Present |
| PLATINT-004 reference in outputs | ✅ Present |

## Files Modified

| File | Change |
|---|---|
| `terraform/modules/databases/cosmos.tf` | +46 lines — two new container resource blocks |
| `terraform/modules/databases/outputs.tf` | +10 lines — two new output blocks |

## Commits

1. `41f44cc` — `feat: add pattern_analysis and business_tiers Cosmos containers (PLATINT-001, PLATINT-004)`
2. `0e0213c` — `feat: add Terraform outputs for pattern_analysis and business_tiers containers`
