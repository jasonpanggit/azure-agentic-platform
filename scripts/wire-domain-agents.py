#!/usr/bin/env python3
"""Wire all 8 domain agents to the Foundry orchestrator assistant as connected_agent tools.

Does three things idempotently:
  1. Reads domain-agent-ids.json for the 8 domain agent IDs.
  2. Registers all 8 as connected_agent tools on the orchestrator Foundry assistant
     (reads current tools first, drops stale connected_agent entries, keeps MCP/function tools).
  3. Sets all 8 *_AGENT_ID env vars on the orchestrator Container App.

Usage:
    # Dry run — prints what would happen, touches nothing
    python3 scripts/wire-domain-agents.py --dry-run

    # Execute against prod
    python3 scripts/wire-domain-agents.py \\
        --resource-group rg-aap-prod \\
        --orchestrator-app ca-orchestrator-prod

    # Wire Foundry tools only (skip Container App update)
    python3 scripts/wire-domain-agents.py --no-deploy

Environment variables:
    AZURE_PROJECT_ENDPOINT: Foundry project endpoint URL (required)
    ORCHESTRATOR_AGENT_ID:  Foundry orchestrator assistant ID (required)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Tool name derivation
# COMPUTE_AGENT_ID → "compute_agent"  (strip _AGENT_ID, lowercase, append _agent)
# ---------------------------------------------------------------------------

def _env_var_to_tool_name(env_var: str) -> str:
    """Convert COMPUTE_AGENT_ID → compute_agent."""
    return env_var.replace("_AGENT_ID", "").lower() + "_agent"


# Human-readable descriptions per domain agent tool
_TOOL_DESCRIPTIONS: dict[str, str] = {
    "compute_agent":  "Azure compute domain specialist — VMs, VMSS, AKS, App Service, disks.",
    "network_agent":  "Azure network domain specialist — VNets, NSGs, load balancers, DNS, ExpressRoute.",
    "storage_agent":  "Azure storage domain specialist — Blob, Files, ADLS Gen2, managed disks.",
    "security_agent": "Azure security domain specialist — Defender, Key Vault, RBAC drift, identity.",
    "sre_agent":      "SRE generalist — cross-domain monitoring, SLA tracking, and incident fallback.",
    "arc_agent":      "Azure Arc domain specialist — Arc Servers, Arc K8s, Arc Data Services.",
    "patch_agent":    "Azure patch management specialist — Update Manager compliance, KB-to-CVE mapping.",
    "eol_agent":      "End-of-Life lifecycle specialist — EOL detection, software lifecycle status, upgrade planning.",
}


# ---------------------------------------------------------------------------
# Foundry client
# ---------------------------------------------------------------------------

def _get_client():
    from azure.identity import DefaultAzureCredential
    from azure.ai.agents import AgentsClient

    endpoint = os.environ.get("AZURE_PROJECT_ENDPOINT") or os.environ.get("FOUNDRY_ACCOUNT_ENDPOINT")
    if not endpoint:
        print("ERROR: Set AZURE_PROJECT_ENDPOINT or FOUNDRY_ACCOUNT_ENDPOINT", file=sys.stderr)
        sys.exit(1)
    return AgentsClient(endpoint=endpoint, credential=DefaultAzureCredential())


def _get_orchestrator_id(cli_override: str) -> str:
    agent_id = cli_override or os.environ.get("ORCHESTRATOR_AGENT_ID", "")
    if not agent_id:
        print("ERROR: Set ORCHESTRATOR_AGENT_ID env var or pass --orchestrator-agent-id", file=sys.stderr)
        sys.exit(1)
    return agent_id


# ---------------------------------------------------------------------------
# Load domain agent IDs from domain-agent-ids.json
# ---------------------------------------------------------------------------

def _load_domain_agent_ids() -> dict[str, str]:
    ids_path = os.path.join(os.path.dirname(__file__), "domain-agent-ids.json")
    if not os.path.exists(ids_path):
        print(f"ERROR: {ids_path} not found. Run provision-domain-agents.py first.", file=sys.stderr)
        sys.exit(1)
    with open(ids_path) as f:
        ids: dict[str, str] = json.load(f)
    if len(ids) != 8:
        print(f"WARN: Expected 8 domain agent IDs, found {len(ids)}", file=sys.stderr)
    return ids


# ---------------------------------------------------------------------------
# Foundry tool wiring
# ---------------------------------------------------------------------------

def _build_connected_agent_tools(domain_ids: dict[str, str]) -> list[Any]:
    """Build ConnectedAgentToolDefinition objects for all 8 domain agents."""
    from azure.ai.agents.models import ConnectedAgentDetails, ConnectedAgentToolDefinition

    tools = []
    for env_var, agent_id in domain_ids.items():
        tool_name = _env_var_to_tool_name(env_var)
        description = _TOOL_DESCRIPTIONS.get(tool_name, f"{tool_name} domain specialist.")
        tool = ConnectedAgentToolDefinition(
            connected_agent=ConnectedAgentDetails(
                id=agent_id,
                name=tool_name,
                description=description,
            )
        )
        tools.append(tool)
    return tools


def wire_foundry_tools(client: Any, orchestrator_id: str, domain_ids: dict[str, str], dry_run: bool) -> None:
    """Register all 8 domain agents as connected_agent tools on the orchestrator assistant.

    Reads current tools, drops stale connected_agent entries, keeps MCP/function tools,
    then appends the 8 new connected_agent tool definitions.
    """
    print(f"\nFetching current orchestrator tools ({orchestrator_id})...")
    agent = client.get_agent(agent_id=orchestrator_id)

    current_tools = list(agent.tools or [])
    print(f"  Current tools: {len(current_tools)}")
    for t in current_tools:
        tool_type = getattr(t, "type", None) or (t.get("type") if isinstance(t, dict) else "unknown")
        print(f"    - type={tool_type}")

    # Filter out stale connected_agent entries; keep MCP and function tools
    preserved = []
    dropped = 0
    for t in current_tools:
        tool_type = getattr(t, "type", None) or (t.get("type") if isinstance(t, dict) else None)
        if tool_type == "connected_agent":
            dropped += 1
        else:
            preserved.append(t)

    if dropped:
        print(f"  Dropping {dropped} stale connected_agent tool(s).")
    if preserved:
        print(f"  Preserving {len(preserved)} non-connected_agent tool(s) (MCP/function).")

    new_connected_tools = _build_connected_agent_tools(domain_ids)
    print(f"\nRegistering {len(new_connected_tools)} connected_agent tools:")
    for env_var, agent_id in domain_ids.items():
        tool_name = _env_var_to_tool_name(env_var)
        print(f"  {tool_name} → {agent_id}")

    merged_tools = preserved + new_connected_tools

    if dry_run:
        print(f"\n[DRY RUN] Would call client.update_agent(agent_id={orchestrator_id}, tools=[{len(merged_tools)} tools])")
        return

    client.update_agent(agent_id=orchestrator_id, tools=merged_tools)
    print(f"\n  Foundry update complete. Total tools: {len(merged_tools)}")


# ---------------------------------------------------------------------------
# Container App env var wiring
# ---------------------------------------------------------------------------

def wire_container_app_env_vars(
    resource_group: str,
    app_name: str,
    domain_ids: dict[str, str],
    orchestrator_id: str,
    dry_run: bool,
) -> None:
    """Set all *_AGENT_ID env vars + ORCHESTRATOR_AGENT_ID on the orchestrator Container App."""
    env_vars = dict(domain_ids)
    env_vars["ORCHESTRATOR_AGENT_ID"] = orchestrator_id

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

    print(f"\nSetting {len(env_vars)} env vars on {app_name}...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"  {app_name} updated successfully.")
        print("  Note: new revision will become active in ~30s.")
    else:
        print(f"  ERROR updating {app_name}:", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_foundry_tools(client: Any, orchestrator_id: str) -> None:
    """Print the orchestrator's current tools after wiring."""
    print("\n=== Verification: Orchestrator tool state ===")
    agent = client.get_agent(agent_id=orchestrator_id)
    tools = list(agent.tools or [])
    print(f"  Total tools: {len(tools)}")
    connected_count = 0
    for t in tools:
        tool_type = getattr(t, "type", None) or (t.get("type") if isinstance(t, dict) else "?")
        if tool_type == "connected_agent":
            ca = getattr(t, "connected_agent", None) or (t.get("connected_agent") if isinstance(t, dict) else {})
            name = getattr(ca, "name", None) or (ca.get("name") if isinstance(ca, dict) else "?")
            agent_id = getattr(ca, "id", None) or (ca.get("id") if isinstance(ca, dict) else "?")
            print(f"    [connected_agent] {name} → {agent_id}")
            connected_count += 1
        else:
            print(f"    [{tool_type}]")
    print(f"\n  Connected domain agents: {connected_count}/8")
    if connected_count == 8:
        print("  PASS: All 8 domain agents registered.")
    else:
        print(f"  WARN: Expected 8, got {connected_count}.", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Wire domain agents to the Foundry orchestrator as connected_agent tools")
    parser.add_argument("--dry-run", action="store_true", help="Print what would happen without making changes")
    parser.add_argument("--no-deploy", action="store_true", help="Wire Foundry tools only, skip Container App update")
    parser.add_argument("--resource-group", default="rg-aap-prod")
    parser.add_argument("--orchestrator-app", default="ca-orchestrator-prod")
    parser.add_argument("--orchestrator-agent-id", default="", help="Override ORCHESTRATOR_AGENT_ID env var")
    args = parser.parse_args()

    print("=== AAP Domain Agent Wiring ===")
    if args.dry_run:
        print("(DRY RUN — no changes will be made)\n")
    else:
        print()

    # Load domain agent IDs
    domain_ids = _load_domain_agent_ids()
    print(f"Loaded {len(domain_ids)} domain agent IDs from domain-agent-ids.json:")
    for env_var, agent_id in domain_ids.items():
        print(f"  {env_var} = {agent_id}")

    # Get orchestrator agent ID
    orchestrator_id = _get_orchestrator_id(args.orchestrator_agent_id)
    print(f"\nOrchestrator agent ID: {orchestrator_id}")

    # Connect to Foundry
    client = _get_client()

    # Step 1: Wire connected_agent tools on Foundry assistant
    wire_foundry_tools(client, orchestrator_id, domain_ids, args.dry_run)

    # Step 2: Set env vars on Container App
    if not args.no_deploy:
        wire_container_app_env_vars(
            resource_group=args.resource_group,
            app_name=args.orchestrator_app,
            domain_ids=domain_ids,
            orchestrator_id=orchestrator_id,
            dry_run=args.dry_run,
        )
    else:
        print("\n--no-deploy set. Skipping Container App update.")

    # Step 3: Verify (only on live run)
    if not args.dry_run:
        verify_foundry_tools(client, orchestrator_id)

    print("\nDone.")


if __name__ == "__main__":
    main()
