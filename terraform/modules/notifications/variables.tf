variable "resource_group_name" {
  description = "Name of the Azure resource group"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
}

variable "data_location" {
  description = "ACS data location (e.g. 'United States')"
  type        = string
  default     = "United States"
}

variable "required_tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}
