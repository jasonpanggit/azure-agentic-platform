---
wave: 1
depends_on: []
requirements: [TOPO-001, TOPO-003]
autonomous: true
files_modified:
  - terraform/modules/databases/cosmos.tf
  - terraform/modules/databases/outputs.tf
---

# Plan 22-1: Cosmos DB Topology Container

Add the `topology` Cosmos DB container to the existing databases Terraform module. This is the storage foundation for TOPO-001 — the adjacency-list property graph. No new infra resources are required; the container joins the existing `aap` database on the already-provisioned Cosmos account.

---

<task id="22-1-01">
<title>Add azurerm_cosmosdb_sql_container.topology to cosmos.tf</title>

<read_first>
- `terraform/modules/databases/cosmos.tf` — understand the existing container pattern (incidents, approvals, sessions); match naming, attribute order, and indexing_policy structure exactly
</read_first>

<action>
Append the following resource block to `terraform/modules/databases/cosmos.tf`, after the `azurerm_cosmosdb_sql_container.sessions` block and before the comment block about private endpoints:

```hcl
resource "azurerm_cosmosdb_sql_container" "topology" {
  name                  = "topology"
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
      path = "/relationships/[]/target_id/?"
    }

    excluded_path {
      path = "/_etag/?"
    }

    # Composite index for BFS traversal queries:
    #   WHERE resource_id = @id (single-partition reads by topology service)
    #   WHERE resource_type = @type AND last_synced_at >= @cutoff (freshness check)
    composite_index {
      index {
        path  = "/resource_type"
        order = "ascending"
      }
      index {
        path  = "/last_synced_at"
        order = "descending"
      }
    }
  }
}
```

Rationale for index choices:
- `relationships[]/target_id` excluded from index — BFS reads entire documents by `resource_id` partition key; indexing nested array fields would waste RU/s
- `_etag` excluded — matches existing container pattern
- Composite index on `(resource_type, last_synced_at DESC)` supports the incremental sync freshness query: `SELECT * FROM c WHERE c.resource_type = @t AND c.last_synced_at < @cutoff`
</action>

<acceptance_criteria>
```bash
# Verify the topology container block is present with correct partition key
grep -A 5 'resource "azurerm_cosmosdb_sql_container" "topology"' terraform/modules/databases/cosmos.tf | grep 'partition_key_paths.*resource_id'

# Verify partition_key_version = 2
grep -A 6 '"topology"' terraform/modules/databases/cosmos.tf | grep 'partition_key_version = 2'

# Verify terraform fmt passes (no formatting drift)
cd terraform && terraform fmt -check -recursive modules/databases/
```
</acceptance_criteria>
</task>

---

<task id="22-1-02">
<title>Add topology_container_name output to outputs.tf</title>

<read_first>
- `terraform/modules/databases/outputs.tf` — match the existing output block style; see `cosmos_sessions_container_name` as the direct template
</read_first>

<action>
Append the following output block to `terraform/modules/databases/outputs.tf`, after the `cosmos_sessions_container_name` output:

```hcl
output "cosmos_topology_container_name" {
  description = "Name of the Cosmos DB topology container for the resource property graph (TOPO-001)"
  value       = azurerm_cosmosdb_sql_container.topology.name
}
```

No changes to `variables.tf` are needed — the topology container reuses all existing variables (`resource_group_name`, `location`, `environment`, etc.). The container is unconditionally created in all environments (dev, staging, prod) because the topology sync service runs in all environments.
</action>

<acceptance_criteria>
```bash
# Verify output block is present
grep -A 3 'cosmos_topology_container_name' terraform/modules/databases/outputs.tf | grep 'azurerm_cosmosdb_sql_container.topology.name'

# Verify terraform validate passes for the databases module
cd terraform && terraform init -backend=false && terraform validate ./modules/databases/ 2>&1 | grep -E "^(Success|Error)"
```
</acceptance_criteria>
</task>

---

<task id="22-1-03">
<title>Verify no duplicate resource names and terraform fmt clean</title>

<read_first>
- `terraform/modules/databases/cosmos.tf` — full file after edits; confirm resource name `topology` does not conflict with any existing container
</read_first>

<action>
After both edits are applied:

1. Confirm there is exactly one `azurerm_cosmosdb_sql_container` with `name = "topology"` in the module.
2. Run `terraform fmt -recursive` on the databases module directory to normalize formatting.
3. Confirm the four containers in the module are: `incidents`, `approvals`, `sessions`, `topology` — in that order.

No changes to `variables.tf` are required. The `agent_principal_ids` RBAC loop (`azurerm_cosmosdb_sql_role_assignment.data_contributor`) is scoped to the account level and already grants access to the topology container without modification.
</action>

<acceptance_criteria>
```bash
# Exactly one topology container resource
grep -c '"topology"' terraform/modules/databases/cosmos.tf | grep '^1$'

# All four containers present
grep 'resource "azurerm_cosmosdb_sql_container"' terraform/modules/databases/cosmos.tf | wc -l | grep '^4$'

# fmt check passes
terraform fmt -check terraform/modules/databases/cosmos.tf && echo "fmt OK"
```
</acceptance_criteria>
</task>

---

## must_haves

- [ ] `azurerm_cosmosdb_sql_container.topology` added to `cosmos.tf` with `partition_key_paths = ["/resource_id"]` and `partition_key_version = 2`
- [ ] `indexing_policy` includes `consistent` mode, `/*` included path, `/_etag/?` and `/relationships/[]/target_id/?` excluded paths, and the composite index on `(resource_type ASC, last_synced_at DESC)`
- [ ] `cosmos_topology_container_name` output added to `outputs.tf` referencing `azurerm_cosmosdb_sql_container.topology.name`
- [ ] `variables.tf` is NOT modified (no new variables needed)
- [ ] `terraform fmt -check` passes on the databases module with no formatting diff
- [ ] No changes to the RBAC `azurerm_cosmosdb_sql_role_assignment.data_contributor` loop (account-scoped, already covers the new container)
