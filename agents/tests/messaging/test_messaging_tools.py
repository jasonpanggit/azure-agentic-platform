"""Unit tests for Messaging Agent tools (Phase 49).

Tests all 7 messaging tools + ALLOWED_MCP_TOOLS + _extract_subscription_id.
Each tool has success path, error path, and SDK-missing path tests.
Pattern follows agents/tests/containerapps/test_containerapps_tools.py.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# Helpers
# ===========================================================================


def _make_cm_mock():
    """Return a context-manager mock for instrument_tool_call."""
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=MagicMock())
    m.__exit__ = MagicMock(return_value=False)
    return m


# ===========================================================================
# TestAllowedMcpTools (4 tests)
# ===========================================================================


class TestAllowedMcpTools:
    """Verify ALLOWED_MCP_TOOLS list is correct and has no wildcards."""

    def test_allowed_mcp_tools_has_exactly_two_entries(self):
        from agents.messaging.tools import ALLOWED_MCP_TOOLS

        assert len(ALLOWED_MCP_TOOLS) == 2

    def test_allowed_mcp_tools_contains_expected_entries(self):
        from agents.messaging.tools import ALLOWED_MCP_TOOLS

        assert "monitor.query_metrics" in ALLOWED_MCP_TOOLS
        assert "monitor.query_logs" in ALLOWED_MCP_TOOLS

    def test_allowed_mcp_tools_no_wildcards(self):
        from agents.messaging.tools import ALLOWED_MCP_TOOLS

        for tool in ALLOWED_MCP_TOOLS:
            assert "*" not in tool, f"Wildcard found in tool: {tool}"

    def test_allowed_mcp_tools_is_list(self):
        from agents.messaging.tools import ALLOWED_MCP_TOOLS

        assert isinstance(ALLOWED_MCP_TOOLS, list)


# ===========================================================================
# TestGetServicebusNamespaceHealth (4 tests)
# ===========================================================================


class TestGetServicebusNamespaceHealth:
    """Verify get_servicebus_namespace_health returns expected structure."""

    def _make_ns_mock(
        self,
        sku_name="Standard",
        sku_capacity=None,
        status="Active",
        provisioning_state="Succeeded",
        zone_redundant=True,
        geo_data_replication=None,
        location="eastus",
    ):
        ns = MagicMock()
        sku = MagicMock()
        sku.name = sku_name
        sku.capacity = sku_capacity
        ns.sku = sku
        ns.status = status
        ns.provisioning_state = provisioning_state
        ns.zone_redundant = zone_redundant
        ns.geo_data_replication = geo_data_replication
        ns.location = location
        return ns

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    @patch("agents.messaging.tools.get_credential", return_value=MagicMock())
    @patch("agents.messaging.tools.ServiceBusManagementClient")
    def test_returns_success_with_namespace_data(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_client_cls.return_value.namespaces.get.return_value = self._make_ns_mock()

        from agents.messaging.tools import get_servicebus_namespace_health

        result = get_servicebus_namespace_health(
            namespace_name="sb-prod",
            resource_group="rg-prod",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "success"
        assert result["sku_tier"] == "Standard"
        assert result["zone_redundant"] is True
        assert result["geo_replication_enabled"] is False
        assert result["duration_ms"] >= 0

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    @patch("agents.messaging.tools.get_credential", return_value=MagicMock())
    def test_sdk_missing_returns_error(self, mock_cred, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        import agents.messaging.tools as tools_module

        original = tools_module.ServiceBusManagementClient
        tools_module.ServiceBusManagementClient = None
        try:
            from agents.messaging.tools import get_servicebus_namespace_health

            result = get_servicebus_namespace_health(
                namespace_name="sb-prod",
                resource_group="rg-prod",
                subscription_id="sub-1",
            )
            assert result["query_status"] == "error"
            assert "not installed" in result["error"]
        finally:
            tools_module.ServiceBusManagementClient = original

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    @patch("agents.messaging.tools.get_credential", return_value=MagicMock())
    @patch("agents.messaging.tools.ServiceBusManagementClient")
    def test_azure_error_returns_error(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_client_cls.return_value.namespaces.get.side_effect = Exception("ResourceNotFound")

        from agents.messaging.tools import get_servicebus_namespace_health

        result = get_servicebus_namespace_health(
            namespace_name="missing-ns",
            resource_group="rg-prod",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "error"
        assert "ResourceNotFound" in result["error"]
        assert result["duration_ms"] >= 0

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    @patch("agents.messaging.tools.get_credential", return_value=MagicMock())
    @patch("agents.messaging.tools.ServiceBusManagementClient")
    def test_no_sku_returns_none_tier(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()

        ns = MagicMock()
        ns.sku = None
        ns.status = "Active"
        ns.provisioning_state = "Succeeded"
        ns.zone_redundant = False
        ns.geo_data_replication = None
        ns.location = "westus"
        mock_client_cls.return_value.namespaces.get.return_value = ns

        from agents.messaging.tools import get_servicebus_namespace_health

        result = get_servicebus_namespace_health(
            namespace_name="sb-basic",
            resource_group="rg-prod",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "success"
        assert result["sku_tier"] is None
        assert result["sku_capacity"] is None


# ===========================================================================
# TestListServicebusQueues (5 tests)
# ===========================================================================


class TestListServicebusQueues:
    """Verify list_servicebus_queues returns expected structure."""

    def _make_queue_mock(
        self,
        name="orders-queue",
        status="Active",
        message_count=10,
        active_count=5,
        dlq_count=5,
        scheduled_count=0,
        max_delivery=10,
        lock_duration_seconds=30.0,
        size_in_bytes=1024,
    ):
        q = MagicMock()
        q.name = name
        q.status = status
        q.message_count = message_count
        q.dead_lettering_on_message_expiration = True
        q.requires_session = False
        q.max_delivery_count = max_delivery
        q.size_in_bytes = size_in_bytes

        cd = MagicMock()
        cd.active_message_count = active_count
        cd.dead_letter_message_count = dlq_count
        cd.scheduled_message_count = scheduled_count
        q.count_details = cd

        from datetime import timedelta
        q.lock_duration = timedelta(seconds=lock_duration_seconds)
        return q

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    @patch("agents.messaging.tools.get_credential", return_value=MagicMock())
    @patch("agents.messaging.tools.ServiceBusManagementClient")
    def test_returns_success_with_queue_list(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        queues = [
            self._make_queue_mock("orders-queue", dlq_count=5),
            self._make_queue_mock("payments-queue", dlq_count=0),
        ]
        mock_client_cls.return_value.queues.list_by_namespace.return_value = iter(queues)

        from agents.messaging.tools import list_servicebus_queues

        result = list_servicebus_queues(
            namespace_name="sb-prod",
            resource_group="rg-prod",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "success"
        assert result["queue_count"] == 2
        assert result["queues"][0]["dead_letter_message_count"] == 5
        assert "duration_ms" in result

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    @patch("agents.messaging.tools.get_credential", return_value=MagicMock())
    @patch("agents.messaging.tools.ServiceBusManagementClient")
    def test_empty_namespace_returns_zero_queues(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_client_cls.return_value.queues.list_by_namespace.return_value = iter([])

        from agents.messaging.tools import list_servicebus_queues

        result = list_servicebus_queues(
            namespace_name="sb-empty",
            resource_group="rg-prod",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "success"
        assert result["queue_count"] == 0
        assert result["queues"] == []

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    @patch("agents.messaging.tools.get_credential", return_value=MagicMock())
    def test_sdk_missing_returns_error(self, mock_cred, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        import agents.messaging.tools as tools_module

        original = tools_module.ServiceBusManagementClient
        tools_module.ServiceBusManagementClient = None
        try:
            from agents.messaging.tools import list_servicebus_queues

            result = list_servicebus_queues(
                namespace_name="sb-prod",
                resource_group="rg-prod",
                subscription_id="sub-1",
            )
            assert result["query_status"] == "error"
            assert "not installed" in result["error"]
        finally:
            tools_module.ServiceBusManagementClient = original

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    @patch("agents.messaging.tools.get_credential", return_value=MagicMock())
    @patch("agents.messaging.tools.ServiceBusManagementClient")
    def test_azure_error_returns_error(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_client_cls.return_value.queues.list_by_namespace.side_effect = Exception(
            "NamespaceNotFound"
        )

        from agents.messaging.tools import list_servicebus_queues

        result = list_servicebus_queues(
            namespace_name="missing-ns",
            resource_group="rg-prod",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "error"
        assert "NamespaceNotFound" in result["error"]

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    @patch("agents.messaging.tools.get_credential", return_value=MagicMock())
    @patch("agents.messaging.tools.ServiceBusManagementClient")
    def test_count_details_none_returns_none_counts(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()

        q = MagicMock()
        q.name = "throttled-queue"
        q.status = "Active"
        q.message_count = None
        q.count_details = None
        q.lock_duration = None
        q.max_delivery_count = 10
        q.dead_lettering_on_message_expiration = False
        q.requires_session = False
        q.size_in_bytes = 0

        mock_client_cls.return_value.queues.list_by_namespace.return_value = iter([q])

        from agents.messaging.tools import list_servicebus_queues

        result = list_servicebus_queues(
            namespace_name="sb-prod",
            resource_group="rg-prod",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "success"
        assert result["queues"][0]["active_message_count"] is None
        assert result["queues"][0]["dead_letter_message_count"] is None


# ===========================================================================
# TestGetServicebusMetrics (4 tests)
# ===========================================================================


class TestGetServicebusMetrics:
    """Verify get_servicebus_metrics returns expected structure."""

    def _make_dp(self, total=None, average=None):
        dp = MagicMock()
        dp.time_stamp = datetime(2026, 4, 14, 12, 0, 0, tzinfo=timezone.utc)
        dp.total = total
        dp.average = average
        return dp

    def _make_metric_response(self, metrics_data):
        mock_metrics = []
        for name, dps in metrics_data.items():
            mock_ts = MagicMock()
            mock_ts.data = dps
            mock_metric = MagicMock()
            mock_metric.name = MagicMock(value=name)
            mock_metric.timeseries = [mock_ts]
            mock_metrics.append(mock_metric)
        response = MagicMock()
        response.value = mock_metrics
        return response

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    @patch("agents.messaging.tools.get_credential", return_value=MagicMock())
    @patch("agents.messaging.tools.MonitorManagementClient")
    def test_returns_success_with_metrics(
        self, mock_mon_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()

        metrics_data = {
            "IncomingMessages": [self._make_dp(total=5000.0)],
            "OutgoingMessages": [self._make_dp(total=4800.0)],
            "ActiveMessages": [self._make_dp(average=200.0)],
            "DeadletteredMessages": [self._make_dp(average=5.0)],
            "ServerErrors": [self._make_dp(total=2.0)],
            "ThrottledRequests": [self._make_dp(total=10.0)],
            "UserErrors": [self._make_dp(total=1.0)],
        }
        mock_mon_cls.return_value.metrics.list.return_value = self._make_metric_response(
            metrics_data
        )

        from agents.messaging.tools import get_servicebus_metrics

        result = get_servicebus_metrics(
            namespace_name="sb-prod",
            resource_group="rg-prod",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "success"
        assert result["timespan_hours"] == 4
        assert result["incoming_messages"] is not None
        assert result["incoming_messages"] == pytest.approx(5000.0)
        assert "duration_ms" in result

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    @patch("agents.messaging.tools.get_credential", return_value=MagicMock())
    def test_sdk_missing_returns_error(self, mock_cred, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        import agents.messaging.tools as tools_module

        original = tools_module.MonitorManagementClient
        tools_module.MonitorManagementClient = None
        try:
            from agents.messaging.tools import get_servicebus_metrics

            result = get_servicebus_metrics(
                namespace_name="sb-prod",
                resource_group="rg-prod",
                subscription_id="sub-1",
            )
            assert result["query_status"] == "error"
            assert "not installed" in result["error"]
        finally:
            tools_module.MonitorManagementClient = original

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    @patch("agents.messaging.tools.get_credential", return_value=MagicMock())
    @patch("agents.messaging.tools.MonitorManagementClient")
    def test_azure_error_returns_error(
        self, mock_mon_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_mon_cls.return_value.metrics.list.side_effect = Exception("MetricsError")

        from agents.messaging.tools import get_servicebus_metrics

        result = get_servicebus_metrics(
            namespace_name="sb-prod",
            resource_group="rg-prod",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "error"
        assert "MetricsError" in result["error"]
        assert result["duration_ms"] >= 0

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    @patch("agents.messaging.tools.get_credential", return_value=MagicMock())
    @patch("agents.messaging.tools.MonitorManagementClient")
    def test_entity_name_filter_sets_field(
        self, mock_mon_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_mon_cls.return_value.metrics.list.return_value = self._make_metric_response({})

        from agents.messaging.tools import get_servicebus_metrics

        result = get_servicebus_metrics(
            namespace_name="sb-prod",
            resource_group="rg-prod",
            subscription_id="sub-1",
            entity_name="orders-queue",
        )

        assert result["entity_name"] == "orders-queue"


# ===========================================================================
# TestProposeServicebusDlqPurge (4 tests)
# ===========================================================================


class TestProposeServicebusDlqPurge:
    """Verify propose_servicebus_dlq_purge always returns approval_required=True."""

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    def test_approval_required_is_true(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.messaging.tools import propose_servicebus_dlq_purge

        result = propose_servicebus_dlq_purge(
            namespace_name="sb-prod",
            resource_group="rg-prod",
            subscription_id="sub-1",
            queue_name="orders-dlq",
            reason="DLQ depth at 500 messages — consumer failure confirmed.",
        )

        assert result["approval_required"] is True

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    def test_risk_level_is_low(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.messaging.tools import propose_servicebus_dlq_purge

        result = propose_servicebus_dlq_purge(
            namespace_name="sb-prod",
            resource_group="rg-prod",
            subscription_id="sub-1",
            queue_name="orders-dlq",
            reason="Clear stale DLQ messages.",
        )

        assert result["risk_level"] == "low"

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    def test_proposed_action_contains_queue_name(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.messaging.tools import propose_servicebus_dlq_purge

        result = propose_servicebus_dlq_purge(
            namespace_name="sb-prod",
            resource_group="rg-prod",
            subscription_id="sub-1",
            queue_name="orders-dlq",
            reason="Consumer failure.",
        )

        assert "orders-dlq" in result["proposed_action"]

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    def test_reversibility_states_not_reversible(self, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        from agents.messaging.tools import propose_servicebus_dlq_purge

        result = propose_servicebus_dlq_purge(
            namespace_name="sb-prod",
            resource_group="rg-prod",
            subscription_id="sub-1",
            queue_name="orders-dlq",
            reason="Stale messages.",
        )

        assert "NOT reversible" in result["reversibility"]


# ===========================================================================
# TestGetEventhubNamespaceHealth (4 tests)
# ===========================================================================


class TestGetEventhubNamespaceHealth:
    """Verify get_eventhub_namespace_health returns expected structure."""

    def _make_ns_mock(
        self,
        sku_name="Standard",
        sku_capacity=2,
        status="Active",
        provisioning_state="Succeeded",
        zone_redundant=True,
        kafka_enabled=True,
        is_auto_inflate_enabled=False,
        maximum_throughput_units=None,
        location="eastus",
    ):
        ns = MagicMock()
        sku = MagicMock()
        sku.name = sku_name
        sku.capacity = sku_capacity
        ns.sku = sku
        ns.status = status
        ns.provisioning_state = provisioning_state
        ns.zone_redundant = zone_redundant
        ns.kafka_enabled = kafka_enabled
        ns.is_auto_inflate_enabled = is_auto_inflate_enabled
        ns.maximum_throughput_units = maximum_throughput_units
        ns.location = location
        return ns

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    @patch("agents.messaging.tools.get_credential", return_value=MagicMock())
    @patch("agents.messaging.tools.EventHubManagementClient")
    def test_returns_success_with_namespace_data(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_client_cls.return_value.namespaces.get.return_value = self._make_ns_mock()

        from agents.messaging.tools import get_eventhub_namespace_health

        result = get_eventhub_namespace_health(
            namespace_name="eh-prod",
            resource_group="rg-prod",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "success"
        assert result["sku_name"] == "Standard"
        assert result["sku_capacity"] == 2
        assert result["kafka_enabled"] is True
        assert result["zone_redundant"] is True
        assert result["duration_ms"] >= 0

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    @patch("agents.messaging.tools.get_credential", return_value=MagicMock())
    def test_sdk_missing_returns_error(self, mock_cred, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        import agents.messaging.tools as tools_module

        original = tools_module.EventHubManagementClient
        tools_module.EventHubManagementClient = None
        try:
            from agents.messaging.tools import get_eventhub_namespace_health

            result = get_eventhub_namespace_health(
                namespace_name="eh-prod",
                resource_group="rg-prod",
                subscription_id="sub-1",
            )
            assert result["query_status"] == "error"
            assert "not installed" in result["error"]
        finally:
            tools_module.EventHubManagementClient = original

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    @patch("agents.messaging.tools.get_credential", return_value=MagicMock())
    @patch("agents.messaging.tools.EventHubManagementClient")
    def test_azure_error_returns_error(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_client_cls.return_value.namespaces.get.side_effect = Exception("NamespaceNotFound")

        from agents.messaging.tools import get_eventhub_namespace_health

        result = get_eventhub_namespace_health(
            namespace_name="missing-eh",
            resource_group="rg-prod",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "error"
        assert "NamespaceNotFound" in result["error"]
        assert result["duration_ms"] >= 0

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    @patch("agents.messaging.tools.get_credential", return_value=MagicMock())
    @patch("agents.messaging.tools.EventHubManagementClient")
    def test_no_sku_returns_none_fields(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()

        ns = MagicMock()
        ns.sku = None
        ns.status = "Active"
        ns.provisioning_state = "Succeeded"
        ns.zone_redundant = False
        ns.kafka_enabled = False
        ns.is_auto_inflate_enabled = False
        ns.maximum_throughput_units = None
        ns.location = "westus"
        mock_client_cls.return_value.namespaces.get.return_value = ns

        from agents.messaging.tools import get_eventhub_namespace_health

        result = get_eventhub_namespace_health(
            namespace_name="eh-basic",
            resource_group="rg-prod",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "success"
        assert result["sku_name"] is None
        assert result["sku_capacity"] is None


# ===========================================================================
# TestListEventhubConsumerGroups (5 tests)
# ===========================================================================


class TestListEventhubConsumerGroups:
    """Verify list_eventhub_consumer_groups returns expected structure."""

    def _make_eh_mock(self, name="telemetry-hub", partition_count=8):
        eh = MagicMock()
        eh.name = name
        eh.partition_count = partition_count
        eh.status = "Active"
        eh.message_retention_in_days = 7
        eh.capture_description = None
        return eh

    def _make_cg_mock(self, name="$Default"):
        cg = MagicMock()
        cg.name = name
        cg.created_at = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        cg.updated_at = datetime(2026, 1, 2, 0, 0, 0, tzinfo=timezone.utc)
        cg.user_metadata = None
        return cg

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    @patch("agents.messaging.tools.get_credential", return_value=MagicMock())
    @patch("agents.messaging.tools.EventHubManagementClient")
    def test_returns_success_with_eventhubs_and_groups(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()

        eh = self._make_eh_mock()
        cg1 = self._make_cg_mock("$Default")
        cg2 = self._make_cg_mock("consumer-app-1")

        mock_client_cls.return_value.event_hubs.list_by_namespace.return_value = iter([eh])
        mock_client_cls.return_value.consumer_groups.list_by_event_hub.return_value = iter(
            [cg1, cg2]
        )

        from agents.messaging.tools import list_eventhub_consumer_groups

        result = list_eventhub_consumer_groups(
            namespace_name="eh-prod",
            resource_group="rg-prod",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "success"
        assert result["eventhub_count"] == 1
        assert result["eventhubs"][0]["consumer_group_count"] == 2
        assert "duration_ms" in result

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    @patch("agents.messaging.tools.get_credential", return_value=MagicMock())
    @patch("agents.messaging.tools.EventHubManagementClient")
    def test_empty_namespace_returns_zero_eventhubs(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_client_cls.return_value.event_hubs.list_by_namespace.return_value = iter([])

        from agents.messaging.tools import list_eventhub_consumer_groups

        result = list_eventhub_consumer_groups(
            namespace_name="eh-empty",
            resource_group="rg-prod",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "success"
        assert result["eventhub_count"] == 0

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    @patch("agents.messaging.tools.get_credential", return_value=MagicMock())
    def test_sdk_missing_returns_error(self, mock_cred, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        import agents.messaging.tools as tools_module

        original = tools_module.EventHubManagementClient
        tools_module.EventHubManagementClient = None
        try:
            from agents.messaging.tools import list_eventhub_consumer_groups

            result = list_eventhub_consumer_groups(
                namespace_name="eh-prod",
                resource_group="rg-prod",
                subscription_id="sub-1",
            )
            assert result["query_status"] == "error"
            assert "not installed" in result["error"]
        finally:
            tools_module.EventHubManagementClient = original

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    @patch("agents.messaging.tools.get_credential", return_value=MagicMock())
    @patch("agents.messaging.tools.EventHubManagementClient")
    def test_azure_error_returns_error(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_client_cls.return_value.event_hubs.list_by_namespace.side_effect = Exception(
            "NamespaceNotFound"
        )

        from agents.messaging.tools import list_eventhub_consumer_groups

        result = list_eventhub_consumer_groups(
            namespace_name="missing-eh",
            resource_group="rg-prod",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "error"
        assert "NamespaceNotFound" in result["error"]

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    @patch("agents.messaging.tools.get_credential", return_value=MagicMock())
    @patch("agents.messaging.tools.EventHubManagementClient")
    def test_empty_consumer_groups_returns_zero_count(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()

        eh = self._make_eh_mock()
        mock_client_cls.return_value.event_hubs.list_by_namespace.return_value = iter([eh])
        mock_client_cls.return_value.consumer_groups.list_by_event_hub.return_value = iter(
            []
        )

        from agents.messaging.tools import list_eventhub_consumer_groups

        result = list_eventhub_consumer_groups(
            namespace_name="eh-prod",
            resource_group="rg-prod",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "success"
        assert result["eventhubs"][0]["consumer_group_count"] == 0


# ===========================================================================
# TestGetEventhubMetrics (4 tests)
# ===========================================================================


class TestGetEventhubMetrics:
    """Verify get_eventhub_metrics returns expected structure."""

    def _make_dp(self, total=None):
        dp = MagicMock()
        dp.time_stamp = datetime(2026, 4, 14, 12, 0, 0, tzinfo=timezone.utc)
        dp.total = total
        return dp

    def _make_metric_response(self, metrics_data):
        mock_metrics = []
        for name, dps in metrics_data.items():
            mock_ts = MagicMock()
            mock_ts.data = dps
            mock_metric = MagicMock()
            mock_metric.name = MagicMock(value=name)
            mock_metric.timeseries = [mock_ts]
            mock_metrics.append(mock_metric)
        response = MagicMock()
        response.value = mock_metrics
        return response

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    @patch("agents.messaging.tools.get_credential", return_value=MagicMock())
    @patch("agents.messaging.tools.MonitorManagementClient")
    def test_returns_success_with_metrics(
        self, mock_mon_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()

        metrics_data = {
            "IncomingMessages": [self._make_dp(total=1000.0)],
            "OutgoingMessages": [self._make_dp(total=900.0)],
            "IncomingBytes": [self._make_dp(total=10000.0)],
            "OutgoingBytes": [self._make_dp(total=9000.0)],
            "ThrottledRequests": [self._make_dp(total=0.0)],
            "ServerErrors": [self._make_dp(total=0.0)],
            "UserErrors": [self._make_dp(total=0.0)],
        }
        mock_mon_cls.return_value.metrics.list.return_value = self._make_metric_response(
            metrics_data
        )

        from agents.messaging.tools import get_eventhub_metrics

        result = get_eventhub_metrics(
            namespace_name="eh-prod",
            resource_group="rg-prod",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "success"
        assert result["estimated_lag_count"] == 100
        assert "duration_ms" in result

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    @patch("agents.messaging.tools.get_credential", return_value=MagicMock())
    def test_sdk_missing_returns_error(self, mock_cred, mock_identity, mock_instrument):
        mock_instrument.return_value = _make_cm_mock()

        import agents.messaging.tools as tools_module

        original = tools_module.MonitorManagementClient
        tools_module.MonitorManagementClient = None
        try:
            from agents.messaging.tools import get_eventhub_metrics

            result = get_eventhub_metrics(
                namespace_name="eh-prod",
                resource_group="rg-prod",
                subscription_id="sub-1",
            )
            assert result["query_status"] == "error"
            assert "not installed" in result["error"]
        finally:
            tools_module.MonitorManagementClient = original

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    @patch("agents.messaging.tools.get_credential", return_value=MagicMock())
    @patch("agents.messaging.tools.MonitorManagementClient")
    def test_azure_error_returns_error(
        self, mock_mon_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_mon_cls.return_value.metrics.list.side_effect = Exception("MetricsError")

        from agents.messaging.tools import get_eventhub_metrics

        result = get_eventhub_metrics(
            namespace_name="eh-prod",
            resource_group="rg-prod",
            subscription_id="sub-1",
        )

        assert result["query_status"] == "error"
        assert "MetricsError" in result["error"]
        assert result["duration_ms"] >= 0

    @patch("agents.messaging.tools.instrument_tool_call")
    @patch("agents.messaging.tools.get_agent_identity", return_value="test-id")
    @patch("agents.messaging.tools.get_credential", return_value=MagicMock())
    @patch("agents.messaging.tools.MonitorManagementClient")
    def test_eventhub_name_filter_sets_field(
        self, mock_mon_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_cm_mock()
        mock_mon_cls.return_value.metrics.list.return_value = self._make_metric_response({})

        from agents.messaging.tools import get_eventhub_metrics

        result = get_eventhub_metrics(
            namespace_name="eh-prod",
            resource_group="rg-prod",
            subscription_id="sub-1",
            eventhub_name="telemetry-hub",
        )

        assert result["eventhub_name"] == "telemetry-hub"


# ===========================================================================
# TestExtractSubscriptionId (3 tests)
# ===========================================================================


class TestExtractSubscriptionId:
    """Verify _extract_subscription_id helper."""

    def test_valid_resource_id(self):
        from agents.messaging.tools import _extract_subscription_id

        result = _extract_subscription_id(
            "/subscriptions/abc123/resourceGroups/rg1/providers/Microsoft.ServiceBus/namespaces/sb-prod"
        )
        assert result == "abc123"

    def test_missing_subscriptions_segment_raises(self):
        from agents.messaging.tools import _extract_subscription_id

        with pytest.raises(ValueError):
            _extract_subscription_id(
                "/resourceGroups/rg1/providers/Microsoft.ServiceBus/namespaces/sb-prod"
            )

    def test_empty_string_raises(self):
        from agents.messaging.tools import _extract_subscription_id

        with pytest.raises(ValueError):
            _extract_subscription_id("")
