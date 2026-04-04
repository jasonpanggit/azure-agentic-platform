terraform {
  backend "azurerm" {
    resource_group_name  = "rg-aap-tfstate-prod"
    storage_account_name = "staaptfstateprod"
    container_name       = "tfstate"
    key                  = "foundation.tfstate"
    use_azuread_auth     = true
    # Auth uses ARM_CLIENT_ID / ARM_CLIENT_SECRET / ARM_TENANT_ID env vars at init time
    # (backend blocks cannot reference Terraform variables)
    # Note: publicNetworkAccess=Enabled on staaptfstateprod required for GitHub Actions runners
  }
}



