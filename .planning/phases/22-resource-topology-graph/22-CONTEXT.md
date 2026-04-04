# Phase 22: Resource Topology Graph - Context

**Gathered:** 2026-04-03
**Status:** Ready for planning
**Mode:** Auto-generated (infrastructure + new API phase — discuss skipped)

<domain>
## Phase Boundary

Build and maintain a real-time property graph of all Azure resources and their relationships. This is the foundational Stage 4 capability that enables causal RCA, blast-radius estimation, and topology-aware alert suppression in Phases 23–27.

**Requirements:** TOPO-001 through TOPO-005
- TOPO-001: Resource property graph maintains all Azure resource types and their relationships
- TOPO-002: Blast-radius query returns results within 2 seconds
- TOPO-003: Topology graph freshness lag <15 minutes
- TOPO-004: Topology traversal used by domain agents as a mandatory triage step
- TOPO-005: Blast-radius query latency validated at ≥10,000 nodes before Phase 26 proceeds

**What this phase does:**
1. Add Cosmos DB container `topology` (adjacency-list, partition `/resource_id`) to Terraform databases module
2. Create `services/api-gateway/topology.py` — ARG bulk bootstrap, 15-min background sync, blast-radius BFS, path query
3. New API endpoints: `GET /api/v1/topology/blast-radius`, `GET /api/v1/topology/path`, `GET /api/v1/topology/snapshot`
4. Domain agents gain topology traversal as a mandatory triage step via `GET /api/v1/topology/blast-radius?resource_id=X`
5. Load test / validation: blast-radius query at ≥10,000 nodes under 2s (TOPO-002, TOPO-005)

**What this phase does NOT do:**
- Does not add Phase 23 change correlation (separate phase)
- Does not change the detection pipeline (Phase 21)
- Does not add new Fabric resources
- Does not add a new UI tab (topology visualization deferred to Phase 27+)

</domain>

<decisions>
## Implementation Decisions

### Storage: Cosmos DB adjacency-list (not a graph database)
- Use the existing `azurerm_cosmosdb_sql_database.main` in the databases module
- Add `azurerm_cosmosdb_sql_container.topology` partitioned by `/resource_id`
- Each document: `{ id: resource_id, resource_type, resource_group, subscription_id, name, tags, relationships: [{target_id, rel_type, direction}], last_synced_at }`
- Reasons: Cosmos DB is already provisioned, no new infra, RBAC already set up, BFS traversal over adjacency-list is sufficient for 10K nodes in <2s

### Bootstrap: ARG bulk query
- ARG supports cross-subscription queries — use existing `_run_arg_query` pattern from `vm_inventory.py` and `patch_endpoints.py`
- Bootstrap query: `Resources | project id, type, resourceGroup, subscriptionId, name, tags, properties`
- Relationship extraction: parse `properties.virtualNetworkSubnetId`, `properties.networkInterfaces[*].id`, `properties.storageProfile.osDisk.managedDisk.id`, etc.
- Bootstrap runs once at startup; background sync runs every 15 minutes (asyncio background task)
- Relationship types: `subnet_of`, `nic_of`, `disk_of`, `vnet_of`, `resource_group_member`, `connected_to`

### Sync: Background asyncio task (15-min interval)
- `asyncio.create_task` launched in lifespan startup
- Incremental sync using `ResourceChanges` ARG API (`resourcechanges | where changeTime > ago(15m)`)
- Full re-bootstrap on startup to handle drift

### Graph algorithms: BFS in Python (no external graph library)
- Blast-radius: BFS from `resource_id`, returns all reachable nodes within `max_depth` hops (default 3)
- Path: bidirectional BFS from source to target
- Keep it simple — no networkx dependency, pure Python dict-based adjacency list loaded from Cosmos

### Domain agent integration: topology_client helper
- New file `services/api-gateway/topology_client.py` with `get_blast_radius(resource_id)` function
- Domain agents call this at the start of triage to understand the blast radius of an affected resource
- The domain-agent services do not live in the api-gateway repo — they are Foundry hosted agents. The topology integration is via the REST API endpoint only.
- TOPO-004 is satisfied by documenting the API contract and adding a topology traversal step to agent prompts (in the foundry module system prompts / tool descriptions)

### Load test: synthetic graph (10,000 nodes)
- Script `scripts/ops/22-4-topology-load-test.sh` creates 10K synthetic nodes in the topology container and runs blast-radius queries
- Validates TOPO-002 (<2s) and TOPO-005 (≥10K nodes validated before Phase 26)

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `services/api-gateway/vm_inventory.py` — `_run_arg_query(credential, subscription_ids, kql)` pattern with pagination
- `services/api-gateway/patch_endpoints.py` — same `_run_arg_query` pattern (duplicate; topology should use a shared helper)
- `services/api-gateway/dependencies.py` — `get_credential`, `get_cosmos_client` dependency injection
- `services/api-gateway/main.py` — lifespan pattern for startup/shutdown, router includes
- `services/api-gateway/models.py` — Pydantic BaseModel patterns
- `terraform/modules/databases/cosmos.tf` — existing container definitions: incidents (`/resource_id`), approvals (`/thread_id`), sessions (`/incident_id`)

### Cosmos DB Container Pattern (from cosmos.tf)
```hcl
resource "azurerm_cosmosdb_sql_container" "topology" {
  name                  = "topology"
  resource_group_name   = var.resource_group_name
  account_name          = azurerm_cosmosdb_account.main.name
  database_name         = azurerm_cosmosdb_sql_database.main.name
  partition_key_paths   = ["/resource_id"]
  partition_key_version = 2
}
```

### API Patterns
- Routes live in dedicated modules (vm_inventory.py, patch_endpoints.py) then included via `app.include_router()`
- Auth: `Depends(verify_token)` on protected endpoints
- Async: endpoints are `async def`, CPU-bound ARG calls wrapped in `loop.run_in_executor(None, ...)`

### ARG Query Pattern
```python
from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions

client = ResourceGraphClient(credential)
request = QueryRequest(subscriptions=subscription_ids, query=kql)
response = client.resources(request)
rows = response.data
```

### Environment Variables Available
- `COSMOS_ENDPOINT` — already used by api-gateway
- `SUBSCRIPTION_IDS` — comma-separated list (used in vm_inventory.py)

### Agent System Prompts Location
- Domain agents are Foundry-hosted; their system prompts are in `terraform/modules/agent-apps/main.tf` as Container App env vars or in the agent deployment config
- Check `terraform/modules/agent-apps/main.tf` for `SYSTEM_PROMPT` or similar env vars

</code_context>

<specifics>
## Specific Ideas

### Topology document schema (Cosmos DB)
```json
{
  "id": "/subscriptions/xxx/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-prod-01",
  "resource_id": "/subscriptions/xxx/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-prod-01",
  "resource_type": "microsoft.compute/virtualmachines",
  "resource_group": "rg-prod",
  "subscription_id": "xxx",
  "name": "vm-prod-01",
  "tags": {},
  "relationships": [
    {"target_id": "/subscriptions/.../nic/vm-prod-01-nic", "rel_type": "nic_of", "direction": "outbound"},
    {"target_id": "/subscriptions/.../subnet/default", "rel_type": "subnet_of", "direction": "outbound"}
  ],
  "last_synced_at": "2026-04-03T10:00:00Z"
}
```

### API endpoints
- `GET /api/v1/topology/blast-radius?resource_id=<id>&max_depth=3` → `{ resource_id, affected_resources: [...], hop_counts: {...} }`
- `GET /api/v1/topology/path?source=<id>&target=<id>` → `{ path: [...], hops: int }`
- `GET /api/v1/topology/snapshot?resource_id=<id>` → full topology doc for one resource
- `POST /api/v1/topology/bootstrap` → trigger full ARG re-bootstrap (operator use, auth required)

### Relationship extraction KQL
```kql
Resources
| where type in~ ('microsoft.compute/virtualmachines', 'microsoft.network/networkinterfaces',
                   'microsoft.network/virtualnetworks', 'microsoft.compute/disks',
                   'microsoft.storage/storageaccounts')
| project id=tolower(id), type=tolower(type), resourceGroup, subscriptionId, name, tags=tostring(tags),
          nic_ids=tostring(properties.networkProfile.networkInterfaces),
          subnet_id=tostring(properties.ipConfigurations[0].properties.subnet.id),
          vnet_id=tostring(properties.subnets[0].id)
```

### TOPO-004 domain agent integration
- Add `X-Topology-Context` enrichment: when an incident comes in for a resource_id, the API gateway's incident handler can pre-fetch the blast-radius and attach it to the Foundry thread as context
- This means the domain agent automatically receives topology context without changing agent code

</specifics>

<deferred>
## Deferred Ideas

- Topology visualization in UI (deferred to Phase 27+)
- Change event streaming via Activity Log Event Hub (Phase 23 handles change correlation)
- Graph database migration (Cosmos DB adjacency-list sufficient for current scale)
- Cross-tenant topology (single tenant scope for this milestone)

</deferred>

---

*Phase: 22-resource-topology-graph*
*Context gathered: 2026-04-03 via autonomous mode*
