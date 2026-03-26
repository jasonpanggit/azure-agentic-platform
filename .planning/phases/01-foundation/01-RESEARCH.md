# Phase 1: Foundation - Research

**Date:** 2026-03-26
**Objective:** What do I need to know to PLAN this phase well?
**Scope:** Terraform provisioning of all Azure infrastructure for the AAP platform

---

## Table of Contents

1. [Requirement-by-Requirement Analysis](#1-requirement-by-requirement-analysis)
2. [Terraform Module Structure & Environment Strategy](#2-terraform-module-structure--environment-strategy)
3. [Provider Strategy & Resource Mapping](#3-provider-strategy--resource-mapping)
4. [Networking Deep Dive](#4-networking-deep-dive)
5. [Azure AI Foundry Provisioning](#5-azure-ai-foundry-provisioning)
6. [Database Provisioning](#6-database-provisioning)
7. [Container Apps & ACR](#7-container-apps--acr)
8. [Key Vault](#8-key-vault)
9. [State Backend & OIDC Authentication](#9-state-backend--oidc-authentication)
10. [CI/CD Pipeline Design](#10-cicd-pipeline-design)
11. [Tag Enforcement Strategy](#11-tag-enforcement-strategy)
12. [Terraform Outputs for Downstream Phases](#12-terraform-outputs-for-downstream-phases)
13. [Risks & Mitigations](#13-risks--mitigations)
14. [Open Questions & Decisions Needed](#14-open-questions--decisions-needed)
15. [Research Sources](#15-research-sources)

---

## 1. Requirement-by-Requirement Analysis

### INFRA-001: Networking + Remote State

**What to provision:**
- VNet with address space sized for all Phase 1-7 workloads
- Subnets: Container Apps, private endpoints, PostgreSQL (delegated), Key Vault, Foundry
- NSGs per subnet with service-tag-based rules
- Private endpoints for Cosmos DB, PostgreSQL, ACR, Key Vault, Foundry
- Private DNS zones + VNet links for all private endpoint services
- Remote state in Azure Storage with lease-based locking

**Key constraints:**
- Container Apps subnet requires `Microsoft.App/environments` delegation
- PostgreSQL Flexible Server uses VNet injection (delegated subnet to `Microsoft.DBforPostgreSQL/flexibleServers`), not private endpoints
- NSGs are now supported on private endpoint subnets (enable via `private_endpoint_network_policies = "Enabled"` on the subnet)
- All private endpoints need corresponding Private DNS Zones linked to the VNet

### INFRA-002: Azure AI Foundry

**What to provision:**
- Foundry account via `azurerm_cognitive_account` (kind = `"AIServices"`)
- Foundry project via `azurerm_cognitive_account_project`
- gpt-4o model deployment via `azurerm_cognitive_deployment`
- Capability host via `azapi_resource` (required for Hosted Agents in Phase 2)

**Key constraints:**
- The Foundry account requires `project_management_enabled = true`
- `custom_subdomain_name` is required for Foundry endpoint resolution
- Capability host uses `2025-10-01-preview` API version (azapi only)
- Capability host is a **long-running operation** (up to 30 min) - needs extended timeouts
- gpt-4o model deployment must specify `format = "OpenAI"`, `name = "gpt-4o"`, and a valid version
- Region availability for gpt-4o is limited (eastus, eastus2, westus3, swedencentral are common)

**Clarification on INFRA-002 wording:** REQUIREMENTS.md says "using `azapi ~>2.9`" but CLAUDE.md's provider mapping shows the Foundry account, project, and model deployment all use `azurerm`. Only the capability host requires `azapi`. The requirement likely refers to the capability host specifically. We use both providers: `azurerm` for the core Foundry resources and `azapi` for the capability host.

### INFRA-003: Databases

**What to provision:**
- Cosmos DB Serverless account with NoSQL API
- Cosmos DB SQL database with `incidents` and `approvals` containers
- PostgreSQL Flexible Server (GP tier for production)
- pgvector extension enabled on PostgreSQL

**Key constraints:**
- **CRITICAL: Cosmos DB Serverless is single-region only.** The REQUIREMENTS.md says "multi-region" but Azure Cosmos DB Serverless does not support geo-replication. This is a **conflict** that must be resolved:
  - Option A: Use Serverless for dev, Provisioned Autoscale for prod (with multi-region)
  - Option B: Use Serverless everywhere and accept single-region (defer multi-region to a future decision)
  - Option C: Use Provisioned Autoscale everywhere (higher cost but meets multi-region requirement)
  - **Recommended: Option A** - Use Serverless for dev/staging (cost savings), Provisioned with autoscale for prod (multi-region capability). Environment-specific tfvars controls this.
- PostgreSQL pgvector: Must allowlist extension via `azure.extensions = "VECTOR"` (uppercase) server configuration, then `CREATE EXTENSION IF NOT EXISTS vector;` in the database
- Cosmos DB partition keys for `incidents` and `approvals` containers need definition:
  - `incidents`: `/resource_id` (distributes by affected resource, enables efficient per-resource queries)
  - `approvals`: `/thread_id` (colocates all approvals for an incident thread, enables efficient lookup during HITL flow)

### INFRA-004: Container Apps + ACR

**What to provision:**
- Container Apps environment with VNet integration (workload profiles mode)
- Azure Container Registry (Premium SKU for private endpoint support)
- GitHub Actions workflow for pushing images to ACR

**Key constraints:**
- Container Apps workload profiles environment: minimum subnet `/27`, recommended `/23`
- Subnet must be delegated to `Microsoft.App/environments` and be empty
- `internal_load_balancer_enabled = true` for internal-only environments (agent workloads)
- ACR Premium SKU required for private endpoint and VNet support
- ACR needs `admin_enabled = false` (use managed identity for auth, not admin credentials)
- Phase 1 only provisions the environment - no actual Container Apps are deployed until Phase 2

### INFRA-008: Environment Isolation + CI

**What to provision:**
- Directory-per-environment: `envs/dev/`, `envs/staging/`, `envs/prod/`
- Per-environment tfvars files
- Per-environment state storage accounts
- Two GitHub Actions workflows: `terraform-plan.yml` (PR) and `terraform-apply.yml` (merge to main)
- Required tags lint in plan workflow

**Key constraints (from D-03 through D-08 decisions):**
- NOT using Terraform workspaces - using directory-per-environment approach
- Each environment has its own `backend.tf` pointing to a separate storage account
- OIDC auth (`use_oidc = true`) for both backend and provider - no storage access keys
- Separate workflows for plan (PR) and apply (merge) - not a single combined workflow
- Tag lint must cause plan job to fail if any resource is untagged

---

## 2. Terraform Module Structure & Environment Strategy

### Directory Layout (Decision D-01, D-02, D-03, D-04)

```
terraform/
|-- modules/                    # Shared reusable modules
|   |-- networking/
|   |   |-- main.tf             # VNet, subnets, NSGs, private DNS zones
|   |   |-- private-endpoints.tf # PE resources (extracted for clarity)
|   |   |-- variables.tf
|   |   +-- outputs.tf          # subnet_ids, private_endpoint_ips, dns_zone_ids
|   |
|   |-- foundry/
|   |   |-- main.tf             # AI Services account, project, model deployment
|   |   |-- capability-host.tf  # azapi capability host (separated for clarity)
|   |   |-- variables.tf
|   |   +-- outputs.tf          # foundry_endpoint, project_id, deployment_name
|   |
|   |-- databases/
|   |   |-- cosmos.tf           # Cosmos DB account, database, containers
|   |   |-- postgres.tf         # PostgreSQL Flexible Server, pgvector config
|   |   |-- variables.tf
|   |   +-- outputs.tf          # cosmos_endpoint, cosmos_id, postgres_fqdn
|   |
|   |-- compute-env/
|   |   |-- main.tf             # Container Apps environment, ACR
|   |   |-- variables.tf
|   |   +-- outputs.tf          # cae_id, cae_default_domain, acr_login_server
|   |
|   |-- keyvault/
|   |   |-- main.tf             # Key Vault, access policies
|   |   |-- variables.tf
|   |   +-- outputs.tf          # keyvault_id, keyvault_uri
|   |
|   +-- monitoring/
|       |-- main.tf             # Log Analytics workspace, App Insights
|       |-- variables.tf
|       +-- outputs.tf          # workspace_id, app_insights_connection_string
|
+-- envs/
    |-- dev/
    |   |-- main.tf             # Module composition with dev variables
    |   |-- variables.tf        # Variable declarations
    |   |-- terraform.tfvars    # Dev-specific values
    |   |-- backend.tf          # azurerm backend -> staaaptfstatedev
    |   |-- providers.tf        # Provider config with OIDC
    |   +-- outputs.tf          # Re-export module outputs
    |
    |-- staging/
    |   |-- main.tf
    |   |-- variables.tf
    |   |-- terraform.tfvars
    |   |-- backend.tf          # azurerm backend -> staaaptfstatestg
    |   |-- providers.tf
    |   +-- outputs.tf
    |
    +-- prod/
        |-- main.tf
        |-- variables.tf
        |-- terraform.tfvars
        |-- backend.tf          # azurerm backend -> staaaptfstateprod
        |-- providers.tf
        +-- outputs.tf
```

### Design Rationale

- **Per-domain modules** (not per-resource): Each module owns a coherent domain (networking, foundry, databases). This keeps module count manageable while maintaining separation of concerns.
- **Databases combined**: Cosmos DB and PostgreSQL share a module because they share the same networking dependencies (private endpoint subnet) and are co-provisioned. Internal files separate them for readability.
- **Monitoring separated**: Log Analytics + App Insights are a dependency for Container Apps environment (`log_analytics_workspace_id`), so they must be a separate module to avoid circular dependencies.
- **Environment dirs call shared modules**: Each `envs/<env>/main.tf` composes modules with env-specific variable overrides. No Terraform code is duplicated between environments.

### Module Dependency Order

```
monitoring (no deps)
    |
    v
networking (no deps)
    |
    +---> databases (needs: subnet_ids, private_dns_zone_ids)
    +---> foundry (needs: subnet_ids - for future PE, monitoring outputs)
    +---> keyvault (needs: subnet_ids, private_dns_zone_ids)
    +---> compute-env (needs: subnet_ids, monitoring.workspace_id)
```

All modules except `monitoring` and `networking` depend on networking outputs. No circular dependencies exist.

---

## 3. Provider Strategy & Resource Mapping

### Provider Versions (Pinned)

```hcl
terraform {
  required_version = ">= 1.9.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.65.0"
    }
    azapi = {
      source  = "azure/azapi"
      version = "~> 2.9.0"
    }
  }
}
```

### Resource-to-Provider Map (Phase 1 only)

| Resource | Provider | Terraform Type |
|---|---|---|
| Resource Group | azurerm | `azurerm_resource_group` |
| VNet | azurerm | `azurerm_virtual_network` |
| Subnets | azurerm | `azurerm_subnet` |
| NSGs | azurerm | `azurerm_network_security_group` |
| NSG-Subnet Associations | azurerm | `azurerm_subnet_network_security_group_association` |
| Private Endpoints | azurerm | `azurerm_private_endpoint` |
| Private DNS Zones | azurerm | `azurerm_private_dns_zone` |
| DNS Zone VNet Links | azurerm | `azurerm_private_dns_zone_virtual_network_link` |
| Log Analytics Workspace | azurerm | `azurerm_log_analytics_workspace` |
| App Insights | azurerm | `azurerm_application_insights` |
| Foundry Account | azurerm | `azurerm_cognitive_account` (kind = "AIServices") |
| Foundry Project | azurerm | `azurerm_cognitive_account_project` |
| gpt-4o Deployment | azurerm | `azurerm_cognitive_deployment` |
| **Capability Host** | **azapi** | `azapi_resource` (CognitiveServices/accounts/capabilityHosts) |
| Cosmos DB Account | azurerm | `azurerm_cosmosdb_account` |
| Cosmos DB Database | azurerm | `azurerm_cosmosdb_sql_database` |
| Cosmos DB Containers | azurerm | `azurerm_cosmosdb_sql_container` |
| PostgreSQL Flexible Server | azurerm | `azurerm_postgresql_flexible_server` |
| PostgreSQL DB | azurerm | `azurerm_postgresql_flexible_server_database` |
| PostgreSQL Config (pgvector) | azurerm | `azurerm_postgresql_flexible_server_configuration` |
| Container Apps Environment | azurerm | `azurerm_container_app_environment` |
| Container Registry | azurerm | `azurerm_container_registry` |
| Key Vault | azurerm | `azurerm_key_vault` |
| Storage Account (TF state) | azurerm | `azurerm_storage_account` (bootstrapped separately) |

**Only 1 resource type requires azapi in Phase 1**: the Foundry capability host.

---

## 4. Networking Deep Dive

### VNet Address Space Design

The VNet must accommodate all Phase 1-7 workloads. Plan generously - expanding VNet CIDR later is possible but creates operational complexity.

**Recommended: `10.0.0.0/16`** (65,536 addresses)

### Subnet Plan

| Subnet | CIDR | Purpose | Delegation | NSG |
|---|---|---|---|---|
| `snet-container-apps` | `10.0.0.0/23` | Container Apps environment | `Microsoft.App/environments` | Yes (limited) |
| `snet-private-endpoints` | `10.0.2.0/24` | All private endpoints (Cosmos, ACR, KV, Foundry) | None | Yes |
| `snet-postgres` | `10.0.3.0/24` | PostgreSQL Flexible Server (VNet injection) | `Microsoft.DBforPostgreSQL/flexibleServers` | Yes |
| `snet-foundry` | `10.0.4.0/24` | Reserved for Foundry PE when GA | None | Yes |
| `snet-reserved-1` | `10.0.5.0/24` | Reserved for Phase 4+ (Event Hub, Fabric) | None | No |
| `snet-reserved-2` | `10.0.6.0/24` | Reserved for future expansion | None | No |

**Why /23 for Container Apps:** Workload profiles mode allows /27 minimum, but /23 gives room for scaling to dozens of Container Apps (agents + API gateway + web frontend + Teams bot + Arc MCP server) without IP exhaustion.

**Why dedicated snet-postgres:** PostgreSQL Flexible Server VNet injection requires a dedicated delegated subnet. It cannot share with private endpoints or Container Apps.

### Private DNS Zones Required

| Service | DNS Zone Name |
|---|---|
| Cosmos DB (SQL API) | `privatelink.documents.azure.com` |
| PostgreSQL Flexible | `privatelink.postgres.database.azure.com` |
| Container Registry | `privatelink.azurecr.io` |
| Key Vault | `privatelink.vaultcore.azure.net` |
| Foundry (AI Services) | `privatelink.cognitiveservices.azure.com` |
| App Insights (future) | `privatelink.monitor.azure.com` |

Each zone needs a `azurerm_private_dns_zone_virtual_network_link` to the VNet.

### NSG Strategy

- **Container Apps subnet**: Minimal NSG rules. Container Apps manages its own internal networking. Allow outbound to Azure services (service tags). Restrict inbound to VNet only.
- **Private endpoints subnet**: Allow inbound from Container Apps subnet (TCP 443, 5432, etc.). Deny all other inbound.
- **PostgreSQL subnet**: Allow inbound TCP 5432 from Container Apps subnet only. Deny all other inbound.
- Use **service tags** (`AzureCloud`, `AzureCosmosDB`, `Sql`, `AzureContainerRegistry`, `AzureKeyVault`) instead of hardcoded IPs.

### Private Endpoint Subresource Names

| Service | `subresource_names` |
|---|---|
| Cosmos DB (SQL API) | `["Sql"]` |
| Container Registry | `["registry"]` |
| Key Vault | `["vault"]` |
| Foundry (AI Services) | `["account"]` |

**Note:** PostgreSQL Flexible Server uses VNet injection (delegated subnet), NOT a private endpoint. The `delegated_subnet_id` and `private_dns_zone_id` are set directly on the server resource.

---

## 5. Azure AI Foundry Provisioning

### Resource Chain

```
azurerm_cognitive_account (kind = "AIServices")
    |
    +---> azurerm_cognitive_account_project
    |         |
    |         +---> azurerm_cognitive_deployment (gpt-4o)
    |
    +---> azapi_resource (capabilityHost)  [Phase 1 provision, Phase 2 uses]
```

### Key Configuration Details

**Foundry Account:**
```hcl
resource "azurerm_cognitive_account" "foundry" {
  name                       = "aap-foundry-${var.environment}"
  location                   = var.location
  resource_group_name        = var.resource_group_name
  kind                       = "AIServices"
  sku_name                   = "S0"
  custom_subdomain_name      = "aap-foundry-${var.environment}"
  project_management_enabled = true

  identity {
    type = "SystemAssigned"
  }

  tags = var.required_tags
}
```

**Critical settings:**
- `kind = "AIServices"` (not "OpenAI" - AIServices is the unified multi-model resource)
- `project_management_enabled = true` (required for creating projects)
- `custom_subdomain_name` is required (must be globally unique)
- System-assigned identity is needed for RBAC

**Model Deployment:**
```hcl
resource "azurerm_cognitive_deployment" "gpt4o" {
  name                 = "gpt-4o"
  cognitive_account_id = azurerm_cognitive_account.foundry.id

  model {
    format  = "OpenAI"
    name    = "gpt-4o"
    version = "2024-11-20"  # Latest stable at time of deployment
  }

  sku {
    name     = "Standard"
    capacity = 10  # 10K TPM - adjust per environment
  }
}
```

**Capability Host (azapi):**
```hcl
resource "azapi_resource" "capability_host" {
  type      = "Microsoft.CognitiveServices/accounts/capabilityHosts@2025-10-01-preview"
  name      = "accountcaphost"
  parent_id = azurerm_cognitive_account.foundry.id

  body = {
    properties = {
      capabilityHostKind              = "Agents"
      enablePublicHostingEnvironment  = true  # Required during Preview (no private networking)
    }
  }

  timeouts {
    create = "30m"
    delete = "30m"
  }
}
```

**Known issues:**
- Capability host is a long-running operation - needs 30-minute timeouts
- May show perpetual drift on subsequent `terraform plan` - may need `lifecycle { ignore_changes }` for specific properties
- `enablePublicHostingEnvironment = true` is required during Preview (PITFALLS.md Section 2: no private networking)

### Region Selection

gpt-4o availability and Foundry features are region-dependent. Recommended primary regions:
- **eastus2** (broad model availability, Foundry GA features)
- **swedencentral** (EU data residency if needed)

The environment-specific tfvars should control region selection.

---

## 6. Database Provisioning

### Cosmos DB

**Account-level:**
```hcl
resource "azurerm_cosmosdb_account" "main" {
  name                      = "aap-cosmos-${var.environment}"
  location                  = var.location
  resource_group_name       = var.resource_group_name
  offer_type                = "Standard"
  kind                      = "GlobalDocumentDB"
  public_network_access_enabled = false  # PE only

  capabilities {
    name = "EnableServerless"  # Dev/staging only - see env strategy below
  }

  consistency_policy {
    consistency_level = "Session"  # Good balance for agent session state
  }

  geo_location {
    location          = var.location
    failover_priority = 0
  }

  tags = var.required_tags
}
```

**Container design:**

| Container | Partition Key | Rationale |
|---|---|---|
| `incidents` | `/resource_id` | Distributes by affected resource; efficient per-resource queries; avoids hot partition on high-volume resources |
| `approvals` | `/thread_id` | Colocates all approvals for an incident thread; efficient lookup during HITL approval flow |

```hcl
resource "azurerm_cosmosdb_sql_container" "incidents" {
  name                  = "incidents"
  resource_group_name   = var.resource_group_name
  account_name          = azurerm_cosmosdb_account.main.name
  database_name         = azurerm_cosmosdb_sql_database.main.name
  partition_key_paths   = ["/resource_id"]
  partition_key_version = 2  # Large partition key support

  indexing_policy {
    indexing_mode = "consistent"
    included_path { path = "/*" }
    excluded_path { path = "/raw_alert/*" }  # Exclude large nested objects
  }
}
```

**Serverless vs. Provisioned - Environment Strategy:**

| Environment | Capacity Mode | Multi-Region | Rationale |
|---|---|---|---|
| dev | Serverless | No (single region) | Cost savings, low traffic |
| staging | Serverless | No (single region) | Cost savings, mirrors dev |
| prod | Provisioned (Autoscale) | Yes (2 regions) | Multi-region HA, SLA requirements |

This is controlled via a `cosmos_serverless` boolean variable in tfvars:
```hcl
# dev.tfvars
cosmos_serverless = true

# prod.tfvars
cosmos_serverless = false
cosmos_secondary_location = "westus2"
cosmos_max_throughput = 4000  # Autoscale max RU/s
```

### PostgreSQL Flexible Server

```hcl
resource "azurerm_postgresql_flexible_server" "main" {
  name                          = "aap-postgres-${var.environment}"
  resource_group_name           = var.resource_group_name
  location                      = var.location
  version                       = "16"
  sku_name                      = var.postgres_sku  # "B_Standard_B1ms" (dev) / "GP_Standard_D4s_v3" (prod)
  storage_mb                    = var.postgres_storage_mb
  delegated_subnet_id           = var.postgres_subnet_id
  private_dns_zone_id           = var.postgres_dns_zone_id
  public_network_access_enabled = false
  zone                          = "1"

  authentication {
    active_directory_auth_enabled = true
    password_auth_enabled         = true  # Needed for pgvector extension setup
    tenant_id                     = var.tenant_id
  }

  tags = var.required_tags
}
```

**pgvector Extension Setup (3-step process):**

1. **Allowlist the extension** (Terraform-managed):
```hcl
resource "azurerm_postgresql_flexible_server_configuration" "extensions" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.main.id
  value     = "VECTOR"  # Uppercase required
}
```

2. **Create the database** (Terraform-managed):
```hcl
resource "azurerm_postgresql_flexible_server_database" "main" {
  name      = "aap"
  server_id = azurerm_postgresql_flexible_server.main.id
  collation = "en_US.utf8"
  charset   = "utf8"
}
```

3. **Enable the extension** (post-provisioning script):
```hcl
resource "null_resource" "pgvector_extension" {
  depends_on = [
    azurerm_postgresql_flexible_server_configuration.extensions,
    azurerm_postgresql_flexible_server_database.main,
  ]

  provisioner "local-exec" {
    command = <<-EOT
      PGPASSWORD="${var.postgres_admin_password}" psql \
        -h ${azurerm_postgresql_flexible_server.main.fqdn} \
        -U ${var.postgres_admin_login} \
        -d aap \
        -c "CREATE EXTENSION IF NOT EXISTS vector;"
    EOT
  }

  triggers = {
    server_id = azurerm_postgresql_flexible_server.main.id
  }
}
```

**Note:** The `null_resource` approach requires `psql` available in the CI runner. An alternative is the `cyrilgdn/postgresql` Terraform provider for a pure-Terraform solution. Both approaches should be considered during implementation.

**Pitfall:** The `local-exec` provisioner runs from the CI runner, which needs network access to the PostgreSQL server. Since the server is VNet-injected with `public_network_access_enabled = false`, the CI runner must either:
- Use a self-hosted runner in the VNet
- Temporarily enable public access during provisioning with a firewall rule for the runner's IP
- Use the `cyrilgdn/postgresql` provider with a VPN/bastion tunnel

This is a **critical implementation detail** that affects CI pipeline design.

---

## 7. Container Apps & ACR

### Container Apps Environment

```hcl
resource "azurerm_container_app_environment" "main" {
  name                           = "cae-aap-${var.environment}"
  location                       = var.location
  resource_group_name            = var.resource_group_name
  log_analytics_workspace_id     = var.log_analytics_workspace_id
  infrastructure_subnet_id       = var.container_apps_subnet_id
  internal_load_balancer_enabled = true  # Internal only - agents don't need public ingress

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
    minimum_count         = 0
    maximum_count         = 0
  }

  tags = var.required_tags
}
```

**Key decisions:**
- `internal_load_balancer_enabled = true`: Agent workloads are internal-only. The web frontend (Phase 5) will need external access but can use a separate Container App with external ingress.
- Workload profiles mode (not legacy Consumption-only): More flexible, smaller subnet requirement, and is the recommended path going forward.
- Phase 1 provisions only the environment - no Container Apps are deployed yet.

### Azure Container Registry

```hcl
resource "azurerm_container_registry" "main" {
  name                          = "aapcr${var.environment}"  # alphanumeric only, globally unique
  resource_group_name           = var.resource_group_name
  location                      = var.location
  sku                           = "Premium"  # Required for PE and VNet support
  admin_enabled                 = false       # Use managed identity, not admin creds
  public_network_access_enabled = false       # PE only
  data_endpoint_enabled         = true        # Recommended for PE scenarios

  identity {
    type = "SystemAssigned"
  }

  tags = var.required_tags
}
```

**GitHub Actions ACR Push (Phase 1 delivers the workflow, Phase 2 uses it):**

The CI workflow for pushing images to ACR uses OIDC/workload identity federation:
- GitHub Actions authenticates to Azure via OIDC (same identity federation as Terraform)
- Uses `az acr login` with the service principal
- The workflow template is created in Phase 1 even though images aren't pushed until Phase 2

---

## 8. Key Vault

### Provisioning

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
  enable_rbac_authorization     = true  # Use RBAC, not access policies

  tags = var.required_tags
}
```

**Phase 1 scope:** Provision the vault only. Seeding with application secrets (connection strings, API keys) is deferred to Phase 2 per D-02 ("Claude's Discretion" in 01-CONTEXT.md).

**RBAC over access policies:** Using `enable_rbac_authorization = true` aligns with the platform's managed-identity-first approach. No access policies to manage.

---

## 9. State Backend & OIDC Authentication

### State Storage Accounts (Pre-provisioned)

State storage accounts must exist BEFORE `terraform init` can run. They are **bootstrapped separately** (manually or via a one-time script) - they cannot be managed by the same Terraform configuration that uses them as a backend.

**Naming convention (Decision D-05):**

| Environment | Storage Account Name | Container |
|---|---|---|
| dev | `staaaptfstatedev` | `tfstate` |
| staging | `staaaptfstatestg` | `tfstate` |
| prod | `staaaptfstateprod` | `tfstate` |

**Bootstrap script** (one-time, run manually):
```bash
#!/bin/bash
for env in dev stg prod; do
  az storage account create \
    --name "staaaptfstate${env}" \
    --resource-group "rg-aap-tfstate-${env}" \
    --location eastus2 \
    --sku Standard_LRS \
    --allow-blob-public-access false \
    --min-tls-version TLS1_2

  az storage container create \
    --name tfstate \
    --account-name "staaaptfstate${env}"
done
```

**State storage security:**
- `allow_blob_public_access = false`
- Storage account access keys disabled (Entra auth only)
- The GitHub Actions service principal needs `Storage Blob Data Contributor` role on each container

### Backend Configuration (per environment)

```hcl
# envs/dev/backend.tf
terraform {
  backend "azurerm" {
    resource_group_name  = "rg-aap-tfstate-dev"
    storage_account_name = "staaaptfstatedev"
    container_name       = "tfstate"
    key                  = "foundation.tfstate"
    use_oidc             = true
  }
}
```

### OIDC / Workload Identity Federation (Decision D-06)

**Azure Setup:**
1. App Registration in Entra ID for GitHub Actions
2. Federated credentials configured:
   - Subject: `repo:<org>/azure-agentic-platform:ref:refs/heads/main` (for apply)
   - Subject: `repo:<org>/azure-agentic-platform:pull_request` (for plan on PRs)
   - Subject: `repo:<org>/azure-agentic-platform:environment:dev` (if using GH environments)
3. RBAC: `Contributor` on all managed resource groups + `Storage Blob Data Contributor` on state storage

**Provider Configuration:**
```hcl
# envs/dev/providers.tf
provider "azurerm" {
  features {}
  use_oidc        = true
  subscription_id = var.subscription_id
}

provider "azapi" {
  use_oidc = true
}
```

**GitHub Actions secrets (repository level):**
- `AZURE_CLIENT_ID` - App Registration client ID
- `AZURE_SUBSCRIPTION_ID` - Target subscription
- `AZURE_TENANT_ID` - Entra tenant ID
- No `AZURE_CLIENT_SECRET` - that's the whole point of OIDC

---

## 10. CI/CD Pipeline Design

### Workflow 1: `terraform-plan.yml` (Decision D-07)

**Trigger:** Pull request targeting `main`
**Purpose:** Run `terraform plan` and post output as PR comment; fail if tag lint fails

```yaml
name: Terraform Plan
on:
  pull_request:
    branches: [main]
    paths:
      - 'terraform/**'

permissions:
  id-token: write    # OIDC
  contents: read
  pull-requests: write  # Post plan as PR comment

jobs:
  plan:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        environment: [dev, staging, prod]
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
      - name: Azure Login (OIDC)
        uses: azure/login@v2
        with:
          client-id: ${{ secrets.AZURE_CLIENT_ID }}
          tenant-id: ${{ secrets.AZURE_TENANT_ID }}
          subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
      - name: Terraform Init
        working-directory: terraform/envs/${{ matrix.environment }}
        run: terraform init
      - name: Terraform Plan
        working-directory: terraform/envs/${{ matrix.environment }}
        run: terraform plan -no-color -out=tfplan
      - name: Tag Lint Check
        # Custom step - see Section 11
      - name: Post Plan to PR
        # Uses github-script or terraform-plan-comment action
```

### Workflow 2: `terraform-apply.yml` (Decision D-07)

**Trigger:** Push to `main` (after PR merge)
**Purpose:** Run `terraform apply -auto-approve` for the target environment

```yaml
name: Terraform Apply
on:
  push:
    branches: [main]
    paths:
      - 'terraform/**'

permissions:
  id-token: write
  contents: read

jobs:
  apply:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        environment: [dev]  # Start with dev; staging/prod gated by GH environments
    environment: ${{ matrix.environment }}  # GitHub environment protection rules
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
      - name: Azure Login (OIDC)
        # Same as plan workflow
      - name: Terraform Init & Apply
        working-directory: terraform/envs/${{ matrix.environment }}
        run: |
          terraform init
          terraform apply -auto-approve
```

### Environment Promotion Strategy

- **dev**: Auto-applies on merge to main (no approval gate)
- **staging**: Auto-applies on merge, gated by GitHub environment protection rules (optional reviewer)
- **prod**: Requires manual approval via GitHub environment protection rules

---

## 11. Tag Enforcement Strategy

### Required Tags (Decision D-08)

All resources must carry:
```hcl
tags = {
  environment = var.environment   # "dev", "staging", "prod"
  managed-by  = "terraform"
  project     = "aap"
}
```

### Enforcement Approaches

**Option A: Common tags variable + validation (Recommended for Phase 1)**

```hcl
# modules/common/tags.tf (or in each environment's variables.tf)
variable "required_tags" {
  type = map(string)
  validation {
    condition = alltrue([
      contains(keys(var.required_tags), "environment"),
      contains(keys(var.required_tags), "managed-by"),
      contains(keys(var.required_tags), "project"),
      var.required_tags["managed-by"] == "terraform",
      var.required_tags["project"] == "aap",
    ])
    error_message = "Tags must include 'environment', 'managed-by: terraform', and 'project: aap'."
  }
}
```

Pass `required_tags` to every module. `terraform plan` fails if tags are missing or incorrect.

**Option B: OPA/Conftest post-plan validation**

Export `terraform plan -out=tfplan && terraform show -json tfplan > tfplan.json`, then run Conftest/OPA against it. More powerful (can check individual resources) but more complex to set up.

**Option C: tflint custom rules**

Use tflint with a custom rule plugin. Good for static analysis but doesn't catch all dynamic cases.

**Recommendation:** Use **Option A** (variable validation) as the primary mechanism - it's native Terraform, zero additional tooling, and fails fast during `terraform plan`. Add **Option B** (Conftest) in Phase 7 hardening for deeper resource-level tag auditing.

---

## 12. Terraform Outputs for Downstream Phases

Phase 1 outputs are critical - they're consumed by Phase 2 (agent identities, Container Apps) and all subsequent phases. These outputs must be carefully designed.

### Required Outputs by Downstream Phase

| Output | Type | Consumer |
|---|---|---|
| `resource_group_name` | string | Phase 2+ (all resources) |
| `resource_group_id` | string | Phase 2 (RBAC assignments) |
| `vnet_id` | string | Phase 2+ (additional subnets if needed) |
| `container_apps_subnet_id` | string | Phase 2 (Container App deployments) |
| `container_apps_environment_id` | string | Phase 2 (Container App deployments) |
| `container_apps_environment_default_domain` | string | Phase 2 (internal DNS for service discovery) |
| `acr_login_server` | string | Phase 2 (image push/pull) |
| `acr_id` | string | Phase 2 (RBAC: AcrPull for agent identities) |
| `foundry_account_id` | string | Phase 2 (agent registration) |
| `foundry_account_endpoint` | string | Phase 2 (agent client configuration) |
| `foundry_project_id` | string | Phase 2 (agent client configuration) |
| `foundry_model_deployment_name` | string | Phase 2 (agent model reference) |
| `cosmos_account_id` | string | Phase 2 (RBAC assignments) |
| `cosmos_endpoint` | string | Phase 2 (agent Cosmos client configuration) |
| `cosmos_database_name` | string | Phase 2 (agent data access) |
| `postgres_server_id` | string | Phase 2 (RBAC assignments) |
| `postgres_fqdn` | string | Phase 2 (connection string construction) |
| `keyvault_id` | string | Phase 2 (secret storage, RBAC) |
| `keyvault_uri` | string | Phase 2 (agent Key Vault client configuration) |
| `log_analytics_workspace_id` | string | Phase 2 (diagnostic settings) |
| `app_insights_connection_string` | string | Phase 2 (agent telemetry configuration) |
| `app_insights_instrumentation_key` | string | Phase 2 (legacy instrumentation if needed) |

### Cross-Environment Output Access

Since environments use separate state files, Phase 2 in the `dev` environment reads Phase 1 `dev` outputs via `terraform_remote_state`:

```hcl
data "terraform_remote_state" "foundation" {
  backend = "azurerm"
  config = {
    resource_group_name  = "rg-aap-tfstate-dev"
    storage_account_name = "staaaptfstatedev"
    container_name       = "tfstate"
    key                  = "foundation.tfstate"
    use_oidc             = true
  }
}
```

---

## 13. Risks & Mitigations

### Risk 1: Cosmos DB Serverless vs. Multi-Region Conflict

**Risk:** INFRA-003 says "multi-region" but Cosmos DB Serverless is single-region only.
**Impact:** High - architectural decision affects cost, availability, and schema.
**Mitigation:** Use environment-conditional provisioning (Serverless for dev/staging, Provisioned Autoscale for prod). Document this as a conscious deviation with rationale in the Terraform code.

### Risk 2: PostgreSQL pgvector Extension in Private Network

**Risk:** The `null_resource` that runs `psql CREATE EXTENSION` needs network access to the private PostgreSQL server. CI runners (GitHub-hosted) cannot reach VNet-injected servers.
**Impact:** High - blocks pgvector setup in CI.
**Mitigation options:**
1. Use the `cyrilgdn/postgresql` Terraform provider instead of `null_resource` (still needs network access)
2. Bootstrap pgvector extension setup via an Azure CLI command that creates a temporary firewall rule, runs the SQL, then removes it
3. Use a self-hosted runner in the VNet
4. Create a separate "bootstrap" job that runs from an Azure VM/Container Instance in the VNet

**Recommended:** Option 2 (temporary firewall rule) for initial setup. Move to Option 3 (self-hosted runner) for production CI.

### Risk 3: Capability Host Long-Running Operation

**Risk:** `azapi_resource` for capability host can take 30+ minutes and may show drift.
**Impact:** Medium - slows CI, may cause flaky plans.
**Mitigation:** Extended timeouts (`create = "30m"`), `lifecycle { ignore_changes }` for known drift-prone properties, and separate the capability host into its own targeted apply if needed.

### Risk 4: State Bootstrap Chicken-and-Egg

**Risk:** State storage accounts must exist before `terraform init` but can't be managed by the same Terraform.
**Impact:** Medium - requires manual one-time bootstrap.
**Mitigation:** Create a `scripts/bootstrap-state.sh` script that provisions the storage accounts, containers, and RBAC assignments. Document clearly in the repo README. This script runs exactly once per environment.

### Risk 5: Foundry Region + Model Availability

**Risk:** Not all Azure regions support gpt-4o or Foundry features.
**Impact:** Medium - wrong region choice blocks Phase 2.
**Mitigation:** Verify gpt-4o availability in the target region before provisioning. Use `eastus2` as the default (broad availability). Make region a variable in tfvars.

### Risk 6: OIDC Federated Credential Subject Mismatch

**Risk:** GitHub Actions OIDC tokens include claims (repo, branch, environment) that must exactly match the federated credential configuration. Mismatches cause silent auth failures.
**Impact:** Medium - blocks all CI.
**Mitigation:** Test OIDC auth in isolation before building the full pipeline. Configure separate federated credentials for PR (pull_request filter) and merge (ref:refs/heads/main filter).

---

## 14. Open Questions & Decisions Needed

### Q1: Cosmos DB Serverless vs. Multi-Region (BLOCKING)

INFRA-003 says "multi-region" but Serverless doesn't support it. **Proposed resolution:** Environment-conditional (Serverless for dev/staging, Provisioned Autoscale for prod). Needs user confirmation.

### Q2: PostgreSQL Admin Authentication Strategy

Should PostgreSQL use password auth, Entra-only auth, or both?
- **Password auth:** Simpler for initial setup (psql extension creation), but secrets to manage.
- **Entra auth:** Aligns with managed-identity-first, but more complex for extension setup.
- **Proposed:** Both enabled in Phase 1 (password for bootstrap, Entra for application access). Password auth can be disabled after pgvector extension is created.

### Q3: Container Apps Internal vs. Mixed

Should the Container Apps environment be `internal_load_balancer_enabled = true` (all internal) or `false` (allows external ingress per-app)?
- Phase 1 only provisions the environment - no apps yet.
- Phase 5 needs external ingress for the web frontend.
- **Proposed:** Set `internal_load_balancer_enabled = false` to allow per-app ingress control. Individual Container Apps (Phase 2+) control their own ingress settings (internal vs. external).

### Q4: Monitoring Module Scope

Should Phase 1 include Event Hub namespace + hub (used by Phase 4 Detection Plane) or only Log Analytics + App Insights?
- Event Hub is required by Phase 4 but provisioning it in Phase 1 adds value (networking integration).
- **Proposed:** Include Event Hub in Phase 1 monitoring module. It's a networking-adjacent resource and having it ready simplifies Phase 4.

### Q5: VNet Address Space

Is `10.0.0.0/16` acceptable as the VNet CIDR, or does the user have existing network constraints?

---

## 15. Research Sources

### Primary Sources (Project-Internal)
- `CLAUDE.md` - Technology Stack, Provider Strategy, Resource Mapping tables
- `.planning/REQUIREMENTS.md` - INFRA-001 through INFRA-004, INFRA-008 definitions
- `.planning/ROADMAP.md` - Phase 1 success criteria (6 items)
- `.planning/phases/01-foundation/01-CONTEXT.md` - User decisions D-01 through D-08
- `.planning/research/ARCHITECTURE.md` - Terraform module structure, build order
- `.planning/research/STACK.md` - Provider versions, resource patterns, Foundry Terraform code
- `.planning/research/PITFALLS.md` - Terraform pitfalls (Sections 2, 7, 9)

### External References (Verified Patterns)
- Terraform AzureRM Provider Registry - `azurerm_container_app_environment`, `azurerm_cosmosdb_account`, `azurerm_postgresql_flexible_server`, `azurerm_cognitive_account` resources
- Terraform AzAPI Provider Registry - `azapi_resource` for capability hosts
- Azure Private Link DNS zone names reference
- Azure Container Apps networking subnet requirements
- Azure Cosmos DB Serverless limitations (single-region only)
- PostgreSQL Flexible Server pgvector extension allowlist pattern
- GitHub Actions OIDC + Workload Identity Federation for Terraform
- OPA/Conftest and native Terraform validation for tag enforcement

---

*Phase: 01-foundation*
*Research completed: 2026-03-26*
