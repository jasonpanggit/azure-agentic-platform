#!/usr/bin/env python3
"""inject-approval.py — Create a synthetic approval record for deterministic demos.

When the Foundry agent does not autonomously propose remediation (the approval
flow is agent-driven), this script creates a realistic approval record by calling
POST /api/v1/approvals on the API gateway.

The API gateway is the right place to go: it reaches Cosmos DB via private endpoint
inside vnet-aap-prod, so no Cosmos firewall rules or public access are required.

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
    - pip install requests  (stdlib urllib works too, but requests is nicer)
    - API gateway must be reachable (public Container App URL)
    - No authentication required (API_GATEWAY_AUTH_MODE=disabled in prod)

The script prints the approval_id and curl commands for approve/reject.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

API_GATEWAY_DEFAULT = (
    "https://ca-api-gateway-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io"
)


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST JSON to url. Uses requests if available, else urllib."""
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}

    try:
        import requests  # type: ignore[import-untyped]

        resp = requests.post(url, data=body, headers=headers, timeout=30)
        if not resp.ok:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:400]}")
        return resp.json()

    except ImportError:
        import urllib.request

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"HTTP {resp.status}: {resp.read().decode()[:400]}")
            return json.loads(resp.read())


def create_synthetic_approval(
    api_gateway: str,
    incident_id: str,
    thread_id: str,
    proposal_text: str,
    risk_level: str,
    agent_name: str,
    resource_id: str,
    timeout_minutes: int,
) -> dict[str, Any]:
    """Call POST /api/v1/approvals on the API gateway to create the record.

    The gateway writes to Cosmos via its private endpoint — no public Cosmos
    access required.
    """
    url = f"{api_gateway.rstrip('/')}/api/v1/approvals"

    payload: dict[str, Any] = {
        "thread_id": thread_id,
        "incident_id": incident_id,
        "agent_name": agent_name,
        "risk_level": risk_level,
        "timeout_minutes": timeout_minutes,
        "proposal": {
            "action": proposal_text,
            "justification": (
                "CPU utilization exceeded 95% on the jumphost VM. "
                "The PowerShell background jobs are consuming all available CPU cores. "
                "Terminating these jobs will immediately restore normal CPU levels."
            ),
            "estimated_impact": "Low — terminates a synthetic load-generation process",
            "rollback_plan": "Re-run stress jobs if load testing must continue",
            "affected_services": ["jumphost VM"],
        },
        "resource_snapshot": {
            "resource_id": resource_id,
            "resource_type": "Microsoft.Compute/virtualMachines",
            "resource_group": resource_id.split("/resourceGroups/")[1].split("/")[0]
            if "/resourceGroups/" in resource_id
            else "aml-rg",
            "subscription_id": resource_id.split("/subscriptions/")[1].split("/")[0]
            if "/subscriptions/" in resource_id
            else "",
            "vm_name": resource_id.split("/")[-1] if resource_id else "jumphost",
            "current_state": "Running",
        },
    }

    return _post_json(url, payload)


def main() -> None:
    """Parse arguments and create the synthetic approval via the API gateway."""
    parser = argparse.ArgumentParser(
        description="Create a synthetic approval record via the API gateway (no Cosmos access needed).",
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
        default="Terminate CPU-intensive processes on jumphost to restore normal utilization",
        help="Proposal action text",
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
        default=(
            "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9"
            "/resourceGroups/aml-rg"
            "/providers/Microsoft.Compute/virtualMachines/jumphost"
        ),
        help="Full ARM resource ID of the target VM",
    )
    parser.add_argument(
        "--timeout-minutes",
        type=int,
        default=30,
        help="Approval expiry timeout in minutes (default: 30)",
    )
    parser.add_argument(
        "--api-gateway",
        default=os.environ.get("API_GATEWAY_URL", API_GATEWAY_DEFAULT),
        help="API gateway base URL (default: API_GATEWAY_URL env var or prod URL)",
    )

    args = parser.parse_args()

    print("Creating synthetic approval via API gateway...")
    print(f"  API Gateway:  {args.api_gateway}")
    print(f"  Incident ID:  {args.incident_id}")
    print(f"  Thread ID:    {args.thread_id}")
    print(f"  Risk level:   {args.risk_level}")
    print(f"  Proposal:     {args.proposal}")
    print()

    try:
        record = create_synthetic_approval(
            api_gateway=args.api_gateway,
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
    expires_at = record.get("expires_at", "")
    gw = args.api_gateway.rstrip("/")

    print("Approval record created successfully!")
    print()
    print(f"  Approval ID:  {approval_id}")
    print(f"  Action ID:    {record.get('action_id', '')}")
    print(f"  Status:       {record.get('status', 'pending')}")
    print(f"  Expires at:   {expires_at}")
    print()
    print("To approve via curl:")
    print(
        f'  curl -s -X POST "{gw}/api/v1/approvals/{approval_id}/approve'
        f'?thread_id={args.thread_id}" \\'
    )
    print('    -H "Content-Type: application/json" \\')
    print('    -d \'{"decided_by": "operator@demo", "scope_confirmed": true}\' | python3 -m json.tool')
    print()
    print("To reject via curl:")
    print(
        f'  curl -s -X POST "{gw}/api/v1/approvals/{approval_id}/reject'
        f'?thread_id={args.thread_id}" \\'
    )
    print('    -H "Content-Type: application/json" \\')
    print('    -d \'{"decided_by": "operator@demo"}\' | python3 -m json.tool')
    print()
    print("To list pending approvals:")
    print(f'  curl -s "{gw}/api/v1/approvals?status=pending" | python3 -m json.tool')
    print()
    print("The approval should now be visible in the Web UI chat stream")
    print("as a ProposalCard with Approve/Reject buttons.")


if __name__ == "__main__":
    main()
