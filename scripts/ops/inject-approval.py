#!/usr/bin/env python3
"""inject-approval.py — Create a synthetic approval record for deterministic demos.

When the Foundry agent does not autonomously propose remediation (the approval
flow is agent-driven), this script creates a realistic approval record directly
in Cosmos DB so the ProposalCard renders in the Web UI chat stream.

Usage:
    python3 scripts/ops/inject-approval.py \
        --incident-id sim-1712345678 \
        --thread-id thread_abc123

    # With custom proposal text:
    python3 scripts/ops/inject-approval.py \
        --incident-id sim-1712345678 \
        --thread-id thread_abc123 \
        --proposal "Restart the stress-ng process" \
        --risk-level medium

Prerequisites:
    - pip install azure-cosmos azure-identity
    - COSMOS_ENDPOINT environment variable (or --cosmos-endpoint flag)
    - Azure credentials available (az login or managed identity)

The script prints the approval_id and curl commands for approve/reject.
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional


def _get_cosmos_client(endpoint: str):
    """Create a CosmosClient with DefaultAzureCredential."""
    try:
        from azure.cosmos import CosmosClient
        from azure.identity import DefaultAzureCredential
    except ImportError:
        print("ERROR: Missing dependencies. Install with:")
        print("  pip install azure-cosmos azure-identity")
        sys.exit(1)

    credential = DefaultAzureCredential()
    return CosmosClient(url=endpoint, credential=credential)


def create_synthetic_approval(
    cosmos_endpoint: str,
    database_name: str,
    incident_id: str,
    thread_id: str,
    proposal_text: str,
    risk_level: str,
    agent_name: str,
    resource_id: str,
    timeout_minutes: int,
) -> dict:
    """Create a synthetic approval record in Cosmos DB approvals container.

    Returns the full record as written to Cosmos.
    """
    client = _get_cosmos_client(cosmos_endpoint)
    database = client.get_database_client(database_name)
    container = database.get_container_client("approvals")

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=timeout_minutes)
    approval_id = f"appr_{uuid.uuid4()}"
    action_id = f"act_{uuid.uuid4()}"

    record = {
        "id": approval_id,
        "action_id": action_id,
        "thread_id": thread_id,
        "incident_id": incident_id,
        "agent_name": agent_name,
        "status": "pending",
        "risk_level": risk_level,
        "proposed_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "decided_at": None,
        "decided_by": None,
        "executed_at": None,
        "abort_reason": None,
        "resource_snapshot": {
            "resource_id": resource_id,
            "resource_type": "Microsoft.Compute/virtualMachines",
            "resource_group": "aml-rg",
            "subscription_id": "4c727b88-12f4-4c91-9c2b-372aab3bbae9",
            "vm_name": "jumphost",
            "current_state": "Running",
        },
        "proposal": {
            "action": proposal_text,
            "justification": (
                "CPU utilization exceeded 95% on the jumphost VM. "
                "The stress-ng process is consuming all available CPU cores. "
                "Terminating this process will restore normal CPU levels."
            ),
            "estimated_impact": "Low — terminates a synthetic load-generation process",
            "rollback_plan": "Re-run stress-ng if testing must continue",
            "affected_services": ["jumphost VM"],
        },
    }

    result = container.create_item(body=record)
    return result


def main() -> None:
    """Parse arguments and create the synthetic approval."""
    parser = argparse.ArgumentParser(
        description="Create a synthetic approval record in Cosmos DB for demo purposes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--incident-id",
        required=True,
        help="Incident ID from the simulate-real-incident.sh output",
    )
    parser.add_argument(
        "--thread-id",
        required=True,
        help="Foundry thread ID from the simulate-real-incident.sh output",
    )
    parser.add_argument(
        "--proposal",
        default="Terminate stress-ng process on jumphost to reduce CPU utilization to normal levels",
        help="Proposal action text (default: terminate stress-ng)",
    )
    parser.add_argument(
        "--risk-level",
        default="low",
        choices=["low", "medium", "high", "critical"],
        help="Risk level for the proposal (default: low)",
    )
    parser.add_argument(
        "--agent-name",
        default="compute",
        help="Name of the proposing agent (default: compute)",
    )
    parser.add_argument(
        "--resource-id",
        default="/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9/resourceGroups/aml-rg/providers/Microsoft.Compute/virtualMachines/jumphost",
        help="Full ARM resource ID of the target VM",
    )
    parser.add_argument(
        "--timeout-minutes",
        type=int,
        default=30,
        help="Approval expiry timeout in minutes (default: 30)",
    )
    parser.add_argument(
        "--cosmos-endpoint",
        default=os.environ.get("COSMOS_ENDPOINT", "https://aap-cosmos-prod.documents.azure.com:443/"),
        help="Cosmos DB endpoint (default: COSMOS_ENDPOINT env var or aap-cosmos-prod)",
    )
    parser.add_argument(
        "--database-name",
        default=os.environ.get("COSMOS_DATABASE_NAME", "aap"),
        help="Cosmos DB database name (default: aap)",
    )

    args = parser.parse_args()

    print("Creating synthetic approval record...")
    print(f"  Incident ID:  {args.incident_id}")
    print(f"  Thread ID:    {args.thread_id}")
    print(f"  Risk level:   {args.risk_level}")
    print(f"  Proposal:     {args.proposal}")
    print(f"  Cosmos:       {args.cosmos_endpoint}")
    print()

    try:
        record = create_synthetic_approval(
            cosmos_endpoint=args.cosmos_endpoint,
            database_name=args.database_name,
            incident_id=args.incident_id,
            thread_id=args.thread_id,
            proposal_text=args.proposal,
            risk_level=args.risk_level,
            agent_name=args.agent_name,
            resource_id=args.resource_id,
            timeout_minutes=args.timeout_minutes,
        )
    except Exception as exc:
        print(f"ERROR: Failed to create approval record: {exc}")
        sys.exit(1)

    approval_id = record["id"]
    expires_at = record["expires_at"]
    api_gateway = "https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"

    print("Approval record created successfully!")
    print()
    print(f"  Approval ID:  {approval_id}")
    print(f"  Action ID:    {record['action_id']}")
    print(f"  Status:       {record['status']}")
    print(f"  Expires at:   {expires_at}")
    print()
    print("To approve via curl:")
    print(f'  curl -s -X POST "{api_gateway}/api/v1/approvals/{approval_id}/approve?thread_id={args.thread_id}" \\')
    print(f'    -H "Content-Type: application/json" \\')
    print(f'    -d \'{{"decided_by": "operator@demo", "scope_confirmed": true}}\' | python3 -m json.tool')
    print()
    print("To reject via curl:")
    print(f'  curl -s -X POST "{api_gateway}/api/v1/approvals/{approval_id}/reject?thread_id={args.thread_id}" \\')
    print(f'    -H "Content-Type: application/json" \\')
    print(f'    -d \'{{"decided_by": "operator@demo"}}\' | python3 -m json.tool')
    print()
    print("To list pending approvals:")
    print(f'  curl -s "{api_gateway}/api/v1/approvals?status=pending" | python3 -m json.tool')
    print()
    print("The approval should now be visible in the Web UI chat stream")
    print("as a ProposalCard with Approve/Reject buttons.")


if __name__ == "__main__":
    main()
