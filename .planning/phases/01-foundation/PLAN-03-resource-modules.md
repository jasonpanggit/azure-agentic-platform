# Plan 03: Resource Module Implementations (Foundry, Databases, Compute-env, Key Vault, Private Endpoints)

```yaml
wave: 3
depends_on:
  - PLAN-01-scaffold-and-bootstrap
  - PLAN-02-networking
files_modified:
  - terraform/modules/foundry/main.tf
  - terraform/modules/foundry/capability-host.tf
  - terraform/modules/databases/cosmos.tf
  - terraform/modules/databases/postgres.tf
  - terraform/modules/compute-env/main.tf
  - terraform/modules/compute-env/versions.tf
  - terraform/modules/keyvault/main.tf
  - terraform/modules/private-endpoints/main.tf
autonomous: true
requirements:
  - INFRA-001
  - INFRA-002
  - INFRA-003
  - INFRA-004
```

## Goal

Implement all remaining resource modules with complete Terraform resource definitions, including the new dedicated private-endpoints module. After this wave, every module can produce a valid `terraform plan` when called from an environment root. All resources must carry required tags and use private networking.

> **REVISION (ISSUE-01):** Added task 03.07 for dedicated private-endpoints module implementation.
> Removed PE blocks from tasks 03.03 (cosmos.tf) and 03.05 (compute-env/main.tf).

> **REVISION (ISSUE-03):** Added `tags = var.required_tags` to `azurerm_cognitive_deployment` in task 03.01.

> **REVISION (ISSUE-04):** Replaced `terraform_data` local-exec pgvector provisioner in task 03.04
> with a comment directing to the GitHub Actions workaround in PLAN-05.

> **REVISION (ISSUE-09):** Removed `identity { type = "SystemAssigned" }` from `azurerm_cognitive_account_project` in task 03.01.

> **REVISION (ISSUE-10):** Added `random_string` for globally unique ACR name in task 03.05.

---

## Tasks

<task id="03.01">
<title>Implement Foundry module (AI Services account, project, model deployment)</title>
<read_first>
- terraform/modules/foundry/variables.tf (variable interface from Plan 01)
- terraform/modules/foundry/outputs.tf (output interface from Plan 01)
- .planning/phases/01-foundation/01-RESEARCH.md (Section 5: Azure AI Foundry Provisioning — full HCL examples)
- CLAUDE.md (Technology Stack — azurerm_cognitive_account kind="AIServices", azurerm_cognitive_account_project, azurerm_cognitive_deployment)
</read_first>
<action>
Replace placeholder in `terraform/modules/foundry/main.tf` with:

```hcl
resource "azurerm_cognitive_account" "foundry" {
  name                          = "aap-foundry-${var.environment}"
  location                      = var.location
  resource_group_name           = var.resource_group_name
  kind                          = "AIServices"
  sku_name                      = "S0"
  custom_subdomain_name         = "aap-foundry-${var.environment}"
  public_network_access_enabled = true # Required during Preview for Hosted Agents
  project_management_enabled    = true

  identity {
    type = "SystemAssigned"
  }

  tags = var.required_tags
}

resource "azurerm_cognitive_account_project" "main" {
  name                 = "aap-project-${var.environment}"
  cognitive_account_id = azurerm_cognitive_account.foundry.id
  location             = var.location

  # NOTE (ISSUE-09): identity block removed — azurerm_cognitive_account_project
  # likely does not support the identity block. The project inherits identity
  # from the parent cognitive account.

  tags = var.required_tags
}

resource "azurerm_cognitive_deployment" "gpt4o" {
  name                 = var.model_name
  cognitive_account_id = azurerm_cognitive_account.foundry.id

  model {
    format  = "OpenAI"
    name    = var.model_name
    version = var.model_version
  }

  sku {
    name     = "Standard"
    capacity = var.model_capacity
  }

  # ISSUE-03: tags were missing from model deployment
  tags = var.required_tags
}

# Diagnostic settings for Foundry account
resource "azurerm_monitor_diagnostic_setting" "foundry" {
  name                       = "diag-foundry-${var.environment}"
  target_resource_id         = azurerm_cognitive_account.foundry.id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log {
    category = "Audit"
  }

  enabled_log {
    category = "RequestResponse"
  }

  metric {
    category = "AllMetrics"
  }
}
```
</action>
<acceptance_criteria>
- `terraform/modules/foundry/main.tf` contains `resource "azurerm_cognitive_account" "foundry"` with `kind = "AIServices"`
- Resource has `custom_subdomain_name = "aap-foundry-${var.environment}"`
- Resource has `project_management_enabled = true`
- Resource has `identity { type = "SystemAssigned" }`
- Resource has `public_network_access_enabled = true` (required during Preview)
- File contains `resource "azurerm_cognitive_account_project" "main"` with `cognitive_account_id = azurerm_cognitive_account.foundry.id`
- `azurerm_cognitive_account_project` does NOT have an `identity` block **(ISSUE-09)**
- File contains `resource "azurerm_cognitive_deployment" "gpt4o"` with `model { format = "OpenAI" name = var.model_name }`
- `azurerm_cognitive_deployment.gpt4o` has `tags = var.required_tags` **(ISSUE-03)**
- File contains `resource "azurerm_monitor_diagnostic_setting" "foundry"` sending logs to `var.log_analytics_workspace_id`
- All taggable resources have `tags = var.required_tags`
</acceptance_criteria>
</task>

<task id="03.02">
<title>Implement Foundry capability host (azapi)</title>
<read_first>
- terraform/modules/foundry/capability-host.tf (current placeholder)
- terraform/modules/foundry/main.tf (after task 03.01 — need the account resource name)
- .planning/phases/01-foundation/01-RESEARCH.md (Section 5: Capability Host HCL example, known issues)
- .planning/research/PITFALLS.md (Section 2: No Private Networking, Section 9: Fabric and Foundry Resources Require azapi)
</read_first>
<action>
Replace placeholder in `terraform/modules/foundry/capability-host.tf` with:

```hcl
# Capability Host — required for Foundry Hosted Agents (Phase 2)
# Uses azapi because this resource type is not available in azurerm.
#
# KNOWN ISSUES:
# - Long-running operation (up to 30 min) — extended timeouts configured
# - May show perpetual drift on specific properties — lifecycle ignore_changes used
# - enablePublicHostingEnvironment = true is REQUIRED during Preview (no private networking)

resource "azapi_resource" "capability_host" {
  type      = "Microsoft.CognitiveServices/accounts/capabilityHosts@2025-10-01-preview"
  name      = "accountcaphost"
  parent_id = azurerm_cognitive_account.foundry.id

  body = {
    properties = {
      capabilityHostKind             = "Agents"
      enablePublicHostingEnvironment = true
    }
  }

  timeouts {
    create = "30m"
    delete = "30m"
  }

  lifecycle {
    ignore_changes = [
      body.properties.enablePublicHostingEnvironment,
    ]
  }
}
```
</action>
<acceptance_criteria>
- `terraform/modules/foundry/capability-host.tf` contains `resource "azapi_resource" "capability_host"`
- Resource type is `"Microsoft.CognitiveServices/accounts/capabilityHosts@2025-10-01-preview"`
- Resource name is `"accountcaphost"`
- `parent_id = azurerm_cognitive_account.foundry.id`
- Body contains `capabilityHostKind = "Agents"`
- Body contains `enablePublicHostingEnvironment = true`
- Timeouts block has `create = "30m"` and `delete = "30m"`
- Lifecycle block has `ignore_changes` containing the public hosting environment property
</acceptance_criteria>
</task>

<task id="03.03">
<title>Implement Cosmos DB (serverless/provisioned conditional, containers — NO private endpoint)</title>
<read_first>
- terraform/modules/databases/variables.tf (variable interface from Plan 01)
- terraform/modules/databases/outputs.tf (output interface from Plan 01)
- terraform/modules/databases/cosmos.tf (current placeholder)
- .planning/phases/01-foundation/01-RESEARCH.md (Section 6: Database Provisioning — Cosmos DB, environment strategy, container design)
</read_first>
<action>
Replace placeholder in `terraform/modules/databases/cosmos.tf` with:

> **REVISION (ISSUE-01):** The `azurerm_private_endpoint.cosmos` resource has been REMOVED from this file.
> It is now created by the dedicated `modules/private-endpoints/` module (task 03.07).

```hcl
resource "azurerm_cosmosdb_account" "main" {
  name                          = "aap-cosmos-${var.environment}"
  location                      = var.location
  resource_group_name           = var.resource_group_name
  offer_type                    = "Standard"
  kind                          = "GlobalDocumentDB"
  public_network_access_enabled = false

  dynamic "capabilities" {
    for_each = var.cosmos_serverless ? [1] : []
    content {
      name = "EnableServerless"
    }
  }

  consistency_policy {
    consistency_level = "Session"
  }

  geo_location {
    location          = var.location
    failover_priority = 0
  }

  dynamic "geo_location" {
    for_each = !var.cosmos_serverless && var.cosmos_secondary_location != "" ? [1] : []
    content {
      location          = var.cosmos_secondary_location
      failover_priority = 1
    }
  }

  identity {
    type = "SystemAssigned"
  }

  tags = var.required_tags
}

resource "azurerm_cosmosdb_sql_database" "main" {
  name                = "aap"
  resource_group_name = var.resource_group_name
  account_name        = azurerm_cosmosdb_account.main.name

  # Autoscale throughput for provisioned mode only
  dynamic "autoscale_settings" {
    for_each = var.cosmos_serverless ? [] : [1]
    content {
      max_throughput = var.cosmos_max_throughput
    }
  }
}

resource "azurerm_cosmosdb_sql_container" "incidents" {
  name                  = "incidents"
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
      path = "/raw_alert/*"
    }

    excluded_path {
      path = "/_etag/?"
    }
  }
}

resource "azurerm_cosmosdb_sql_container" "approvals" {
  name                  = "approvals"
  resource_group_name   = var.resource_group_name
  account_name          = azurerm_cosmosdb_account.main.name
  database_name         = azurerm_cosmosdb_sql_database.main.name
  partition_key_paths   = ["/thread_id"]
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

# NOTE: Cosmos DB private endpoint is created by modules/private-endpoints (task 03.07),
# NOT in this file. This prevents duplicate PE definitions (ISSUE-01).
```
</action>
<acceptance_criteria>
- `terraform/modules/databases/cosmos.tf` contains `resource "azurerm_cosmosdb_account" "main"` with `kind = "GlobalDocumentDB"`
- Account has `public_network_access_enabled = false`
- Account has dynamic `capabilities` block that adds `EnableServerless` only when `var.cosmos_serverless` is true
- Account has dynamic `geo_location` block for secondary region only when `!var.cosmos_serverless && var.cosmos_secondary_location != ""`
- Account has `consistency_policy { consistency_level = "Session" }`
- File contains `resource "azurerm_cosmosdb_sql_database" "main"` with `name = "aap"`
- Database has dynamic `autoscale_settings` block only when not serverless
- File contains `resource "azurerm_cosmosdb_sql_container" "incidents"` with `partition_key_paths = ["/resource_id"]`
- File contains `resource "azurerm_cosmosdb_sql_container" "approvals"` with `partition_key_paths = ["/thread_id"]`
- Both containers have `partition_key_version = 2`
- File does NOT contain `resource "azurerm_private_endpoint" "cosmos"` **(ISSUE-01 fix)**
</acceptance_criteria>
</task>

<task id="03.04">
<title>Implement PostgreSQL Flexible Server with pgvector (no local-exec provisioner)</title>
<read_first>
- terraform/modules/databases/variables.tf (variable interface from Plan 01)
- terraform/modules/databases/outputs.tf (output interface from Plan 01)
- terraform/modules/databases/postgres.tf (current placeholder)
- .planning/phases/01-foundation/01-RESEARCH.md (Section 6: PostgreSQL Flexible Server, pgvector Extension Setup)
- .planning/research/PITFALLS.md (Section 9: Terraform pitfalls)
</read_first>
<action>
Replace placeholder in `terraform/modules/databases/postgres.tf` with:

> **REVISION (ISSUE-04):** The `terraform_data` `local-exec` provisioner for `CREATE EXTENSION vector`
> has been REMOVED. A GitHub-hosted runner cannot reach a VNet-injected PostgreSQL server with
> `public_network_access_enabled = false`. The pgvector extension creation is handled by a
> GitHub Actions post-deploy step in PLAN-05 (task 05.04) that temporarily opens a firewall rule
> for the runner's egress IP.

```hcl
resource "azurerm_postgresql_flexible_server" "main" {
  name                          = "aap-postgres-${var.environment}"
  resource_group_name           = var.resource_group_name
  location                      = var.location
  version                       = "16"
  sku_name                      = var.postgres_sku
  storage_mb                    = var.postgres_storage_mb
  delegated_subnet_id           = var.postgres_subnet_id
  private_dns_zone_id           = var.postgres_dns_zone_id
  public_network_access_enabled = false
  zone                          = "1"

  administrator_login    = var.postgres_admin_login
  administrator_password = var.postgres_admin_password

  authentication {
    active_directory_auth_enabled = true
    password_auth_enabled         = true
    tenant_id                     = var.tenant_id
  }

  tags = var.required_tags
}

resource "azurerm_postgresql_flexible_server_database" "main" {
  name      = "aap"
  server_id = azurerm_postgresql_flexible_server.main.id
  collation = "en_US.utf8"
  charset   = "UTF8"
}

# Allowlist pgvector extension (uppercase required by Azure)
resource "azurerm_postgresql_flexible_server_configuration" "extensions" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.main.id
  value     = "VECTOR"
}

# NOTE (ISSUE-04): The actual `CREATE EXTENSION IF NOT EXISTS vector;` SQL command
# is NOT run here via local-exec because the PostgreSQL server is VNet-injected with
# public_network_access_enabled = false. GitHub-hosted runners cannot reach it.
#
# Instead, pgvector extension creation is handled in the terraform-apply.yml workflow
# (PLAN-05, task 05.04) which:
#   1. Retrieves the runner's egress IP
#   2. Temporarily adds a firewall rule to the PostgreSQL server
#   3. Runs `CREATE EXTENSION IF NOT EXISTS vector;` via psql
#   4. Removes the firewall rule
#
# For manual bootstrap, run from a VNet-connected machine:
#   PGPASSWORD="..." psql -h <fqdn> -U aap_admin -d aap -c "CREATE EXTENSION IF NOT EXISTS vector;"
```
</action>
<acceptance_criteria>
- `terraform/modules/databases/postgres.tf` contains `resource "azurerm_postgresql_flexible_server" "main"` with `version = "16"`
- Server has `delegated_subnet_id = var.postgres_subnet_id`
- Server has `private_dns_zone_id = var.postgres_dns_zone_id`
- Server has `public_network_access_enabled = false`
- Server has `authentication` block with `active_directory_auth_enabled = true` and `password_auth_enabled = true`
- File contains `resource "azurerm_postgresql_flexible_server_database" "main"` with `name = "aap"`
- File contains `resource "azurerm_postgresql_flexible_server_configuration" "extensions"` with `name = "azure.extensions"` and `value = "VECTOR"`
- File does NOT contain `resource "terraform_data" "pgvector_extension"` or any `local-exec` provisioner **(ISSUE-04 fix)**
- File contains a comment explaining that pgvector extension creation is handled in PLAN-05 workflow
</acceptance_criteria>
</task>

<task id="03.05">
<title>Implement Container Apps environment and ACR (no private endpoint, globally unique ACR name)</title>
<read_first>
- terraform/modules/compute-env/variables.tf (variable interface from Plan 01)
- terraform/modules/compute-env/outputs.tf (output interface from Plan 01)
- terraform/modules/compute-env/main.tf (current placeholder)
- .planning/phases/01-foundation/01-RESEARCH.md (Section 7: Container Apps & ACR)
- .planning/phases/01-foundation/01-RESEARCH.md (Section 14: Q3 — internal_load_balancer_enabled = false)
</read_first>
<action>

> **REVISION (ISSUE-01):** The `azurerm_private_endpoint.acr` resource has been REMOVED from this file.
> It is now created by the dedicated `modules/private-endpoints/` module (task 03.07).

> **REVISION (ISSUE-10):** ACR name now uses `random_string` suffix for global uniqueness.

First, create `terraform/modules/compute-env/versions.tf`:

```hcl
terraform {
  required_providers {
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}
```

Then replace placeholder in `terraform/modules/compute-env/main.tf` with:

```hcl
# Random suffix for globally unique ACR name (ISSUE-10)
resource "random_string" "acr_suffix" {
  length  = 6
  special = false
  upper   = false
}

resource "azurerm_container_app_environment" "main" {
  name                           = "cae-aap-${var.environment}"
  location                       = var.location
  resource_group_name            = var.resource_group_name
  log_analytics_workspace_id     = var.log_analytics_workspace_id
  infrastructure_subnet_id       = var.container_apps_subnet_id
  internal_load_balancer_enabled = false

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
    minimum_count         = 0
    maximum_count         = 0
  }

  tags = var.required_tags
}

resource "azurerm_container_registry" "main" {
  name                          = "aapcr${var.environment}${random_string.acr_suffix.result}"
  resource_group_name           = var.resource_group_name
  location                      = var.location
  sku                           = "Premium"
  admin_enabled                 = false
  public_network_access_enabled = false
  data_endpoint_enabled         = true

  identity {
    type = "SystemAssigned"
  }

  tags = var.required_tags
}

# NOTE: ACR private endpoint is created by modules/private-endpoints (task 03.07),
# NOT in this file. This prevents duplicate PE definitions (ISSUE-01).
```
</action>
<acceptance_criteria>
- `terraform/modules/compute-env/versions.tf` exists and contains `hashicorp/random` provider requirement
- `terraform/modules/compute-env/main.tf` contains `resource "random_string" "acr_suffix"` with `length = 6`, `special = false`, `upper = false` **(ISSUE-10)**
- File contains `resource "azurerm_container_app_environment" "main"` with `internal_load_balancer_enabled = false`
- Container Apps environment has `infrastructure_subnet_id = var.container_apps_subnet_id`
- Container Apps environment has `log_analytics_workspace_id = var.log_analytics_workspace_id`
- Container Apps environment has `workload_profile` block with `workload_profile_type = "Consumption"`
- File contains `resource "azurerm_container_registry" "main"` with name `"aapcr${var.environment}${random_string.acr_suffix.result}"` **(ISSUE-10)**
- ACR has `sku = "Premium"`
- ACR has `admin_enabled = false`
- ACR has `public_network_access_enabled = false`
- ACR has `data_endpoint_enabled = true`
- ACR has `identity { type = "SystemAssigned" }`
- File does NOT contain `resource "azurerm_private_endpoint" "acr"` **(ISSUE-01 fix)**
- All taggable resources have `tags = var.required_tags`
</acceptance_criteria>
</task>

<task id="03.06">
<title>Implement Key Vault module (no private endpoint)</title>
<read_first>
- terraform/modules/keyvault/variables.tf (variable interface from Plan 01)
- terraform/modules/keyvault/outputs.tf (output interface from Plan 01)
- terraform/modules/keyvault/main.tf (current placeholder)
- .planning/phases/01-foundation/01-RESEARCH.md (Section 8: Key Vault)
</read_first>
<action>

> **REVISION (ISSUE-01):** The `azurerm_private_endpoint.keyvault` resource has been REMOVED from this file.
> It is now created by the dedicated `modules/private-endpoints/` module (task 03.07).

Replace placeholder in `terraform/modules/keyvault/main.tf` with:

```hcl
resource "azurerm_key_vault" "main" {
  name                          = "kv-aap-${var.environment}"
  location                      = var.location
  resource_group_name           = var.resource_group_name
  tenant_id                     = var.tenant_id
  sku_name                      = "standard"
  soft_delete_retention_days    = 90
  purge_protection_enabled      = true
  public_network_access_enabled = false
  enable_rbac_authorization     = true

  tags = var.required_tags
}

# NOTE: Key Vault private endpoint is created by modules/private-endpoints (task 03.07),
# NOT in this file. This prevents duplicate PE definitions (ISSUE-01).
```
</action>
<acceptance_criteria>
- `terraform/modules/keyvault/main.tf` contains `resource "azurerm_key_vault" "main"`
- Key Vault has `enable_rbac_authorization = true`
- Key Vault has `purge_protection_enabled = true`
- Key Vault has `soft_delete_retention_days = 90`
- Key Vault has `public_network_access_enabled = false`
- Key Vault has `sku_name = "standard"`
- File does NOT contain `resource "azurerm_private_endpoint" "keyvault"` **(ISSUE-01 fix)**
- All taggable resources have `tags = var.required_tags`
</acceptance_criteria>
</task>

<task id="03.07">
<title>Implement dedicated private-endpoints module</title>
<read_first>
- terraform/modules/private-endpoints/variables.tf (variable interface from Plan 01 task 01.09)
- terraform/modules/private-endpoints/outputs.tf (output interface from Plan 01 task 01.09)
- terraform/modules/private-endpoints/main.tf (current placeholder)
- .planning/phases/01-foundation/01-RESEARCH.md (Section 4: Private Endpoint Subresource Names table)
</read_first>
<action>

> **NEW TASK (ISSUE-01, ISSUE-02):** This is the centralized private-endpoints module that
> replaces the duplicate PE definitions that were previously split across the networking,
> databases, compute-env, and keyvault modules. By centralizing all PEs here, we:
> 1. Eliminate duplicate PE creation that would fail at `terraform apply`
> 2. Break the circular dependency where networking needed resource IDs from modules that depended on networking

Replace placeholder in `terraform/modules/private-endpoints/main.tf` with:

```hcl
# Private Endpoints module — centralized PE creation for all platform services.
#
# This module depends on:
#   - networking module (for subnet_id and DNS zone IDs)
#   - databases module (for cosmos_account_id)
#   - compute-env module (for acr_id)
#   - keyvault module (for keyvault_id)
#   - foundry module (for foundry_account_id)
#
# It must be instantiated AFTER all resource modules in the environment root.
#
# PostgreSQL Flexible Server uses VNet injection (delegated subnet),
# NOT a private endpoint. No PE is created for PostgreSQL.

resource "azurerm_private_endpoint" "cosmos" {
  name                = "pe-cosmos-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  subnet_id           = var.private_endpoint_subnet_id

  private_service_connection {
    name                           = "psc-cosmos-${var.environment}"
    private_connection_resource_id = var.cosmos_account_id
    is_manual_connection           = false
    subresource_names              = ["Sql"]
  }

  private_dns_zone_group {
    name                 = "dns-cosmos"
    private_dns_zone_ids = [var.private_dns_zone_cosmos_id]
  }

  tags = var.required_tags
}

resource "azurerm_private_endpoint" "acr" {
  name                = "pe-acr-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  subnet_id           = var.private_endpoint_subnet_id

  private_service_connection {
    name                           = "psc-acr-${var.environment}"
    private_connection_resource_id = var.acr_id
    is_manual_connection           = false
    subresource_names              = ["registry"]
  }

  private_dns_zone_group {
    name                 = "dns-acr"
    private_dns_zone_ids = [var.private_dns_zone_acr_id]
  }

  tags = var.required_tags
}

resource "azurerm_private_endpoint" "keyvault" {
  name                = "pe-keyvault-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  subnet_id           = var.private_endpoint_subnet_id

  private_service_connection {
    name                           = "psc-keyvault-${var.environment}"
    private_connection_resource_id = var.keyvault_id
    is_manual_connection           = false
    subresource_names              = ["vault"]
  }

  private_dns_zone_group {
    name                 = "dns-keyvault"
    private_dns_zone_ids = [var.private_dns_zone_keyvault_id]
  }

  tags = var.required_tags
}

resource "azurerm_private_endpoint" "foundry" {
  name                = "pe-foundry-${var.environment}"
  location            = var.location
  resource_group_name = var.resource_group_name
  subnet_id           = var.private_endpoint_subnet_id

  private_service_connection {
    name                           = "psc-foundry-${var.environment}"
    private_connection_resource_id = var.foundry_account_id
    is_manual_connection           = false
    subresource_names              = ["account"]
  }

  private_dns_zone_group {
    name                 = "dns-cognitive"
    private_dns_zone_ids = [var.private_dns_zone_cognitive_id]
  }

  tags = var.required_tags
}
```
</action>
<acceptance_criteria>
- `terraform/modules/private-endpoints/main.tf` contains 4 `azurerm_private_endpoint` resources: `cosmos`, `acr`, `keyvault`, `foundry`
- Cosmos PE has `subresource_names = ["Sql"]`
- ACR PE has `subresource_names = ["registry"]`
- Key Vault PE has `subresource_names = ["vault"]`
- Foundry PE has `subresource_names = ["account"]`
- All PEs use `var.private_endpoint_subnet_id` for subnet
- All PEs include a `private_dns_zone_group` block linking to the correct DNS zone variable
- All PEs have `tags = var.required_tags`
- File does NOT contain a private endpoint for PostgreSQL (PostgreSQL uses VNet injection)
- No conditional `count` logic — all PEs are unconditional (resource IDs are always provided by upstream modules)
</acceptance_criteria>
</task>

---

## Verification

After all tasks complete:
1. Every module's `main.tf` (or domain-specific `.tf`) has real resource definitions (no more placeholders)
2. All resource references match the output definitions in each module's `outputs.tf`
3. All resources that support tags have `tags = var.required_tags` (including `azurerm_cognitive_deployment`)
4. Private endpoints are ONLY in `modules/private-endpoints/main.tf` — not duplicated elsewhere
5. PostgreSQL uses VNet injection (no private endpoint)
6. Foundry capability host uses azapi provider
7. No `local-exec` provisioners for pgvector (handled in PLAN-05 workflow)
8. ACR name uses random suffix for global uniqueness

## must_haves

- [ ] Foundry account with `kind = "AIServices"` and `project_management_enabled = true`
- [ ] Foundry project WITHOUT `identity` block (ISSUE-09)
- [ ] `azurerm_cognitive_deployment.gpt4o` has `tags = var.required_tags` (ISSUE-03)
- [ ] Capability host using `azapi_resource` with 30-minute timeouts
- [ ] gpt-4o model deployment with configurable capacity
- [ ] Cosmos DB with conditional serverless/provisioned based on `cosmos_serverless` variable
- [ ] `incidents` container with partition key `/resource_id`
- [ ] `approvals` container with partition key `/thread_id`
- [ ] PostgreSQL v16 with pgvector (`azure.extensions = "VECTOR"`) — NO local-exec provisioner (ISSUE-04)
- [ ] Container Apps environment with workload profiles mode
- [ ] ACR Premium SKU with `admin_enabled = false` and globally unique name via `random_string` (ISSUE-10)
- [ ] Key Vault with RBAC authorization (no access policies)
- [ ] Dedicated `modules/private-endpoints/` with 4 PEs: Cosmos, ACR, Key Vault, Foundry (ISSUE-01)
- [ ] NO private endpoint resources in databases, compute-env, or keyvault modules (ISSUE-01)
