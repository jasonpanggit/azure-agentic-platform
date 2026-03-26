# Plan 05: CI/CD Pipelines & Validation

```yaml
wave: 5
depends_on:
  - PLAN-01-scaffold-and-bootstrap
  - PLAN-04-environment-composition
files_modified:
  - .github/workflows/terraform-plan.yml
  - .github/workflows/terraform-apply.yml
  - .github/workflows/docker-push.yml
autonomous: true
requirements:
  - INFRA-004
  - INFRA-008
```

## Goal

Create the GitHub Actions CI/CD workflows: `terraform-plan.yml` (runs on PR, posts plan output as PR comment, fails on tag lint violations), `terraform-apply.yml` (runs on merge to main, applies to dev automatically with staging/prod gated by GitHub environments, includes pgvector extension setup), and `docker-push.yml` (template workflow for pushing agent images to ACR in Phase 2+). After this wave, the full Terraform CI pipeline is operational.

> **REVISION (ISSUE-04):** Added task 05.04 for pgvector extension setup as a post-deploy step
> in `terraform-apply.yml`. The `local-exec` provisioner was removed from PLAN-03 because
> GitHub-hosted runners cannot reach a VNet-injected PostgreSQL server.

> **REVISION (ISSUE-05):** Fixed tag lint `jq` filter to catch resources with null `tags` field.

> **REVISION (ISSUE-06):** Added `if: steps.plan.outcome == 'success'` condition to tag lint step.

---

## Tasks

<task id="05.01">
<title>Create terraform-plan.yml workflow</title>
<read_first>
- terraform/envs/dev/providers.tf (verify provider versions used)
- terraform/envs/dev/backend.tf (verify backend configuration)
- .planning/phases/01-foundation/01-RESEARCH.md (Section 10: CI/CD Pipeline Design — plan workflow)
- .planning/phases/01-foundation/01-CONTEXT.md (Decisions D-07, D-08)
</read_first>
<action>
Create `.github/workflows/terraform-plan.yml`:

> **REVISION (ISSUE-05):** The tag lint `jq` filter now catches resources with null `tags` field
> OR resources with tags missing required keys. The initial `select(.change.after.tags != null)`
> guard has been removed.

> **REVISION (ISSUE-06):** The "Tag Lint Check" step now has `if: steps.plan.outcome == 'success'`
> so it only runs when `terraform plan` succeeds and the `tfplan` file exists.

```yaml
name: Terraform Plan

on:
  pull_request:
    branches: [main]
    paths:
      - 'terraform/**'
      - '.github/workflows/terraform-plan.yml'

permissions:
  id-token: write
  contents: read
  pull-requests: write

concurrency:
  group: terraform-plan-${{ github.head_ref }}
  cancel-in-progress: true

env:
  TERRAFORM_VERSION: '1.9.8'
  ARM_USE_OIDC: true

jobs:
  plan:
    name: Plan (${{ matrix.environment }})
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        environment: [dev, staging, prod]
        include:
          - environment: dev
            working_directory: terraform/envs/dev
          - environment: staging
            working_directory: terraform/envs/staging
          - environment: prod
            working_directory: terraform/envs/prod

    env:
      ARM_CLIENT_ID: ${{ secrets.AZURE_CLIENT_ID }}
      ARM_SUBSCRIPTION_ID: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
      ARM_TENANT_ID: ${{ secrets.AZURE_TENANT_ID }}
      TF_VAR_subscription_id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
      TF_VAR_tenant_id: ${{ secrets.AZURE_TENANT_ID }}
      TF_VAR_postgres_admin_password: ${{ secrets.POSTGRES_ADMIN_PASSWORD }}

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Terraform
        uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: ${{ env.TERRAFORM_VERSION }}
          terraform_wrapper: true

      - name: Azure Login (OIDC)
        uses: azure/login@v2
        with:
          client-id: ${{ secrets.AZURE_CLIENT_ID }}
          tenant-id: ${{ secrets.AZURE_TENANT_ID }}
          subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}

      - name: Terraform Init
        working-directory: ${{ matrix.working_directory }}
        run: terraform init -input=false

      - name: Terraform Validate
        working-directory: ${{ matrix.working_directory }}
        run: terraform validate

      - name: Terraform Plan
        id: plan
        working-directory: ${{ matrix.working_directory }}
        run: terraform plan -no-color -input=false -out=tfplan
        continue-on-error: true

      - name: Tag Lint Check
        # ISSUE-06: Only run tag lint when terraform plan succeeded and tfplan file exists
        if: steps.plan.outcome == 'success'
        working-directory: ${{ matrix.working_directory }}
        run: |
          terraform show -json tfplan > tfplan.json
          # ISSUE-05: Check ALL resources for required tags, including those with null tags.
          # Resources with null tags field are caught (they're missing all required tags).
          # Resources with tags present but missing required keys are also caught.
          UNTAGGED=$(jq -r '
            [.resource_changes[]? |
              select(.change.actions != ["delete"]) |
              select(
                (.change.after.tags == null) or
                (.change.after.tags.environment == null) or
                (.change.after.tags["managed-by"] != "terraform") or
                (.change.after.tags.project != "aap")
              ) |
              .address
            ] | join("\n")
          ' tfplan.json)
          if [ -n "$UNTAGGED" ]; then
            echo "::error::The following resources are missing required tags (environment, managed-by: terraform, project: aap):"
            echo "$UNTAGGED"
            exit 1
          fi
          echo "All resources have required tags."

      - name: Post Plan to PR
        if: always()
        uses: actions/github-script@v7
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
          script: |
            const planOutput = `${{ steps.plan.outputs.stdout }}`.substring(0, 65000);
            const planExitCode = `${{ steps.plan.outcome }}`;
            const env = `${{ matrix.environment }}`;
            const status = planExitCode === 'success' ? ':white_check_mark:' : ':x:';

            const body = `### ${status} Terraform Plan — \`${env}\`

            <details>
            <summary>Plan output (click to expand)</summary>

            \`\`\`
            ${planOutput}
            \`\`\`

            </details>

            *Triggered by @${{ github.actor }} on \`${{ github.event.pull_request.head.ref }}\`*`;

            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: body
            });

      - name: Plan Status
        if: steps.plan.outcome == 'failure'
        run: exit 1
```
</action>
<acceptance_criteria>
- `.github/workflows/terraform-plan.yml` exists
- Workflow triggers on `pull_request` targeting `main` branch with path filter `terraform/**`
- Workflow has `permissions: id-token: write` (required for OIDC)
- Workflow has `permissions: pull-requests: write` (required for PR comments)
- Matrix strategy includes 3 environments: `dev`, `staging`, `prod`
- Workflow uses `hashicorp/setup-terraform@v3`
- Workflow uses `azure/login@v2` with OIDC (no client-secret)
- Workflow has `ARM_USE_OIDC: true` environment variable
- Workflow contains a "Tag Lint Check" step that parses `tfplan.json` and fails if resources are missing required tags
- Tag lint `jq` filter catches resources with `tags == null` (no tags field at all) **(ISSUE-05)**
- Tag lint checks for `environment`, `managed-by` == `terraform`, and `project` == `aap`
- Tag lint step has `if: steps.plan.outcome == 'success'` condition **(ISSUE-06)**
- Workflow posts plan output as a PR comment using `actions/github-script@v7`
- Workflow fails the job if `terraform plan` fails
</acceptance_criteria>
</task>

<task id="05.02">
<title>Create terraform-apply.yml workflow</title>
<read_first>
- .github/workflows/terraform-plan.yml (plan workflow for consistency)
- .planning/phases/01-foundation/01-RESEARCH.md (Section 10: CI/CD Pipeline Design — apply workflow, environment promotion strategy)
- .planning/phases/01-foundation/01-CONTEXT.md (Decisions D-07)
</read_first>
<action>
Create `.github/workflows/terraform-apply.yml`:

```yaml
name: Terraform Apply

on:
  push:
    branches: [main]
    paths:
      - 'terraform/**'

permissions:
  id-token: write
  contents: read

env:
  TERRAFORM_VERSION: '1.9.8'
  ARM_USE_OIDC: true

jobs:
  apply-dev:
    name: Apply (dev)
    runs-on: ubuntu-latest
    environment: dev

    env:
      ARM_CLIENT_ID: ${{ secrets.AZURE_CLIENT_ID }}
      ARM_SUBSCRIPTION_ID: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
      ARM_TENANT_ID: ${{ secrets.AZURE_TENANT_ID }}
      TF_VAR_subscription_id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
      TF_VAR_tenant_id: ${{ secrets.AZURE_TENANT_ID }}
      TF_VAR_postgres_admin_password: ${{ secrets.POSTGRES_ADMIN_PASSWORD }}

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Terraform
        uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: ${{ env.TERRAFORM_VERSION }}

      - name: Azure Login (OIDC)
        uses: azure/login@v2
        with:
          client-id: ${{ secrets.AZURE_CLIENT_ID }}
          tenant-id: ${{ secrets.AZURE_TENANT_ID }}
          subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}

      - name: Terraform Init
        working-directory: terraform/envs/dev
        run: terraform init -input=false

      - name: Terraform Apply
        working-directory: terraform/envs/dev
        run: terraform apply -auto-approve -input=false

  apply-staging:
    name: Apply (staging)
    runs-on: ubuntu-latest
    needs: apply-dev
    environment: staging

    env:
      ARM_CLIENT_ID: ${{ secrets.AZURE_CLIENT_ID }}
      ARM_SUBSCRIPTION_ID: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
      ARM_TENANT_ID: ${{ secrets.AZURE_TENANT_ID }}
      TF_VAR_subscription_id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
      TF_VAR_tenant_id: ${{ secrets.AZURE_TENANT_ID }}
      TF_VAR_postgres_admin_password: ${{ secrets.POSTGRES_ADMIN_PASSWORD }}

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Terraform
        uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: ${{ env.TERRAFORM_VERSION }}

      - name: Azure Login (OIDC)
        uses: azure/login@v2
        with:
          client-id: ${{ secrets.AZURE_CLIENT_ID }}
          tenant-id: ${{ secrets.AZURE_TENANT_ID }}
          subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}

      - name: Terraform Init
        working-directory: terraform/envs/staging
        run: terraform init -input=false

      - name: Terraform Apply
        working-directory: terraform/envs/staging
        run: terraform apply -auto-approve -input=false

  apply-prod:
    name: Apply (prod)
    runs-on: ubuntu-latest
    needs: apply-staging
    environment: prod

    env:
      ARM_CLIENT_ID: ${{ secrets.AZURE_CLIENT_ID }}
      ARM_SUBSCRIPTION_ID: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
      ARM_TENANT_ID: ${{ secrets.AZURE_TENANT_ID }}
      TF_VAR_subscription_id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
      TF_VAR_tenant_id: ${{ secrets.AZURE_TENANT_ID }}
      TF_VAR_postgres_admin_password: ${{ secrets.POSTGRES_ADMIN_PASSWORD }}

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Terraform
        uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: ${{ env.TERRAFORM_VERSION }}

      - name: Azure Login (OIDC)
        uses: azure/login@v2
        with:
          client-id: ${{ secrets.AZURE_CLIENT_ID }}
          tenant-id: ${{ secrets.AZURE_TENANT_ID }}
          subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}

      - name: Terraform Init
        working-directory: terraform/envs/prod
        run: terraform init -input=false

      - name: Terraform Apply
        working-directory: terraform/envs/prod
        run: terraform apply -auto-approve -input=false
```
</action>
<acceptance_criteria>
- `.github/workflows/terraform-apply.yml` exists
- Workflow triggers on `push` to `main` branch with path filter `terraform/**`
- Workflow has `permissions: id-token: write` (required for OIDC)
- Workflow has 3 sequential jobs: `apply-dev`, `apply-staging`, `apply-prod`
- `apply-staging` has `needs: apply-dev`
- `apply-prod` has `needs: apply-staging`
- Each job has `environment:` set to its respective environment name (for GitHub environment protection rules)
- All jobs use `azure/login@v2` with OIDC (no client-secret)
- All jobs use `terraform apply -auto-approve -input=false`
- `apply-dev` uses `working-directory: terraform/envs/dev`
- `apply-staging` uses `working-directory: terraform/envs/staging`
- `apply-prod` uses `working-directory: terraform/envs/prod`
</acceptance_criteria>
</task>

<task id="05.03">
<title>Create docker-push.yml workflow template</title>
<read_first>
- .planning/phases/01-foundation/01-RESEARCH.md (Section 7: GitHub Actions ACR Push)
- CLAUDE.md (Technology Stack — Container Apps, ACR, GitHub Actions)
</read_first>
<action>
Create `.github/workflows/docker-push.yml`:

```yaml
name: Build & Push Docker Image

on:
  workflow_call:
    inputs:
      image_name:
        description: 'Name of the Docker image (e.g., compute-agent)'
        required: true
        type: string
      dockerfile_path:
        description: 'Path to the Dockerfile'
        required: true
        type: string
      build_context:
        description: 'Docker build context path'
        required: true
        type: string

permissions:
  id-token: write
  contents: read

env:
  ARM_USE_OIDC: true

jobs:
  build-and-push:
    name: Build & Push ${{ inputs.image_name }}
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Azure Login (OIDC)
        uses: azure/login@v2
        with:
          client-id: ${{ secrets.AZURE_CLIENT_ID }}
          tenant-id: ${{ secrets.AZURE_TENANT_ID }}
          subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}

      - name: Login to ACR
        run: az acr login --name ${{ secrets.ACR_NAME }}

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Build and Push
        uses: docker/build-push-action@v6
        with:
          context: ${{ inputs.build_context }}
          file: ${{ inputs.dockerfile_path }}
          push: true
          platforms: linux/amd64
          tags: |
            ${{ secrets.ACR_LOGIN_SERVER }}/${{ inputs.image_name }}:${{ github.sha }}
            ${{ secrets.ACR_LOGIN_SERVER }}/${{ inputs.image_name }}:latest
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: Image Size Check
        run: |
          IMAGE="${{ secrets.ACR_LOGIN_SERVER }}/${{ inputs.image_name }}:${{ github.sha }}"
          SIZE=$(docker manifest inspect "$IMAGE" 2>/dev/null | jq '[.layers[].size] | add // 0')
          SIZE_MB=$((SIZE / 1024 / 1024))
          echo "Image size: ${SIZE_MB}MB"
          if [ "$SIZE_MB" -gt 1500 ]; then
            echo "::error::Image size ${SIZE_MB}MB exceeds 1500MB limit"
            exit 1
          fi
```
</action>
<acceptance_criteria>
- `.github/workflows/docker-push.yml` exists
- Workflow uses `workflow_call` trigger (reusable workflow)
- Workflow has 3 inputs: `image_name`, `dockerfile_path`, `build_context`
- Workflow uses `azure/login@v2` with OIDC
- Workflow contains `az acr login` step
- Workflow uses `docker/build-push-action@v6` with `platforms: linux/amd64`
- Tags include both `${{ github.sha }}` and `latest`
- Workflow contains an "Image Size Check" step that fails if image exceeds 1500MB
- Workflow has `permissions: id-token: write`
</acceptance_criteria>
</task>

<task id="05.04">
<title>Add pgvector extension setup step to terraform-apply.yml</title>
<read_first>
- .github/workflows/terraform-apply.yml (current state after task 05.02)
- terraform/modules/databases/postgres.tf (PLAN-03 task 03.04 — no local-exec, comment about PLAN-05)
</read_first>
<action>

> **NEW TASK (ISSUE-04):** The `terraform_data` `local-exec` provisioner for pgvector was removed
> from the databases module because GitHub-hosted runners cannot reach a VNet-injected PostgreSQL
> server. This task adds a post-Terraform-apply step to `terraform-apply.yml` that:
> 1. Retrieves the runner's egress IP
> 2. Temporarily adds a firewall rule to the PostgreSQL server
> 3. Runs `CREATE EXTENSION IF NOT EXISTS vector;` via psql
> 4. Removes the firewall rule (cleanup runs even if extension creation fails)

Add the following steps to each `apply-*` job in `.github/workflows/terraform-apply.yml`, **after** the "Terraform Apply" step:

```yaml
      - name: Get Runner Egress IP
        id: runner_ip
        run: echo "ip=$(curl -s https://api.ipify.org)" >> "$GITHUB_OUTPUT"

      - name: Add Temporary PostgreSQL Firewall Rule
        run: |
          POSTGRES_SERVER_NAME="aap-postgres-${{ matrix.environment || 'dev' }}"
          RESOURCE_GROUP="rg-aap-${{ matrix.environment || 'dev' }}"
          az postgres flexible-server firewall-rule create \
            --resource-group "$RESOURCE_GROUP" \
            --name "$POSTGRES_SERVER_NAME" \
            --rule-name "gh-runner-temp-$$" \
            --start-ip-address "${{ steps.runner_ip.outputs.ip }}" \
            --end-ip-address "${{ steps.runner_ip.outputs.ip }}"

      - name: Create pgvector Extension
        env:
          PGPASSWORD: ${{ secrets.POSTGRES_ADMIN_PASSWORD }}
        run: |
          POSTGRES_FQDN="aap-postgres-${{ matrix.environment || 'dev' }}.postgres.database.azure.com"
          psql \
            -h "$POSTGRES_FQDN" \
            -U aap_admin \
            -d aap \
            -c "CREATE EXTENSION IF NOT EXISTS vector;"

      - name: Remove Temporary PostgreSQL Firewall Rule
        if: always()
        run: |
          POSTGRES_SERVER_NAME="aap-postgres-${{ matrix.environment || 'dev' }}"
          RESOURCE_GROUP="rg-aap-${{ matrix.environment || 'dev' }}"
          az postgres flexible-server firewall-rule delete \
            --resource-group "$RESOURCE_GROUP" \
            --name "$POSTGRES_SERVER_NAME" \
            --rule-name "gh-runner-temp-$$" \
            --yes || true
```

**IMPORTANT:** Since `terraform-apply.yml` uses separate jobs (not a matrix), these 4 steps must be added to each of the 3 apply jobs (`apply-dev`, `apply-staging`, `apply-prod`) with the correct environment name hardcoded:
- `apply-dev`: `POSTGRES_SERVER_NAME="aap-postgres-dev"`, `RESOURCE_GROUP="rg-aap-dev"`
- `apply-staging`: `POSTGRES_SERVER_NAME="aap-postgres-staging"`, `RESOURCE_GROUP="rg-aap-staging"`
- `apply-prod`: `POSTGRES_SERVER_NAME="aap-postgres-prod"`, `RESOURCE_GROUP="rg-aap-prod"`

Also add `postgresql-client` installation step before the psql step:

```yaml
      - name: Install PostgreSQL Client
        run: |
          sudo apt-get update -qq
          sudo apt-get install -y -qq postgresql-client
```
</action>
<acceptance_criteria>
- `terraform-apply.yml` contains "Get Runner Egress IP" step using `curl -s https://api.ipify.org`
- `terraform-apply.yml` contains "Add Temporary PostgreSQL Firewall Rule" step using `az postgres flexible-server firewall-rule create`
- `terraform-apply.yml` contains "Install PostgreSQL Client" step
- `terraform-apply.yml` contains "Create pgvector Extension" step running `CREATE EXTENSION IF NOT EXISTS vector;` via `psql`
- `terraform-apply.yml` contains "Remove Temporary PostgreSQL Firewall Rule" step with `if: always()` (cleanup even on failure)
- The firewall rule removal step uses `|| true` to avoid failing if the rule doesn't exist
- These steps are present in all 3 apply jobs (dev, staging, prod) with environment-specific server names
- The `PGPASSWORD` is sourced from `${{ secrets.POSTGRES_ADMIN_PASSWORD }}`
</acceptance_criteria>
</task>

---

## Verification

After all tasks complete:
1. `.github/workflows/` directory contains 3 workflow files
2. `terraform-plan.yml` runs on PR, covers all 3 environments, includes tag lint
3. Tag lint catches resources with null tags AND resources missing required tag keys (ISSUE-05)
4. Tag lint only runs when `terraform plan` succeeds (ISSUE-06)
5. `terraform-apply.yml` runs on merge, sequential dev -> staging -> prod with GitHub environment gates
6. `terraform-apply.yml` includes pgvector extension setup with temporary firewall rule (ISSUE-04)
7. `docker-push.yml` is a reusable workflow template for Phase 2+ image builds
8. All workflows use OIDC auth (no client secrets for Azure)

## must_haves

- [ ] `terraform-plan.yml` triggers on PR to main with terraform/** path filter
- [ ] `terraform-plan.yml` tag lint catches resources with `tags == null` (ISSUE-05)
- [ ] `terraform-plan.yml` tag lint has `if: steps.plan.outcome == 'success'` condition (ISSUE-06)
- [ ] `terraform-plan.yml` posts plan output as PR comment
- [ ] `terraform-apply.yml` triggers on push to main with terraform/** path filter
- [ ] `terraform-apply.yml` uses sequential jobs gated by GitHub environments
- [ ] `terraform-apply.yml` includes pgvector extension setup with temp firewall rule (ISSUE-04)
- [ ] pgvector firewall rule is always cleaned up via `if: always()` (ISSUE-04)
- [ ] All workflows use OIDC authentication (no AZURE_CLIENT_SECRET)
- [ ] `docker-push.yml` builds for linux/amd64 and enforces 1500MB image size limit
