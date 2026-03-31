#!/usr/bin/env bash
# bootstrap-github-secrets.sh — Set GitHub Actions secrets for the AAP prod environment.
#
# USAGE:
#   export POSTGRES_ADMIN_PASSWORD="..."
#   export AZURE_OPENAI_ENDPOINT="https://<account>.openai.azure.com/"
#   export AZURE_OPENAI_API_KEY="..."
#   export FOUNDRY_PROJECT_ENDPOINT="https://<account>.services.ai.azure.com/api/projects/<project-id>"
#   ./scripts/bootstrap-github-secrets.sh
#
# REQUIREMENTS:
#   - gh CLI installed and authenticated: gh auth login
#   - Run from the project root (or any directory inside the git repo)
#
# IDEMPOTENT: gh secret set overwrites any existing value — safe to run multiple times.
#
# SECRETS SET:
#   POSTGRES_ADMIN_PASSWORD   — PostgreSQL admin password (Terraform + container env)
#   AZURE_OPENAI_ENDPOINT     — Azure OpenAI / Foundry endpoint used by agents
#   AZURE_OPENAI_API_KEY      — Azure OpenAI API key for agent services
#   FOUNDRY_PROJECT_ENDPOINT  — Full Foundry project endpoint for provision-foundry-agents.py
#
# All values are read from environment variables. Nothing is hardcoded in this script.

set -euo pipefail

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
GH_ENV="prod"

# Auto-detect the repo from the current git remote; fall back to the known default.
if REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null); then
  echo "Detected repo: ${REPO}"
else
  REPO="jasonpanggit/azure-agentic-platform"
  echo "Could not detect repo via gh; using default: ${REPO}"
fi

# ---------------------------------------------------------------------------
# Validate required env vars are set and non-empty
# ---------------------------------------------------------------------------
REQUIRED_VARS=(
  POSTGRES_ADMIN_PASSWORD
  AZURE_OPENAI_ENDPOINT
  AZURE_OPENAI_API_KEY
  FOUNDRY_PROJECT_ENDPOINT
)

missing=()
for var in "${REQUIRED_VARS[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    missing+=("$var")
  fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
  echo ""
  echo "ERROR: The following required environment variables are not set:" >&2
  for var in "${missing[@]}"; do
    echo "  - $var" >&2
  done
  echo ""
  echo "Export them before running this script:" >&2
  echo "  export POSTGRES_ADMIN_PASSWORD=\"...\"" >&2
  echo "  export AZURE_OPENAI_ENDPOINT=\"...\"" >&2
  echo "  export AZURE_OPENAI_API_KEY=\"...\"" >&2
  echo "  export FOUNDRY_PROJECT_ENDPOINT=\"...\"" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Set secrets
# ---------------------------------------------------------------------------
echo ""
echo "Setting GitHub Actions secrets for environment '${GH_ENV}' in repo '${REPO}'..."
echo ""

set_secret() {
  local name="$1"
  local value="$2"
  echo "  • ${name}"
  gh secret set "${name}" \
    --env "${GH_ENV}" \
    --body "${value}" \
    --repo "${REPO}"
}

set_secret "POSTGRES_ADMIN_PASSWORD"  "${POSTGRES_ADMIN_PASSWORD}"
set_secret "AZURE_OPENAI_ENDPOINT"    "${AZURE_OPENAI_ENDPOINT}"
set_secret "AZURE_OPENAI_API_KEY"     "${AZURE_OPENAI_API_KEY}"
set_secret "FOUNDRY_PROJECT_ENDPOINT" "${FOUNDRY_PROJECT_ENDPOINT}"

echo ""
echo "Done. Verify at: https://github.com/${REPO}/settings/environments/${GH_ENV}"
