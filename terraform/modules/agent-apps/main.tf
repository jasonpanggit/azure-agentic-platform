locals {
  agents = {
    orchestrator = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
    compute      = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
    network      = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
    storage      = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
    security     = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
    arc          = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
    sre          = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
    patch        = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
    eol          = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
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
  max_inactive_revisions       = 0
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"

  identity {
    type = "SystemAssigned"
  }

  # ACR registry configuration — always present so existing ACR-tagged images can pull
  # even when use_placeholder_image=true. The placeholder image (public) doesn't need it
  # but existing revisions with ACR SHA tags do.
  registry {
    server   = var.acr_login_server
    identity = "system"
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
        value = var.foundry_project_endpoint
      }
      # AZURE_AI_PROJECT_ENDPOINT is read by azure-ai-agentserver-core to configure
      # the hosted agent adapter. Must match AZURE_PROJECT_ENDPOINT.
      env {
        name  = "AZURE_AI_PROJECT_ENDPOINT"
        value = var.foundry_project_endpoint
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
      # API Gateway: Entra auth mode and credentials.
      # api_gateway_auth_mode defaults to "entra" (fail-closed).
      # Set api_gateway_auth_mode="disabled" only for local dev; never in prod.
      # api_gateway_client_id and api_gateway_tenant_id must be set when mode is "entra".
      dynamic "env" {
        for_each = each.key == "api-gateway" ? [1] : []
        content {
          name  = "API_GATEWAY_AUTH_MODE"
          value = var.api_gateway_auth_mode
        }
      }
      dynamic "env" {
        for_each = each.key == "api-gateway" && var.api_gateway_client_id != "" ? [1] : []
        content {
          name  = "API_GATEWAY_CLIENT_ID"
          value = var.api_gateway_client_id
        }
      }
      dynamic "env" {
        for_each = each.key == "api-gateway" && var.api_gateway_tenant_id != "" ? [1] : []
        content {
          name  = "API_GATEWAY_TENANT_ID"
          value = var.api_gateway_tenant_id
        }
      }
      # API Gateway: Azure OpenAI endpoint for embedding generation in runbook RAG (TRIAGE-005).
      # Uses the Foundry account endpoint — same cognitive services resource.
      dynamic "env" {
        for_each = each.key == "api-gateway" ? [1] : []
        content {
          name  = "AZURE_OPENAI_ENDPOINT"
          value = var.foundry_account_endpoint
        }
      }
      # AGENT_ENTRA_ID — required by agents/shared/auth.py for AUDIT-005 attribution.
      # Value is injected post-creation via azurerm_container_app_custom_domain or
      # read at runtime from IMDS / DefaultAzureCredential JWT `oid` claim.
      # Cannot be set inline — self-reference creates a Terraform dependency cycle
      # (each for_each instance depends on the entire resource block).
      # See .planning/debug/terraform-plan-errors.md for details.
      # Orchestrator Agent ID — required by api-gateway and orchestrator for Foundry dispatch
      dynamic "env" {
        for_each = var.orchestrator_agent_id != "" ? [1] : []
        content {
          name  = "ORCHESTRATOR_AGENT_ID"
          value = var.orchestrator_agent_id
        }
      }
      # Inject domain agent IDs into the orchestrator and api-gateway.
      # Orchestrator uses them for routing; api-gateway uses them for sub-run MCP approval.
      dynamic "env" {
        for_each = contains(["orchestrator", "api-gateway"], each.key) && var.compute_agent_id != "" ? [1] : []
        content {
          name  = "COMPUTE_AGENT_ID"
          value = var.compute_agent_id
        }
      }
      dynamic "env" {
        for_each = contains(["orchestrator", "api-gateway"], each.key) && var.network_agent_id != "" ? [1] : []
        content {
          name  = "NETWORK_AGENT_ID"
          value = var.network_agent_id
        }
      }
      dynamic "env" {
        for_each = contains(["orchestrator", "api-gateway"], each.key) && var.storage_agent_id != "" ? [1] : []
        content {
          name  = "STORAGE_AGENT_ID"
          value = var.storage_agent_id
        }
      }
      dynamic "env" {
        for_each = contains(["orchestrator", "api-gateway"], each.key) && var.security_agent_id != "" ? [1] : []
        content {
          name  = "SECURITY_AGENT_ID"
          value = var.security_agent_id
        }
      }
      dynamic "env" {
        for_each = contains(["orchestrator", "api-gateway"], each.key) && var.sre_agent_id != "" ? [1] : []
        content {
          name  = "SRE_AGENT_ID"
          value = var.sre_agent_id
        }
      }
      dynamic "env" {
        for_each = contains(["orchestrator", "api-gateway"], each.key) && var.arc_agent_id != "" ? [1] : []
        content {
          name  = "ARC_AGENT_ID"
          value = var.arc_agent_id
        }
      }
      dynamic "env" {
        for_each = contains(["orchestrator", "api-gateway"], each.key) && var.patch_agent_id != "" ? [1] : []
        content {
          name  = "PATCH_AGENT_ID"
          value = var.patch_agent_id
        }
      }
      dynamic "env" {
        for_each = contains(["orchestrator", "api-gateway"], each.key) && var.eol_agent_id != "" ? [1] : []
        content {
          name  = "EOL_AGENT_ID"
          value = var.eol_agent_id
        }
      }
      # EOL agent needs PostgreSQL DSN for eol_cache table
      dynamic "env" {
        for_each = each.key == "eol" && var.postgres_dsn != "" ? [1] : []
        content {
          name  = "POSTGRES_DSN"
          value = var.postgres_dsn
        }
      }
      # API Gateway: pgvector connection string for runbook RAG (TRIAGE-005)
      # Only injected on api-gateway to avoid leaking credentials to other containers.
      dynamic "env" {
        for_each = each.key == "api-gateway" && var.pgvector_connection_string != "" ? [1] : []
        content {
          name  = "PGVECTOR_CONNECTION_STRING"
          value = var.pgvector_connection_string
        }
      }
      # Inject Arc MCP Server URL into the arc agent
      dynamic "env" {
        for_each = each.key == "arc" && var.arc_mcp_server_url != "" ? [1] : []
        content {
          name  = "ARC_MCP_SERVER_URL"
          value = var.arc_mcp_server_url
        }
      }
      # Inject Azure MCP Server URL into patch and EOL agents
      # Both agents mount MCPTool / MCPStreamableHTTPTool only when this URL is non-empty,
      # so leaving it empty preserves graceful degradation (MCP tools silently skipped).
      dynamic "env" {
        for_each = contains(["patch", "eol"], each.key) && var.azure_mcp_server_url != "" ? [1] : []
        content {
          name  = "AZURE_MCP_SERVER_URL"
          value = var.azure_mcp_server_url
        }
      }
      # Log Analytics workspace ID for:
      # - web-ui: Observability tab queries
      # - api-gateway: Patch installed detail, assessment enrichment, audit log queries
      dynamic "env" {
        for_each = contains(["web-ui", "api-gateway"], each.key) && var.log_analytics_workspace_customer_id != "" ? [1] : []
        content {
          name  = "LOG_ANALYTICS_WORKSPACE_ID"
          value = var.log_analytics_workspace_customer_id
        }
      }
      # Web UI specific: API Gateway URL for server-side proxy routes (chat, incidents, approvals)
      dynamic "env" {
        for_each = each.key == "web-ui" ? [1] : []
        content {
          name  = "API_GATEWAY_URL"
          value = var.api_gateway_internal_url != "" ? var.api_gateway_internal_url : "https://ca-api-gateway-${var.environment}.internal.${var.environment}.azurecontainerapps.io"
        }
      }
      # Phase 29: GenAI tracing env vars for Foundry portal OTel trace waterfall.
      # Applied to all agent Container Apps (not web-ui or api-gateway services).
      dynamic "env" {
        for_each = contains(keys(local.agents), each.key) ? [1] : []
        content {
          name  = "AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING"
          value = "true"
        }
      }
      dynamic "env" {
        for_each = contains(keys(local.agents), each.key) ? [1] : []
        content {
          name  = "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"
          value = "true"
        }
      }
      # Phase 29: Orchestrator agent name for Responses API dispatch.
      dynamic "env" {
        for_each = contains(["orchestrator", "api-gateway"], each.key) ? [1] : []
        content {
          name  = "ORCHESTRATOR_AGENT_NAME"
          value = "aap-orchestrator"
        }
      }
      # Phase 30: SOP Engine — vector store ID for all domain agents (not orchestrator/services).
      # Domain agents use this to attach the SOP vector store via FileSearchTool.
      dynamic "env" {
        for_each = contains(keys(local.agents), each.key) && each.key != "orchestrator" && var.sop_vector_store_id != "" ? [1] : []
        content {
          name  = "SOP_VECTOR_STORE_ID"
          value = var.sop_vector_store_id
        }
      }
      # Phase 30: SOP Engine — notification email config for sop_notify @ai_function.
      dynamic "env" {
        for_each = contains(keys(local.agents), each.key) && each.key != "orchestrator" && var.notification_email_from != "" ? [1] : []
        content {
          name  = "NOTIFICATION_EMAIL_FROM"
          value = var.notification_email_from
        }
      }
      dynamic "env" {
        for_each = contains(keys(local.agents), each.key) && each.key != "orchestrator" && var.notification_email_to != "" ? [1] : []
        content {
          name  = "NOTIFICATION_EMAIL_TO"
          value = var.notification_email_to
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

  # NOTE (TASK-12-03): template[0].container[0].env is intentionally NOT in ignore_changes.
  # Required env vars (agent IDs, endpoints) must propagate on every `terraform apply`.
  # AGENT_ENTRA_ID is no longer set inline (was causing dependency cycle) — agents
  # now auto-discover their own principal_id at runtime from the IMDS token.
  #
  # ⚠️  IMPORTANT: Any env vars set manually via `az containerapp update --set-env-vars`
  # (e.g. ORCHESTRATOR_AGENT_ID, domain agent IDs) will be WIPED on the next `terraform apply`
  # unless they are also set in terraform.tfvars (var.orchestrator_agent_id etc.).
  # Before running `terraform apply` in production, ensure all required agent IDs are
  # populated in the tfvars file for that environment.
  #
  # Runtime image revisions are still ignored — CI/CD owns the image tag.
  lifecycle {
    ignore_changes = [
      template[0].container[0].image,
    ]
  }
}

# Teams Bot managed separately to support bot-specific env vars (BOT_ID, BOT_PASSWORD, etc.)
resource "azurerm_container_app" "teams_bot" {
  name                         = "ca-teams-bot-${var.environment}"
  container_app_environment_id = var.container_apps_environment_id
  resource_group_name          = var.resource_group_name
  max_inactive_revisions       = 0
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"

  identity {
    type = "SystemAssigned"
  }

  # ACR registry configuration — always present so existing ACR-tagged images can pull
  # even when use_placeholder_image=true.
  registry {
    server   = var.acr_login_server
    identity = "system"
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
        value = var.foundry_project_endpoint
      }
      # AZURE_AI_PROJECT_ENDPOINT is read by azure-ai-agentserver-core to configure
      # the hosted agent adapter. Must match AZURE_PROJECT_ENDPOINT.
      env {
        name  = "AZURE_AI_PROJECT_ENDPOINT"
        value = var.foundry_project_endpoint
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
        name  = "BOT_TENANT_ID"
        value = var.teams_bot_tenant_id
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
      # AGENT_ENTRA_ID — required by agents/shared/auth.py for AUDIT-005 attribution.
      # Cannot be set inline — self-reference on azurerm_container_app.teams_bot
      # causes Terraform error "Configuration may not refer to itself."
      # Injected post-creation or read at runtime from IMDS / JWT `oid` claim.
      # See .planning/debug/terraform-plan-errors.md for details.
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

  # NOTE (TASK-12-03): template[0].container[0].env is intentionally NOT in ignore_changes.
  # AGENT_ENTRA_ID is no longer set inline (was causing self-referential error) — agents
  # now auto-discover their own principal_id at runtime from the IMDS token.
  # Secret values (BOT_PASSWORD) are managed out-of-band via `az containerapp secret set`.
  # BOT_ID, BOT_TENANT_ID, and TEAMS_CHANNEL_ID are managed via Terraform variables
  # (teams_bot_id, teams_bot_tenant_id, teams_channel_id) in credentials.tfvars.
  # Runtime image revisions are still ignored — CI/CD owns the image tag.
  lifecycle {
    ignore_changes = [
      secret,
      template[0].container[0].image,
    ]
  }
}

# ---------------------------------------------------------------------------
# Phase 29: A2A connections — one per domain agent
# These register each domain agent as an A2A connection in the Foundry
# project so the Orchestrator can wire them as A2APreviewTool targets.
# ---------------------------------------------------------------------------

locals {
  a2a_domains = {
    compute  = var.compute_agent_endpoint
    arc      = var.arc_agent_endpoint
    eol      = var.eol_agent_endpoint
    network  = var.network_agent_endpoint
    patch    = var.patch_agent_endpoint
    security = var.security_agent_endpoint
    sre      = var.sre_agent_endpoint
    storage  = var.storage_agent_endpoint
  }
}

resource "azapi_resource" "a2a_connection" {
  for_each = local.a2a_domains

  type      = "Microsoft.CognitiveServices/accounts/projects/connections@2025-05-01-preview"
  name      = "aap-${each.key}-agent-connection"
  parent_id = var.foundry_project_id

  body = {
    properties = {
      category    = "RemoteA2A"
      target      = each.value
      authType    = "ManagedIdentity"
      displayName = "AAP ${title(each.key)} Agent (A2A)"
    }
  }
}
