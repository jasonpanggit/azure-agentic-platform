resource "azurerm_cosmosdb_account" "main" {
  name                          = "aap-cosmos-${var.environment}"
  location                      = var.location
  resource_group_name           = var.resource_group_name
  offer_type                    = "Standard"
  kind                          = "GlobalDocumentDB"
  local_authentication_disabled = true
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

    # Composite index for dedup queries (DETECT-005):
    #   Layer 1: WHERE resource_id = @rid AND detection_rule = @rule AND created_at >= @window_start AND status != 'closed'
    #   Layer 2: WHERE resource_id = @rid AND status IN ('new', 'acknowledged')
    composite_index {
      index {
        path  = "/resource_id"
        order = "ascending"
      }
      index {
        path  = "/detection_rule"
        order = "ascending"
      }
      index {
        path  = "/created_at"
        order = "descending"
      }
      index {
        path  = "/status"
        order = "ascending"
      }
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

resource "azurerm_cosmosdb_sql_container" "sessions" {
  name                  = "sessions"
  resource_group_name   = var.resource_group_name
  account_name          = azurerm_cosmosdb_account.main.name
  database_name         = azurerm_cosmosdb_sql_database.main.name
  partition_key_paths   = ["/incident_id"]
  partition_key_version = 2

  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }

    excluded_path {
      path = "/iterations/history/*"
    }

    excluded_path {
      path = "/_etag/?"
    }
  }
}

# NOTE: Cosmos DB private endpoint is created by modules/private-endpoints (task 03.07),
# NOT in this file. This prevents duplicate PE definitions (ISSUE-01).

# Cosmos DB data-plane RBAC — Built-in Data Contributor for all agent MIs
# local_authentication_disabled = true means all data access requires data-plane RBAC.
# ARM role "Cosmos DB Operator" (assigned by rbac module) is control-plane only.
# This resource manages the data-plane role assignments that allow document read/write.
#
# Built-in role ID 00000000-0000-0000-0000-000000000002 = Cosmos DB Built-in Data Contributor
# Scope = Cosmos account (not database or container level, matching what was done manually)
resource "azurerm_cosmosdb_sql_role_assignment" "data_contributor" {
  for_each = var.agent_principal_ids

  resource_group_name = var.resource_group_name
  account_name        = azurerm_cosmosdb_account.main.name
  role_definition_id  = "${azurerm_cosmosdb_account.main.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id        = each.value
  scope               = azurerm_cosmosdb_account.main.id
}
