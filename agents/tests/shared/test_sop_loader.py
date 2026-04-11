"""Tests for agents/shared/sop_loader.py — per-incident SOP selection."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_sop_row(
    filename: str = "vm-high-cpu.md",
    title: str = "VM High CPU",
    version: str = "1.0",
    is_generic: bool = False,
):
    """Build a mock asyncpg row."""
    row = MagicMock()
    row.__getitem__ = lambda self, key: {
        "foundry_filename": filename,
        "title": title,
        "version": version,
        "is_generic": is_generic,
    }[key]
    return row


class TestSelectSopForIncident:
    """Verify select_sop_for_incident returns correct SOP and grounding instruction."""

    @pytest.mark.asyncio
    async def test_returns_sop_load_result(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = _make_sop_row()

        incident = {
            "incident_id": "inc-001",
            "alert_title": "CPU high on vm1",
            "resource_type": "Microsoft.Compute/virtualMachines",
            "domain": "compute",
        }

        from agents.shared.sop_loader import SopLoadResult, select_sop_for_incident

        result = await select_sop_for_incident(incident, "compute", mock_conn)
        assert isinstance(result, SopLoadResult)

    @pytest.mark.asyncio
    async def test_returns_correct_filename(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = _make_sop_row(filename="vm-high-cpu.md")

        incident = {
            "incident_id": "inc-002",
            "alert_title": "CPU high",
            "resource_type": "Microsoft.Compute/virtualMachines",
        }

        from agents.shared.sop_loader import select_sop_for_incident

        result = await select_sop_for_incident(incident, "compute", mock_conn)
        assert result.foundry_filename == "vm-high-cpu.md"

    @pytest.mark.asyncio
    async def test_falls_back_to_generic_when_no_specific_match(self):
        mock_conn = AsyncMock()
        # First call (specific) returns None, second (generic) returns row
        mock_conn.fetchrow.side_effect = [
            None,
            _make_sop_row(filename="compute-generic.md", is_generic=True),
        ]

        incident = {
            "incident_id": "inc-003",
            "alert_title": "unknown issue",
            "resource_type": "Microsoft.Compute/virtualMachines",
        }

        from agents.shared.sop_loader import select_sop_for_incident

        result = await select_sop_for_incident(incident, "compute", mock_conn)
        assert result.foundry_filename == "compute-generic.md"
        assert result.is_generic is True

    @pytest.mark.asyncio
    async def test_grounding_instruction_contains_filename(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = _make_sop_row(filename="vm-disk-exhaustion.md")

        incident = {"incident_id": "inc-004", "alert_title": "disk full", "resource_type": ""}

        from agents.shared.sop_loader import select_sop_for_incident

        result = await select_sop_for_incident(incident, "compute", mock_conn)
        assert "vm-disk-exhaustion.md" in result.grounding_instruction

    @pytest.mark.asyncio
    async def test_grounding_instruction_contains_hitl_warning(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = _make_sop_row()

        incident = {"incident_id": "inc-005", "alert_title": "test", "resource_type": ""}

        from agents.shared.sop_loader import select_sop_for_incident

        result = await select_sop_for_incident(incident, "compute", mock_conn)
        assert "REMEDIATION" in result.grounding_instruction
        assert "ApprovalRecord" in result.grounding_instruction

    @pytest.mark.asyncio
    async def test_grounding_instruction_marks_generic_fallback(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow.side_effect = [
            None,
            _make_sop_row(filename="compute-generic.md", is_generic=True),
        ]

        incident = {"incident_id": "inc-006", "alert_title": "unknown", "resource_type": ""}

        from agents.shared.sop_loader import select_sop_for_incident

        result = await select_sop_for_incident(incident, "compute", mock_conn)
        assert "GENERIC FALLBACK" in result.grounding_instruction

    @pytest.mark.asyncio
    async def test_raises_when_no_sop_found(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = None

        incident = {"incident_id": "inc-007", "alert_title": "test", "resource_type": ""}

        from agents.shared.sop_loader import select_sop_for_incident

        with pytest.raises(ValueError, match="No SOP found"):
            await select_sop_for_incident(incident, "unknown-domain", mock_conn)

    @pytest.mark.asyncio
    async def test_grounding_instruction_mentions_file_search(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = _make_sop_row()

        incident = {"incident_id": "inc-008", "alert_title": "cpu", "resource_type": ""}

        from agents.shared.sop_loader import select_sop_for_incident

        result = await select_sop_for_incident(incident, "compute", mock_conn)
        assert "file_search" in result.grounding_instruction
