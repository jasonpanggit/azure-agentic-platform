terraform {
  backend "azurerm" {
    resource_group_name  = "rg-aap-tfstate-dev"
    storage_account_name = "staaptfstatedev"
    container_name       = "tfstate"
    key                  = "foundation.tfstate"
    use_oidc             = true
  }
}
