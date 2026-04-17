# Capability Host — required for Foundry Agent Service to process runs.
# Uses azapi because this resource type is not available in azurerm.
#
# The Agent Service requires BOTH an account-level AND a project-level
# capability host. Without both, agent runs stay permanently in "queued"
# status because Foundry has no compute allocated to process them.
#
# KNOWN ISSUES:
# - Long-running operation (up to 30 min) — extended timeouts configured
# - May show perpetual drift on specific properties — lifecycle ignore_changes used
# - enablePublicHostingEnvironment = true is REQUIRED during Preview (no private networking)
# - capabilityHost can show Succeeded but be non-functional if connections are missing

# ---------------------------------------------------------------------------
# AI Services connection (self-referential) — required by capability host
# ---------------------------------------------------------------------------
# The capability host needs an explicit AI Services connection to link the
# model deployment to the Agent Service runtime. Without it, runs may stay
# in "queued" status because the backend cannot discover the model endpoint.

# ---------------------------------------------------------------------------
# Blob Storage connection — required for Foundry Agent Service thread storage
# ---------------------------------------------------------------------------
# The Foundry Agent Service threads/runs API requires a Blob Storage connection
# on the capability host to persist thread state (messages, run metadata, file
# attachments). Without storageConnections, every create_thread_and_run() call
# fails with ServiceInvocationException HTTP 500.
#
# Category must be "AzureBlob" (not "AzureStorageBlob"). AAD auth (managed
# identity) is used — no SAS keys required.
# AccountName + ContainerName are required metadata fields.
resource "azapi_resource" "storage_connection" {
  type      = "Microsoft.CognitiveServices/accounts/connections@2025-10-01-preview"
  name      = "aap-storage-connection"
  parent_id = azurerm_cognitive_account.foundry.id

  body = {
    properties = {
      category     = "AzureBlob"
      target       = "https://${var.storage_account_name}.blob.core.windows.net"
      authType     = "AAD"
      isSharedToAll = true
      metadata = {
        AccountName   = var.storage_account_name
        ContainerName = "foundry-threads"
        ResourceId    = var.storage_account_id
      }
    }
  }

  lifecycle {
    ignore_changes = all
  }
}

resource "azapi_resource" "aiservices_connection" {
  type      = "Microsoft.CognitiveServices/accounts/connections@2025-10-01-preview"
  name      = "aap-aiservices-connection"
  parent_id = azurerm_cognitive_account.foundry.id

  body = {
    properties = {
      category = "AIServices"
      target   = azurerm_cognitive_account.foundry.endpoint
      authType = "AAD"
      metadata = {
        ApiType    = "Azure"
        ResourceId = azurerm_cognitive_account.foundry.id
      }
    }
  }
}

# ---------------------------------------------------------------------------
# Account-level capability host
# ---------------------------------------------------------------------------

resource "azapi_resource" "capability_host" {
  type      = "Microsoft.CognitiveServices/accounts/capabilityHosts@2025-10-01-preview"
  name      = "accountcaphost"
  parent_id = azurerm_cognitive_account.foundry.id

  # schema_validation_enabled = false: preview API schema is fluid and rejects
  # valid properties (capabilityHostKind, enablePublicHostingEnvironment) that
  # the API accepts at runtime. Disable to avoid spurious validation failures.
  schema_validation_enabled = false

  body = {
    properties = {
      capabilityHostKind             = "Agents"
      enablePublicHostingEnvironment = true
      aiServicesConnections          = [azapi_resource.aiservices_connection.id]
      storageConnections             = [azapi_resource.storage_connection.id]
    }
  }

  timeouts {
    create = "30m"
    update = "30m"
    delete = "30m"
  }

  depends_on = [azapi_resource.storage_connection]

  lifecycle {
    # Ignore ALL changes — capability host was manually provisioned and is working.
    # schema_validation_enabled, timeouts, and body drift all trigger a 30-minute
    # ARM re-provisioning operation. Ignore everything to prevent CI timeouts.
    ignore_changes = all
  }
}

# ---------------------------------------------------------------------------
# Project-level capability host
# ---------------------------------------------------------------------------
# The project-level capability host inherits connections from the account-level
# host but must exist explicitly for the Agent Service to process runs on
# agents within this project. Without it, runs stay in "queued" forever.

resource "azapi_resource" "project_capability_host" {
  type      = "Microsoft.CognitiveServices/accounts/projects/capabilityHosts@2025-10-01-preview"
  name      = "projectcaphost"
  parent_id = azurerm_cognitive_account_project.main.id

  # schema_validation_enabled = false: same preview schema issue as account-level host.
  schema_validation_enabled = false

  body = {
    properties = {
      capabilityHostKind             = "Agents"
      enablePublicHostingEnvironment = true
    }
  }

  timeouts {
    create = "30m"
    update = "30m"
    delete = "30m"
  }

  lifecycle {
    # Ignore ALL changes — this resource was manually provisioned and is working.
    # schema_validation_enabled, timeouts, and body drift all trigger a 30-minute
    # ARM re-provisioning operation. Ignore everything to prevent CI timeouts.
    ignore_changes = all
  }

  depends_on = [azapi_resource.capability_host]
}
