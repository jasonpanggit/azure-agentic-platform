variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
}

variable "web_ui_public_url" {
  description = "Public URL of the web UI (e.g. https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io)"
  type        = string
  default     = ""
}

variable "additional_redirect_uris" {
  description = "Additional SPA redirect URIs (e.g. localhost for development)"
  type        = list(string)
  default     = ["http://localhost:3000/auth/callback"]
}

variable "keyvault_id" {
  description = "Key Vault resource ID for storing the client ID secret"
  type        = string
}
