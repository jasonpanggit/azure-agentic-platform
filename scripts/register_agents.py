"""Register all 9 AAP agents as versioned PromptAgentDefinitions in Foundry.

Run this script once after Phase 29 deployment, and again after any
agent definition change (instructions, tools, model):

    python scripts/register_agents.py

The script prints the version ID for each registered agent.
Store the version IDs in environment variables if you need to pin to a
specific version. By default, Foundry serves the latest version.
"""
from __future__ import annotations

import logging
import os

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

from agents.arc.agent import create_arc_agent_version
from agents.compute.agent import create_compute_agent_version
from agents.eol.agent import create_eol_agent_version
from agents.network.agent import create_network_agent_version
from agents.orchestrator.agent import create_orchestrator_agent_version
from agents.patch.agent import create_patch_agent_version
from agents.security.agent import create_security_agent_version
from agents.sre.agent import create_sre_agent_version
from agents.storage.agent import create_storage_agent_version

logger = logging.getLogger(__name__)


def register_all_agents(project: AIProjectClient) -> dict[str, object]:
    """Register all 9 AAP agents as versioned Foundry agent definitions.

    Domain agents are registered before the Orchestrator so A2A
    connections resolve correctly.

    Args:
        project: Authenticated AIProjectClient (azure-ai-projects 2.0.x).

    Returns:
        Dict mapping agent_name -> AgentVersion.
    """
    results: dict[str, object] = {}

    domain_agents = [
        ("aap-compute-agent", create_compute_agent_version),
        ("aap-arc-agent", create_arc_agent_version),
        ("aap-eol-agent", create_eol_agent_version),
        ("aap-network-agent", create_network_agent_version),
        ("aap-patch-agent", create_patch_agent_version),
        ("aap-security-agent", create_security_agent_version),
        ("aap-sre-agent", create_sre_agent_version),
        ("aap-storage-agent", create_storage_agent_version),
    ]

    for agent_name, create_fn in domain_agents:
        logger.info("Registering %s ...", agent_name)
        version = create_fn(project)
        results[agent_name] = version
        logger.info("  %s -> version %s", agent_name, getattr(version, "id", "?"))

    # Orchestrator last — needs domain A2A connections to exist
    logger.info("Registering aap-orchestrator ...")
    orch_version = create_orchestrator_agent_version(project)
    results["aap-orchestrator"] = orch_version
    logger.info("  aap-orchestrator -> version %s", getattr(orch_version, "id", "?"))

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    endpoint = os.environ.get("AZURE_PROJECT_ENDPOINT") or os.environ.get(
        "FOUNDRY_ACCOUNT_ENDPOINT"
    )
    if not endpoint:
        raise SystemExit(
            "ERROR: AZURE_PROJECT_ENDPOINT environment variable not set."
        )

    project = AIProjectClient(
        endpoint=endpoint,
        credential=DefaultAzureCredential(),
    )

    versions = register_all_agents(project)
    print("\nRegistered agent versions:")
    for name, ver in versions.items():
        print(f"  {name}: {getattr(ver, 'id', '?')}")
