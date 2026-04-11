terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.65.0"
    }
    azapi = {
      source  = "azure/azapi"
      version = "~> 2.9.0"
    }
  }
}
