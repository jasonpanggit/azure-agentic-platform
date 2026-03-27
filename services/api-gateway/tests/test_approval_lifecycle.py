"""Tests for the HITL approval lifecycle (REMEDI-002, REMEDI-003, REMEDI-004, REMEDI-005, REMEDI-006)."""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch


def _past_timestamp(minutes: int = 60) -> str:
    """Return an ISO 8601 timestamp `minutes` ago."""
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def _future_timestamp(minutes: int = 30) -> str:
    """Return an ISO 8601 timestamp `minutes` from now."""
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


class TestApprovalLifecycle:
    """Tests for the human-in-the-loop approval lifecycle (D-12 schema)."""

    def test_create_pending_approval(self, mock_cosmos_approvals, sample_approval_record):
        """Creates approval record with status=pending."""
        import asyncio
        from agents.shared.approval_manager import create_approval_record

        # create_approval_record calls container.create_item and returns the record
        mock_cosmos_approvals.create_item.return_value = {
            **sample_approval_record,
            "status": "pending",
        }

        result = asyncio.get_event_loop().run_until_complete(
            create_approval_record(
                container=mock_cosmos_approvals,
                thread_id="thread-test-001",
                incident_id="inc-test-001",
                agent_name="compute",
                proposal=sample_approval_record["proposal"],
                resource_snapshot=sample_approval_record["resource_snapshot"],
                risk_level="high",
            )
        )

        mock_cosmos_approvals.create_item.assert_called_once()
        assert result["status"] == "pending"

    @pytest.mark.asyncio
    async def test_approve_pending_sets_approved(self, client, mock_cosmos_approvals):
        """Pending approval transitions to approved status."""
        record = mock_cosmos_approvals.read_item.return_value
        record["expires_at"] = _future_timestamp(30)
        record["status"] = "pending"

        captured_body = {}

        def fake_replace_item(item, body, etag=None, match_condition=None):
            captured_body.update(body)
            return body

        mock_cosmos_approvals.replace_item.side_effect = fake_replace_item

        with patch(
            "services.api_gateway.approvals._get_approvals_container",
            return_value=mock_cosmos_approvals,
        ), patch(
            "services.api_gateway.approvals._resume_foundry_thread",
            new=AsyncMock(),
        ):
            from services.api_gateway.approvals import process_approval_decision
            await process_approval_decision(
                approval_id="appr_test-001",
                thread_id="thread-test-001",
                decision="approved",
                decided_by="operator@contoso.com",
            )

        assert captured_body["status"] == "approved"
        mock_cosmos_approvals.replace_item.assert_called_once()

    @pytest.mark.asyncio
    async def test_reject_pending_sets_rejected(self, client, mock_cosmos_approvals):
        """Pending approval transitions to rejected status."""
        record = mock_cosmos_approvals.read_item.return_value
        record["expires_at"] = _future_timestamp(30)
        record["status"] = "pending"

        captured_body = {}

        def fake_replace_item(item, body, etag=None, match_condition=None):
            captured_body.update(body)
            return body

        mock_cosmos_approvals.replace_item.side_effect = fake_replace_item

        with patch(
            "services.api_gateway.approvals._get_approvals_container",
            return_value=mock_cosmos_approvals,
        ):
            from services.api_gateway.approvals import process_approval_decision
            await process_approval_decision(
                approval_id="appr_test-001",
                thread_id="thread-test-001",
                decision="rejected",
                decided_by="operator@contoso.com",
            )

        assert captured_body["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_expired_approval_returns_410(self, client, mock_cosmos_approvals):
        """Expired proposal raises ValueError('expired')."""
        record = mock_cosmos_approvals.read_item.return_value
        record["expires_at"] = _past_timestamp(60)
        record["status"] = "pending"

        with patch(
            "services.api_gateway.approvals._get_approvals_container",
            return_value=mock_cosmos_approvals,
        ):
            from services.api_gateway.approvals import process_approval_decision
            with pytest.raises(ValueError) as exc_info:
                await process_approval_decision(
                    approval_id="appr_test-001",
                    thread_id="thread-test-001",
                    decision="approved",
                    decided_by="operator@contoso.com",
                )

        assert "expired" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_expired_never_executed(self, mock_cosmos_approvals):
        """After expiry, _resume_foundry_thread is NOT called."""
        record = mock_cosmos_approvals.read_item.return_value
        record["expires_at"] = _past_timestamp(60)
        record["status"] = "pending"

        mock_resume = AsyncMock()

        with patch(
            "services.api_gateway.approvals._get_approvals_container",
            return_value=mock_cosmos_approvals,
        ), patch(
            "services.api_gateway.approvals._resume_foundry_thread",
            new=mock_resume,
        ):
            from services.api_gateway.approvals import process_approval_decision
            with pytest.raises(ValueError):
                await process_approval_decision(
                    approval_id="appr_test-001",
                    thread_id="thread-test-001",
                    decision="approved",
                    decided_by="operator@contoso.com",
                )

        mock_resume.assert_not_called()

    def test_thread_not_polled_after_park(self, mock_foundry_client):
        """create_run not called after proposal is parked awaiting approval."""
        import asyncio
        from agents.shared.approval_manager import create_approval_record

        proposal = {
            "description": "Restart VM",
            "target_resources": ["/subscriptions/sub-1/rgs/rg-1/providers/Microsoft.Compute/virtualMachines/vm-1"],
            "estimated_impact": "~2 min",
            "risk_level": "high",
            "reversibility": "reversible",
            "action_type": "restart",
        }
        snapshot = {
            "resource_id": "/subscriptions/sub-1/rgs/rg-1/providers/Microsoft.Compute/virtualMachines/vm-1",
            "provisioning_state": "Succeeded",
            "tags": {},
            "resource_health": "Available",
            "snapshot_hash": "a" * 64,
        }
        mock_container = MagicMock()
        mock_container.create_item.return_value = {
            "id": "appr_xyz",
            "status": "pending",
            "thread_id": "thread-test-001",
        }

        asyncio.get_event_loop().run_until_complete(
            create_approval_record(
                container=mock_container,
                thread_id="thread-test-001",
                incident_id="inc-001",
                agent_name="compute",
                proposal=proposal,
                resource_snapshot=snapshot,
                risk_level="high",
            )
        )

        # write-then-return: create_run must NOT have been called during parking
        mock_foundry_client.agents.create_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_thread_resume_on_webhook(
        self, client, mock_foundry_client, mock_cosmos_approvals
    ):
        """Approval webhook resumes the Foundry thread (create_message + create_run)."""
        record = mock_cosmos_approvals.read_item.return_value
        record["expires_at"] = _future_timestamp(30)
        record["status"] = "pending"

        mock_cosmos_approvals.replace_item.return_value = {
            **record,
            "status": "approved",
        }

        # _resume_foundry_thread imports _get_foundry_client lazily from
        # services.api_gateway.foundry — patch it there.
        import services.api_gateway.foundry as foundry_module

        with patch(
            "services.api_gateway.approvals._get_approvals_container",
            return_value=mock_cosmos_approvals,
        ), patch.object(
            foundry_module, "_get_foundry_client", return_value=mock_foundry_client
        ), patch.dict(
            "os.environ", {"ORCHESTRATOR_AGENT_ID": "agent-orch-001"}
        ):
            from services.api_gateway.approvals import process_approval_decision
            await process_approval_decision(
                approval_id="appr_test-001",
                thread_id="thread-test-001",
                decision="approved",
                decided_by="operator@contoso.com",
            )

        mock_foundry_client.agents.create_message.assert_called_once()
        mock_foundry_client.agents.create_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_etag_concurrency_on_write(self, mock_cosmos_approvals):
        """replace_item is called with match_condition='IfMatch'."""
        record = mock_cosmos_approvals.read_item.return_value
        record["expires_at"] = _future_timestamp(30)
        record["status"] = "pending"
        record["_etag"] = '"etag-test-001"'

        captured_kwargs: dict = {}

        def fake_replace_item(item, body, etag=None, match_condition=None):
            captured_kwargs["etag"] = etag
            captured_kwargs["match_condition"] = match_condition
            return body

        mock_cosmos_approvals.replace_item.side_effect = fake_replace_item

        with patch(
            "services.api_gateway.approvals._get_approvals_container",
            return_value=mock_cosmos_approvals,
        ), patch(
            "services.api_gateway.approvals._resume_foundry_thread",
            new=AsyncMock(),
        ):
            from services.api_gateway.approvals import process_approval_decision
            await process_approval_decision(
                approval_id="appr_test-001",
                thread_id="thread-test-001",
                decision="approved",
                decided_by="operator@contoso.com",
            )

        assert captured_kwargs["match_condition"] == "IfMatch", (
            f"Expected match_condition='IfMatch', got {captured_kwargs['match_condition']!r}"
        )
        assert captured_kwargs["etag"] == '"etag-test-001"'


class TestListPendingApprovals:
    """Tests for GET /api/v1/approvals?status=pending (TEAMS-005)."""

    def test_list_pending_approvals_endpoint(self, client, mock_cosmos_approvals):
        """GET /api/v1/approvals?status=pending returns list of ApprovalRecord."""
        pending_records = [
            {
                "id": "appr_001",
                "action_id": "act_001",
                "thread_id": "thread-001",
                "incident_id": "inc-001",
                "agent_name": "compute",
                "status": "pending",
                "risk_level": "high",
                "proposed_at": "2026-03-27T14:30:00Z",
                "expires_at": "2026-03-27T15:00:00Z",
                "decided_at": None,
                "decided_by": None,
                "executed_at": None,
                "abort_reason": None,
                "resource_snapshot": {"resource_id": "/sub/rg/vm-01"},
                "proposal": {"description": "Restart VM"},
            },
            {
                "id": "appr_002",
                "action_id": "act_002",
                "thread_id": "thread-002",
                "incident_id": "inc-002",
                "agent_name": "network",
                "status": "pending",
                "risk_level": "critical",
                "proposed_at": "2026-03-27T14:35:00Z",
                "expires_at": "2026-03-27T15:05:00Z",
                "decided_at": None,
                "decided_by": None,
                "executed_at": None,
                "abort_reason": None,
                "resource_snapshot": None,
                "proposal": {"description": "Update NSG rule"},
            },
        ]
        mock_cosmos_approvals.query_items.return_value = iter(pending_records)

        with patch(
            "services.api_gateway.approvals._get_approvals_container",
            return_value=mock_cosmos_approvals,
        ):
            response = client.get("/api/v1/approvals?status=pending")

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 2
        assert body[0]["id"] == "appr_001"
        assert body[1]["id"] == "appr_002"
        assert all(r["status"] == "pending" for r in body)

    @pytest.mark.asyncio
    async def test_list_approvals_by_status_queries_cosmos(self, mock_cosmos_approvals):
        """list_approvals_by_status sends cross-partition query to Cosmos (TEAMS-005)."""
        mock_cosmos_approvals.query_items.return_value = iter([])

        with patch(
            "services.api_gateway.approvals._get_approvals_container",
            return_value=mock_cosmos_approvals,
        ):
            from services.api_gateway.approvals import list_approvals_by_status

            result = await list_approvals_by_status(status_filter="pending")

        assert result == []
        mock_cosmos_approvals.query_items.assert_called_once()
        call_kwargs = mock_cosmos_approvals.query_items.call_args
        assert call_kwargs.kwargs.get("enable_cross_partition_query") is True

    def test_list_approvals_defaults_to_pending(self, client, mock_cosmos_approvals):
        """GET /api/v1/approvals without status param defaults to pending."""
        mock_cosmos_approvals.query_items.return_value = iter([])

        with patch(
            "services.api_gateway.approvals._get_approvals_container",
            return_value=mock_cosmos_approvals,
        ):
            response = client.get("/api/v1/approvals")

        assert response.status_code == 200
        call_kwargs = mock_cosmos_approvals.query_items.call_args
        params = call_kwargs.kwargs.get("parameters", [])
        assert any(p["value"] == "pending" for p in params)


class TestApprovalThreadIdInBody:
    """Tests for thread_id in approval request body (TEAMS-003 Action.Execute)."""

    def test_approve_with_thread_id_in_body(self, client, mock_cosmos_approvals):
        """POST /approve with thread_id in body works (TEAMS-003)."""
        record = mock_cosmos_approvals.read_item.return_value
        record["expires_at"] = _future_timestamp(30)
        record["status"] = "pending"

        mock_cosmos_approvals.replace_item.return_value = {
            **record,
            "status": "approved",
        }

        with patch(
            "services.api_gateway.approvals._get_approvals_container",
            return_value=mock_cosmos_approvals,
        ), patch(
            "services.api_gateway.approvals._resume_foundry_thread",
            new=AsyncMock(),
        ):
            response = client.post(
                "/api/v1/approvals/appr_test-001/approve",
                json={
                    "decided_by": "operator@contoso.com",
                    "thread_id": "thread-test-001",
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "approved"

    def test_approve_without_thread_id_returns_400(self, client, mock_cosmos_approvals):
        """POST /approve without thread_id in either body or query returns 400."""
        with patch(
            "services.api_gateway.approvals._get_approvals_container",
            return_value=mock_cosmos_approvals,
        ):
            response = client.post(
                "/api/v1/approvals/appr_test-001/approve",
                json={
                    "decided_by": "operator@contoso.com",
                },
            )

        assert response.status_code == 400
        assert "thread_id" in response.json()["detail"].lower()

    def test_reject_with_thread_id_in_body(self, client, mock_cosmos_approvals):
        """POST /reject with thread_id in body works (TEAMS-003)."""
        record = mock_cosmos_approvals.read_item.return_value
        record["expires_at"] = _future_timestamp(30)
        record["status"] = "pending"

        mock_cosmos_approvals.replace_item.return_value = {
            **record,
            "status": "rejected",
        }

        with patch(
            "services.api_gateway.approvals._get_approvals_container",
            return_value=mock_cosmos_approvals,
        ):
            response = client.post(
                "/api/v1/approvals/appr_test-001/reject",
                json={
                    "decided_by": "operator@contoso.com",
                    "thread_id": "thread-test-001",
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "rejected"

    def test_approve_query_param_still_works(self, client, mock_cosmos_approvals):
        """POST /approve with thread_id as query param still works (backward compat)."""
        record = mock_cosmos_approvals.read_item.return_value
        record["expires_at"] = _future_timestamp(30)
        record["status"] = "pending"

        mock_cosmos_approvals.replace_item.return_value = {
            **record,
            "status": "approved",
        }

        with patch(
            "services.api_gateway.approvals._get_approvals_container",
            return_value=mock_cosmos_approvals,
        ), patch(
            "services.api_gateway.approvals._resume_foundry_thread",
            new=AsyncMock(),
        ):
            response = client.post(
                "/api/v1/approvals/appr_test-001/approve?thread_id=thread-test-001",
                json={"decided_by": "operator@contoso.com"},
            )

        assert response.status_code == 200
