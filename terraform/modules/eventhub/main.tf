# Event Hub module — Azure Event Hub namespace, hub, consumer groups, and Action Group
# Phase 4: Detection Plane ingest point (DETECT-001)
#
# Resources created here:
#   - azurerm_eventhub_namespace (Standard SKU, private, VNet-locked)
#   - azurerm_eventhub "raw-alerts" (single ingest hub for Azure Monitor alerts)
#   - azurerm_eventhub_consumer_group "eventhouse-consumer" (for Fabric Eventstreams)
#   - azurerm_eventhub_namespace_authorization_rule "action-group-send" (Monitor → EH)
#   - azurerm_eventhub_namespace_authorization_rule "eventhouse-listen" (EH → Eventhouse)
#   - azurerm_monitor_action_group (forwards Azure Monitor alerts to Event Hub)
#
# NOTE: Private endpoint for this namespace is created by modules/private-endpoints.

data "azurerm_subscription" "current" {}

# --- Event Hub Namespace ---

resource "azurerm_eventhub_namespace" "main" {
  name                          = "evhns-aap-${var.environment}"
  location                      = var.location
  resource_group_name           = var.resource_group_name
  sku                           = "Standard"
  capacity                      = var.eventhub_capacity
  auto_inflate_enabled          = var.environment == "prod" ? true : false
  maximum_throughput_units      = var.environment == "prod" ? 10 : 0
  public_network_access_enabled = false

  # network_rulesets.public_network_access_enabled MUST match the namespace-level
  # public_network_access_enabled to avoid the Azure API conflict:
  # "the value of public network access of namespace should be the same as of the network rulesets"
  network_rulesets {
    default_action                = "Deny"
    public_network_access_enabled = false
    trusted_service_access_enabled = true

    virtual_network_rule {
      subnet_id = var.subnet_reserved_1_id
    }
  }

  tags = var.required_tags
}

# --- Event Hub: raw-alerts ---
# Single ingest point for all Azure Monitor alert payloads.

resource "azurerm_eventhub" "raw_alerts" {
  name              = "raw-alerts"
  namespace_id      = azurerm_eventhub_namespace.main.id
  partition_count   = var.eventhub_partition_count
  message_retention = 7
}

# --- Consumer Group: eventhouse-consumer ---
# Used by Fabric Eventstreams to pull messages from the raw-alerts hub.

resource "azurerm_eventhub_consumer_group" "eventhouse" {
  name                = "eventhouse-consumer"
  namespace_name      = azurerm_eventhub_namespace.main.name
  eventhub_name       = azurerm_eventhub.raw_alerts.name
  resource_group_name = var.resource_group_name
}

# --- Authorization Rule: action-group-send ---
# Used by Azure Monitor Action Group to forward alerts to Event Hub.

resource "azurerm_eventhub_namespace_authorization_rule" "action_group_send" {
  name                = "action-group-send"
  namespace_name      = azurerm_eventhub_namespace.main.name
  resource_group_name = var.resource_group_name
  listen              = false
  send                = true
  manage              = false
}

# --- Authorization Rule: eventhouse-listen ---
# Used by Fabric Eventstreams to consume messages from Event Hub.

resource "azurerm_eventhub_namespace_authorization_rule" "eventhouse_listen" {
  name                = "eventhouse-listen"
  namespace_name      = azurerm_eventhub_namespace.main.name
  resource_group_name = var.resource_group_name
  listen              = true
  send                = false
  manage              = false
}

# --- Monitor Action Group ---
# Receives Azure Monitor alerts and forwards them to the raw-alerts Event Hub.

resource "azurerm_monitor_action_group" "main" {
  name                = "ag-aap-alert-forward-${var.environment}"
  resource_group_name = var.resource_group_name
  short_name          = "aap-alerts"

  event_hub_receiver {
    name                    = "forward-to-eventhub"
    event_hub_namespace     = azurerm_eventhub_namespace.main.name
    event_hub_name          = azurerm_eventhub.raw_alerts.name
    subscription_id         = data.azurerm_subscription.current.subscription_id
    use_common_alert_schema = true
  }

  tags = var.required_tags
}
