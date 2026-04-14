#!/usr/bin/env bash
# provision-finops-agent.sh
#
# Provisions the FinOps Foundry Agent via azure-ai-projects SDK and prints
# the agent ID for insertion into terraform/envs/prod/terraform.tfvars.
#
# Usage:
#   export AZURE_PROJECT_ENDPOINT="https://..."
#   ./scripts/ops/provision-finops-agent.sh
#
# Prerequisites: az login, python3, azure-ai-projects installed

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

AZURE_PROJECT_ENDPOINT="${AZURE_PROJECT_ENDPOINT:-}"
if [ -z "$AZURE_PROJECT_ENDPOINT" ]; then
  echo "ERROR: AZURE_PROJECT_ENDPOINT is not set" >&2
  echo "  export AZURE_PROJECT_ENDPOINT=https://<account>.api.azureml.ms/..." >&2
  exit 1
fi

echo "Provisioning FinOps Agent on Foundry project: $AZURE_PROJECT_ENDPOINT"

python3 - <<'PYTHON'
import os
import sys

try:
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential
except ImportError:
    print("ERROR: azure-ai-projects package not installed. Run: pip install azure-ai-projects>=2.0.1", file=sys.stderr)
    sys.exit(1)

endpoint = os.environ["AZURE_PROJECT_ENDPOINT"]
model = os.environ.get("FOUNDRY_MODEL_DEPLOYMENT", "gpt-4o")

client = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())

# Read the system prompt from agent.py (or use a minimal inline prompt)
system_prompt = (
    "You are the AAP FinOps Agent. You reason over Azure Cost Management data to surface "
    "wasteful spend, forecast monthly bills, and propose cost-saving actions through the "
    "existing HITL workflow. Always include data_lag_note in cost responses."
)

agent = client.agents.create_agent(
    model=model,
    name="finops-agent",
    description="FinOps specialist — cost breakdown, idle resource detection, RI utilisation, budget forecasting.",
    instructions=system_prompt,
)

print(f"\nFinOps agent provisioned successfully!")
print(f"  Agent ID: {agent.id}")
print(f"\nAdd to terraform/envs/prod/terraform.tfvars:")
print(f'  finops_agent_id = "{agent.id}"')
PYTHON
