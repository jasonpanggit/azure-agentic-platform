#!/usr/bin/env python3
"""Update domain agent system prompts in Foundry using the source files directly.

Reads each agent's SYSTEM_PROMPT by extracting the string literal from the source file,
then patches the Foundry agent via the REST API.
"""
from __future__ import annotations

import ast
import os
import sys

from azure.identity import DefaultAzureCredential
from azure.ai.agents import AgentsClient


ENDPOINT = os.environ.get("AZURE_PROJECT_ENDPOINT", "https://aap-foundry-prod.services.ai.azure.com/api/projects/aap-project-prod")

AGENT_MAP = {
    "compute":  ("asst_LRwIRuuMi0vxzfe0sN6Gl7ro", "COMPUTE_AGENT_SYSTEM_PROMPT"),
    "network":  ("asst_xgfrgpYy3t0tHMz6XtuZSfkt", "NETWORK_AGENT_SYSTEM_PROMPT"),
    "storage":  ("asst_eyJ5bKQLMpuC17sfeZZmwOkI", "STORAGE_AGENT_SYSTEM_PROMPT"),
    "security": ("asst_E3zcct7P9mKHlqcRzU5CGbp4", "SECURITY_AGENT_SYSTEM_PROMPT"),
    "sre":      ("asst_nSWrfRFyGhMqmtgzuWF4GgKH", "SRE_AGENT_SYSTEM_PROMPT"),
    "arc":      ("asst_xTN3oTWku0R5Cbxsf56WkEdP", "ARC_AGENT_SYSTEM_PROMPT"),
    "patch":    ("asst_XxAMxgwC9NAlKqqN7FLRiA3O", "PATCH_AGENT_SYSTEM_PROMPT"),
}


def extract_prompt(domain: str, var_name: str) -> str:
    """Extract a string constant assigned to var_name using pure AST — no imports executed."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src_path = os.path.join(project_root, "agents", domain, "agent.py")
    with open(src_path) as f:
        source = f.read()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not (isinstance(target, ast.Name) and target.id == var_name):
                continue
            v = node.value
            # Simple string constant: var = "..."
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                return v.value
            # Method call on string constant: var = """...""".strip()
            # AST shape: Call(func=Attribute(value=Constant(str), attr='strip'/'dedent'/etc))
            if (
                isinstance(v, ast.Call)
                and isinstance(v.func, ast.Attribute)
                and isinstance(v.func.value, ast.Constant)
                and isinstance(v.func.value.value, str)
            ):
                raw = v.func.value.value
                method = v.func.attr
                if method == "strip":
                    return raw.strip()
                if method == "dedent":
                    import textwrap
                    return textwrap.dedent(raw)
                return raw  # unknown method, return raw string
            # ast.literal_eval handles concatenated strings
            try:
                return ast.literal_eval(v)
            except (ValueError, TypeError):
                pass
    return ""


def main() -> None:
    client = AgentsClient(endpoint=ENDPOINT, credential=DefaultAzureCredential())

    for domain, (agent_id, var_name) in AGENT_MAP.items():
        print(f"Updating {domain} ({agent_id})...", end=" ", flush=True)
        try:
            prompt = extract_prompt(domain, var_name)
            if not prompt:
                print(f"WARN: empty prompt for {domain}")
                continue
            client.update_agent(
                agent_id=agent_id,
                instructions=prompt,
            )
            print(f"OK ({len(prompt)} chars)")
        except Exception as e:
            print(f"ERROR: {e}")

    print("\nAll domain agent prompts updated.")


if __name__ == "__main__":
    main()
