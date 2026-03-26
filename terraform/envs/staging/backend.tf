terraform {
  backend "azurerm" {
    resource_group_name  = "rg-aap-tfstate-stg"
    storage_account_name = "staaptfstatestg"
    container_name       = "tfstate"
    key                  = "foundation.tfstate"
    use_oidc             = true
  }
}
