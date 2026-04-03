# Plan 21-1: Terraform Activation

---
wave: 1
depends_on: []
files_modified:
  - terraform/envs/prod/main.tf
  - terraform/envs/prod/terraform.tfvars
requirements:
  - PROD-004
autonomous: true
---

## Objective

Flip `enable_fabric_data_plane = false` to `true` in the production Terraform configuration and add documentation comments so the operator knows this is intentional. This is the single Terraform change that provisions all 5 Fabric data-plane resources (workspace, eventhouse, KQL database, activator, lakehouse) in production.

## Tasks

<task id="21-1-01">
<title>Flip enable_fabric_data_plane flag to true</title>
<read_first>
- terraform/envs/prod/main.tf (line 334-345, the fabric module block)
- terraform/modules/fabric/main.tf (all resources gated by count)
- terraform/modules/fabric/variables.tf (variable definition)
</read_first>
<action>
In `terraform/envs/prod/main.tf`, change line 344 from:

```hcl
enable_fabric_data_plane = false
```

to:

```hcl
enable_fabric_data_plane = true
```

Add a comment above the line:

```hcl
# Phase 21: Fabric data plane activated (workspace, Eventhouse, KQL DB, Activator, Lakehouse).
# Post-apply: run scripts/ops/21-2-activate-detection-plane.sh for manual wiring steps.
enable_fabric_data_plane = true
```

The fabric module block (lines 334-345) should look like:

```hcl
module "fabric" {
  source = "../../modules/fabric"

  resource_group_name      = azurerm_resource_group.main.name
  location                 = var.location
  environment              = var.environment
  required_tags            = local.required_tags
  fabric_capacity_sku      = "F4" # Prod: higher capacity
  fabric_admin_email       = var.fabric_admin_email
  fabric_capacity_name     = "fcaapprod"
  # Phase 21: Fabric data plane activated (workspace, Eventhouse, KQL DB, Activator, Lakehouse).
  # Post-apply: run scripts/ops/21-2-activate-detection-plane.sh for manual wiring steps.
  enable_fabric_data_plane = true
}
```
</action>
<acceptance_criteria>
- `grep -n "enable_fabric_data_plane = true" terraform/envs/prod/main.tf` returns exactly 1 match on the line inside the fabric module block
- `grep -c "enable_fabric_data_plane = false" terraform/envs/prod/main.tf` returns 0
- `grep "Phase 21" terraform/envs/prod/main.tf` returns the comment line
- `grep "21-2-activate-detection-plane" terraform/envs/prod/main.tf` returns the comment referencing the operator runbook
</acceptance_criteria>
</task>

<task id="21-1-02">
<title>Add fabric_admin_email to terraform.tfvars if missing</title>
<read_first>
- terraform/envs/prod/terraform.tfvars (check if fabric_admin_email is already set)
- terraform/modules/fabric/variables.tf (variable definition — no default, required)
</read_first>
<action>
Check if `fabric_admin_email` is already defined in `terraform/envs/prod/terraform.tfvars`. If it is NOT present, add the following block after the `enable_teams_bot` line:

```hcl
# Fabric capacity administrator email (required for Fabric module)
# This is the email of the Entra user who administers the Fabric capacity.
# Set via: TF_VAR_fabric_admin_email="admin@yourdomain.com"
# fabric_admin_email = ""  # Set via TF_VAR_fabric_admin_email or credentials.tfvars
```

If it IS already present, no changes needed.

Also check if `fabric_admin_email` is declared as a variable in `terraform/envs/prod/variables.tf`. The fabric module call references `var.fabric_admin_email` — ensure the variable exists.
</action>
<acceptance_criteria>
- `terraform -chdir=terraform/envs/prod fmt -check` exits 0 (no formatting issues introduced)
- `grep "fabric_admin_email" terraform/envs/prod/main.tf` returns 1 match (the module argument)
- Either `grep "fabric_admin_email" terraform/envs/prod/terraform.tfvars` returns a match OR `grep "fabric_admin_email" terraform/envs/prod/variables.tf` confirms the variable is declared
</acceptance_criteria>
</task>

<task id="21-1-03">
<title>Validate Terraform format passes</title>
<read_first>
- terraform/envs/prod/main.tf (the modified file)
</read_first>
<action>
Run `terraform -chdir=terraform/envs/prod fmt -check` to verify the modified file passes formatting.

If formatting fails, run `terraform -chdir=terraform/envs/prod fmt` to auto-fix and commit the formatted version.
</action>
<acceptance_criteria>
- `terraform -chdir=terraform/envs/prod fmt -check` exits with code 0
- `terraform -chdir=terraform/envs/prod fmt -diff` produces no output (no diff means already formatted)
</acceptance_criteria>
</task>

## Verification

After all tasks complete:
1. `grep "enable_fabric_data_plane = true" terraform/envs/prod/main.tf` returns exactly 1 match
2. `grep -c "enable_fabric_data_plane = false" terraform/envs/prod/main.tf` returns 0
3. `terraform -chdir=terraform/envs/prod fmt -check` exits 0

## must_haves

- [ ] `enable_fabric_data_plane` is set to `true` in `terraform/envs/prod/main.tf`
- [ ] No instances of `enable_fabric_data_plane = false` remain in prod main.tf
- [ ] Comment references the operator runbook script path
- [ ] Terraform formatting passes
