"""Phase 30 smoke tests -- SOP engine wiring."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestPhase30Smoke:
    """Verify the Phase 30 SOP engine components are importable and wired."""

    def test_sop_store_importable(self):
        from agents.shared.sop_store import provision_sop_vector_store

        assert provision_sop_vector_store

    def test_sop_loader_importable(self):
        from agents.shared.sop_loader import SopLoadResult, select_sop_for_incident

        assert select_sop_for_incident
        assert SopLoadResult

    def test_sop_notify_importable(self):
        from agents.shared.sop_notify import sop_notify

        assert sop_notify

    def test_migration_file_exists(self):
        import os

        assert os.path.exists("services/api-gateway/migrations/003_create_sops_table.py")

    def test_upload_sops_script_importable(self):
        from scripts.upload_sops import (
            compute_sop_hash,
            parse_sop_front_matter,
            upload_sops,
        )

        assert all([compute_sop_hash, parse_sop_front_matter, upload_sops])

    def test_sop_store_vector_store_name(self):
        from agents.shared.sop_store import SOP_VECTOR_STORE_NAME

        assert SOP_VECTOR_STORE_NAME == "aap-sops-v1"

    @pytest.mark.asyncio
    async def test_sop_loader_returns_grounding_for_mock_incident(self):
        mock_conn = AsyncMock()
        row = MagicMock()
        row.__getitem__ = lambda self, k: {
            "foundry_filename": "vm-high-cpu.md",
            "title": "VM High CPU",
            "version": "1.0",
            "is_generic": False,
        }[k]
        mock_conn.fetchrow.return_value = row

        from agents.shared.sop_loader import select_sop_for_incident

        result = await select_sop_for_incident(
            {"incident_id": "inc-smoke", "alert_title": "cpu high", "resource_type": ""},
            "compute",
            mock_conn,
        )
        assert result.foundry_filename == "vm-high-cpu.md"
        assert "file_search" in result.grounding_instruction

    @pytest.mark.asyncio
    async def test_sop_loader_grounding_contains_remediation_rule(self):
        mock_conn = AsyncMock()
        row = MagicMock()
        row.__getitem__ = lambda self, k: {
            "foundry_filename": "test.md",
            "title": "Test SOP",
            "version": "1.0",
            "is_generic": False,
        }[k]
        mock_conn.fetchrow.return_value = row

        from agents.shared.sop_loader import select_sop_for_incident

        result = await select_sop_for_incident(
            {"incident_id": "inc-smoke-2", "alert_title": "test", "resource_type": ""},
            "compute",
            mock_conn,
        )
        assert "REMEDIATION" in result.grounding_instruction
        assert "ApprovalRecord" in result.grounding_instruction

    def test_terraform_notifications_module_exists(self):
        import os

        assert os.path.exists("terraform/modules/notifications/main.tf")
        assert os.path.exists("terraform/modules/notifications/variables.tf")
        assert os.path.exists("terraform/modules/notifications/outputs.tf")

    def test_terraform_agent_apps_has_sop_vector_store_var(self):
        with open("terraform/modules/agent-apps/variables.tf") as f:
            content = f.read()
        assert "sop_vector_store_id" in content

    def test_terraform_agent_apps_has_notification_email_vars(self):
        with open("terraform/modules/agent-apps/variables.tf") as f:
            content = f.read()
        assert "notification_email_from" in content
        assert "notification_email_to" in content
