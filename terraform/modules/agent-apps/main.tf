locals {
  agents = {
    orchestrator = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
    compute      = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
    network      = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
    storage      = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
    security     = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
    arc          = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
    sre          = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
  }

  # services excludes teams-bot (managed separately for bot-specific env vars)
  services = {
    api-gateway = { cpu = 0.5, memory = "1Gi", ingress_external = true, min_replicas = 1, max_replicas = 5, target_port = 8000 }
    web-ui      = { cpu = 0.5, memory = "1Gi", ingress_external = true, min_replicas = 1, max_replicas = 3, target_port = 3000 }
  }

  all_apps = merge(local.agents, local.services)
}

resource "azurerm_container_app" "agents" {
  for_each = local.all_apps

  name                         = "ca-${each.key}-${var.environment}"
  container_app_environment_id = var.container_apps_environment_id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"

  identity {
    type = "SystemAssigned"
  }

  template {
    min_replicas = each.value.min_replicas
    max_replicas = each.value.max_replicas

    container {
      name   = each.key
      image  = var.use_placeholder_image ? "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest" : "${var.acr_login_server}/${contains(keys(local.agents), each.key) ? "agents" : "services"}/${each.key}:${var.image_tag}"
      cpu    = each.value.cpu
      memory = each.value.memory

      env {
        name  = "FOUNDRY_ACCOUNT_ENDPOINT"
        value = var.foundry_account_endpoint
      }
      env {
        name  = "AZURE_PROJECT_ENDPOINT"
        value = var.foundry_account_endpoint
      }
      env {
        name  = "FOUNDRY_PROJECT_ID"
        value = var.foundry_project_id
      }
      env {
        name  = "FOUNDRY_MODEL_DEPLOYMENT"
        value = var.foundry_model_deployment_name
      }
      env {
        name        = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        secret_name = "appinsights-connection-string"
      }
      env {
        name  = "COSMOS_ENDPOINT"
        value = var.cosmos_endpoint
      }
      env {
        name  = "COSMOS_DATABASE_NAME"
        value = var.cosmos_database_name
      }
      env {
        name  = "AGENT_NAME"
        value = each.key
      }
      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }
      env {
        name  = "CORS_ALLOWED_ORIGINS"
        value = var.cors_allowed_origins
      }
      # Orchestrator Agent ID — required by api-gateway and orchestrator for Foundry dispatch
      dynamic "env" {
        for_each = var.orchestrator_agent_id != "" ? [1] : []
        content {
          name  = "ORCHESTRATOR_AGENT_ID"
          value = var.orchestrator_agent_id
        }
      }
      # Web UI specific: Log Analytics workspace for Observability tab
      dynamic "env" {
        for_each = each.key == "web-ui" && var.log_analytics_workspace_customer_id != "" ? [1] : []
        content {
          name  = "LOG_ANALYTICS_WORKSPACE_ID"
          value = var.log_analytics_workspace_customer_id
        }
      }
    }
  }

  secret {
    name  = "appinsights-connection-string"
    value = var.app_insights_connection_string
  }

  dynamic "ingress" {
    for_each = each.value.ingress_external ? [1] : []
    content {
      external_enabled = true
      target_port      = each.value.target_port
      transport        = "http"
      traffic_weight {
        percentage      = 100
        latest_revision = true
      }
    }
  }

  tags = var.required_tags
}

# Teams Bot managed separately to support bot-specific env vars (BOT_ID, BOT_PASSWORD, etc.)
resource "azurerm_container_app" "teams_bot" {
  name                         = "ca-teams-bot-${var.environment}"
  container_app_environment_id = var.container_apps_environment_id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"

  identity {
    type = "SystemAssigned"
  }

  template {
    min_replicas = 1
    max_replicas = 3

    container {
      name   = "teams-bot"
      image  = var.use_placeholder_image ? "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest" : "${var.acr_login_server}/services/teams-bot:${var.image_tag}"
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "FOUNDRY_ACCOUNT_ENDPOINT"
        value = var.foundry_account_endpoint
      }
      env {
        name  = "AZURE_PROJECT_ENDPOINT"
        value = var.foundry_account_endpoint
      }
      env {
        name  = "FOUNDRY_PROJECT_ID"
        value = var.foundry_project_id
      }
      env {
        name  = "FOUNDRY_MODEL_DEPLOYMENT"
        value = var.foundry_model_deployment_name
      }
      env {
        name        = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        secret_name = "appinsights-connection-string"
      }
      env {
        name  = "COSMOS_ENDPOINT"
        value = var.cosmos_endpoint
      }
      env {
        name  = "COSMOS_DATABASE_NAME"
        value = var.cosmos_database_name
      }
      env {
        name  = "AGENT_NAME"
        value = "teams-bot"
      }
      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }
      # Teams Bot specific env vars
      env {
        name  = "BOT_ID"
        value = var.teams_bot_id
      }
      env {
        name        = "BOT_PASSWORD"
        secret_name = "teams-bot-password"
      }
      env {
        name  = "API_GATEWAY_INTERNAL_URL"
        value = var.api_gateway_internal_url != "" ? var.api_gateway_internal_url : "https://ca-api-gateway-${var.environment}.internal.${var.environment}.azurecontainerapps.io"
      }
      env {
        name  = "WEB_UI_PUBLIC_URL"
        value = var.web_ui_public_url
      }
      env {
        name  = "TEAMS_CHANNEL_ID"
        value = var.teams_channel_id
      }
      env {
        name  = "PORT"
        value = "3978"
      }
    }
  }

  secret {
    name  = "appinsights-connection-string"
    value = var.app_insights_connection_string
  }

  secret {
    name  = "teams-bot-password"
    value = var.teams_bot_password != "" ? var.teams_bot_password : "placeholder-not-configured"
  }

  ingress {
    external_enabled = true
    target_port      = 3978
    transport        = "http"
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  tags = var.required_tags
}
