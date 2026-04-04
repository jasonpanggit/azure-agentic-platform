locals {
  compute_sub = var.compute_subscription_id != "" ? var.compute_subscription_id : var.platform_subscription_id
  network_sub = var.network_subscription_id != "" ? var.network_subscription_id : var.platform_subscription_id
  storage_sub = var.storage_subscription_id != "" ? var.storage_subscription_id : var.platform_subscription_id

  # Flatten role assignments into a map keyed by unique assignment key for for_each
  role_assignments = merge(

    # Orchestrator: Reader on platform subscription only (no direct Azure resource access)
    {
      "orchestrator-reader-platform" = {
        principal_id         = var.agent_principal_ids["orchestrator"]
        role_definition_name = "Reader"
        scope                = "/subscriptions/${var.platform_subscription_id}"
      }
    },

    # Compute Agent: Virtual Machine Contributor on compute sub + Monitoring Reader on platform + compute
    {
      "compute-vmcontributor-compute" = {
        principal_id         = var.agent_principal_ids["compute"]
        role_definition_name = "Virtual Machine Contributor"
        scope                = "/subscriptions/${local.compute_sub}"
      }
      "compute-monreader-platform" = {
        principal_id         = var.agent_principal_ids["compute"]
        role_definition_name = "Monitoring Reader"
        scope                = "/subscriptions/${var.platform_subscription_id}"
      }
      "compute-monreader-compute" = {
        principal_id         = var.agent_principal_ids["compute"]
        role_definition_name = "Monitoring Reader"
        scope                = "/subscriptions/${local.compute_sub}"
      }
    },

    # Network Agent: Network Contributor on network sub + Reader on compute sub for correlation
    {
      "network-netcontributor-network" = {
        principal_id         = var.agent_principal_ids["network"]
        role_definition_name = "Network Contributor"
        scope                = "/subscriptions/${local.network_sub}"
      }
      "network-reader-compute" = {
        principal_id         = var.agent_principal_ids["network"]
        role_definition_name = "Reader"
        scope                = "/subscriptions/${local.compute_sub}"
      }
    },

    # Storage Agent: Storage Blob Data Reader across all in-scope subscriptions
    {
      for sub_id in var.all_subscription_ids :
      "storage-blobdatareader-${replace(sub_id, "-", "")}" => {
        principal_id         = var.agent_principal_ids["storage"]
        role_definition_name = "Storage Blob Data Reader"
        scope                = "/subscriptions/${sub_id}"
      }
    },

    # Security Agent: Security Reader across all in-scope subscriptions
    {
      for sub_id in var.all_subscription_ids :
      "security-secreader-${replace(sub_id, "-", "")}" => {
        principal_id         = var.agent_principal_ids["security"]
        role_definition_name = "Security Reader"
        scope                = "/subscriptions/${sub_id}"
      }
    },

    # SRE Agent: Reader + Monitoring Reader across all in-scope subscriptions (cross-subscription monitoring)
    merge(
      {
        for sub_id in var.all_subscription_ids :
        "sre-reader-${replace(sub_id, "-", "")}" => {
          principal_id         = var.agent_principal_ids["sre"]
          role_definition_name = "Reader"
          scope                = "/subscriptions/${sub_id}"
        }
      },
      {
        for sub_id in var.all_subscription_ids :
        "sre-monreader-${replace(sub_id, "-", "")}" => {
          principal_id         = var.agent_principal_ids["sre"]
          role_definition_name = "Monitoring Reader"
          scope                = "/subscriptions/${sub_id}"
        }
      }
    ),

    # Arc Agent: Contributor on Arc resource groups (empty in Phase 2; real RBAC added in Phase 3)
    {
      for rg_id in var.arc_resource_group_ids :
      "arc-contributor-${md5(rg_id)}" => {
        principal_id         = var.agent_principal_ids["arc"]
        role_definition_name = "Contributor"
        scope                = rg_id
      }
    },

    # Patch Agent: Reader + Monitoring Reader across all in-scope subscriptions (ARG cross-subscription queries)
    merge(
      {
        for sub_id in var.all_subscription_ids :
        "patch-reader-${replace(sub_id, "-", "")}" => {
          principal_id         = var.agent_principal_ids["patch"]
          role_definition_name = "Reader"
          scope                = "/subscriptions/${sub_id}"
        }
      },
      {
        for sub_id in var.all_subscription_ids :
        "patch-monreader-${replace(sub_id, "-", "")}" => {
          principal_id         = var.agent_principal_ids["patch"]
          role_definition_name = "Monitoring Reader"
          scope                = "/subscriptions/${sub_id}"
        }
      }
    ),

    # API Gateway: Cognitive Services User on platform subscription (Foundry API access)
    {
      "api-gateway-coguser-platform" = {
        principal_id         = var.agent_principal_ids["api-gateway"]
        role_definition_name = "Cognitive Services User"
        scope                = "/subscriptions/${var.platform_subscription_id}"
      }
    },

    # API Gateway: Azure AI Developer on Foundry account (agent/thread/run APIs — F-01 fix)
    # Only provisioned when foundry_account_name is set (not empty).
    var.foundry_account_name != "" && var.resource_group_name != "" ? {
      "api-gateway-aidev-foundry" = {
        principal_id         = var.agent_principal_ids["api-gateway"]
        role_definition_name = "Azure AI Developer"
        scope                = "/subscriptions/${var.platform_subscription_id}/resourceGroups/${var.resource_group_name}/providers/Microsoft.CognitiveServices/accounts/${var.foundry_account_name}"
      }
    } : {},

    # API Gateway: Reader + Monitoring Reader across all in-scope subscriptions
    # (VM health checks via ResourceHealth API + Azure Monitor metrics reads)
    merge(
      {
        for sub_id in var.all_subscription_ids :
        "api-gateway-reader-${replace(sub_id, "-", "")}" => {
          principal_id         = var.agent_principal_ids["api-gateway"]
          role_definition_name = "Reader"
          scope                = "/subscriptions/${sub_id}"
        }
      },
      {
        for sub_id in var.all_subscription_ids :
        "api-gateway-monreader-${replace(sub_id, "-", "")}" => {
          principal_id         = var.agent_principal_ids["api-gateway"]
          role_definition_name = "Monitoring Reader"
          scope                = "/subscriptions/${sub_id}"
        }
      }
    ),

    # All agents: Cosmos DB Operator on platform subscription
    {
      for name, principal_id in var.agent_principal_ids :
      "${name}-cosmoscontributor-platform" => {
        principal_id         = principal_id
        role_definition_name = "Cosmos DB Operator"
        scope                = "/subscriptions/${var.platform_subscription_id}"
      }
    },
  )
}

resource "azurerm_role_assignment" "agent_rbac" {
  for_each = local.role_assignments

  principal_id         = each.value.principal_id
  role_definition_name = each.value.role_definition_name
  scope                = each.value.scope
}

# AcrPull role for all agent and service managed identities to pull images from ACR
resource "azurerm_role_assignment" "acr_pull" {
  for_each = var.acr_id != "" ? var.agent_principal_ids : {}

  principal_id         = each.value
  role_definition_name = "AcrPull"
  scope                = var.acr_id
}
