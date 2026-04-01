#!/usr/bin/env python3
"""Provision all 8 domain agents in Foundry and wire their IDs to the orchestrator
and API gateway Container Apps.

Usage:
    # Dry run — prints what would be created/updated
    python3 scripts/provision-domain-agents.py --dry-run

    # Create agents and set env vars on orchestrator + api-gateway (default)
    python3 scripts/provision-domain-agents.py \
        --resource-group rg-aap-prod \
        --orchestrator-app ca-orchestrator-prod \
        --api-gateway-app ca-api-gateway-prod

    # Create agents only (skip Container App updates)
    python3 scripts/provision-domain-agents.py --no-deploy

    # Re-run safely — skips agents that already exist by name

Agent IDs are distributed to TWO container apps:
    - ca-orchestrator-prod: needs them for handoff routing decisions
    - ca-api-gateway-prod:  needs them for sub-run scanner (/api/v1/runs/{run_id})
      which dispatches directly to domain agents (task 14-01)

Environment variables:
    AZURE_PROJECT_ENDPOINT: Foundry project endpoint URL (required)
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass


def _load_prompt(domain: str) -> str:
    """Dynamically load system prompt from the agent module."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    try:
        mod = importlib.import_module(f"agents.{domain}.agent")
        for attr in dir(mod):
            if "SYSTEM_PROMPT" in attr and not attr.startswith("_"):
                return getattr(mod, attr)
    except Exception as e:
        print(f"  WARN: Could not load prompt for {domain}: {e}", file=sys.stderr)
    return f"You are the AAP {domain.title()} Agent, an Azure {domain} specialist."


@dataclass
class DomainAgentSpec:
    env_var: str
    name: str
    description: str
    system_prompt: str


def _build_agents() -> list[DomainAgentSpec]:
    specs = [
        ("COMPUTE_AGENT_ID",  "compute-agent",  "Azure compute domain specialist — VMs, VMSS, AKS, App Service.",                   "compute"),
        ("NETWORK_AGENT_ID",  "network-agent",  "Azure network domain specialist — VNets, NSGs, load balancers, DNS, ExpressRoute.", "network"),
        ("STORAGE_AGENT_ID",  "storage-agent",  "Azure storage domain specialist — Blob, Files, ADLS Gen2, managed disks.",          "storage"),
        ("SECURITY_AGENT_ID", "security-agent", "Azure security domain specialist — Defender, Key Vault, RBAC drift.",               "security"),
        ("SRE_AGENT_ID",      "sre-agent",      "SRE generalist — cross-domain monitoring, SLA tracking, and incident fallback.",    "sre"),
        ("ARC_AGENT_ID",      "arc-agent",      "Azure Arc domain specialist — Arc Servers, Arc K8s, Arc Data Services.",            "arc"),
        ("PATCH_AGENT_ID",    "patch-agent",    "Azure patch management specialist — Update Manager compliance, KB-to-CVE mapping.", "patch"),
        ("EOL_AGENT_ID",      "eol-agent",      "End-of-Life lifecycle specialist — EOL detection, software lifecycle status, upgrade planning across Azure VMs, Arc servers, and Arc K8s.", "eol"),
    ]
    return [
        DomainAgentSpec(
            env_var=env_var,
            name=name,
            description=desc,
            system_prompt=_load_prompt(domain),
        )
        for env_var, name, desc, domain in specs
    ]


def get_client():
    from azure.identity import DefaultAzureCredential
    from azure.ai.agents import AgentsClient

    endpoint = os.environ.get("AZURE_PROJECT_ENDPOINT") or os.environ.get("FOUNDRY_ACCOUNT_ENDPOINT")
    if not endpoint:
        print("ERROR: Set AZURE_PROJECT_ENDPOINT or FOUNDRY_ACCOUNT_ENDPOINT", file=sys.stderr)
        sys.exit(1)
    return AgentsClient(endpoint=endpoint, credential=DefaultAzureCredential())


def list_existing_agents(client) -> dict[str, str]:
    existing: dict[str, str] = {}
    try:
        for agent in client.list_agents():
            existing[agent.name] = agent.id
    except Exception as e:
        print(f"WARN: Could not list existing agents: {e}", file=sys.stderr)
    return existing


def provision_or_get_agent(client, spec: DomainAgentSpec, existing: dict[str, str], model: str, dry_run: bool) -> str:
    if spec.name in existing:
        agent_id = existing[spec.name]
        print(f"  [SKIP] {spec.name} already exists: {agent_id}")
        return agent_id
    if dry_run:
        print(f"  [DRY RUN] Would create: {spec.name}")
        return "asst_DRY_RUN"
    print(f"  [CREATE] {spec.name} ...", end=" ", flush=True)
    agent = client.create_agent(
        model=model,
        name=spec.name,
        description=spec.description,
        instructions=spec.system_prompt,
    )
    print(f"-> {agent.id}")
    return agent.id


def set_container_app_env_vars(resource_group: str, app_name: str, env_vars: dict[str, str], dry_run: bool) -> None:
    cmd = [
        "az", "containerapp", "update",
        "--name", app_name,
        "--resource-group", resource_group,
        "--set-env-vars",
    ] + [f"{k}={v}" for k, v in env_vars.items()]

    if dry_run:
        print(f"\n[DRY RUN] Would run:")
        print(f"  az containerapp update --name {app_name} --resource-group {resource_group} \\")
        print(f"    --set-env-vars " + " ".join(f'"{k}={v}"' for k, v in env_vars.items()))
        return

    print(f"\nSetting {len(env_vars)} env vars on {app_name} ...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"  {app_name} updated successfully.")
    else:
        print(f"  ERROR updating {app_name}:", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision domain agents in Foundry")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-deploy", action="store_true", help="Create agents but skip Container App update")
    parser.add_argument("--resource-group", default="rg-aap-prod")
    parser.add_argument("--orchestrator-app", default="ca-orchestrator-prod")
    parser.add_argument("--api-gateway-app", default="ca-api-gateway-prod")
    parser.add_argument("--model", default="gpt-4o")
    args = parser.parse_args()

    print("=== AAP Domain Agent Provisioner ===\n")

    client = get_client()
    domain_agents = _build_agents()

    print("Checking existing Foundry agents...")
    existing = list_existing_agents(client)
    print(f"  Found {len(existing)} existing: {list(existing.keys()) or 'none'}\n")

    print("Provisioning domain agents:")
    agent_ids: dict[str, str] = {}
    for spec in domain_agents:
        agent_id = provision_or_get_agent(client, spec, existing, args.model, args.dry_run)
        agent_ids[spec.env_var] = agent_id

    print("\n=== Agent IDs ===")
    for env_var, agent_id in agent_ids.items():
        print(f"  {env_var}={agent_id}")

    output_path = os.path.join(os.path.dirname(__file__), "domain-agent-ids.json")
    if not args.dry_run:
        with open(output_path, "w") as f:
            json.dump(agent_ids, f, indent=2)
        print(f"\n  Saved to {output_path}")

    if not args.no_deploy:
        # Wire agent IDs to orchestrator (needs them for handoff routing)
        set_container_app_env_vars(args.resource_group, args.orchestrator_app, agent_ids, args.dry_run)
        # Also wire agent IDs to api-gateway (14-01: needed for sub-run scanner /api/v1/runs/{run_id})
        set_container_app_env_vars(args.resource_group, args.api_gateway_app, agent_ids, args.dry_run)
    else:
        print("\n--no-deploy set. To wire manually:")
        print(f"  az containerapp update --name {args.orchestrator_app} --resource-group {args.resource_group} \\")
        print(f"    --set-env-vars " + " ".join(f"{k}={v}" for k, v in agent_ids.items()))
        print(f"  az containerapp update --name {args.api_gateway_app} --resource-group {args.resource_group} \\")
        print(f"    --set-env-vars " + " ".join(f"{k}={v}" for k, v in agent_ids.items()))

    print("\nDone.")


if __name__ == "__main__":
    main()
