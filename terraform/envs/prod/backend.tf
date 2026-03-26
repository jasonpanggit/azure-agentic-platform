terraform {
  backend "azurerm" {
    resource_group_name  = "rg-aap-tfstate-prod"
    storage_account_name = "staaptfstateprod"
    container_name       = "tfstate"
    key                  = "foundation.tfstate"
    use_oidc             = true
  }
}
