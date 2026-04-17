# terraform

Infrastructure as Code for the Azure Agentic Platform, using the `azurerm` (~> 4.65.0) and `azapi` (~> 2.9.0) providers. Provisions all platform resources across dev, staging, and prod environments.

## Contents

- `envs/` — per-environment root modules (dev, staging, prod) with `.tfvars` files
- `modules/` — reusable child modules for each platform concern (networking, compute, Foundry, databases, etc.)
