# Plan 27-1: remediation_audit Cosmos Container + Terraform

**Phase:** 27 — Closed-Loop Remediation
**Wave:** 1 (no dependencies)
**Requirements:** REMEDI-011, REMEDI-013
**Autonomous:** true

---

## Objective

Add the `remediation_audit` Cosmos DB SQL container to Terraform and expose it via an output. This container is the write-ahead log (WAL) store and immutable audit trail for every automated ARM action executed by the platform.

---

## Context

### Existing container pattern (from `cosmos.tf`)
All containers follow the same resource block signature:
```hcl
resource "azurerm_cosmosdb_sql_container" "<name>" {
  name                  = "<name>"
  resource_group_name   = var.resource_group_name
  account_name          = azurerm_cosmosdb_account.main.name
  database_name         = azurerm_cosmosdb_sql_database.main.name
  partition_key_paths   = ["/..."]
  partition_key_version = 2

  indexing_policy { ... }
}
```

### Existing outputs pattern (from `outputs.tf`)
```hcl
output "cosmos_baselines_container_name" {
  description = "..."
  value       = azurerm_cosmosdb_sql_container.baselines.name
}
```

### Why `/incident_id` as partition key
- Every WAL/audit record carries an `incident_id` (inherited from the approval record).
- All verification and rollback records for the same incident land in the same logical partition.
- Cross-partition queries are only needed for the WAL stale-monitor (every 5 min, low frequency).
- Consistent with `sessions` container which also partitions by `/incident_id`.

### Immutability design
- The Cosmos SDK client code **never issues DELETE** against this container.
- The WAL pattern allows one `replace_item` per execution (pending → complete/failed) — this is not a delete; it updates status within the same immutable record.
- No TTL is set; records are retained indefinitely for compliance (REMEDI-013).

### Composite index rationale
Two query patterns drive the index design:
1. **WAL stale monitor** (REMEDI-011): `WHERE c.status = "pending" AND c.wal_written_at < @cutoff` — cross-partition, runs every 5 min.
2. **Compliance export** (REMEDI-013): `WHERE c.executed_at >= @from AND c.executed_at <= @to` — time-range scan.

---

## Files to Modify

### 1. `terraform/modules/databases/cosmos.tf`

**Location:** After the `azurerm_cosmosdb_sql_container.baselines` block (before the NOTE comment about private endpoints).

**Add:**
```hcl
resource "azurerm_cosmosdb_sql_container" "remediation_audit" {
  name                  = "remediation_audit"
  resource_group_name   = var.resource_group_name
  account_name          = azurerm_cosmosdb_account.main.name
  database_name         = azurerm_cosmosdb_sql_database.main.name
  partition_key_paths   = ["/incident_id"]
  partition_key_version = 2

  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }

    excluded_path {
      path = "/_etag/?"
    }

    # Composite index for WAL stale-monitor query (REMEDI-011):
    #   WHERE c.status = "pending" AND c.wal_written_at < @cutoff
    composite_index {
      index {
        path  = "/status"
        order = "ascending"
      }
      index {
        path  = "/wal_written_at"
        order = "ascending"
      }
    }

    # Composite index for compliance export query (REMEDI-013):
    #   WHERE c.executed_at >= @from AND c.executed_at <= @to
    composite_index {
      index {
        path  = "/executed_at"
        order = "ascending"
      }
      index {
        path  = "/incident_id"
        order = "ascending"
      }
    }
  }
}
```

### 2. `terraform/modules/databases/outputs.tf`

**Location:** After the `cosmos_baselines_container_name` output block.

**Add:**
```hcl
output "cosmos_remediation_audit_container_name" {
  description = "Name of the Cosmos DB remediation_audit container for WAL and immutable audit trail (REMEDI-011, REMEDI-013)"
  value       = azurerm_cosmosdb_sql_container.remediation_audit.name
}
```

---

## Implementation Steps

- [ ] Read `terraform/modules/databases/cosmos.tf` (verify current last container block)
- [ ] Read `terraform/modules/databases/outputs.tf` (verify current last output block)
- [ ] Add `azurerm_cosmosdb_sql_container.remediation_audit` resource block to `cosmos.tf` after `baselines` block
- [ ] Add `cosmos_remediation_audit_container_name` output to `outputs.tf`
- [ ] Run `terraform validate` in `terraform/modules/databases/` to confirm HCL syntax is valid
- [ ] Run `terraform plan` (dry-run) to confirm exactly 2 resources will be added: `azurerm_cosmosdb_sql_container.remediation_audit` and `output.cosmos_remediation_audit_container_name`

---

## Verification Checklist

- [ ] `terraform validate` exits 0 with no errors
- [ ] `terraform plan` shows `Plan: 1 to add` for the container resource (output changes are not counted as resource adds)
- [ ] Container name in plan output is `remediation_audit`
- [ ] Partition key path in plan output is `/incident_id`
- [ ] `partition_key_version = 2` is present in plan
- [ ] Two `composite_index` blocks appear in the indexing policy
- [ ] No existing resources are modified (incidents, approvals, sessions, topology, baselines all show no change)
- [ ] Output `cosmos_remediation_audit_container_name` resolves to `"remediation_audit"` in plan

---

## Constraints

- **No throughput block** — the database uses `autoscale_settings` at the database level; container-level throughput must not be set (matches all other containers in the file).
- **No TTL** — retention is indefinite for compliance; do not add `default_ttl`.
- **No delete ever** — the application layer must never delete from this container; this is enforced by convention and code review, not by Terraform.
- **Serverless compatibility** — the `cosmos_serverless` variable controls throughput at the database level; the container definition requires no conditional logic.

---

## Handoff to Plan 27-2

Plan 27-2 (`remediation_executor.py`) will reference the container name `"remediation_audit"` via the env var `COSMOS_REMEDIATION_AUDIT_CONTAINER` (defaulting to `"remediation_audit"`). The Terraform output `cosmos_remediation_audit_container_name` feeds this env var in the Container Apps configuration (not in scope for this phase — operator sets it via `terraform.tfvars`).
