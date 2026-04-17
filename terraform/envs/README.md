# terraform/envs

Per-environment Terraform root modules that wire together the shared modules with environment-specific variable values.

## Contents

- `dev/` — development environment configuration
- `staging/` — staging environment configuration
- `prod/` — production environment configuration; state stored in Azure Storage with Entra auth, applied via CI on merge to main
