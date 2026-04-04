locals {
  name_prefix = "aap-${var.environment}"

  gh_url                     = "https://github.com/${var.github_owner}/${var.github_repo}"
  registration_token_api_url = "https://api.github.com/repos/${var.github_owner}/${var.github_repo}/actions/runners/registration-token"
}

# ── User-Assigned Managed Identity for the runner ─────────────────────────────
resource "azurerm_user_assigned_identity" "runner" {
  name                = "id-github-runner-${var.environment}"
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.required_tags
}

# ── ACR Pull permission ────────────────────────────────────────────────────────
resource "azurerm_role_assignment" "acr_pull" {
  scope                = var.acr_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.runner.principal_id
}

# ── Container App Job — GitHub Actions Runner ──────────────────────────────────
resource "azurerm_container_app_job" "github_runner" {
  name                         = "caj-github-runner-${var.environment}"
  resource_group_name          = var.resource_group_name
  location                     = var.location
  container_app_environment_id = var.container_apps_environment_id

  # One runner per queued job; no retries (prevents double-execution)
  replica_timeout_in_seconds = var.replica_timeout_seconds
  replica_retry_limit        = 0

  # Event-driven scaling via KEDA GitHub runner scaler
  event_trigger_config {
    parallelism              = 1
    replica_completion_count = 1

    scale {
      min_executions              = 0
      max_executions              = var.max_runners
      polling_interval_in_seconds = 30

      rules {
        name             = "github-runner-scale-rule"
        custom_rule_type = "github-runner"

        metadata = {
          githubApiURL              = "https://api.github.com"
          owner                     = var.github_owner
          runnerScope               = "repo"
          repos                     = var.github_repo
          targetWorkflowQueueLength = "1"
          labels                    = var.runner_labels
        }

        authentication {
          secret_name       = "github-runner-pat"
          trigger_parameter = "personalAccessToken"
        }
      }
    }
  }

  # Managed identity for ACR pull + KV secret reference
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.runner.id]
  }

  # PAT stored inline — KV reference causes 400 on first apply due to identity
  # propagation lag. The value is marked sensitive in variables.tf.
  secret {
    name  = "github-runner-pat"
    value = var.github_pat
  }

  # Pull runner image from ACR using managed identity
  registry {
    server   = var.acr_login_server
    identity = azurerm_user_assigned_identity.runner.id
  }

  template {
    container {
      name   = "github-runner"
      image  = "${var.acr_login_server}/github-runner:${var.runner_image_tag}"
      cpu    = var.runner_cpu
      memory = var.runner_memory

      env {
        name        = "GITHUB_PAT"
        secret_name = "github-runner-pat"
      }
      env {
        name  = "GH_URL"
        value = local.gh_url
      }
      env {
        name  = "REGISTRATION_TOKEN_API_URL"
        value = local.registration_token_api_url
      }
      env {
        name  = "RUNNER_LABELS"
        value = var.runner_labels
      }
    }
  }

  tags = var.required_tags

  depends_on = [
    azurerm_role_assignment.acr_pull,
  ]
}
