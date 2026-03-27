# Summary: 04-01 — Infrastructure: Fabric, Event Hub, Networking & Activity Log

**Plan:** 04-01
**Phase:** 04-detection-plane
**Completed:** 2026-03-26
**Commits:** 37674ac, 6e28292, bc4dc3d, 881f32f, 009c004, 4cce929, aa027f3, 11c8459, 8335dd5

---

## What Was Built

### Task 4-01-01 — Fabric Terraform Module (INFRA-007)
**Files:** `terraform/modules/fabric/{main,variables,outputs}.tf`

Created a new Fabric module provisioning all Phase 4 detection plane Fabric resources via `azapi_resource`:
- `Microsoft.Fabric/capacities@2023-11-01` — F2 dev, F4 prod
- `Microsoft.Fabric/workspaces@2023-11-01` — workspace attached to capacity
- `Microsoft.Fabric/workspaces/eventhouses@2023-11-01` — Eventhouse for KQL storage
- `Microsoft.Fabric/workspaces/eventhouses/databases@2023-11-01` — KQL database
- `Microsoft.Fabric/workspaces/reflex@2023-11-01` — Activator for trigger-based detection
- `Microsoft.Fabric/workspaces/lakehouses@2023-11-01` — OneLake Lakehouse for audit data

Two `null_resource` post-apply reminders:
- `activator_setup_reminder` — notifies operator to configure Activator trigger manually
- `onelake_mirror_setup_reminder` — notifies operator to configure AUDIT-003 OneLake mirror

### Task 4-01-02 — Event Hub Terraform Module (DETECT-001)
**Files:** `terraform/modules/eventhub/{main,variables,outputs}.tf`

Created Event Hub module using `azurerm`:
- Standard SKU namespace with `public_network_access_enabled = false`
- VNet rule referencing `snet-reserved-1`
- `raw-alerts` hub (7-day retention)
- `eventhouse-consumer` consumer group for Fabric Eventstreams
- `action-group-send` and `eventhouse-listen` auth rules
- `azurerm_monitor_action_group` with `use_common_alert_schema = true`

### Task 4-01-03 — Networking: snet-reserved-1 Activation + Service Bus DNS (DETECT-001)
**Files:** `terraform/modules/networking/{main,outputs}.tf`

- Added `service_endpoints = ["Microsoft.EventHub"]` to `azurerm_subnet.reserved_1`
- Added NSG (`reserved_1`) with VNet inbound + Azure outbound rules
- Added `azurerm_private_dns_zone.servicebus` (`privatelink.servicebus.windows.net`)
- Added VNet link for servicebus DNS zone
- Exported `subnet_reserved_1_id` and `private_dns_zone_servicebus_id` outputs

### Task 4-01-04 — Cosmos DB Composite Index (DETECT-005)
**File:** `terraform/modules/databases/cosmos.tf`

Added `composite_index` block to `incidents` container `indexing_policy`:
- `(resource_id ASC, detection_rule ASC, created_at DESC, status ASC)`
- Supports Layer 1 time-window dedup query and Layer 2 open-incident check

### Task 4-01-05 — Event Hub Private Endpoint (DETECT-001)
**Files:** `terraform/modules/private-endpoints/{main,variables}.tf`

- Added `azurerm_private_endpoint.eventhub` (count-gated, `subresource_names = ["namespace"]`)
- Added `eventhub_namespace_id` and `private_dns_zone_servicebus_id` variables (default `""` to skip)

### Task 4-01-06 — Activity Log Module + azuread Provider + Fabric SP Variables (AUDIT-003, DETECT-003)
**Files:** `terraform/modules/activity-log/{main,variables,outputs}.tf`, `terraform/envs/*/providers.tf`, `terraform/envs/*/variables.tf`

- Created `activity-log` module with `for_each` over subscription IDs, exporting all 8 Activity Log categories
- Added `azuread` provider (`~> 3.0`, `use_oidc = true`) to dev/staging/prod environments
- Added `gateway_app_client_id` and `gateway_incidents_write_role_id` variables to all envs
- Added `fabric_admin_email` variable to all envs

### Task 4-01-07 — Environment Wiring (all Phase 4 requirements)
**Files:** `terraform/envs/{dev,staging,prod}/{main,variables}.tf`

Wired all new modules into all environments:
- `module "eventhub"` — dev/staging: 2 partitions; prod: 10 partitions, capacity 2
- `module "fabric"` — dev/staging: F2 SKU; prod: F4 SKU
- `module "activity_log"` — dev/staging: single subscription; prod: `var.all_subscription_ids`
- `module "private_endpoints"` — extended with `eventhub_namespace_id` + `private_dns_zone_servicebus_id`
- Fabric SP inline resources (`azuread_application`, `azuread_service_principal`, `azuread_application_password`)
  with `count` gate on `gateway_app_client_id`, fixed `end_date = "2027-03-26T00:00:00Z"` (WARN-D4a)
- Fabric SP client ID + secret stored in Key Vault

### Task 4-01-08 — AUDIT-003 OneLake Mirror Setup Documentation
**File:** `services/detection-plane/docs/AUDIT-003-onelake-setup.md`

Created comprehensive setup guide with:
- Two options: OneLake Shortcut (preferred) and Fabric Data Pipeline (alternative)
- Retention configuration (730 days / 2 years) via Fabric portal or Spark SQL
- Verification queries (KQL and Spark)
- Compliance checklist

---

## Must-Haves Verified

- [x] Fabric capacity via `azapi_resource` with `Microsoft.Fabric/capacities` (INFRA-007)
- [x] Fabric Eventhouse via `azapi_resource` with `Microsoft.Fabric/workspaces/eventhouses` (INFRA-007)
- [x] KQL Database via `azapi_resource` with `Microsoft.Fabric/workspaces/eventhouses/databases` (INFRA-007)
- [x] Fabric Activator via `azapi_resource` with `Microsoft.Fabric/workspaces/reflex` (INFRA-007)
- [x] OneLake Lakehouse via `azapi_resource` with `Microsoft.Fabric/workspaces/lakehouses` (INFRA-007)
- [x] Event Hub namespace + `raw-alerts` hub + consumer group + Action Group (DETECT-001)
- [x] `snet-reserved-1` activated with `Microsoft.EventHub` service endpoint (DETECT-001)
- [x] Private DNS zone `privatelink.servicebus.windows.net` created and linked to VNet (DETECT-001)
- [x] Event Hub private endpoint in private-endpoints module (DETECT-001)
- [x] Cosmos DB `incidents` container composite index on (resource_id, detection_rule, created_at, status) (DETECT-005)
- [x] Activity Log diagnostic settings export to Log Analytics (AUDIT-003)
- [x] `AUDIT-003-onelake-setup.md` exists with retention, 2 years, 730 days content (AUDIT-003)
- [x] `null_resource.onelake_mirror_setup_reminder` with AUDIT-003 reference (AUDIT-003)
- [x] Entra app registration + SP for Fabric User Data Function auth (DETECT-003 prereq)
- [x] `azuread_application_password` uses fixed `end_date`, NOT `timeadd(timestamp(), ...)` (WARN-D4a)
- [x] `azuread` provider added to all environment providers.tf files (DETECT-003 prereq)
- [x] Fabric, Event Hub, and Activity Log modules wired into dev/staging/prod (all reqs)
- [x] Fabric Activator trigger manual setup documented with `null_resource` reminder (NOTE-D8d)

---

## Decisions Made

| Decision | Rationale |
|---|---|
| `azapi_resource` for all Fabric data-plane items | Fabric REST API types supported via azapi; consistent with project Fabric Terraform pattern |
| `count` gate on Fabric SP resources | `gateway_app_client_id = ""` default allows deploy before API gateway Entra app is registered |
| Fixed `end_date = "2027-03-26T00:00:00Z"` | Avoids perpetual diff from `timeadd(timestamp(), ...)` per WARN-D4a |
| Activity Log module with `for_each` | Supports multi-subscription export (single in dev/staging, all subs in prod) |
| Service Bus DNS zone in networking module | Follows existing pattern: DNS zones + VNet links in networking, PEs in private-endpoints |

---

## Notes / Post-Apply Manual Steps Required

1. **Fabric Activator trigger**: Configure via Fabric portal after `terraform apply` — set data source to `DetectionResults` table, trigger on `domain IS NOT NULL`, invoke `handle_activator_trigger` function
2. **OneLake mirror**: Follow `services/detection-plane/docs/AUDIT-003-onelake-setup.md` — configure shortcut or Data Pipeline, set 730-day retention
3. **Fabric SP consent**: After `terraform apply` provisions the app registration, grant admin consent for the `incidents.write` app role assignment in Entra admin center
