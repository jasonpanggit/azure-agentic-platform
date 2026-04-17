# docker

Dockerfiles and build context files for platform container images. All images are built for `linux/amd64` (required by Foundry Hosted Agents) and pushed to the private ACR (`aapcrprodjgmjti.azurecr.io`) via `az acr build --agent-pool aap-builder-prod`.

## Contents

- `github-runner/` — Dockerfile for the self-hosted GitHub Actions runner Container App used for Terraform apply and ACR builds inside the private network
