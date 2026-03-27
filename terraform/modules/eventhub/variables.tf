variable "resource_group_name" {
  description = "Name of the resource group"
  type        = string
}

variable "location" {
  description = "Azure region for resources"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
}

variable "required_tags" {
  description = "Required tags for all resources"
  type        = map(string)

  validation {
    condition = alltrue([
      contains(keys(var.required_tags), "environment"),
      contains(keys(var.required_tags), "managed-by"),
      contains(keys(var.required_tags), "project"),
      var.required_tags["managed-by"] == "terraform",
      var.required_tags["project"] == "aap",
    ])
    error_message = "Tags must include 'environment', 'managed-by: terraform', and 'project: aap'."
  }
}

variable "subnet_reserved_1_id" {
  description = "Subnet ID for Event Hub VNet integration (snet-reserved-1)"
  type        = string
}

variable "eventhub_partition_count" {
  description = "Event Hub partition count — 2 dev, 10 prod"
  type        = number
  default     = 2
}

variable "eventhub_capacity" {
  description = "Event Hub namespace throughput units"
  type        = number
  default     = 1
}
