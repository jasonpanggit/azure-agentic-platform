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
