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

resource "azurerm_cosmosdb_sql_container" "topology" {
  name                  = "topology"
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
      path = "/relationships/[]/target_id/?"
    }

    excluded_path {
      path = "/_etag/?"
    }

    # Composite index for BFS traversal queries:
    #   WHERE resource_id = @id (single-partition reads by topology service)
    #   WHERE resource_type = @type AND last_synced_at >= @cutoff (freshness check)
    composite_index {
      index {
        path  = "/resource_type"
        order = "ascending"
      }
      index {
        path  = "/last_synced_at"
        order = "descending"
      }
    }
  }
}

resource "azurerm_cosmosdb_sql_container" "baselines" {
  name                  = "baselines"
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
      path = "/data_points/[]/*"
    }

    excluded_path {
      path = "/_etag/?"
    }

    # Composite index for the sweep query:
    #   WHERE resource_type = @type AND last_updated >= @cutoff
    #   Used by ForecasterClient.get_all_imminent() to find breach-imminent resources
    composite_index {
      index {
        path  = "/resource_type"
        order = "ascending"
      }
      index {
        path  = "/last_updated"
        order = "descending"
      }
    }

    # Composite index for time-to-breach alert queries:
    #   WHERE resource_id = @id AND time_to_breach_minutes <= @threshold
    composite_index {
      index {
        path  = "/resource_id"
        order = "ascending"
      }
      index {
        path  = "/time_to_breach_minutes"
        order = "ascending"
      }
    }
  }
}

resource "azurerm_cosmosdb_sql_container" "remediation_audit" {
  name                  = "remediation_audit"
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
      path = "/_etag/?"
    }

    # Composite index for WAL stale-monitor query (REMEDI-011):
    #   WHERE c.status = "pending" AND c.wal_written_at < @cutoff
    composite_index {
      index {
        path  = "/status"
        order = "ascending"
      }
      index {
        path  = "/wal_written_at"
        order = "ascending"
      }
    }

    # Composite index for compliance export query (REMEDI-013):
    #   WHERE c.executed_at >= @from AND c.executed_at <= @to
    composite_index {
      index {
        path  = "/executed_at"
        order = "ascending"
      }
      index {
        path  = "/incident_id"
        order = "ascending"
      }
    }
  }
}

resource "azurerm_cosmosdb_sql_container" "pattern_analysis" {
  name                  = "pattern_analysis"
  resource_group_name   = var.resource_group_name
  account_name          = azurerm_cosmosdb_account.main.name
  database_name         = azurerm_cosmosdb_sql_database.main.name
  partition_key_paths   = ["/analysis_date"]
  partition_key_version = 2

  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }

    excluded_path {
      path = "/top_patterns/[]/*"
    }

    excluded_path {
      path = "/_etag/?"
    }
  }
}

resource "azurerm_cosmosdb_sql_container" "business_tiers" {
  name                  = "business_tiers"
  resource_group_name   = var.resource_group_name
  account_name          = azurerm_cosmosdb_account.main.name
  database_name         = azurerm_cosmosdb_sql_database.main.name
  partition_key_paths   = ["/tier_name"]
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

resource "azurerm_cosmosdb_sql_container" "policy_suggestions" {
  name                  = "policy_suggestions"
  resource_group_name   = var.resource_group_name
  account_name          = azurerm_cosmosdb_account.main.name
  database_name         = azurerm_cosmosdb_sql_database.main.name
  partition_key_paths   = ["/action_class"]
  partition_key_version = 2
  default_ttl           = 2592000 # 30 days in seconds

  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }

    excluded_path {
      path = "/\"_etag\"/?"
    }
  }
}

resource "azurerm_cosmosdb_sql_container" "subscriptions" {
  name                  = "subscriptions"
  resource_group_name   = var.resource_group_name
  account_name          = azurerm_cosmosdb_account.main.name
  database_name         = azurerm_cosmosdb_sql_database.main.name
  partition_key_paths   = ["/subscription_id"]
  partition_key_version = 2

  # TTL: none — subscription records are long-lived; registry re-syncs every 6h
  default_ttl = -1

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

resource "azurerm_cosmosdb_sql_container" "war_rooms" {
  name                  = "war_rooms"
  resource_group_name   = var.resource_group_name
  account_name          = azurerm_cosmosdb_account.main.name
  database_name         = azurerm_cosmosdb_sql_database.main.name
  partition_key_paths   = ["/incident_id"]
  partition_key_version = 2
  default_ttl           = 604800 # 7 days — war rooms are operational artefacts

  indexing_policy {
    indexing_mode = "consistent"

    included_path { path = "/*" }
    excluded_path { path = "/annotations/[]/*" }        # large text fields in annotations array — exclude from index
    excluded_path { path = "/_etag/?" }
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
