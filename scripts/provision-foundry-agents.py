#!/usr/bin/env python3
"""Provision all 9 Foundry agents (orchestrator + 8 domain) idempotently.

Outputs scripts/agents.tfvars with Terraform variable assignments so that
``terraform apply -var-file`` can consume the agent IDs without manual steps.

Usage:
    # Dry run — prints what would be created, no API calls made
    python3 scripts/provision-foundry-agents.py --dry-run

    # Create/verify agents, write agents.tfvars, skip Container App update
    python3 scripts/provision-foundry-agents.py --no-deploy

    # Create/verify agents and wire env vars to a Container App
    python3 scripts/provision-foundry-agents.py \\
        --resource-group rg-aap-prod \\
        --orchestrator-app ca-api-gateway-prod

    # Re-run safely — skips any agent that already exists by name

Environment variables:
    AZURE_PROJECT_ENDPOINT  Foundry project endpoint URL (required)
"""
from __future__ import annotations

import argparse
import importlib
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPTS_DIR.parent
_TFVARS_PATH = _SCRIPTS_DIR / "agents.tfvars"

_DEFAULT_ORCHESTRATOR_PROMPT = (
    "You are the AAP Orchestrator Agent, the central coordinator for the "
    "Azure Agentic Platform. Route user requests to the appropriate domain specialists."
)


# ---------------------------------------------------------------------------
# Prompt loader
# ---------------------------------------------------------------------------

def _load_prompt(domain: str) -> str:
    """Dynamically load the SYSTEM_PROMPT constant from an agent module.

    Falls back to a sensible default if the module cannot be imported (e.g.,
    when running in CI without the full agent dependencies installed).
    """
    project_root = str(_PROJECT_ROOT)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    try:
        mod = importlib.import_module(f"agents.{domain}.agent")
        for attr in dir(mod):
            if "SYSTEM_PROMPT" in attr and not attr.startswith("_"):
                return getattr(mod, attr)
    except Exception as exc:
        print(f"  WARN: Could not load prompt for '{domain}': {exc}", file=sys.stderr)

    if domain == "orchestrator":
        return _DEFAULT_ORCHESTRATOR_PROMPT
    return f"You are the AAP {domain.title()} Agent, an Azure {domain} specialist."


# ---------------------------------------------------------------------------
# Agent spec model
# ---------------------------------------------------------------------------

@dataclass
class AgentSpec:
    tfvars_key: str   # Terraform variable name, e.g. orchestrator_agent_id
    name: str         # Foundry agent name used for idempotency check
    domain: str       # Module domain for prompt loading


def _build_all_agents() -> list[AgentSpec]:
    """Return ordered specs for orchestrator + all 8 domain agents."""
    return [
        AgentSpec("orchestrator_agent_id", "aap-orchestrator-agent", "orchestrator"),
        AgentSpec("compute_agent_id",      "aap-compute-agent",      "compute"),
        AgentSpec("network_agent_id",      "aap-network-agent",      "network"),
        AgentSpec("storage_agent_id",      "aap-storage-agent",      "storage"),
        AgentSpec("security_agent_id",     "aap-security-agent",     "security"),
        AgentSpec("sre_agent_id",          "aap-sre-agent",          "sre"),
        AgentSpec("arc_agent_id",          "aap-arc-agent",          "arc"),
        AgentSpec("patch_agent_id",        "aap-patch-agent",        "patch"),
        AgentSpec("eol_agent_id",          "aap-eol-agent",          "eol"),
    ]


# ---------------------------------------------------------------------------
# Foundry client
# ---------------------------------------------------------------------------

def _get_client():
    """Build an AgentsClient using DefaultAzureCredential."""
    from azure.identity import DefaultAzureCredential
    from azure.ai.agents import AgentsClient

    endpoint = os.environ.get("AZURE_PROJECT_ENDPOINT") or os.environ.get("FOUNDRY_ACCOUNT_ENDPOINT")
    if not endpoint:
        print(
            "ERROR: AZURE_PROJECT_ENDPOINT (or FOUNDRY_ACCOUNT_ENDPOINT) is not set.",
            file=sys.stderr,
        )
        sys.exit(1)
    return AgentsClient(endpoint=endpoint, credential=DefaultAzureCredential())


# ---------------------------------------------------------------------------
# Agent operations
# ---------------------------------------------------------------------------

def _list_existing(client) -> dict[str, str]:
    """Return {agent_name: agent_id} for all agents visible in this project."""
    existing: dict[str, str] = {}
    try:
        for agent in client.list_agents():
            existing[agent.name] = agent.id
    except Exception as exc:
        print(f"WARN: Could not list existing agents: {exc}", file=sys.stderr)
    return existing


def _provision_or_get(
    client,
    spec: AgentSpec,
    existing: dict[str, str],
    model: str,
    dry_run: bool,
) -> str:
    """Return the agent ID, creating the agent only if it does not exist."""
    if spec.name in existing:
        agent_id = existing[spec.name]
        print(f"  [SKIP]   {spec.name:<24} already exists: {agent_id}")
        return agent_id

    if dry_run:
        print(f"  [DRY RUN] Would create: {spec.name}")
        return "asst_DRY_RUN"

    system_prompt = _load_prompt(spec.domain)
    print(f"  [CREATE] {spec.name:<24} ...", end=" ", flush=True)
    # NOTE: description= is intentionally omitted — GA SDK 2.0.1 does not
    # accept that parameter on create_agent().
    agent = client.create_agent(
        model=model,
        name=spec.name,
        instructions=system_prompt,
    )
    print(f"-> {agent.id}")
    return agent.id


# ---------------------------------------------------------------------------
# tfvars writer
# ---------------------------------------------------------------------------

def _write_tfvars(agent_ids: dict[str, str]) -> None:
    """Write agents.tfvars in HCL variable-assignment format."""
    # Determine column width for alignment
    max_key_len = max(len(k) for k in agent_ids)

    lines: list[str] = [
        "# Generated by scripts/provision-foundry-agents.py — do not edit manually.",
        "# Consumed by: terraform apply -var-file ../../../scripts/agents.tfvars",
        "",
    ]
    for key, value in agent_ids.items():
        padding = " " * (max_key_len - len(key))
        lines.append(f'{key}{padding} = "{value}"')
    lines.append("")  # trailing newline

    _TFVARS_PATH.write_text("\n".join(lines))
    print(f"\n  agents.tfvars written to: {_TFVARS_PATH}")


# ---------------------------------------------------------------------------
# Container App update (optional)
# ---------------------------------------------------------------------------

def _set_container_app_env_vars(
    resource_group: str,
    app_name: str,
    env_vars: dict[str, str],
    dry_run: bool,
) -> None:
    """Wire agent IDs as Container App environment variables via Azure CLI."""
    # Convert tfvars keys (snake_case) → env var names (UPPER_CASE)
    env_assignments = {k.upper(): v for k, v in env_vars.items()}

    cmd = [
        "az", "containerapp", "update",
        "--name", app_name,
        "--resource-group", resource_group,
        "--set-env-vars",
    ] + [f"{k}={v}" for k, v in env_assignments.items()]

    if dry_run:
        print(f"\n[DRY RUN] Would run:")
        print(f"  az containerapp update --name {app_name} --resource-group {resource_group} \\")
        print("    --set-env-vars " + " ".join(f'"{k}={v}"' for k, v in env_assignments.items()))
        return

    print(f"\nUpdating {len(env_assignments)} env vars on {app_name} ...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"  {app_name} updated successfully.")
    else:
        print(f"  ERROR updating {app_name}:", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Provision all 9 AAP Foundry agents idempotently and write agents.tfvars"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be created without making any API calls",
    )
    parser.add_argument(
        "--no-deploy",
        action="store_true",
        help="Create/verify agents and write agents.tfvars but skip Container App env-var update",
    )
    parser.add_argument("--resource-group", default="rg-aap-prod")
    parser.add_argument("--orchestrator-app", default="ca-api-gateway-prod")
    parser.add_argument("--model", default="gpt-4o")
    args = parser.parse_args()

    print("=== AAP Foundry Agent Provisioner ===\n")

    if args.dry_run:
        print("DRY RUN mode — no Foundry API calls will be made.\n")
        # In dry-run mode we still build the spec list; just skip the client.
        all_specs = _build_all_agents()
        for spec in all_specs:
            print(f"  [DRY RUN] Would create or verify: {spec.name} -> {spec.tfvars_key}")
        print("\nDone (dry run).")
        return

    client = _get_client()
    all_specs = _build_all_agents()

    print("Checking existing Foundry agents ...")
    existing = _list_existing(client)
    print(f"  Found {len(existing)} existing agent(s): {list(existing.keys()) or 'none'}\n")

    print("Provisioning agents (9 total):")
    agent_ids: dict[str, str] = {}
    for spec in all_specs:
        agent_id = _provision_or_get(client, spec, existing, args.model, dry_run=False)
        agent_ids[spec.tfvars_key] = agent_id

    print("\n=== Agent IDs ===")
    for key, agent_id in agent_ids.items():
        print(f"  {key} = {agent_id}")

    _write_tfvars(agent_ids)

    if not args.no_deploy:
        _set_container_app_env_vars(
            args.resource_group, args.orchestrator_app, agent_ids, dry_run=False
        )
    else:
        print(
            "\n--no-deploy set. Container App env vars will be managed by Terraform via agents.tfvars."
        )

    print("\nDone.")


if __name__ == "__main__":
    main()
