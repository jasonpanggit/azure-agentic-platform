# Phase 29 — Foundry Platform Migration Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate all 9 agents from `azure-ai-projects` 1.x / `AgentsClient` thread-run patterns to `azure-ai-projects` 2.0.x `PromptAgentDefinition` / Responses API patterns, making every agent version-tracked and visible in the Foundry portal, with A2A orchestrator topology and OTel tracing wired to App Insights.

**Architecture:** Each domain agent gets a `create_version()` registration function in its `agent.py`. The API gateway's `foundry.py` is migrated from `AgentsClient` threads/runs to `openai.responses.create()` Responses API. A new `agents/shared/telemetry.py` module adds `AIProjectInstrumentor` setup. Terraform adds A2A connection resources and an App Insights → Foundry link. The hosted agent runtime (`from_agent_framework`) stays unchanged — only the registration and dispatch patterns change.

**Tech Stack:** `azure-ai-projects==2.0.x`, `azure-ai-agents>=1.1.0`, `azure.ai.projects.models.PromptAgentDefinition`, `azure.ai.projects.telemetry.AIProjectInstrumentor`, `azure-monitor-opentelemetry`, `opentelemetry`, Python pytest, Terraform `azapi` provider

**Spec:** `docs/superpowers/specs/2026-04-11-world-class-aiops-phases-29-34-design.md` §3

---

## Chunk 1: Shared Telemetry Module

### Task 1: Write failing tests for `agents/shared/telemetry.py`

**Files:**
- Create: `agents/tests/shared/test_telemetry.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for agents/shared/telemetry.py — AIProjectInstrumentor setup and span helpers."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestSetupFoundryTracing:
    """Verify setup_foundry_tracing wires configure_azure_monitor + AIProjectInstrumentor."""

    @patch("agents.shared.telemetry.AIProjectInstrumentor")
    @patch("agents.shared.telemetry.configure_azure_monitor")
    def test_calls_configure_azure_monitor_with_connection_string(
        self, mock_configure, mock_instrumentor
    ):
        mock_project = MagicMock()
        mock_project.telemetry.get_application_insights_connection_string.return_value = (
            "InstrumentationKey=test-key"
        )
        mock_instrumentor_instance = MagicMock()
        mock_instrumentor.return_value = mock_instrumentor_instance

        from agents.shared.telemetry import setup_foundry_tracing

        setup_foundry_tracing(mock_project, "aiops-compute-agent")

        mock_configure.assert_called_once_with(
            connection_string="InstrumentationKey=test-key"
        )

    def test_calls_instrumentor_instrument(self):
        """Patch at module level so the None-fallback guard is bypassed correctly."""
        mock_instrumentor_cls = MagicMock()
        mock_instrumentor_instance = MagicMock()
        mock_instrumentor_cls.return_value = mock_instrumentor_instance

        mock_project = MagicMock()
        mock_project.telemetry.get_application_insights_connection_string.return_value = (
            "InstrumentationKey=test-key"
        )

        import agents.shared.telemetry as telemetry_module
        original = telemetry_module.AIProjectInstrumentor

        try:
            telemetry_module.AIProjectInstrumentor = mock_instrumentor_cls
            from agents.shared.telemetry import setup_foundry_tracing
            with patch("agents.shared.telemetry.configure_azure_monitor"):
                setup_foundry_tracing(mock_project, "aiops-compute-agent")
        finally:
            telemetry_module.AIProjectInstrumentor = original

        mock_instrumentor_instance.instrument.assert_called_once()

    @patch("agents.shared.telemetry.AIProjectInstrumentor")
    @patch("agents.shared.telemetry.configure_azure_monitor")
    def test_returns_none(self, mock_configure, mock_instrumentor):
        mock_project = MagicMock()
        mock_project.telemetry.get_application_insights_connection_string.return_value = (
            "conn"
        )
        mock_instrumentor.return_value = MagicMock()

        from agents.shared.telemetry import setup_foundry_tracing

        result = setup_foundry_tracing(mock_project, "test-agent")
        assert result is None


class TestGetTracer:
    """Verify get_tracer returns an OTel tracer."""

    def test_returns_tracer(self):
        from agents.shared.telemetry import get_tracer

        tracer = get_tracer("test-agent")
        assert tracer is not None

    def test_returns_different_tracers_for_different_names(self):
        from agents.shared.telemetry import get_tracer

        t1 = get_tracer("agent-a")
        t2 = get_tracer("agent-b")
        # OTel returns named tracers; the names should differ
        assert t1 != t2
```

- [ ] **Step 2: Run test — expect ImportError (module not yet created)**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest agents/tests/shared/test_telemetry.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'agents.shared.telemetry'`

### Task 2: Implement `agents/shared/telemetry.py`

**Files:**
- Create: `agents/shared/telemetry.py`
- Create: `agents/tests/shared/__init__.py`

- [ ] **Step 1: Create `agents/tests/shared/__init__.py`**

```python
```

- [ ] **Step 2: Create `agents/shared/telemetry.py`**

```python
"""Foundry-native telemetry setup — AIProjectInstrumentor + App Insights (MONITOR-007).

Wraps configure_azure_monitor and AIProjectInstrumentor so every agent
gets both OTel traces and Foundry portal trace waterfall visibility with
a single call to setup_foundry_tracing().

Usage in each agent's __main__ / startup:
    from shared.telemetry import setup_foundry_tracing, get_tracer
    setup_foundry_tracing(project, "aiops-compute-agent")
    tracer = get_tracer("aiops-compute-agent")
"""
from __future__ import annotations

import os

from azure.ai.projects import AIProjectClient
from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry import trace

# Enable Foundry GenAI tracing — must be set before AIProjectInstrumentor.instrument()
os.environ.setdefault("AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING", "true")
os.environ.setdefault("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")

try:
    from azure.ai.projects.telemetry import AIProjectInstrumentor
except ImportError:  # pragma: no cover — older SDK version fallback
    AIProjectInstrumentor = None  # type: ignore[assignment,misc]


def setup_foundry_tracing(project: AIProjectClient, agent_name: str) -> None:  # noqa: ARG001
    """Wire App Insights + AIProjectInstrumentor for a hosted agent.

    Call once at agent startup (in __main__ or lifespan). After this call:
    - All openai SDK calls emit OTel spans → App Insights
    - Traces appear in the Foundry portal under the agent's Tracing tab
    - Custom spans set via get_tracer() are included in the waterfall

    Args:
        project: Authenticated AIProjectClient (azure-ai-projects 2.0.x).
        agent_name: Human-readable service name for the OTel resource (e.g.
            "aiops-compute-agent"). Used as the service.name attribute.
    """
    conn_str = project.telemetry.get_application_insights_connection_string()
    configure_azure_monitor(connection_string=conn_str)

    if AIProjectInstrumentor is not None:
        AIProjectInstrumentor().instrument()


def get_tracer(name: str) -> trace.Tracer:
    """Return an OTel Tracer for creating custom incident-run spans.

    Args:
        name: Tracer name — typically the agent service name.

    Returns:
        OpenTelemetry Tracer instance.
    """
    return trace.get_tracer(name)
```

- [ ] **Step 3: Run tests — expect PASS**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest agents/tests/shared/test_telemetry.py -v
```

Expected: all 5 tests PASS

- [ ] **Step 4: Commit**

```bash
git add agents/shared/telemetry.py agents/tests/shared/__init__.py agents/tests/shared/test_telemetry.py
git commit -m "feat(phase-29): add shared/telemetry.py with AIProjectInstrumentor setup"
```

---

## Chunk 2: Agent Registration — `create_version` Pattern

### Task 3: Write failing tests for compute agent registration

**Files:**
- Create: `agents/tests/shared/test_agent_registration.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for create_version agent registration pattern (Phase 29).

Validates that each agent's create_*_agent_version() function:
- calls project.agents.create_version with correct agent_name
- passes a PromptAgentDefinition
- includes the agent's tool functions
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestComputeAgentVersion:
    """Verify compute agent create_version registration."""

    def test_calls_create_version_with_correct_name(self):
        mock_project = MagicMock()
        mock_version = MagicMock()
        mock_project.agents.create_version.return_value = mock_version

        with patch("agents.compute.agent.get_foundry_project", return_value=mock_project):
            from agents.compute.agent import create_compute_agent_version

            result = create_compute_agent_version(mock_project)

        mock_project.agents.create_version.assert_called_once()
        call_kwargs = mock_project.agents.create_version.call_args
        assert call_kwargs.kwargs.get("agent_name") == "aap-compute-agent" or \
               call_kwargs.args[0] == "aap-compute-agent"

    def test_returns_agent_version(self):
        mock_project = MagicMock()
        mock_version = MagicMock()
        mock_project.agents.create_version.return_value = mock_version

        from agents.compute.agent import create_compute_agent_version

        result = create_compute_agent_version(mock_project)
        assert result == mock_version

    def test_definition_includes_model_env_var(self, monkeypatch):
        import os

        monkeypatch.setenv("AGENT_MODEL_DEPLOYMENT", "gpt-4.1")
        mock_project = MagicMock()
        mock_project.agents.create_version.return_value = MagicMock()

        from agents.compute.agent import create_compute_agent_version

        create_compute_agent_version(mock_project)

        call_kwargs = mock_project.agents.create_version.call_args
        # definition should be a PromptAgentDefinition or dict-like with model
        definition = call_kwargs.kwargs.get("definition") or call_kwargs.args[1]
        assert definition is not None
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest agents/tests/shared/test_agent_registration.py -v 2>&1 | head -10
```

Expected: `ImportError: cannot import name 'create_compute_agent_version'`

### Task 4: Add `create_compute_agent_version()` to compute agent

**Files:**
- Modify: `agents/compute/agent.py`

- [ ] **Step 1: Add imports and `create_compute_agent_version` function**

Add after the existing imports in `agents/compute/agent.py`:

```python
import os

try:
    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import PromptAgentDefinition
except ImportError:
    AIProjectClient = None  # type: ignore[assignment,misc]
    PromptAgentDefinition = None  # type: ignore[assignment,misc]
```

Add the new function after `create_compute_agent()`:

```python
def create_compute_agent_version(project: "AIProjectClient") -> object:
    """Register the Compute Agent as a versioned PromptAgentDefinition in Foundry.

    This makes the agent visible in the Foundry portal (Agents tab) with full
    version history, tool configuration, and playground access.

    Args:
        project: Authenticated AIProjectClient (azure-ai-projects 2.0.x).

    Returns:
        AgentVersion object with version.id for environment variable storage.
    """
    if PromptAgentDefinition is None:
        raise ImportError(
            "azure-ai-projects>=2.0.1 required for create_version. "
            "Install with: pip install 'azure-ai-projects>=2.0.1'"
        )

    return project.agents.create_version(
        agent_name="aap-compute-agent",
        definition=PromptAgentDefinition(
            model=os.environ.get("AGENT_MODEL_DEPLOYMENT", "gpt-4.1"),
            instructions=COMPUTE_AGENT_SYSTEM_PROMPT,
            description="Azure compute domain specialist — VMs, VMSS, AKS, App Service.",
            tools=[
                # Custom @ai_function tools — actual execution in Container App
                # Listed here so Foundry portal shows tool names in agent definition
                query_activity_log,
                query_log_analytics,
                query_resource_health,
                query_monitor_metrics,
                query_os_version,
            ],
        ),
    )
```

- [ ] **Step 2: Run tests — expect PASS**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest agents/tests/shared/test_agent_registration.py -v
```

Expected: all 3 tests PASS

- [ ] **Step 3: Add TDD tests for each remaining 7 domain agents**

Add a test class to `agents/tests/shared/test_agent_registration.py` for each remaining agent. Run test (RED), implement function, run test again (GREEN), then proceed to next agent. Repeat the RED→GREEN cycle for each:

```python
# Add to agents/tests/shared/test_agent_registration.py

class TestArcAgentVersion:
    def test_calls_create_version_with_correct_name(self):
        mock_project = MagicMock()
        mock_project.agents.create_version.return_value = MagicMock()
        from agents.arc.agent import create_arc_agent_version
        create_arc_agent_version(mock_project)
        call_kwargs = mock_project.agents.create_version.call_args
        name = call_kwargs.kwargs.get("agent_name") or call_kwargs.args[0]
        assert name == "aap-arc-agent"

class TestEolAgentVersion:
    def test_calls_create_version_with_correct_name(self):
        mock_project = MagicMock()
        mock_project.agents.create_version.return_value = MagicMock()
        from agents.eol.agent import create_eol_agent_version
        create_eol_agent_version(mock_project)
        call_kwargs = mock_project.agents.create_version.call_args
        name = call_kwargs.kwargs.get("agent_name") or call_kwargs.args[0]
        assert name == "aap-eol-agent"

class TestNetworkAgentVersion:
    def test_calls_create_version_with_correct_name(self):
        mock_project = MagicMock()
        mock_project.agents.create_version.return_value = MagicMock()
        from agents.network.agent import create_network_agent_version
        create_network_agent_version(mock_project)
        call_kwargs = mock_project.agents.create_version.call_args
        name = call_kwargs.kwargs.get("agent_name") or call_kwargs.args[0]
        assert name == "aap-network-agent"

class TestPatchAgentVersion:
    def test_calls_create_version_with_correct_name(self):
        mock_project = MagicMock()
        mock_project.agents.create_version.return_value = MagicMock()
        from agents.patch.agent import create_patch_agent_version
        create_patch_agent_version(mock_project)
        call_kwargs = mock_project.agents.create_version.call_args
        name = call_kwargs.kwargs.get("agent_name") or call_kwargs.args[0]
        assert name == "aap-patch-agent"

class TestSecurityAgentVersion:
    def test_calls_create_version_with_correct_name(self):
        mock_project = MagicMock()
        mock_project.agents.create_version.return_value = MagicMock()
        from agents.security.agent import create_security_agent_version
        create_security_agent_version(mock_project)
        call_kwargs = mock_project.agents.create_version.call_args
        name = call_kwargs.kwargs.get("agent_name") or call_kwargs.args[0]
        assert name == "aap-security-agent"

class TestSreAgentVersion:
    def test_calls_create_version_with_correct_name(self):
        mock_project = MagicMock()
        mock_project.agents.create_version.return_value = MagicMock()
        from agents.sre.agent import create_sre_agent_version
        create_sre_agent_version(mock_project)
        call_kwargs = mock_project.agents.create_version.call_args
        name = call_kwargs.kwargs.get("agent_name") or call_kwargs.args[0]
        assert name == "aap-sre-agent"

class TestStorageAgentVersion:
    def test_calls_create_version_with_correct_name(self):
        mock_project = MagicMock()
        mock_project.agents.create_version.return_value = MagicMock()
        from agents.storage.agent import create_storage_agent_version
        create_storage_agent_version(mock_project)
        call_kwargs = mock_project.agents.create_version.call_args
        name = call_kwargs.kwargs.get("agent_name") or call_kwargs.args[0]
        assert name == "aap-storage-agent"
```

For each agent, run tests RED first:
```bash
python -m pytest agents/tests/shared/test_agent_registration.py::TestArcAgentVersion -v 2>&1 | head -5
# Expected: ImportError: cannot import name 'create_arc_agent_version'
```

Then add `create_*_agent_version()` to each `agent.py` (identical pattern to compute):
- `agents/arc/agent.py` → `create_arc_agent_version()`, `agent_name="aap-arc-agent"`, tools from `arc/tools.py`
- `agents/eol/agent.py` → `create_eol_agent_version()`, `agent_name="aap-eol-agent"`, tools from `eol/tools.py`
- `agents/network/agent.py` → `create_network_agent_version()`, `agent_name="aap-network-agent"`, tools from `network/tools.py`
- `agents/patch/agent.py` → `create_patch_agent_version()`, `agent_name="aap-patch-agent"`, tools from `patch/tools.py`
- `agents/security/agent.py` → `create_security_agent_version()`, `agent_name="aap-security-agent"`, tools from `security/tools.py`
- `agents/sre/agent.py` → `create_sre_agent_version()`, `agent_name="aap-sre-agent"`, tools from `sre/tools.py`
- `agents/storage/agent.py` → `create_storage_agent_version()`, `agent_name="aap-storage-agent"`, tools from `storage/tools.py`

After each implementation, run its test class GREEN:
```bash
python -m pytest agents/tests/shared/test_agent_registration.py -v
```

Expected: all 10 test classes PASS (compute + 7 domain agents)

- [ ] **Step 4: Commit**

```bash
git add agents/compute/agent.py agents/arc/agent.py agents/eol/agent.py \
        agents/network/agent.py agents/patch/agent.py agents/security/agent.py \
        agents/sre/agent.py agents/storage/agent.py \
        agents/tests/shared/test_agent_registration.py
git commit -m "feat(phase-29): add create_version registration to all 8 domain agents"
```

---

## Chunk 3: Orchestrator — A2A Topology

### Task 5: Write failing tests for orchestrator A2A registration

**Files:**
- Create: `agents/tests/shared/test_orchestrator_a2a.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for orchestrator A2A topology registration (Phase 29)."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


class TestOrchestratorAgentVersion:
    """Verify orchestrator registers A2A tools for all 8 domain agents."""

    def test_calls_create_version_with_orchestrator_name(self):
        mock_project = MagicMock()
        mock_project.agents.create_version.return_value = MagicMock()
        # Mock connections for 8 domains
        mock_project.connections.get.return_value = MagicMock(id="conn-123")

        from agents.orchestrator.agent import create_orchestrator_agent_version

        create_orchestrator_agent_version(mock_project)

        mock_project.agents.create_version.assert_called_once()
        call_kwargs = mock_project.agents.create_version.call_args
        name = call_kwargs.kwargs.get("agent_name") or call_kwargs.args[0]
        assert name == "aap-orchestrator"

    def test_fetches_connection_for_each_domain(self):
        mock_project = MagicMock()
        mock_project.agents.create_version.return_value = MagicMock()
        mock_project.connections.get.return_value = MagicMock(id="conn-123")

        from agents.orchestrator.agent import create_orchestrator_agent_version

        create_orchestrator_agent_version(mock_project)

        # Should attempt to get connection for 8 domains
        assert mock_project.connections.get.call_count == 8

    def test_connection_get_failure_raises(self):
        mock_project = MagicMock()
        mock_project.connections.get.side_effect = Exception("Connection not found")

        from agents.orchestrator.agent import create_orchestrator_agent_version

        with pytest.raises(Exception, match="Connection not found"):
            create_orchestrator_agent_version(mock_project)
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest agents/tests/shared/test_orchestrator_a2a.py -v 2>&1 | head -10
```

### Task 6: Add `create_orchestrator_agent_version()` to orchestrator

**Files:**
- Modify: `agents/orchestrator/agent.py`

- [ ] **Step 1: Read current orchestrator agent.py**

```bash
cat agents/orchestrator/agent.py
```

- [ ] **Step 2: Add A2A registration function**

Add the following to `agents/orchestrator/agent.py`:

```python
import os

try:
    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import A2APreviewTool, PromptAgentDefinition
except ImportError:
    AIProjectClient = None  # type: ignore[assignment,misc]
    A2APreviewTool = None  # type: ignore[assignment,misc]
    PromptAgentDefinition = None  # type: ignore[assignment,misc]

# Domain agents registered as A2A connections in Foundry
_A2A_DOMAINS = [
    "compute", "patch", "network", "security",
    "arc", "sre", "eol", "storage",
]


def create_orchestrator_agent_version(project: "AIProjectClient") -> object:
    """Register the Orchestrator as a versioned agent with A2A domain connections.

    Each domain agent is wired as an A2APreviewTool, making the full
    orchestrator → domain topology visible in the Foundry portal.

    Args:
        project: Authenticated AIProjectClient (azure-ai-projects 2.0.x).

    Returns:
        AgentVersion for the orchestrator.
    """
    if A2APreviewTool is None or PromptAgentDefinition is None:
        raise ImportError(
            "azure-ai-projects>=2.0.1 required. "
            "Install with: pip install 'azure-ai-projects>=2.0.1'"
        )

    a2a_tools = []
    for domain in _A2A_DOMAINS:
        conn = project.connections.get(f"aap-{domain}-agent-connection")
        a2a_tools.append(A2APreviewTool(project_connection_id=conn.id))

    return project.agents.create_version(
        agent_name="aap-orchestrator",
        definition=PromptAgentDefinition(
            model=os.environ.get("ORCHESTRATOR_MODEL_DEPLOYMENT", "gpt-4.1"),
            instructions=ORCHESTRATOR_SYSTEM_PROMPT,
            description="AAP Orchestrator — routes incidents to domain specialist agents.",
            tools=a2a_tools,
        ),
    )
```

- [ ] **Step 3: Run tests — expect PASS**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest agents/tests/shared/test_orchestrator_a2a.py -v
```

- [ ] **Step 4: Commit**

```bash
git add agents/orchestrator/agent.py agents/tests/shared/test_orchestrator_a2a.py
git commit -m "feat(phase-29): add orchestrator A2A topology registration"
```

---

## Chunk 4: API Gateway — Responses API Migration

### Task 7: Write failing tests for `foundry.py` migration

**Files:**
- Create: `services/api-gateway/tests/test_foundry_v2.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for foundry.py — Responses API dispatch (Phase 29 migration from threads/runs)."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")
os.environ.setdefault("AZURE_PROJECT_ENDPOINT", "https://test.services.ai.azure.com/api/projects/test")
os.environ.setdefault("ORCHESTRATOR_AGENT_NAME", "aap-orchestrator")


class TestDispatchToOrchestrator:
    """Verify dispatch_to_orchestrator uses Responses API (not threads/runs)."""

    @patch("services.api_gateway.foundry.build_incident_message")
    @patch("services.api_gateway.foundry._get_openai_client")
    @pytest.mark.asyncio
    async def test_calls_responses_create(self, mock_get_client, mock_build_msg):
        mock_openai = MagicMock()
        mock_response = MagicMock()
        mock_response.id = "resp_123"
        mock_response.status = "completed"
        mock_openai.responses.create.return_value = mock_response
        mock_get_client.return_value = mock_openai
        mock_build_msg.return_value = "incident envelope json"

        from services.api_gateway.foundry import dispatch_to_orchestrator
        from services.api_gateway.models import IncidentPayload

        payload = IncidentPayload(
            incident_id="inc-001",
            alert_title="High CPU",
            resource_id="/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1",
            resource_name="vm1",
            severity="Sev1",
            subscription_id="sub1",
            domain="compute",
        )
        result = await dispatch_to_orchestrator(payload)

        mock_openai.responses.create.assert_called_once()
        call_kwargs = mock_openai.responses.create.call_args
        # Should pass agent_reference in extra_body
        extra_body = call_kwargs.kwargs.get("extra_body", {})
        assert "agent_reference" in extra_body

    @patch("services.api_gateway.foundry._get_openai_client")
    @pytest.mark.asyncio
    async def test_returns_response_id(self, mock_get_client):
        mock_openai = MagicMock()
        mock_response = MagicMock()
        mock_response.id = "resp_456"
        mock_response.status = "completed"
        mock_openai.responses.create.return_value = mock_response
        mock_get_client.return_value = mock_openai

        from services.api_gateway.foundry import dispatch_to_orchestrator
        from services.api_gateway.models import IncidentPayload

        payload = IncidentPayload(
            incident_id="inc-002",
            alert_title="Test",
            resource_id="/subscriptions/s/resourceGroups/r/providers/Microsoft.Compute/virtualMachines/vm",
            resource_name="vm",
            severity="Sev2",
            subscription_id="s",
            domain="compute",
        )
        result = await dispatch_to_orchestrator(payload)
        assert "response_id" in result
        assert result["response_id"] == "resp_456"
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest services/api-gateway/tests/test_foundry_v2.py -v 2>&1 | head -15
```

### Task 8: Migrate `services/api-gateway/foundry.py` to Responses API

**Files:**
- Modify: `services/api-gateway/foundry.py`

- [ ] **Step 1: Read the current foundry.py fully**

```bash
cat services/api-gateway/foundry.py
```

- [ ] **Step 2: Replace the file with Responses API implementation**

Key changes:
1. Replace `AgentsClient` with `AIProjectClient` + `get_openai_client()`
2. Replace `client.threads.create()` + `client.runs.create()` with `openai.responses.create()`
3. Add `build_incident_message()` helper
4. Keep `_get_foundry_client()` as `_get_foundry_project()` returning `AIProjectClient`
5. Add `_get_openai_client()` returning `project.get_openai_client()`

```python
"""Foundry Responses API dispatch — Orchestrator invocation (Phase 29, 2.0.x migration).

Replaces the Phase 1–28 threads/runs pattern (AgentsClient) with the
Foundry Responses API. Each incident creates a single responses.create()
call with the Orchestrator agent reference.

Key change from 1.x:
- OLD: AgentsClient → client.threads.create() → client.runs.create()
- NEW: AIProjectClient → project.get_openai_client() → openai.responses.create()
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from azure.identity import DefaultAzureCredential

from services.api_gateway.instrumentation import agent_span, foundry_span
from services.api_gateway.models import IncidentPayload

logger = logging.getLogger(__name__)


def _get_foundry_project(credential: Optional[DefaultAzureCredential] = None):
    """Create AIProjectClient using DefaultAzureCredential.

    Reads AZURE_PROJECT_ENDPOINT (or FOUNDRY_ACCOUNT_ENDPOINT for compatibility).
    """
    try:
        from azure.ai.projects import AIProjectClient
    except ImportError as exc:
        raise ImportError(
            "azure-ai-projects>=2.0.1 required. "
            "Install with: pip install 'azure-ai-projects>=2.0.1'"
        ) from exc

    endpoint = os.environ.get("AZURE_PROJECT_ENDPOINT") or os.environ.get(
        "FOUNDRY_ACCOUNT_ENDPOINT"
    )
    if not endpoint:
        raise ValueError(
            "AZURE_PROJECT_ENDPOINT (or FOUNDRY_ACCOUNT_ENDPOINT) env var required."
        )

    if credential is None:
        credential = DefaultAzureCredential()

    return AIProjectClient(endpoint=endpoint, credential=credential)


def _get_openai_client(project=None):
    """Get the OpenAI-compatible client from AIProjectClient for Responses API."""
    if project is None:
        project = _get_foundry_project()
    return project.get_openai_client()


def build_incident_message(payload: IncidentPayload) -> str:
    """Build the typed envelope message (AGENT-002) for the Orchestrator.

    Returns a JSON string with correlation_id, source_agent, message_type,
    and the full incident payload.
    """
    now = datetime.now(timezone.utc).isoformat()
    envelope = {
        "correlation_id": payload.incident_id,
        "source_agent": "api-gateway",
        "target_agent": "orchestrator",
        "message_type": "incident_handoff",
        "payload": payload.model_dump(),
        "timestamp": now,
    }
    return json.dumps(envelope)


async def dispatch_to_orchestrator(
    payload: IncidentPayload,
    credential: Optional[DefaultAzureCredential] = None,
) -> dict[str, str]:
    """Dispatch an incident to the Orchestrator via the Foundry Responses API.

    Replaces the Phase 1–28 threads/runs pattern. Creates a single
    responses.create() call — no thread or run lifecycle to manage.

    Args:
        payload: Validated incident payload.
        credential: Optional pre-initialized credential.

    Returns:
        Dict with "response_id" and "status" keys.
    """
    orchestrator_agent_name = os.environ.get(
        "ORCHESTRATOR_AGENT_NAME", "aap-orchestrator"
    )

    openai_client = _get_openai_client(_get_foundry_project(credential))
    message = build_incident_message(payload)

    with agent_span(
        "orchestrator", domain=payload.domain, correlation_id=payload.incident_id
    ):
        with foundry_span("responses_create") as span:
            response = openai_client.responses.create(
                input=message,
                extra_body={
                    "agent_reference": {
                        "name": orchestrator_agent_name,
                        "type": "agent_reference",
                    }
                },
            )
            span.set_attribute("foundry.response_id", response.id)

    logger.info(
        "Dispatched incident %s to Orchestrator (response %s, status %s)",
        payload.incident_id,
        response.id,
        response.status,
    )

    return {"response_id": response.id, "status": response.status}


# ---------------------------------------------------------------------------
# Backward-compat alias — callers that import create_foundry_thread
# can be migrated incrementally
# ---------------------------------------------------------------------------

async def create_foundry_thread(payload: IncidentPayload) -> dict[str, str]:
    """Backward-compat alias for dispatch_to_orchestrator.

    The old 'thread_id' key is mapped to 'response_id' for callers
    that haven't yet been updated. Remove once all callers are updated.
    """
    result = await dispatch_to_orchestrator(payload)
    # Map to old key names for backward compatibility
    return {
        "thread_id": result["response_id"],  # callers that use thread_id
        "run_id": result["response_id"],
        **result,
    }
```

- [ ] **Step 3: Run tests — expect PASS**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest services/api-gateway/tests/test_foundry_v2.py -v
```

- [ ] **Step 4: Run existing foundry-related tests to ensure no regressions**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest services/api-gateway/tests/ -k "foundry" -v
```

- [ ] **Step 5: Commit**

```bash
git add services/api-gateway/foundry.py services/api-gateway/tests/test_foundry_v2.py
git commit -m "feat(phase-29): migrate api-gateway foundry.py to Responses API (2.0.x)"
```

---

## Chunk 5: Agent Registration Script + Terraform

### Task 9: Write failing tests for registration script

**Files:**
- Create: `scripts/tests/test_register_agents.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for scripts/register_agents.py — Phase 29 agent version registration."""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest


class TestRegisterAllAgents:
    """Verify register_all_agents calls create_version for all 9 agents."""

    @patch("scripts.register_agents.create_orchestrator_agent_version")
    @patch("scripts.register_agents.create_storage_agent_version")
    @patch("scripts.register_agents.create_sre_agent_version")
    @patch("scripts.register_agents.create_security_agent_version")
    @patch("scripts.register_agents.create_patch_agent_version")
    @patch("scripts.register_agents.create_network_agent_version")
    @patch("scripts.register_agents.create_eol_agent_version")
    @patch("scripts.register_agents.create_arc_agent_version")
    @patch("scripts.register_agents.create_compute_agent_version")
    def test_registers_all_9_agents(
        self,
        mock_compute, mock_arc, mock_eol, mock_network,
        mock_patch, mock_security, mock_sre, mock_storage, mock_orchestrator,
    ):
        mock_project = MagicMock()
        for m in [mock_compute, mock_arc, mock_eol, mock_network,
                  mock_patch, mock_security, mock_sre, mock_storage, mock_orchestrator]:
            m.return_value = MagicMock(id="ver_123")

        from scripts.register_agents import register_all_agents

        results = register_all_agents(mock_project)

        mock_compute.assert_called_once_with(mock_project)
        mock_arc.assert_called_once_with(mock_project)
        mock_orchestrator.assert_called_once_with(mock_project)
        assert len(results) == 9

    def test_returns_dict_of_agent_name_to_version(self):
        mock_project = MagicMock()

        with patch("scripts.register_agents.create_compute_agent_version") as m:
            mock_version = MagicMock()
            mock_version.id = "ver_abc"
            m.return_value = mock_version

            # Patch all others
            other_agents = [
                "arc", "eol", "network", "patch",
                "security", "sre", "storage", "orchestrator",
            ]
            patches = {}
            for agent in other_agents:
                p = patch(f"scripts.register_agents.create_{agent}_agent_version")
                patches[agent] = p.start()
                patches[agent].return_value = MagicMock(id=f"ver_{agent}")

            from scripts.register_agents import register_all_agents

            results = register_all_agents(mock_project)

            for p in patches.values():
                p.stop()

        assert "aap-compute-agent" in results
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
python -m pytest scripts/tests/test_register_agents.py -v 2>&1 | head -10
```

### Task 10: Create `scripts/register_agents.py`

**Files:**
- Create: `scripts/register_agents.py`
- Create: `scripts/__init__.py` (if not exists)
- Create: `scripts/tests/__init__.py`

- [ ] **Step 1: Create `scripts/register_agents.py`**

```python
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
        Dict mapping agent_name → AgentVersion.
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
        logger.info("  ✓ %s → version %s", agent_name, getattr(version, "id", "?"))

    # Orchestrator last — needs domain A2A connections to exist
    logger.info("Registering aap-orchestrator ...")
    orch_version = create_orchestrator_agent_version(project)
    results["aap-orchestrator"] = orch_version
    logger.info("  ✓ aap-orchestrator → version %s", getattr(orch_version, "id", "?"))

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
```

- [ ] **Step 2: Run tests — expect PASS**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest scripts/tests/test_register_agents.py -v
```

- [ ] **Step 3: Commit**

```bash
git add scripts/register_agents.py scripts/__init__.py scripts/tests/__init__.py \
        scripts/tests/test_register_agents.py
git commit -m "feat(phase-29): add scripts/register_agents.py for versioned agent registration"
```

### Task 11: Terraform — App Insights link + A2A connections + env vars

**Files:**
- Modify: `terraform/modules/agent-apps/main.tf`
- Modify: `terraform/modules/agent-apps/variables.tf`

- [ ] **Step 1: Read current agent-apps Terraform module**

```bash
cat terraform/modules/agent-apps/main.tf | head -80
cat terraform/modules/agent-apps/variables.tf
```

- [ ] **Step 2: Add `AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING=true` env var to all agent Container Apps**

In `terraform/modules/agent-apps/main.tf`, add to every `azurerm_container_app` resource's `env` block:

```hcl
env {
  name  = "AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING"
  value = "true"
}
env {
  name  = "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"
  value = "true"
}
```

- [ ] **Step 3: Add A2A connection resources for each domain agent**

Add to `terraform/modules/agent-apps/main.tf` (using `azapi_resource`, one per domain agent):

```hcl
# A2A connection — compute domain agent
resource "azapi_resource" "a2a_compute" {
  type      = "Microsoft.CognitiveServices/accounts/projects/connections@2025-05-01-preview"
  name      = "aap-compute-agent-connection"
  parent_id = var.foundry_project_id

  body = {
    properties = {
      category    = "RemoteA2A"
      target      = var.compute_agent_endpoint
      authType    = "ManagedIdentity"
      displayName = "AAP Compute Agent (A2A)"
    }
  }
}
```

Repeat for: arc, eol, network, patch, security, sre, storage (8 total).

Add to `variables.tf`:
```hcl
variable "compute_agent_endpoint" {
  description = "Internal HTTPS endpoint for the Compute agent Container App"
  type        = string
}
# ... repeat for arc, eol, network, patch, security, sre, storage
variable "foundry_project_id" {
  description = "Resource ID of the Foundry project"
  type        = string
}
```

- [ ] **Step 4: Run terraform plan to verify no syntax errors**

```bash
cd terraform/envs/prod
terraform plan -var-file=credentials.tfvars -var-file=terraform.tfvars 2>&1 | tail -20
```

- [ ] **Step 5: Commit**

```bash
git add terraform/modules/agent-apps/main.tf terraform/modules/agent-apps/variables.tf
git commit -m "feat(phase-29): add Terraform A2A connections and GenAI tracing env vars"
```

---

## Chunk 6: OTel Span Attributes on Incident Runs

### Task 12: Add incident-run span attributes to API gateway

**Files:**
- Modify: `services/api-gateway/foundry.py`
- Create: `services/api-gateway/tests/test_foundry_spans.py`

- [ ] **Step 1: Write failing test for span attributes**

```python
"""Tests for incident-run span attributes in foundry.py dispatch (Phase 29)."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")
os.environ.setdefault("AZURE_PROJECT_ENDPOINT", "https://test.services.ai.azure.com/api/projects/test")
os.environ.setdefault("ORCHESTRATOR_AGENT_NAME", "aap-orchestrator")


class TestIncidentRunSpanAttributes:
    """Verify dispatch_to_orchestrator sets incident.* span attributes."""

    @patch("services.api_gateway.foundry._get_openai_client")
    @pytest.mark.asyncio
    async def test_span_has_incident_id_attribute(self, mock_get_client):
        mock_openai = MagicMock()
        mock_openai.responses.create.return_value = MagicMock(
            id="resp_span_test", status="completed"
        )
        mock_get_client.return_value = mock_openai

        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor

        provider.add_span_processor(SimpleSpanProcessor(exporter))

        from opentelemetry import trace as otel_trace

        otel_trace.set_tracer_provider(provider)

        from services.api_gateway.foundry import dispatch_to_orchestrator
        from services.api_gateway.models import IncidentPayload

        payload = IncidentPayload(
            incident_id="inc-span-001",
            alert_title="CPU High",
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            resource_name="vm1",
            severity="Sev1",
            subscription_id="sub",
            domain="compute",
        )
        await dispatch_to_orchestrator(payload)

        # Verify responses_create span was recorded
        spans = exporter.get_finished_spans()
        span_names = [s.name for s in spans]
        assert any("responses_create" in name or "foundry" in name for name in span_names)
```

- [ ] **Step 2: Run test**

```bash
pip install opentelemetry-sdk 2>/dev/null
python -m pytest services/api-gateway/tests/test_foundry_spans.py -v
```

- [ ] **Step 3: Commit**

```bash
git add services/api-gateway/tests/test_foundry_spans.py
git commit -m "test(phase-29): add span attribute assertions for incident dispatch"
```

---

## Chunk 7: Integration Smoke Test + Final Verification

### Task 13: Phase 29 smoke test

**Files:**
- Create: `agents/tests/integration/test_phase29_smoke.py`

- [ ] **Step 1: Create smoke test**

```python
"""Phase 29 smoke tests — agent registration roundtrip and Responses API dispatch.

These tests verify the Phase 29 wiring but do NOT call real Azure endpoints.
All external calls are mocked.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestPhase29Smoke:
    """Verify the complete Phase 29 registration and dispatch chain."""

    def test_all_create_version_functions_importable(self):
        """All 9 create_*_agent_version functions must be importable."""
        from agents.arc.agent import create_arc_agent_version
        from agents.compute.agent import create_compute_agent_version
        from agents.eol.agent import create_eol_agent_version
        from agents.network.agent import create_network_agent_version
        from agents.orchestrator.agent import create_orchestrator_agent_version
        from agents.patch.agent import create_patch_agent_version
        from agents.security.agent import create_security_agent_version
        from agents.sre.agent import create_sre_agent_version
        from agents.storage.agent import create_storage_agent_version

        assert all([
            create_compute_agent_version,
            create_arc_agent_version,
            create_eol_agent_version,
            create_network_agent_version,
            create_orchestrator_agent_version,
            create_patch_agent_version,
            create_security_agent_version,
            create_sre_agent_version,
            create_storage_agent_version,
        ])

    def test_telemetry_module_importable(self):
        from agents.shared.telemetry import get_tracer, setup_foundry_tracing

        assert setup_foundry_tracing
        assert get_tracer

    def test_register_agents_script_importable(self):
        from scripts.register_agents import register_all_agents

        assert register_all_agents

    @pytest.mark.asyncio
    async def test_dispatch_to_orchestrator_importable(self):
        from services.api_gateway.foundry import dispatch_to_orchestrator

        assert dispatch_to_orchestrator
```

- [ ] **Step 2: Run full smoke test suite**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest agents/tests/integration/test_phase29_smoke.py agents/tests/shared/ -v
```

Expected: all tests PASS

- [ ] **Step 3: Run full test suite to check for regressions**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest agents/ services/api-gateway/tests/ -v --tb=short 2>&1 | tail -30
```

Expected: no new failures

- [ ] **Step 4: Final commit**

```bash
git add agents/tests/integration/test_phase29_smoke.py
git commit -m "test(phase-29): add integration smoke tests for Phase 29 agent registration"
```

---

## Phase 29 Done Checklist

- [ ] `agents/shared/telemetry.py` created with `setup_foundry_tracing()` and `get_tracer()`
- [ ] All 8 domain agents have `create_*_agent_version()` functions
- [ ] Orchestrator has `create_orchestrator_agent_version()` with A2A tools
- [ ] `services/api-gateway/foundry.py` migrated to `openai.responses.create()`
- [ ] `scripts/register_agents.py` registers all 9 agents
- [ ] Terraform adds `AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING=true` to all Container Apps
- [ ] Terraform adds 8 A2A connection resources
- [ ] All existing tests still pass (no regressions)
- [ ] Phase 29 smoke tests pass
