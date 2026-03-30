# Fabric module — Fabric capacity, workspace, Eventhouse, KQL Database, Activator, OneLake lakehouse
# Phase 4: Detection Plane infrastructure (INFRA-007)
#
# Resources created here (all via azapi_resource using Fabric REST API types):
#   - Microsoft.Fabric/capacities (Fabric capacity)
#   - Microsoft.Fabric/workspaces (Fabric workspace)
#   - Microsoft.Fabric/workspaces/eventhouses (Eventhouse)
#   - Microsoft.Fabric/workspaces/eventhouses/databases (KQL Database)
#   - Microsoft.Fabric/workspaces/reflex (Activator)
#   - Microsoft.Fabric/workspaces/lakehouses (OneLake Lakehouse)
#
# NOTE: Fabric data-plane items (workspace, Eventhouse, KQL Database, Activator, Lakehouse)
# use the Fabric REST API through azapi_resource. These are provisioned as child resources
# of the Fabric capacity.
#
# POST-APPLY MANUAL STEPS REQUIRED:
#   1. Activator trigger configuration (see null_resource.activator_setup_reminder)
#   2. Activity Log OneLake mirror (see null_resource.onelake_mirror_setup_reminder)

data "azurerm_subscription" "current" {}

locals {
  fabric_capacity_name = var.fabric_capacity_name != "" ? var.fabric_capacity_name : "fcaap${var.environment}"
}

# --- Fabric Capacity ---

resource "azapi_resource" "fabric_capacity" {
  type      = "Microsoft.Fabric/capacities@2023-11-01"
  name      = local.fabric_capacity_name
  location  = var.location
  parent_id = "/subscriptions/${data.azurerm_subscription.current.subscription_id}/resourceGroups/${var.resource_group_name}"

  # Fabric capacity types are not reliably covered by the AzAPI embedded schema catalog.
  schema_validation_enabled = false

  body = {
    properties = {
      administration = {
        members = [var.fabric_admin_email]
      }
    }
    sku = {
      name = var.fabric_capacity_sku
      tier = "Fabric"
    }
  }

  tags = var.required_tags
}

# --- Fabric Workspace ---
# NOTE: Fabric workspace is a data-plane resource provisioned via the Fabric REST API.
# azapi_resource supports this via the Microsoft.Fabric/workspaces type.

resource "azapi_resource" "fabric_workspace" {
  count     = var.enable_fabric_data_plane ? 1 : 0
  type      = "Microsoft.Fabric/workspaces@2023-11-01"
  name      = "aap-${var.environment}"
  parent_id = "/subscriptions/${data.azurerm_subscription.current.subscription_id}"

  # Fabric workspace items are data-plane resources and are not available in
  # the AzAPI embedded ARM schema catalog.
  schema_validation_enabled = false

  body = {
    properties = {
      displayName = "aap-${var.environment}"
      capacityId  = azapi_resource.fabric_capacity.id
    }
  }

  tags = var.required_tags

  depends_on = [azapi_resource.fabric_capacity]
}

# --- Fabric Eventhouse ---
# Eventhouse is the KQL-native time-series store within the Fabric workspace.

resource "azapi_resource" "fabric_eventhouse" {
  count     = var.enable_fabric_data_plane ? 1 : 0
  type      = "Microsoft.Fabric/workspaces/eventhouses@2023-11-01"
  name      = "eh-aap-${var.environment}"
  parent_id = azapi_resource.fabric_workspace[0].id

  schema_validation_enabled = false

  body = {
    properties = {
      displayName = "eh-aap-${var.environment}"
    }
  }

  tags = var.required_tags

  depends_on = [azapi_resource.fabric_workspace]
}

# --- KQL Database within Eventhouse ---
# The KQL database holds detection results, ingested from Event Hub via Eventstreams.

resource "azapi_resource" "fabric_kql_database" {
  count     = var.enable_fabric_data_plane ? 1 : 0
  type      = "Microsoft.Fabric/workspaces/eventhouses/databases@2023-11-01"
  name      = "kqldb-aap-${var.environment}"
  parent_id = azapi_resource.fabric_eventhouse[0].id

  schema_validation_enabled = false

  body = {
    properties = {
      displayName = "kqldb-aap-${var.environment}"
    }
  }

  depends_on = [azapi_resource.fabric_eventhouse]
}

# --- Fabric Activator ---
# Activator fires triggers to the agent platform API when detection rules are met.
# NOTE: Activator trigger wiring must be configured manually — see null_resource below.

resource "azapi_resource" "fabric_activator" {
  count     = var.enable_fabric_data_plane ? 1 : 0
  type      = "Microsoft.Fabric/workspaces/reflex@2023-11-01"
  name      = "act-aap-${var.environment}"
  parent_id = azapi_resource.fabric_workspace[0].id

  schema_validation_enabled = false

  body = {
    properties = {
      displayName = "act-aap-${var.environment}"
    }
  }

  tags = var.required_tags

  depends_on = [azapi_resource.fabric_workspace]
}

# --- OneLake Lakehouse ---
# Lakehouse stores audit logs, alert history, and resource inventory snapshots.
# Activity Log mirroring must be configured manually — see null_resource below.

resource "azapi_resource" "fabric_lakehouse" {
  count     = var.enable_fabric_data_plane ? 1 : 0
  type      = "Microsoft.Fabric/workspaces/lakehouses@2023-11-01"
  name      = "lh-aap-${var.environment}"
  parent_id = azapi_resource.fabric_workspace[0].id

  schema_validation_enabled = false

  body = {
    properties = {
      displayName = "lh-aap-${var.environment}"
    }
  }

  tags = var.required_tags

  depends_on = [azapi_resource.fabric_workspace]
}

# --- Post-Apply Reminders ---

# Activator trigger configuration cannot be automated via Terraform or the Fabric REST API.
# After terraform apply, configure the Activator trigger manually via the Fabric portal:
#   1. Open the Activator item in the Fabric workspace
#   2. Set data source to the Eventhouse `DetectionResults` table
#   3. Set trigger condition: new row where `domain IS NOT NULL`
#   4. Set action: invoke User Data Function (`handle_activator_trigger`)
resource "null_resource" "activator_setup_reminder" {
  count = var.enable_fabric_data_plane ? 1 : 0
  depends_on = [azapi_resource.fabric_capacity]

  provisioner "local-exec" {
    command = "echo 'ACTION REQUIRED: Configure Fabric Activator trigger manually. See 04-01-PLAN.md Task 4-01-01 for steps.'"
  }
}

# Activity Log OneLake mirror cannot be automated via Terraform or the Fabric REST API.
# After terraform apply, configure the OneLake mirror manually:
#   See services/detection-plane/docs/AUDIT-003-onelake-setup.md for detailed steps.
#   Retention must be >= 2 years (730 days) per AUDIT-003.
resource "null_resource" "onelake_mirror_setup_reminder" {
  count = var.enable_fabric_data_plane ? 1 : 0
  depends_on = [azapi_resource.fabric_capacity]

  provisioner "local-exec" {
    command = "echo 'ACTION REQUIRED: Configure Activity Log OneLake mirror for AUDIT-003 compliance. See services/detection-plane/docs/AUDIT-003-onelake-setup.md. Retention must be >= 2 years (730 days).'"
  }
}
