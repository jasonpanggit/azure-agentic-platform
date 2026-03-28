#!/usr/bin/env python3
"""Configure the Foundry Orchestrator assistant with system instructions and MCP tools.

Usage:
    # Step 1: Update assistant instructions only (no MCP yet)
    python3 scripts/configure-orchestrator.py --instructions-only

    # Step 2: After MCP connection is created, add MCP tools
    python3 scripts/configure-orchestrator.py --mcp-connection azure-mcp-connection

    # Full setup (instructions + MCP tools)
    python3 scripts/configure-orchestrator.py --mcp-connection azure-mcp-connection

Environment variables:
    AZURE_PROJECT_ENDPOINT: Foundry project endpoint URL
    ORCHESTRATOR_AGENT_ID: Existing assistant ID (asst_xxx)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from azure.identity import DefaultAzureCredential
from azure.ai.agents import AgentsClient


ORCHESTRATOR_INSTRUCTIONS = """You are the AAP Orchestrator, an Azure infrastructure operations assistant for the Azure Agentic Platform (AAP).

## Your Capabilities

You help operators manage and monitor their Azure infrastructure. You can:
- Query Azure resources (VMs, storage, networking, databases, etc.)
- Check resource health and monitor metrics
- Investigate alerts and incidents
- Provide operational guidance and best practices

## How to Respond

1. **Azure resource queries**: When operators ask about their Azure resources (e.g., "show my virtual machines", "list storage accounts"), use the available Azure MCP tools to query real resource data. Always provide structured, actionable results.

2. **Operational guidance**: For questions about Azure best practices, troubleshooting, or architecture, provide expert guidance based on Azure Well-Architected Framework principles.

3. **Incident investigation**: When investigating alerts or incidents, follow a systematic approach:
   - Check Activity Log for recent changes (last 2 hours)
   - Query Resource Health for platform status
   - Check relevant metrics and logs
   - Provide a root-cause hypothesis with confidence level

## Response Format

- Use clear, structured output (tables, bullet points)
- Include resource IDs and relevant metadata
- Always note the subscription and resource group context
- If data is unavailable, explain what's needed and suggest next steps

## Safety Constraints

- NEVER execute destructive operations (delete, deallocate, restart) without explicit operator approval
- NEVER expose secrets, connection strings, or credentials in responses
- Always confirm before proposing remediation actions
- Clearly state your confidence level for any diagnosis
"""


def get_client() -> AgentsClient:
    """Create AgentsClient from environment."""
    endpoint = os.environ.get("AZURE_PROJECT_ENDPOINT") or os.environ.get(
        "FOUNDRY_ACCOUNT_ENDPOINT"
    )
    if not endpoint:
        print("ERROR: Set AZURE_PROJECT_ENDPOINT or FOUNDRY_ACCOUNT_ENDPOINT", file=sys.stderr)
        sys.exit(1)

    return AgentsClient(
        endpoint=endpoint,
        credential=DefaultAzureCredential(),
    )


def update_assistant_instructions(client: AgentsClient, agent_id: str) -> None:
    """Update the assistant's system instructions."""
    print(f"Updating assistant {agent_id} instructions...")

    updated = client.update_agent(
        agent_id=agent_id,
        instructions=ORCHESTRATOR_INSTRUCTIONS,
        name="AAP Orchestrator",
        description="Azure Agentic Platform central orchestrator — routes queries to domain agents and MCP tools.",
    )

    print(f"  Name: {updated.name}")
    print(f"  Model: {updated.model}")
    print(f"  Instructions: {len(updated.instructions)} chars")
    print(f"  Tools: {len(updated.tools)} configured")
    print("  Instructions updated successfully.")


def add_mcp_tools(client: AgentsClient, agent_id: str, mcp_server_url: str) -> None:
    """Add MCP tool connection to the assistant.

    Uses the Foundry data-plane API to set MCP tool type on the assistant.
    The MCP tool type requires server_label (alphanumeric + underscore) and server_url.
    """
    print(f"Adding MCP tools from server '{mcp_server_url}'...")

    # Use direct REST API — the SDK doesn't support MCP tool type in azure-ai-agents 1.1.0
    import requests

    endpoint = os.environ.get("AZURE_PROJECT_ENDPOINT") or os.environ.get(
        "FOUNDRY_ACCOUNT_ENDPOINT"
    )
    credential = DefaultAzureCredential()
    token = credential.get_token("https://ai.azure.com/.default")

    url = f"{endpoint}/assistants/{agent_id}?api-version=2025-05-15-preview"
    headers = {
        "Authorization": f"Bearer {token.token}",
        "Content-Type": "application/json",
    }
    body = {
        "tools": [
            {
                "type": "mcp",
                "server_label": "azure_mcp",
                "server_url": mcp_server_url,
            }
        ],
    }

    resp = requests.post(url, headers=headers, json=body)
    if resp.status_code in (200, 201):
        result = resp.json()
        print(f"  Tools: {len(result.get('tools', []))} configured")
        print("  MCP tools added successfully.")
    else:
        print(f"  ERROR: {resp.status_code} -- {resp.text}", file=sys.stderr)
        print("  MCP tool addition failed. You may need to add tools via Azure Portal.")


def show_current_state(client: AgentsClient, agent_id: str) -> None:
    """Show current assistant configuration."""
    agent = client.get_agent(agent_id=agent_id)
    print(f"\nCurrent assistant state:")
    print(f"  ID: {agent.id}")
    print(f"  Name: {agent.name}")
    print(f"  Model: {agent.model}")
    print(f"  Instructions: {len(agent.instructions or '')} chars")
    print(f"  Tools: {len(agent.tools)} configured")
    if agent.tools:
        for tool in agent.tools:
            print(f"    - {tool}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure the Foundry Orchestrator assistant")
    parser.add_argument(
        "--instructions-only",
        action="store_true",
        help="Only update system instructions, skip MCP tools",
    )
    parser.add_argument(
        "--mcp-connection",
        type=str,
        default="",
        help="MCP server URL for Azure MCP Server tools (e.g., https://ca-azure-mcp-prod.xxx.azurecontainerapps.io)",
    )
    parser.add_argument(
        "--agent-id",
        type=str,
        default="",
        help="Override assistant ID (default: from ORCHESTRATOR_AGENT_ID env var)",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Show current assistant state and exit",
    )
    args = parser.parse_args()

    agent_id = args.agent_id or os.environ.get("ORCHESTRATOR_AGENT_ID", "")
    if not agent_id:
        print("ERROR: Set --agent-id or ORCHESTRATOR_AGENT_ID", file=sys.stderr)
        sys.exit(1)

    client = get_client()

    if args.show:
        show_current_state(client, agent_id)
        return

    # Always update instructions
    update_assistant_instructions(client, agent_id)

    # Add MCP tools if connection specified and not instructions-only
    if args.mcp_connection and not args.instructions_only:
        add_mcp_tools(client, agent_id, args.mcp_connection)

    # Show final state
    show_current_state(client, agent_id)
    print("Configuration complete.")


if __name__ == "__main__":
    main()
