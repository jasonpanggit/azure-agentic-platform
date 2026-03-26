# Plan 04: Environment Composition (dev/staging/prod)

```yaml
wave: 4
depends_on:
  - PLAN-01-scaffold-and-bootstrap
  - PLAN-02-networking
  - PLAN-03-resource-modules
files_modified:
  - terraform/envs/dev/main.tf
  - terraform/envs/dev/variables.tf
  - terraform/envs/dev/terraform.tfvars
  - terraform/envs/dev/backend.tf
  - terraform/envs/dev/providers.tf
  - terraform/envs/dev/outputs.tf
  - terraform/envs/staging/main.tf
  - terraform/envs/staging/variables.tf
  - terraform/envs/staging/terraform.tfvars
  - terraform/envs/staging/backend.tf
  - terraform/envs/staging/providers.tf
  - terraform/envs/staging/outputs.tf
  - terraform/envs/prod/main.tf
  - terraform/envs/prod/variables.tf
  - terraform/envs/prod/terraform.tfvars
  - terraform/envs/prod/backend.tf
  - terraform/envs/prod/providers.tf
  - terraform/envs/prod/outputs.tf
autonomous: true
requirements:
  - INFRA-001
  - INFRA-002
  - INFRA-003
  - INFRA-004
  - INFRA-008
```

## Goal

Create the 3 environment root directories (dev, staging, prod) that compose all shared modules with environment-specific overrides. Each environment has its own backend, providers, variables, tfvars, and outputs. After this wave, `terraform init && terraform plan` succeeds in each environment directory.

> **REVISION (ISSUE-01, ISSUE-02):** The networking module no longer receives resource IDs from
> downstream modules. Private endpoints are created by `module.private_endpoints` which is
> instantiated AFTER all resource modules. This eliminates the circular dependency.

> **REVISION (ISSUE-10):** The `random` provider is required for the ACR name suffix in compute-env.

---

## Tasks

<task id="04.01">
<title>Create dev environment root</title>
<read_first>
- terraform/modules/monitoring/variables.tf (module input interface)
- terraform/modules/networking/variables.tf (module input interface)
- terraform/modules/foundry/variables.tf (module input interface)
- terraform/modules/databases/variables.tf (module input interface)
- terraform/modules/compute-env/variables.tf (module input interface)
- terraform/modules/keyvault/variables.tf (module input interface)
- terraform/modules/private-endpoints/variables.tf (module input interface)
- .planning/phases/01-foundation/01-RESEARCH.md (Section 9: State Backend — backend config)
- .planning/phases/01-foundation/01-RESEARCH.md (Section 2: Module Dependency Order)
- .planning/phases/01-foundation/01-CONTEXT.md (Decisions D-03, D-04, D-05, D-06)
</read_first>
<action>
Create `terraform/envs/dev/providers.tf`:

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
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy = false
    }
  }
  use_oidc        = true
  subscription_id = var.subscription_id
}

provider "azapi" {
  use_oidc = true
}
```

Create `terraform/envs/dev/backend.tf`:

```hcl
terraform {
  backend "azurerm" {
    resource_group_name  = "rg-aap-tfstate-dev"
    storage_account_name = "staaptfstatedev"
    container_name       = "tfstate"
    key                  = "foundation.tfstate"
    use_oidc             = true
  }
}
```

Create `terraform/envs/dev/variables.tf`:

```hcl
variable "subscription_id" {
  description = "Azure subscription ID"
  type        = string
}

variable "tenant_id" {
  description = "Entra tenant ID"
  type        = string
}

variable "location" {
  description = "Azure region for all resources"
  type        = string
  default     = "eastus2"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "dev"
}

variable "postgres_admin_password" {
  description = "Administrator password for PostgreSQL"
  type        = string
  sensitive   = true
}
```

Create `terraform/envs/dev/terraform.tfvars`:

```hcl
environment = "dev"
location    = "eastus2"

# Subscription and tenant IDs — set via environment variables or CI secrets:
#   TF_VAR_subscription_id = "..."
#   TF_VAR_tenant_id       = "..."
#   TF_VAR_postgres_admin_password = "..."
```

Create `terraform/envs/dev/main.tf`:

> **REVISION (ISSUE-01, ISSUE-02):** The networking module NO LONGER receives `cosmos_account_id`,
> `acr_id`, `keyvault_id`, or `foundry_account_id`. Private endpoints are created by a NEW
> `module.private_endpoints` that is instantiated AFTER all resource modules.

```hcl
locals {
  required_tags = {
    environment = var.environment
    managed-by  = "terraform"
    project     = "aap"
  }
}

resource "azurerm_resource_group" "main" {
  name     = "rg-aap-${var.environment}"
  location = var.location

  tags = local.required_tags
}

# --- Monitoring (no dependencies) ---

module "monitoring" {
  source = "../../modules/monitoring"

  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  environment         = var.environment
  required_tags       = local.required_tags
}

# --- Networking (no module dependencies) ---

module "networking" {
  source = "../../modules/networking"

  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  environment         = var.environment
  required_tags       = local.required_tags

  # NOTE (ISSUE-02): No resource IDs passed here. Private endpoints are
  # created by module.private_endpoints below, not by the networking module.
}

# --- Foundry (depends on: monitoring) ---

module "foundry" {
  source = "../../modules/foundry"

  resource_group_name        = azurerm_resource_group.main.name
  location                   = var.location
  environment                = var.environment
  required_tags              = local.required_tags
  log_analytics_workspace_id = module.monitoring.log_analytics_workspace_id
}

# --- Databases (depends on: networking) ---

module "databases" {
  source = "../../modules/databases"

  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  environment         = var.environment
  required_tags       = local.required_tags
  tenant_id           = var.tenant_id

  # Cosmos DB — dev uses Serverless
  cosmos_serverless = true

  # PostgreSQL — dev uses burstable SKU
  postgres_subnet_id      = module.networking.subnet_postgres_id
  postgres_dns_zone_id    = module.networking.private_dns_zone_postgres_id
  postgres_sku            = "B_Standard_B1ms"
  postgres_storage_mb     = 32768
  postgres_admin_login    = "aap_admin"
  postgres_admin_password = var.postgres_admin_password

  # NOTE (ISSUE-01): No private_endpoint_subnet_id or private_dns_zone_cosmos_id
  # passed here. Cosmos DB PE is created by module.private_endpoints below.
}

# --- Compute Environment (depends on: networking, monitoring) ---

module "compute_env" {
  source = "../../modules/compute-env"

  resource_group_name        = azurerm_resource_group.main.name
  location                   = var.location
  environment                = var.environment
  required_tags              = local.required_tags
  container_apps_subnet_id   = module.networking.subnet_container_apps_id
  log_analytics_workspace_id = module.monitoring.log_analytics_workspace_id

  # NOTE (ISSUE-01): No private_endpoint_subnet_id or private_dns_zone_acr_id
  # passed here. ACR PE is created by module.private_endpoints below.
}

# --- Key Vault (depends on: networking) ---

module "keyvault" {
  source = "../../modules/keyvault"

  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  environment         = var.environment
  required_tags       = local.required_tags
  tenant_id           = var.tenant_id

  # NOTE (ISSUE-01): No private_endpoint_subnet_id or private_dns_zone_keyvault_id
  # passed here. Key Vault PE is created by module.private_endpoints below.
}

# --- Private Endpoints (depends on: networking + ALL resource modules) ---
# ISSUE-01/ISSUE-02: Centralized PE module eliminates duplicates and circular deps.

module "private_endpoints" {
  source = "../../modules/private-endpoints"

  resource_group_name        = azurerm_resource_group.main.name
  location                   = var.location
  environment                = var.environment
  required_tags              = local.required_tags
  private_endpoint_subnet_id = module.networking.subnet_private_endpoints_id

  # Target resource IDs from upstream modules
  cosmos_account_id  = module.databases.cosmos_account_id
  acr_id             = module.compute_env.acr_id
  keyvault_id        = module.keyvault.keyvault_id
  foundry_account_id = module.foundry.foundry_account_id

  # DNS zone IDs from networking module
  private_dns_zone_cosmos_id    = module.networking.private_dns_zone_cosmos_id
  private_dns_zone_acr_id       = module.networking.private_dns_zone_acr_id
  private_dns_zone_keyvault_id  = module.networking.private_dns_zone_keyvault_id
  private_dns_zone_cognitive_id = module.networking.private_dns_zone_cognitive_id
}
```

Create `terraform/envs/dev/outputs.tf`:

```hcl
# --- Resource Group ---
output "resource_group_name" {
  value = azurerm_resource_group.main.name
}

output "resource_group_id" {
  value = azurerm_resource_group.main.id
}

# --- Networking ---
output "vnet_id" {
  value = module.networking.vnet_id
}

output "container_apps_subnet_id" {
  value = module.networking.subnet_container_apps_id
}

# --- Monitoring ---
output "log_analytics_workspace_id" {
  value = module.monitoring.log_analytics_workspace_id
}

output "app_insights_connection_string" {
  value     = module.monitoring.app_insights_connection_string
  sensitive = true
}

# --- Foundry ---
output "foundry_account_id" {
  value = module.foundry.foundry_account_id
}

output "foundry_account_endpoint" {
  value = module.foundry.foundry_account_endpoint
}

output "foundry_project_id" {
  value = module.foundry.foundry_project_id
}

output "foundry_model_deployment_name" {
  value = module.foundry.foundry_model_deployment_name
}

# --- Databases ---
output "cosmos_account_id" {
  value = module.databases.cosmos_account_id
}

output "cosmos_endpoint" {
  value = module.databases.cosmos_endpoint
}

output "cosmos_database_name" {
  value = module.databases.cosmos_database_name
}

output "postgres_server_id" {
  value = module.databases.postgres_server_id
}

output "postgres_fqdn" {
  value = module.databases.postgres_fqdn
}

# --- Compute ---
output "container_apps_environment_id" {
  value = module.compute_env.container_apps_environment_id
}

output "container_apps_environment_default_domain" {
  value = module.compute_env.container_apps_environment_default_domain
}

output "acr_id" {
  value = module.compute_env.acr_id
}

output "acr_login_server" {
  value = module.compute_env.acr_login_server
}

# --- Key Vault ---
output "keyvault_id" {
  value = module.keyvault.keyvault_id
}

output "keyvault_uri" {
  value = module.keyvault.keyvault_uri
}

# --- Private Endpoints ---
output "cosmos_private_endpoint_id" {
  value = module.private_endpoints.cosmos_private_endpoint_id
}

output "acr_private_endpoint_id" {
  value = module.private_endpoints.acr_private_endpoint_id
}
```
</action>
<acceptance_criteria>
- `terraform/envs/dev/providers.tf` contains `required_version = ">= 1.9.0"`
- `terraform/envs/dev/providers.tf` contains `version = "~> 4.65.0"` for azurerm
- `terraform/envs/dev/providers.tf` contains `version = "~> 2.9.0"` for azapi
- `terraform/envs/dev/providers.tf` contains `hashicorp/random` provider requirement
- `terraform/envs/dev/providers.tf` contains `use_oidc = true` in both azurerm and azapi providers
- `terraform/envs/dev/backend.tf` contains `storage_account_name = "staaptfstatedev"`
- `terraform/envs/dev/backend.tf` contains `key = "foundation.tfstate"`
- `terraform/envs/dev/backend.tf` contains `use_oidc = true`
- `terraform/envs/dev/main.tf` contains `module "monitoring"` with `source = "../../modules/monitoring"`
- `terraform/envs/dev/main.tf` contains `module "networking"` with `source = "../../modules/networking"`
- `terraform/envs/dev/main.tf` contains `module "foundry"` with `source = "../../modules/foundry"`
- `terraform/envs/dev/main.tf` contains `module "databases"` with `cosmos_serverless = true`
- `terraform/envs/dev/main.tf` contains `module "compute_env"` with `source = "../../modules/compute-env"`
- `terraform/envs/dev/main.tf` contains `module "keyvault"` with `source = "../../modules/keyvault"`
- `terraform/envs/dev/main.tf` contains `module "private_endpoints"` with `source = "../../modules/private-endpoints"` **(ISSUE-01)**
- `module "networking"` does NOT receive `cosmos_account_id`, `acr_id`, `keyvault_id`, or `foundry_account_id` **(ISSUE-02)**
- `module "databases"` does NOT receive `private_endpoint_subnet_id` or `private_dns_zone_cosmos_id` **(ISSUE-01)**
- `module "compute_env"` does NOT receive `private_endpoint_subnet_id` or `private_dns_zone_acr_id` **(ISSUE-01)**
- `module "keyvault"` does NOT receive `private_endpoint_subnet_id` or `private_dns_zone_keyvault_id` **(ISSUE-01)**
- `module "private_endpoints"` receives resource IDs from databases, compute_env, keyvault, and foundry modules
- `module "private_endpoints"` receives DNS zone IDs from networking module
- `terraform/envs/dev/main.tf` contains `local.required_tags` with `managed-by = "terraform"` and `project = "aap"`
- `terraform/envs/dev/terraform.tfvars` contains `environment = "dev"`
- `terraform/envs/dev/outputs.tf` contains at least 17 outputs covering all module outputs
</acceptance_criteria>
</task>

<task id="04.02">
<title>Create staging environment root</title>
<read_first>
- terraform/envs/dev/main.tf (dev environment as template — staging is nearly identical)
- terraform/envs/dev/providers.tf (provider config — identical across envs)
- terraform/envs/dev/variables.tf (variable declarations — identical across envs)
- terraform/envs/dev/outputs.tf (outputs — identical across envs)
</read_first>
<action>
Create staging environment by copying dev structure with these differences:

`terraform/envs/staging/providers.tf` — identical to dev.

`terraform/envs/staging/backend.tf`:
```hcl
terraform {
  backend "azurerm" {
    resource_group_name  = "rg-aap-tfstate-stg"
    storage_account_name = "staaptfstatestg"
    container_name       = "tfstate"
    key                  = "foundation.tfstate"
    use_oidc             = true
  }
}
```

`terraform/envs/staging/variables.tf` — identical to dev.

`terraform/envs/staging/terraform.tfvars`:
```hcl
environment = "staging"
location    = "eastus2"
```

`terraform/envs/staging/main.tf` — identical to dev except:
- `cosmos_serverless = true` (staging also uses serverless)
- `postgres_sku = "B_Standard_B2ms"` (slightly larger than dev)
- `postgres_storage_mb = 65536`
- Includes `module "private_endpoints"` block identical to dev

`terraform/envs/staging/outputs.tf` — identical to dev.
</action>
<acceptance_criteria>
- `terraform/envs/staging/backend.tf` contains `storage_account_name = "staaptfstatestg"`
- `terraform/envs/staging/backend.tf` contains `resource_group_name = "rg-aap-tfstate-stg"`
- `terraform/envs/staging/terraform.tfvars` contains `environment = "staging"`
- `terraform/envs/staging/main.tf` contains `cosmos_serverless = true`
- `terraform/envs/staging/main.tf` contains `postgres_sku = "B_Standard_B2ms"`
- `terraform/envs/staging/main.tf` contains `module "private_endpoints"` with `source = "../../modules/private-endpoints"`
- `terraform/envs/staging/providers.tf` contains `version = "~> 4.65.0"` for azurerm
- `terraform/envs/staging/providers.tf` contains `hashicorp/random` provider requirement
- `terraform/envs/staging/outputs.tf` exists and contains `output "foundry_account_id"`
</acceptance_criteria>
</task>

<task id="04.03">
<title>Create prod environment root</title>
<read_first>
- terraform/envs/dev/main.tf (dev environment as template — prod differs significantly)
- terraform/envs/dev/providers.tf (provider config — identical across envs)
- terraform/envs/dev/variables.tf (variable declarations — needs additional prod vars)
- terraform/envs/dev/outputs.tf (outputs — identical across envs)
- .planning/phases/01-foundation/01-RESEARCH.md (Section 6: Serverless vs. Provisioned Environment Strategy)
</read_first>
<action>
Create prod environment with these key differences from dev:

`terraform/envs/prod/providers.tf` — identical to dev.

`terraform/envs/prod/backend.tf`:
```hcl
terraform {
  backend "azurerm" {
    resource_group_name  = "rg-aap-tfstate-prod"
    storage_account_name = "staaptfstateprod"
    container_name       = "tfstate"
    key                  = "foundation.tfstate"
    use_oidc             = true
  }
}
```

`terraform/envs/prod/variables.tf` — identical to dev.

`terraform/envs/prod/terraform.tfvars`:
```hcl
environment = "prod"
location    = "eastus2"
```

`terraform/envs/prod/main.tf` — differs from dev in these ways:
- `cosmos_serverless = false` (prod uses provisioned autoscale)
- `cosmos_secondary_location = "westus2"` (multi-region HA)
- `cosmos_max_throughput = 4000` (autoscale max RU/s)
- `postgres_sku = "GP_Standard_D4s_v3"` (General Purpose for prod)
- `postgres_storage_mb = 131072` (128 GB)
- `model_capacity = 30` for Foundry (higher TPM for prod)
- Includes `module "private_endpoints"` block identical to dev

```hcl
module "databases" {
  source = "../../modules/databases"

  # ... same as dev except:
  cosmos_serverless          = false
  cosmos_secondary_location  = "westus2"
  cosmos_max_throughput      = 4000

  postgres_sku            = "GP_Standard_D4s_v3"
  postgres_storage_mb     = 131072
  # ... rest same as dev
}

module "foundry" {
  source = "../../modules/foundry"

  # ... same as dev except:
  model_capacity = 30
  # ... rest same as dev
}

module "private_endpoints" {
  source = "../../modules/private-endpoints"
  # ... identical structure to dev
}
```

`terraform/envs/prod/outputs.tf` — identical to dev.
</action>
<acceptance_criteria>
- `terraform/envs/prod/backend.tf` contains `storage_account_name = "staaptfstateprod"`
- `terraform/envs/prod/terraform.tfvars` contains `environment = "prod"`
- `terraform/envs/prod/main.tf` contains `cosmos_serverless = false`
- `terraform/envs/prod/main.tf` contains `cosmos_secondary_location = "westus2"`
- `terraform/envs/prod/main.tf` contains `cosmos_max_throughput = 4000`
- `terraform/envs/prod/main.tf` contains `postgres_sku = "GP_Standard_D4s_v3"`
- `terraform/envs/prod/main.tf` contains `postgres_storage_mb = 131072`
- `terraform/envs/prod/main.tf` contains `model_capacity = 30`
- `terraform/envs/prod/main.tf` contains `module "private_endpoints"` with `source = "../../modules/private-endpoints"`
- `terraform/envs/prod/providers.tf` contains `use_oidc = true`
- `terraform/envs/prod/providers.tf` contains `hashicorp/random` provider requirement
</acceptance_criteria>
</task>

---

## Verification

After all tasks complete:
1. Three environment directories exist under `terraform/envs/` (dev, staging, prod)
2. Each has 6 files: `main.tf`, `variables.tf`, `terraform.tfvars`, `backend.tf`, `providers.tf`, `outputs.tf`
3. Each backend points to a different storage account (`staaptfstatedev`, `staaptfstatestg`, `staaptfstateprod`)
4. Dev and staging use `cosmos_serverless = true`; prod uses `cosmos_serverless = false` with multi-region
5. Prod PostgreSQL uses `GP_Standard_D4s_v3` (General Purpose); dev uses `B_Standard_B1ms` (Burstable)
6. All environments include `module "private_endpoints"` instantiated after all resource modules
7. No circular dependencies — networking module does not receive resource IDs

## must_haves

- [ ] 3 separate environment directories with independent backend configurations
- [ ] Each environment uses OIDC auth (`use_oidc = true`) for both provider and backend
- [ ] Dev uses Cosmos DB Serverless; prod uses Provisioned Autoscale with multi-region
- [ ] Dev uses burstable PostgreSQL SKU; prod uses General Purpose
- [ ] All environments compose the same shared modules
- [ ] All environments define the required tags (`environment`, `managed-by: terraform`, `project: aap`)
- [ ] Each environment exports all outputs needed by downstream phases
- [ ] All environments include `module "private_endpoints"` instantiated AFTER resource modules (ISSUE-01)
- [ ] Networking module receives NO resource IDs from downstream modules (ISSUE-02)
- [ ] All environments include `random` provider requirement (ISSUE-10)
