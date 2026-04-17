# Network Agent

Domain specialist for Azure networking resources. Supplements the Azure MCP Server (which lacks dedicated VNet/NSG/LB tools) with direct `azure-mgmt-network` SDK wrappers, covering VNets, NSGs, load balancers, DNS, ExpressRoute, VPN gateways, and point-in-time connectivity checks. Never executes remediation without explicit human approval.

## Responsibilities
- List and inspect VNets, subnets, NSG rules, and peering configurations
- Query effective NSG rules and route tables for a given VM NIC
- Run connectivity checks between source and destination endpoints
- Retrieve flow log data and ExpressRoute/VPN circuit states
- Correlate Activity Log (prior 2h) and Resource Health before diagnosing (TRIAGE-002, TRIAGE-003)
- Produce root-cause hypotheses with confidence scores (0.0–1.0) (TRIAGE-004)

## Key Files
- `agent.py` — `ChatAgent` definition, system prompt, MCP tool allowlist (`monitor`, `resourcehealth`, `advisor`, `compute`), and Foundry registration
- `tools.py` — `@ai_function` tools: VNet list, NSG rules, effective routes, connectivity check, flow log query, Activity Log and Resource Health wrappers
- `requirements.txt` — agent-specific dependencies (`azure-mgmt-network`, `azure-mgmt-monitor`, `azure-monitor-query`)
- `Dockerfile` — container image built from `Dockerfile.base`
