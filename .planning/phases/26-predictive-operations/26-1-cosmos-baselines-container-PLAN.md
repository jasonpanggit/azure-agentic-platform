# Plan 26-1: Cosmos Baselines Container + Terraform

**Phase:** 26 — Predictive Operations
**Wave:** 1 (no dependencies)
**Autonomous:** true
**Requirement:** INTEL-005 — storage layer for per-resource metric baselines

---

## Goal

Add the `baselines` Cosmos DB container to Terraform and expose it as a module output. This is the only infrastructure change in Phase 26. All Python code in Wave 2 and Wave 3 depends on this container existing.

---

## Files to Change

| File | Change |
|---|---|
| `terraform/modules/databases/cosmos.tf` | Add `azurerm_cosmosdb_sql_container.baselines` |
| `terraform/modules/databases/outputs.tf` | Add `cosmos_baselines_container_name` output |

---

## Implementation

### 1. `terraform/modules/databases/cosmos.tf`

Append after the `azurerm_cosmosdb_sql_container.topology` block (before the comment block at line 187). Follow the exact same structure as the `topology` container — same partition key path, same version, same indexing mode.

```hcl
resource "azurerm_cosmosdb_sql_container" "baselines" {
  name                  = "baselines"
  resource_group_name   = var.resource_group_name
  account_name          = azurerm_cosmosdb_account.main.name
  database_name         = azurerm_cosmosdb_sql_database.main.name
  partition_key_paths   = ["/resource_id"]
  partition_key_version = 2

  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }

    excluded_path {
      path = "/data_points/[]/*"
    }

    excluded_path {
      path = "/_etag/?"
    }

    # Composite index for the sweep query:
    #   WHERE resource_type = @type AND last_updated >= @cutoff
    #   Used by ForecasterClient.get_all_imminent() to find breach-imminent resources
    composite_index {
      index {
        path  = "/resource_type"
        order = "ascending"
      }
      index {
        path  = "/last_updated"
        order = "descending"
      }
    }

    # Composite index for time-to-breach alert queries:
    #   WHERE resource_id = @id AND time_to_breach_minutes <= @threshold
    composite_index {
      index {
        path  = "/resource_id"
        order = "ascending"
      }
      index {
        path  = "/time_to_breach_minutes"
        order = "ascending"
      }
    }
  }
}
```

**Why `data_points/[]/*` excluded:** The `data_points` array holds up to 24 timestamped metric readings per document. Indexing each element would bloat the index for no query benefit — all queries hit `resource_id`, `resource_type`, or `time_to_breach_minutes`.

### 2. `terraform/modules/databases/outputs.tf`

Append after the `cosmos_topology_container_name` output:

```hcl
output "cosmos_baselines_container_name" {
  description = "Name of the Cosmos DB baselines container for capacity forecasting (INTEL-005)"
  value       = azurerm_cosmosdb_sql_container.baselines.name
}
```

---

## Cosmos Document Schema (reference for Wave 2)

Documents in the `baselines` container follow this structure. The Python `ForecasterClient` in Plan 26-2 writes and reads these documents.

```json
{
  "id": "<resource_id>:<metric_name>",
  "resource_id": "<arm resource id lowercased>",
  "metric_name": "Percentage CPU",
  "resource_type": "microsoft.compute/virtualmachines",
  "data_points": [
    {"timestamp": "2026-04-03T10:00:00Z", "value": 42.3},
    ...
  ],
  "level": 45.2,
  "trend": 0.8,
  "threshold": 90.0,
  "invert": false,
  "time_to_breach_minutes": 56.0,
  "confidence": "medium",
  "mape": 18.5,
  "last_updated": "2026-04-03T10:00:00Z"
}
```

- **Partition key:** `/resource_id` — all metrics for a given resource are co-located in the same logical partition, enabling efficient per-resource queries without cross-partition fan-out.
- **Document ID:** `<resource_id>:<metric_name>` — allows upsert by exact ID (no need to query first).
- **`data_points` excluded from index:** array of up to 24 elements; never queried by timestamp.

---

## Verification Steps

```bash
# 1. Validate Terraform config parses without error
cd terraform && terraform validate

# 2. Confirm the new container block is present
grep -A5 'resource "azurerm_cosmosdb_sql_container" "baselines"' modules/databases/cosmos.tf

# 3. Confirm the new output is present
grep "cosmos_baselines_container_name" modules/databases/outputs.tf

# 4. Terraform plan (requires Azure credentials — skip in CI if not available)
terraform plan -var-file=credentials.tfvars 2>&1 | grep -E "(baselines|Plan)"
```

Expected plan output:
```
# azurerm_cosmosdb_sql_container.baselines will be created
Plan: 1 to add, 0 to change, 0 to destroy.
```

---

## Acceptance Criteria

- [ ] `azurerm_cosmosdb_sql_container.baselines` present in `cosmos.tf` with partition `/resource_id` and version 2
- [ ] `data_points` array path excluded from indexing
- [ ] Composite indexes defined for `resource_type+last_updated` and `resource_id+time_to_breach_minutes`
- [ ] `cosmos_baselines_container_name` output in `outputs.tf`
- [ ] `terraform validate` passes

---

## Notes

- No variables to add — the container inherits all existing `var.resource_group_name`, `var.environment`, and `azurerm_cosmosdb_account.main` references from the module.
- No RBAC changes needed — `azurerm_cosmosdb_sql_role_assignment.data_contributor` already grants `Cosmos DB Built-in Data Contributor` at the account scope, which covers all containers including `baselines`.
- The container name `"baselines"` is hardcoded (not a variable), consistent with all other containers in this module (`"incidents"`, `"approvals"`, `"sessions"`, `"topology"`).
