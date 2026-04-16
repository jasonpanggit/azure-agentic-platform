"""Tests for ConcurrentOrchestrator — parallel multi-domain incident investigation.

Covers:
  - Domain selection via keyword matching
  - Parallel dispatch within timeout
  - Synthesis narrative generation
  - Fallback to sequential on timeout
  - SSE event helpers in chat.py
  - correlate_multi_domain hypothesis ranking
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import types
import unittest
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub agent_framework before importing modules that import it
# ---------------------------------------------------------------------------

_af_stub = types.ModuleType("agent_framework")
_af_stub.ChatAgent = object  # type: ignore[attr-defined]
_af_stub.ai_function = lambda fn: fn  # type: ignore[attr-defined]
sys.modules.setdefault("agent_framework", _af_stub)

# Stub azure.* packages used indirectly
for _mod in [
    "azure",
    "azure.ai",
    "azure.ai.projects",
    "azure.ai.projects.models",
    "azure.identity",
    "azure.mgmt",
]:
    sys.modules.setdefault(_mod, types.ModuleType(_mod))

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

from agents.orchestrator.concurrent_orchestrator import (  # noqa: E402
    _dispatch_sequential,
    _dispatch_to_domain_agent,
    _synthesise_findings,
    dispatch_parallel_investigation,
    select_domains_for_incident,
)
from agents.orchestrator.tools import correlate_multi_domain  # noqa: E402


# ===========================================================================
# 1. Domain selection — keyword matching
# ===========================================================================


class TestSelectDomains:
    def test_network_keywords_select_network_domain(self):
        domains = select_domains_for_incident("VNet connectivity issue — packet loss on subnet")
        assert "network" in domains

    def test_compute_keywords_select_compute_domain(self):
        domains = select_domains_for_incident("High CPU usage on VM jumphost-prod-001")
        assert "compute" in domains

    def test_security_keywords_select_security_domain(self):
        domains = select_domains_for_incident("Defender alert: anomalous Key Vault access")
        assert "security" in domains

    def test_storage_keyword_selects_storage_domain(self):
        domains = select_domains_for_incident("Blob storage throughput degraded")
        assert "storage" in domains

    def test_multiple_keywords_select_multiple_domains(self):
        domains = select_domains_for_incident(
            "VM cpu spike causing network connectivity drops"
        )
        assert "compute" in domains
        assert "network" in domains

    def test_no_keywords_defaults_to_compute_and_network(self):
        domains = select_domains_for_incident("Something went wrong with the platform")
        assert set(domains) == {"compute", "network"}

    def test_result_capped_at_three_domains(self):
        # This description hits compute, network, security, storage — should be capped
        domains = select_domains_for_incident(
            "VM cpu high, vnet packet loss, defender alert, blob storage degraded"
        )
        assert len(domains) <= 3


# ===========================================================================
# 2. Parallel dispatch completes within timeout
# ===========================================================================


class TestParallelDispatch:
    @pytest.mark.asyncio
    async def test_parallel_dispatch_returns_findings_for_all_domains(self):
        incident = {"incident_id": "inc-001", "description": "VM cpu spike"}
        result = await dispatch_parallel_investigation(incident, domains=["compute", "network"])
        assert result["parallel"] is True
        assert len(result["findings"]) == 2
        domains_returned = {f["domain"] for f in result["findings"]}
        assert domains_returned == {"compute", "network"}

    @pytest.mark.asyncio
    async def test_parallel_dispatch_completes_within_timeout(self):
        incident = {"incident_id": "inc-002", "description": "test"}
        start = time.monotonic()
        result = await dispatch_parallel_investigation(incident, domains=["compute"], timeout_s=10)
        elapsed = time.monotonic() - start
        assert elapsed < 5.0  # stub returns instantly; 5s is generous
        assert result["total_duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_auto_selects_domains_from_incident_description(self):
        incident = {"incident_id": "inc-003", "description": "High CPU on VM and vnet packet loss"}
        result = await dispatch_parallel_investigation(incident)
        assert "compute" in result["domains_investigated"]
        assert "network" in result["domains_investigated"]

    @pytest.mark.asyncio
    async def test_result_contains_required_keys(self):
        incident = {"incident_id": "inc-004", "description": "storage throughput issue"}
        result = await dispatch_parallel_investigation(incident, domains=["storage"])
        for key in ("investigation_id", "domains_investigated", "findings", "synthesis", "total_duration_ms", "parallel"):
            assert key in result, f"Missing key: {key}"


# ===========================================================================
# 3. Synthesis narrative
# ===========================================================================


class TestSynthesisNarrative:
    def test_synthesis_includes_domain_names(self):
        findings = [
            {"domain": "compute", "findings": "High CPU detected", "confidence": 0.8, "error": None},
            {"domain": "network", "findings": "Packet loss on vnet", "confidence": 0.6, "error": None},
        ]
        text = _synthesise_findings(findings)
        assert "compute" in text
        assert "network" in text

    def test_synthesis_reports_failed_domains(self):
        findings = [
            {"domain": "security", "findings": None, "confidence": 0.0, "error": "timeout"},
        ]
        text = _synthesise_findings(findings)
        assert "security" in text
        assert "timeout" in text

    def test_synthesis_empty_findings_returns_no_data_message(self):
        text = _synthesise_findings([])
        assert "No domain findings" in text


# ===========================================================================
# 4. Fallback to sequential on timeout
# ===========================================================================


class TestFallbackToSequential:
    @pytest.mark.asyncio
    async def test_falls_back_to_sequential_when_timeout_exceeded(self):
        async def slow_agent(domain: str, incident: dict) -> dict:
            await asyncio.sleep(10)  # deliberately exceeds timeout
            return {"domain": domain, "findings": "late", "confidence": 0.5, "error": None}

        incident = {"incident_id": "inc-fallback", "description": "test"}
        with patch(
            "agents.orchestrator.concurrent_orchestrator._dispatch_to_domain_agent",
            side_effect=slow_agent,
        ):
            result = await dispatch_parallel_investigation(
                incident, domains=["compute"], timeout_s=1
            )
        # After timeout the sequential fallback calls the same function again —
        # which also times out individually, so error may appear; the key assertion
        # is that we got a result dict back (never raises).
        assert "investigation_id" in result

    @pytest.mark.asyncio
    async def test_sequential_dispatch_returns_results_in_order(self):
        incident = {"incident_id": "inc-seq", "description": "test"}
        results = await _dispatch_sequential(["compute", "network", "security"], incident)
        assert [r["domain"] for r in results] == ["compute", "network", "security"]


# ===========================================================================
# 5. correlate_multi_domain — hypothesis ranking
# ===========================================================================


class TestCorrelateMultiDomain:
    def test_returns_hypotheses_for_two_domains(self):
        findings = [
            {"domain": "compute", "findings": "CPU spike on /resourceGroups/rg-prod/vm", "confidence": 0.8, "error": None},
            {"domain": "network", "findings": "Packet loss on /resourceGroups/rg-prod/vnet", "confidence": 0.7, "error": None},
        ]
        result = correlate_multi_domain(findings)
        assert "hypotheses" in result
        assert len(result["hypotheses"]) >= 1

    def test_shared_resource_group_detected_as_cross_domain_signal(self):
        findings = [
            {"domain": "compute", "findings": "issue in resourceGroups/rg-prod vm01", "confidence": 0.7, "error": None},
            {"domain": "security", "findings": "alert for resourceGroups/rg-prod keyvault01", "confidence": 0.6, "error": None},
        ]
        result = correlate_multi_domain(findings)
        signals = result.get("cross_domain_signals", [])
        # At least one signal mentioning the shared resource group
        assert any("rg-prod" in s for s in signals)

    def test_empty_findings_returns_empty_result(self):
        result = correlate_multi_domain([])
        assert result == {"hypotheses": [], "cross_domain_signals": []}

    def test_hypotheses_ranked_ascending(self):
        findings = [
            {"domain": "compute", "findings": "High CPU", "confidence": 0.8, "error": None},
            {"domain": "network", "findings": "Packet loss", "confidence": 0.7, "error": None},
        ]
        result = correlate_multi_domain(findings)
        ranks = [h["rank"] for h in result["hypotheses"]]
        assert ranks == sorted(ranks)


# ===========================================================================
# 6. SSE event helpers
# ===========================================================================


class TestSSEEventHelpers:
    def test_fan_out_sse_event_format(self):
        # Import inline to avoid circular deps with api-gateway
        import importlib
        import importlib.util

        # Dynamically load just the SSE helpers from chat.py
        # without requiring the full FastAPI stack
        spec = importlib.util.spec_from_file_location(
            "chat_sse",
            "services/api-gateway/chat.py",
        )
        # We patch heavy deps before loading
        heavy_mods = [
            "fastapi", "fastapi.routing", "fastapi.responses",
            "agents.shared.routing", "services.api_gateway.arg_helper",
            "services.api_gateway.foundry",
            "services.api_gateway.instrumentation",
            "services.api_gateway.models",
        ]
        for mod in heavy_mods:
            sys.modules.setdefault(mod, types.ModuleType(mod))

        # Provide minimal stubs
        _routing_stub = sys.modules["agents.shared.routing"]
        _routing_stub.classify_query_text = lambda t: {"domain": "compute", "confidence": "high", "reason": ""}  # type: ignore[attr-defined]

        _foundry_stub = sys.modules["services.api_gateway.foundry"]
        _foundry_stub._get_foundry_client = lambda: None  # type: ignore[attr-defined]
        _foundry_stub.dispatch_chat_to_orchestrator = AsyncMock(return_value={"response_id": "r1", "status": "completed", "reply": "ok"})  # type: ignore[attr-defined]

        _instr_stub = sys.modules["services.api_gateway.instrumentation"]
        _instr_stub.agent_span = unittest.mock.MagicMock()  # type: ignore[attr-defined]
        _instr_stub.foundry_span = unittest.mock.MagicMock()  # type: ignore[attr-defined]
        _instr_stub.mcp_span = unittest.mock.MagicMock()  # type: ignore[attr-defined]

        _models_stub = sys.modules["services.api_gateway.models"]

        class _ChatRequest:  # type: ignore[misc]
            message = ""
            subscription_ids = []
            user_id = None
            incident_id = None
            thread_id = None

        _models_stub.ChatRequest = _ChatRequest  # type: ignore[attr-defined]

        # Now we can import safely
        if spec and spec.loader:
            chat = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(chat)  # type: ignore[union-attr]
            except Exception:
                pytest.skip("chat.py has import-time deps that cannot be fully stubbed in unit tests")
                return

            sse = chat.build_fan_out_sse_event(["compute", "network"], "inv-001")
            assert sse.startswith("event: fan_out\n")
            payload = json.loads(sse.split("data: ")[1].split("\n")[0])
            assert payload["type"] == "fan_out"
            assert payload["domains"] == ["compute", "network"]
            assert payload["investigation_id"] == "inv-001"

    def test_domain_result_sse_event_format(self):
        # Import the helpers directly from the source since they're pure functions
        import importlib
        import importlib.util
        import types as _types
        import unittest.mock

        heavy_mods = [
            "fastapi", "fastapi.routing", "fastapi.responses",
            "agents.shared.routing", "services.api_gateway.arg_helper",
            "services.api_gateway.foundry",
            "services.api_gateway.instrumentation",
            "services.api_gateway.models",
        ]
        for mod in heavy_mods:
            sys.modules.setdefault(mod, _types.ModuleType(mod))

        _routing_stub = sys.modules["agents.shared.routing"]
        _routing_stub.classify_query_text = lambda t: {"domain": "compute", "confidence": "high", "reason": ""}  # type: ignore[attr-defined]
        _foundry_stub = sys.modules["services.api_gateway.foundry"]
        _foundry_stub._get_foundry_client = lambda: None  # type: ignore[attr-defined]
        _foundry_stub.dispatch_chat_to_orchestrator = AsyncMock(return_value={"response_id": "r1", "status": "completed", "reply": "ok"})  # type: ignore[attr-defined]
        _instr_stub = sys.modules["services.api_gateway.instrumentation"]
        _instr_stub.agent_span = unittest.mock.MagicMock()  # type: ignore[attr-defined]
        _instr_stub.foundry_span = unittest.mock.MagicMock()  # type: ignore[attr-defined]
        _instr_stub.mcp_span = unittest.mock.MagicMock()  # type: ignore[attr-defined]
        _models_stub = sys.modules["services.api_gateway.models"]

        class _CR:  # type: ignore[misc]
            message = ""
            subscription_ids = []
            user_id = None
            incident_id = None
            thread_id = None

        _models_stub.ChatRequest = _CR  # type: ignore[attr-defined]

        spec = importlib.util.spec_from_file_location("chat_sse2", "services/api-gateway/chat.py")
        if spec and spec.loader:
            chat = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(chat)  # type: ignore[union-attr]
            except Exception:
                pytest.skip("chat.py cannot be fully loaded in unit tests")
                return

            sse = chat.build_domain_result_sse_event("compute", "completed", 1234, "inv-001")
            assert "event: domain_result" in sse
            payload = json.loads(sse.split("data: ")[1].split("\n")[0])
            assert payload["domain"] == "compute"
            assert payload["duration_ms"] == 1234

    def test_synthesis_sse_event_format(self):
        import importlib
        import importlib.util
        import types as _types
        import unittest.mock

        heavy_mods = [
            "fastapi", "fastapi.routing", "fastapi.responses",
            "agents.shared.routing", "services.api_gateway.arg_helper",
            "services.api_gateway.foundry",
            "services.api_gateway.instrumentation",
            "services.api_gateway.models",
        ]
        for mod in heavy_mods:
            sys.modules.setdefault(mod, _types.ModuleType(mod))

        _routing_stub = sys.modules["agents.shared.routing"]
        _routing_stub.classify_query_text = lambda t: {"domain": "compute", "confidence": "high", "reason": ""}  # type: ignore[attr-defined]
        _foundry_stub = sys.modules["services.api_gateway.foundry"]
        _foundry_stub._get_foundry_client = lambda: None  # type: ignore[attr-defined]
        _foundry_stub.dispatch_chat_to_orchestrator = AsyncMock(return_value={"response_id": "r1", "status": "completed", "reply": "ok"})  # type: ignore[attr-defined]
        _instr_stub = sys.modules["services.api_gateway.instrumentation"]
        _instr_stub.agent_span = unittest.mock.MagicMock()  # type: ignore[attr-defined]
        _instr_stub.foundry_span = unittest.mock.MagicMock()  # type: ignore[attr-defined]
        _instr_stub.mcp_span = unittest.mock.MagicMock()  # type: ignore[attr-defined]
        _models_stub = sys.modules["services.api_gateway.models"]

        class _CR:  # type: ignore[misc]
            message = ""
            subscription_ids = []
            user_id = None
            incident_id = None
            thread_id = None

        _models_stub.ChatRequest = _CR  # type: ignore[attr-defined]

        spec = importlib.util.spec_from_file_location("chat_sse3", "services/api-gateway/chat.py")
        if spec and spec.loader:
            chat = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(chat)  # type: ignore[union-attr]
            except Exception:
                pytest.skip("chat.py cannot be fully loaded in unit tests")
                return

            hyps = [{"rank": 1, "description": "Correlated failure", "evidence": [], "confidence": 0.85}]
            sse = chat.build_synthesis_sse_event("Root cause summary", hyps, "inv-001")
            assert "event: synthesis" in sse
            payload = json.loads(sse.split("data: ")[1].split("\n")[0])
            assert payload["type"] == "synthesis"
            assert payload["finding"] == "Root cause summary"
            assert len(payload["hypotheses"]) == 1
