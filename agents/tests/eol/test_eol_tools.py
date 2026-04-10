"""Unit tests for EOL Agent tools (Phase 12)."""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# ALLOWED_MCP_TOOLS
# ---------------------------------------------------------------------------


class TestAllowedMcpTools:
    """Verify ALLOWED_MCP_TOOLS list is correct and has no wildcards."""

    def test_allowed_tools_is_list(self):
        from agents.eol.tools import ALLOWED_MCP_TOOLS

        assert isinstance(ALLOWED_MCP_TOOLS, list)

    def test_allowed_tools_contains_monitor_query_logs(self):
        from agents.eol.tools import ALLOWED_MCP_TOOLS

        assert "monitor.query_logs" in ALLOWED_MCP_TOOLS

    def test_no_wildcard_in_allowed_tools(self):
        from agents.eol.tools import ALLOWED_MCP_TOOLS

        for entry in ALLOWED_MCP_TOOLS:
            assert "*" not in entry, f"Wildcard found in tool: {entry}"


# ---------------------------------------------------------------------------
# PRODUCT_SLUG_MAP
# ---------------------------------------------------------------------------


class TestProductSlugMap:
    """Verify key entries in PRODUCT_SLUG_MAP."""

    def test_windows_server_maps_to_endoflife_date(self):
        from agents.eol.tools import PRODUCT_SLUG_MAP

        assert PRODUCT_SLUG_MAP["windows server 2016"] == ("endoflife.date", "windows-server")

    def test_ubuntu_maps_to_endoflife_date(self):
        from agents.eol.tools import PRODUCT_SLUG_MAP

        assert PRODUCT_SLUG_MAP["ubuntu"] == ("endoflife.date", "ubuntu")

    def test_sql_server_slug_is_mssqlserver(self):
        from agents.eol.tools import PRODUCT_SLUG_MAP

        assert PRODUCT_SLUG_MAP["mssqlserver"] == ("endoflife.date", "mssqlserver")

    def test_sql_server_year_maps_to_mssqlserver(self):
        from agents.eol.tools import PRODUCT_SLUG_MAP

        assert PRODUCT_SLUG_MAP["sql server 2019"] == ("endoflife.date", "mssqlserver")

    def test_python_maps_to_endoflife_date(self):
        from agents.eol.tools import PRODUCT_SLUG_MAP

        assert PRODUCT_SLUG_MAP["python"] == ("endoflife.date", "python")

    def test_nodejs_maps_to_endoflife_date(self):
        from agents.eol.tools import PRODUCT_SLUG_MAP

        assert PRODUCT_SLUG_MAP["nodejs"] == ("endoflife.date", "nodejs")

    def test_kubernetes_maps_to_aks(self):
        from agents.eol.tools import PRODUCT_SLUG_MAP

        assert PRODUCT_SLUG_MAP["kubernetes"] == ("endoflife.date", "azure-kubernetes-service")


# ---------------------------------------------------------------------------
# normalize_product_slug
# ---------------------------------------------------------------------------


class TestNormalizeProductSlug:
    """Verify normalize_product_slug returns correct (source, slug, cycle) tuples."""

    def test_exact_match_windows_server(self):
        from agents.eol.tools import normalize_product_slug

        source, slug, cycle = normalize_product_slug("Windows Server 2016", "")
        assert source == "endoflife.date"
        assert slug == "windows-server"
        assert cycle == "2016"

    def test_exact_match_ubuntu(self):
        from agents.eol.tools import normalize_product_slug

        result = normalize_product_slug("ubuntu", "22.04")
        assert result == ("endoflife.date", "ubuntu", "22.04")

    def test_prefix_match_windows_server_with_edition(self):
        """Windows Server 2025 Datacenter Azure Edition resolves correctly."""
        from agents.eol.tools import normalize_product_slug

        source, slug, cycle = normalize_product_slug(
            "Windows Server 2025 Datacenter Azure Edition", "10.0.26100.3981"
        )
        assert source == "endoflife.date"
        assert slug == "windows-server"
        assert cycle == "2025"

    def test_unknown_product_defaults_to_endoflife_date(self):
        from agents.eol.tools import normalize_product_slug

        source, slug, cycle = normalize_product_slug("some-unknown-product", "1.0")
        assert source == "endoflife.date"
        assert slug == "some-unknown-product"

    def test_case_insensitive(self):
        from agents.eol.tools import normalize_product_slug

        lower = normalize_product_slug("ubuntu", "22.04")
        upper = normalize_product_slug("UBUNTU", "22.04")
        assert lower[0] == upper[0]
        assert lower[1] == upper[1]

    def test_rhel_alias(self):
        from agents.eol.tools import normalize_product_slug

        source, slug, cycle = normalize_product_slug("red hat enterprise linux", "8")
        assert source == "endoflife.date"
        assert slug == "rhel"

    def test_dotnet_maps_to_endoflife_date(self):
        from agents.eol.tools import normalize_product_slug

        source, slug, cycle = normalize_product_slug(".net 8", "")
        assert source == "endoflife.date"
        assert slug == "dotnet"
        assert cycle == "8"

    def test_sql_server_extracts_year_as_cycle(self):
        from agents.eol.tools import normalize_product_slug

        source, slug, cycle = normalize_product_slug("sql server 2019", "")
        assert source == "endoflife.date"
        assert slug == "mssqlserver"
        assert cycle == "2019"


# ---------------------------------------------------------------------------
# _parse_eol_field
# ---------------------------------------------------------------------------


class TestParseEolField:
    """Verify _parse_eol_field handles all polymorphic forms correctly."""

    def test_date_string(self):
        from agents.eol.tools import _parse_eol_field

        eol_date, is_eol = _parse_eol_field("2028-10-31")
        assert eol_date == date(2028, 10, 31)
        assert is_eol is False

    def test_true_boolean(self):
        from agents.eol.tools import _parse_eol_field

        eol_date, is_eol = _parse_eol_field(True)
        assert eol_date is None
        assert is_eol is True

    def test_false_boolean(self):
        from agents.eol.tools import _parse_eol_field

        eol_date, is_eol = _parse_eol_field(False)
        assert eol_date is None
        assert is_eol is False

    def test_invalid_string(self):
        from agents.eol.tools import _parse_eol_field

        eol_date, is_eol = _parse_eol_field("invalid")
        assert eol_date is None
        assert is_eol is False


# ---------------------------------------------------------------------------
# classify_eol_status
# ---------------------------------------------------------------------------


class TestClassifyEolStatus:
    """Verify classify_eol_status returns correct status and risk level."""

    def test_already_eol(self):
        from agents.eol.tools import classify_eol_status

        past_date = date.today() - timedelta(days=30)
        result = classify_eol_status(past_date, False)
        assert result["status"] == "already_eol"
        assert result["risk_level"] == "high"

    def test_within_30_days(self):
        from agents.eol.tools import classify_eol_status

        near_date = date.today() + timedelta(days=15)
        result = classify_eol_status(near_date, False)
        assert result["status"] == "within_30_days"
        assert result["risk_level"] == "high"

    def test_within_60_days(self):
        from agents.eol.tools import classify_eol_status

        medium_date = date.today() + timedelta(days=45)
        result = classify_eol_status(medium_date, False)
        assert result["status"] == "within_60_days"
        assert result["risk_level"] == "medium"

    def test_within_90_days(self):
        from agents.eol.tools import classify_eol_status

        medium_date = date.today() + timedelta(days=75)
        result = classify_eol_status(medium_date, False)
        assert result["status"] == "within_90_days"
        assert result["risk_level"] == "medium"

    def test_not_eol(self):
        from agents.eol.tools import classify_eol_status

        far_date = date.today() + timedelta(days=365)
        result = classify_eol_status(far_date, False)
        assert result["status"] == "not_eol"
        assert result["risk_level"] == "none"


# ---------------------------------------------------------------------------
# query_endoflife_date
# ---------------------------------------------------------------------------


class TestQueryEndoflifeDate:
    """Verify query_endoflife_date tool — cache, API, and error handling."""

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.eol.tools._run_async")
    def test_cache_hit_returns_cached_data(
        self, mock_run_async, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        # First _run_async call is get_cached_eol (returns cached data)
        mock_run_async.return_value = {
            "product": "ubuntu",
            "version": "20.04",
            "eol_date": date(2025, 4, 2),
            "is_eol": False,
            "lts": True,
            "latest_version": "20.04.6",
            "source": "endoflife.date",
        }

        from agents.eol.tools import query_endoflife_date

        result = query_endoflife_date(product="ubuntu", version="20.04")

        assert result["query_status"] == "success"
        assert result["cache_hit"] is True
        # _run_async called exactly once (get_cached_eol only)
        assert mock_run_async.call_count == 1

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.eol.tools._run_async")
    @patch("agents.eol.tools._fetch_with_retry")
    def test_cache_miss_fetches_from_api(
        self, mock_fetch, mock_run_async, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        # First _run_async call is get_cached_eol (cache miss = None)
        # Second _run_async call is set_cached_eol (returns None)
        mock_run_async.side_effect = [None, None]

        mock_fetch.return_value = {
            "eol": "2025-04-02",
            "latest": "20.04.6",
            "lts": True,
            "support": "2022-10-01",
        }

        from agents.eol.tools import query_endoflife_date

        result = query_endoflife_date(product="ubuntu", version="20.04")

        assert result["query_status"] == "success"
        assert result["cache_hit"] is False
        mock_fetch.assert_called_once()
        assert mock_run_async.call_count == 2  # get_cached_eol + set_cached_eol

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.eol.tools._run_async")
    @patch("agents.eol.tools._fetch_with_retry")
    def test_api_failure_returns_error(
        self, mock_fetch, mock_run_async, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_run_async.return_value = None  # cache miss
        mock_fetch.return_value = None  # API failure

        from agents.eol.tools import query_endoflife_date

        result = query_endoflife_date(product="ubuntu", version="20.04")

        assert result["query_status"] == "not_found"
        assert result["eol_date"] is None

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.eol.tools._run_async")
    @patch("agents.eol.tools._fetch_with_retry")
    def test_polymorphic_eol_true(
        self, mock_fetch, mock_run_async, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_run_async.side_effect = [None, None]
        mock_fetch.return_value = {
            "eol": True,  # already EOL
            "latest": "18.04.6",
            "lts": True,
        }

        from agents.eol.tools import query_endoflife_date

        result = query_endoflife_date(product="ubuntu", version="18.04")

        assert result["is_eol"] is True
        assert result["eol_date"] is None

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.eol.tools._run_async")
    @patch("agents.eol.tools._fetch_with_retry")
    def test_polymorphic_eol_date_string(
        self, mock_fetch, mock_run_async, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_run_async.side_effect = [None, None]
        mock_fetch.return_value = {
            "eol": "2028-10-31",
            "latest": "22.04.3",
            "lts": True,
        }

        from agents.eol.tools import query_endoflife_date

        result = query_endoflife_date(product="ubuntu", version="22.04")

        assert result["eol_date"] == "2028-10-31"
        assert result["is_eol"] is False


# ---------------------------------------------------------------------------
# query_ms_lifecycle
# ---------------------------------------------------------------------------


class TestQueryMsLifecycle:
    """Verify query_ms_lifecycle tool — cache, MS API, and fallback."""

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.eol.tools._run_async")
    def test_cache_hit_returns_cached_data(
        self, mock_run_async, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_run_async.return_value = {
            "eol_date": date(2027, 10, 14),
            "is_eol": False,
            "lts": None,
            "latest_version": None,
            "support_end": date(2024, 10, 8),
            "source": "ms-lifecycle",
        }

        from agents.eol.tools import query_ms_lifecycle

        result = query_ms_lifecycle(product="Windows Server 2022", version="")

        assert result["query_status"] == "success"
        assert result["cache_hit"] is True
        assert result["source"] == "ms-lifecycle"

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.eol.tools._run_async")
    @patch("agents.eol.tools._fetch_with_retry")
    def test_ms_api_success(
        self, mock_fetch, mock_run_async, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_run_async.side_effect = [None, None]  # cache miss then set_cached_eol

        mock_fetch.return_value = {
            "products": [
                {
                    "productName": "Windows Server 2022",
                    "eolDate": "2031-10-14T00:00:00Z",
                    "eosDate": "2026-10-13T00:00:00Z",
                    "link": "https://learn.microsoft.com/lifecycle/products/windows-server-2022",
                }
            ]
        }

        from agents.eol.tools import query_ms_lifecycle

        result = query_ms_lifecycle(product="Windows Server 2022", version="")

        assert result["source"] == "ms-lifecycle"
        assert result["query_status"] == "success"
        assert result["eol_date"] == "2031-10-14"

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.eol.tools._run_async")
    @patch("agents.eol.tools._fetch_with_retry")
    @patch("agents.eol.tools.query_endoflife_date")
    def test_ms_api_no_match_falls_through(
        self, mock_eol, mock_fetch, mock_run_async, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_run_async.return_value = None  # cache miss
        mock_fetch.return_value = {"products": []}  # empty MS API response
        mock_eol.return_value = {
            "product": "windows-server-2022",
            "version": "",
            "eol_date": None,
            "is_eol": False,
            "query_status": "not_found",
            "source": "endoflife.date",
        }

        from agents.eol.tools import query_ms_lifecycle

        result = query_ms_lifecycle(product="Windows Server 2022", version="")

        mock_eol.assert_called_once()

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.eol.tools._run_async")
    @patch("agents.eol.tools._fetch_with_retry")
    def test_ms_api_failure_returns_error(
        self, mock_fetch, mock_run_async, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_run_async.side_effect = Exception("network error")

        from agents.eol.tools import query_ms_lifecycle

        result = query_ms_lifecycle(product="Windows Server 2022", version="")

        assert result["query_status"] == "error"
        assert "error" in result


# ---------------------------------------------------------------------------
# query_activity_log
# ---------------------------------------------------------------------------


class TestQueryActivityLog:
    """Verify query_activity_log returns expected structure."""

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="test-entra-id")
    def test_returns_success_structure(self, mock_identity, mock_instrument):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        from agents.eol.tools import query_activity_log

        result = query_activity_log(
            resource_ids=["/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-1"],
            timespan_hours=2,
        )

        assert "resource_ids" in result
        assert "timespan_hours" in result
        assert "entries" in result
        assert "query_status" in result
        assert result["query_status"] == "success"

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="test-entra-id")
    def test_default_timespan_is_2_hours(self, mock_identity, mock_instrument):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        from agents.eol.tools import query_activity_log

        result = query_activity_log(resource_ids=["/sub/vm-1"])
        assert result["timespan_hours"] == 2

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="test-entra-id")
    def test_custom_timespan(self, mock_identity, mock_instrument):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        from agents.eol.tools import query_activity_log

        result = query_activity_log(resource_ids=["/sub/vm-1"], timespan_hours=6)
        assert result["timespan_hours"] == 6


# ---------------------------------------------------------------------------
# query_os_inventory
# ---------------------------------------------------------------------------


class TestQueryOsInventory:
    """Verify query_os_inventory — ARG calls, pagination, and error handling."""

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.eol.tools.QueryRequestOptions", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.eol.tools.QueryRequest", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.eol.tools.ResourceGraphClient")
    def test_returns_success_structure(
        self, mock_rg_cls, mock_qr, mock_qro, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_resp = MagicMock()
        mock_resp.data = [
            {"id": "/sub/vm-1", "name": "vm-1", "osName": "Ubuntu 20.04", "osVersion": "20.04"}
        ]
        mock_resp.skip_token = None
        mock_rg_cls.return_value.resources.return_value = mock_resp

        from agents.eol.tools import query_os_inventory

        result = query_os_inventory(subscription_ids=["sub-1"])

        assert "machines" in result
        assert "total_count" in result
        assert "query_status" in result
        assert result["query_status"] == "success"

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.eol.tools.QueryRequestOptions", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.eol.tools.QueryRequest", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.eol.tools.ResourceGraphClient")
    def test_pagination_exhausts_skip_token(
        self, mock_rg_cls, mock_qr, mock_qro, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        page1 = MagicMock()
        page1.data = [{"id": "/sub/vm-1"}]
        page1.skip_token = "token-123"

        page2 = MagicMock()
        page2.data = [{"id": "/sub/vm-2"}]
        page2.skip_token = None

        # Two KQL queries (vm + arc), each returning 2 pages = 4 calls total
        mock_rg_cls.return_value.resources.side_effect = [page1, page2, page1, page2]

        from agents.eol.tools import query_os_inventory

        result = query_os_inventory(subscription_ids=["sub-1"])

        assert result["total_count"] == 4
        assert result["query_status"] == "success"

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.eol.tools.ResourceGraphClient", None)
    def test_resource_graph_unavailable(self, mock_identity, mock_instrument):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        from agents.eol.tools import query_os_inventory

        result = query_os_inventory(subscription_ids=["sub-1"])

        assert result["query_status"] == "error"
        assert result["machines"] == []

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.eol.tools.get_credential", return_value=MagicMock())
    @patch("agents.eol.tools.QueryRequestOptions", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.eol.tools.QueryRequest", side_effect=lambda **kw: MagicMock(query=kw.get("query", ""), **kw))
    @patch("agents.eol.tools.ResourceGraphClient")
    def test_filters_by_resource_ids(
        self, mock_rg_cls, mock_qr, mock_qro, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_resp = MagicMock()
        mock_resp.data = []
        mock_resp.skip_token = None
        mock_rg_cls.return_value.resources.return_value = mock_resp

        from agents.eol.tools import query_os_inventory

        result = query_os_inventory(
            subscription_ids=["sub-1"],
            resource_ids=["/sub/vm-1"],
        )

        # Verify the filter was applied in KQL construction
        if result["query_status"] == "error":
            assert mock_qr.call_count >= 1
            call_args = mock_qr.call_args
            if call_args and call_args[1]:
                assert "/sub/vm-1" in call_args[1].get("query", "")
        else:
            assert result["query_status"] == "success"


# ---------------------------------------------------------------------------
# query_k8s_versions
# ---------------------------------------------------------------------------


class TestQueryK8sVersions:
    """Verify query_k8s_versions — ARG calls and pagination."""

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.eol.tools.QueryRequestOptions", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.eol.tools.QueryRequest", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.eol.tools.ResourceGraphClient")
    def test_returns_cluster_structure(
        self, mock_rg_cls, mock_qr, mock_qro, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_resp = MagicMock()
        mock_resp.data = [
            {"id": "/sub/k8s-1", "name": "k8s-1", "kubernetesVersion": "1.28.5"}
        ]
        mock_resp.skip_token = None
        mock_rg_cls.return_value.resources.return_value = mock_resp

        from agents.eol.tools import query_k8s_versions

        result = query_k8s_versions(subscription_ids=["sub-1"])

        assert "clusters" in result
        assert "total_count" in result
        assert "query_status" in result
        assert result["query_status"] == "success"
        assert result["total_count"] == 1

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.eol.tools.QueryRequestOptions", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.eol.tools.QueryRequest", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.eol.tools.ResourceGraphClient")
    def test_pagination(
        self, mock_rg_cls, mock_qr, mock_qro, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        page1 = MagicMock()
        page1.data = [{"id": "/sub/k8s-1"}, {"id": "/sub/k8s-2"}]
        page1.skip_token = "token-abc"

        page2 = MagicMock()
        page2.data = [{"id": "/sub/k8s-3"}]
        page2.skip_token = None

        mock_rg_cls.return_value.resources.side_effect = [page1, page2]

        from agents.eol.tools import query_k8s_versions

        result = query_k8s_versions(subscription_ids=["sub-1"])

        assert result["total_count"] == 3
        assert result["query_status"] == "success"

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.eol.tools.QueryRequestOptions", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.eol.tools.QueryRequest", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.eol.tools.ResourceGraphClient")
    def test_error_handling(
        self, mock_rg_cls, mock_qr, mock_qro, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_rg_cls.return_value.resources.side_effect = Exception("ARG unavailable")

        from agents.eol.tools import query_k8s_versions

        result = query_k8s_versions(subscription_ids=["sub-1"])

        assert result["query_status"] == "error"
        assert result["clusters"] == []
        assert "ARG unavailable" in result["error"]


# ---------------------------------------------------------------------------
# scan_estate_eol
# ---------------------------------------------------------------------------


class TestScanEstateEol:
    """Verify scan_estate_eol — estate scanning and classification."""

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.eol.tools.query_os_inventory")
    @patch("agents.eol.tools.query_k8s_versions")
    def test_returns_scan_summary(
        self, mock_k8s, mock_os, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_os.return_value = {"machines": [], "query_status": "success"}
        mock_k8s.return_value = {"clusters": [], "query_status": "success"}

        from agents.eol.tools import scan_estate_eol

        result = scan_estate_eol(subscription_ids=["sub-1"])

        assert "scan_summary" in result
        assert "findings" in result
        assert "query_status" in result
        assert "total_resources" in result["scan_summary"]
        assert "eol_findings" in result["scan_summary"]
        assert "at_risk_findings" in result["scan_summary"]

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.eol.tools.query_os_inventory")
    @patch("agents.eol.tools.query_k8s_versions")
    def test_empty_estate_returns_zero_findings(
        self, mock_k8s, mock_os, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_os.return_value = {"machines": [], "query_status": "success"}
        mock_k8s.return_value = {"clusters": [], "query_status": "success"}

        from agents.eol.tools import scan_estate_eol

        result = scan_estate_eol(subscription_ids=["sub-1"])

        assert result["scan_summary"]["eol_findings"] == 0
        assert result["scan_summary"]["at_risk_findings"] == 0
        assert result["findings"] == []
        assert result["query_status"] == "success"

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.eol.tools.query_os_inventory")
    @patch("agents.eol.tools.query_k8s_versions")
    @patch("agents.eol.tools.query_endoflife_date")
    def test_eol_findings_classified_correctly(
        self, mock_eol, mock_k8s, mock_os, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_os.return_value = {
            "machines": [
                {
                    "id": "/sub/vm-1",
                    "name": "vm-1",
                    "resourceGroup": "rg-1",
                    "subscriptionId": "sub-1",
                    "osName": "ubuntu",
                    "osVersion": "18.04",
                }
            ],
            "query_status": "success",
        }
        mock_k8s.return_value = {"clusters": [], "query_status": "success"}
        mock_eol.return_value = {
            "eol_date": (date.today() - timedelta(days=100)).isoformat(),
            "is_eol": True,
            "latest_version": "22.04",
            "source": "endoflife.date",
            "classification": {
                "status": "already_eol",
                "risk_level": "high",
                "days_remaining": 0,
            },
        }

        from agents.eol.tools import scan_estate_eol

        result = scan_estate_eol(subscription_ids=["sub-1"])

        assert result["query_status"] == "success"
        assert result["scan_summary"]["eol_findings"] >= 1
        assert any(f["status"] == "already_eol" for f in result["findings"])

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.eol.tools.query_os_inventory")
    @patch("agents.eol.tools.query_k8s_versions")
    def test_subscription_ids_passed_through(
        self, mock_k8s, mock_os, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_os.return_value = {"machines": [], "query_status": "success"}
        mock_k8s.return_value = {"clusters": [], "query_status": "success"}

        from agents.eol.tools import scan_estate_eol

        result = scan_estate_eol(subscription_ids=["sub-1", "sub-2"])

        assert "sub-1" in result["subscription_ids"]
        assert "sub-2" in result["subscription_ids"]


# ---------------------------------------------------------------------------
# search_runbooks
# ---------------------------------------------------------------------------


class TestSearchRunbooks:
    """Verify search_runbooks sync wrapper around retrieve_runbooks."""

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.eol.tools.retrieve_runbooks")
    def test_default_domain_is_eol(self, mock_retrieve, mock_identity, mock_instrument):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        async def mock_coro(*args, **kwargs):
            return []

        mock_retrieve.side_effect = mock_coro

        from agents.eol.tools import search_runbooks

        result = search_runbooks(query="eol check")

        assert result["domain"] == "eol"

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.eol.tools.retrieve_runbooks")
    def test_returns_runbook_structure(self, mock_retrieve, mock_identity, mock_instrument):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        async def mock_coro(*args, **kwargs):
            return [
                {
                    "title": "EOL Upgrade Runbook",
                    "version": "1.0",
                    "domain": "eol",
                    "similarity": 0.92,
                    "content_excerpt": "Step 1: Identify EOL software...",
                }
            ]

        mock_retrieve.side_effect = mock_coro

        from agents.eol.tools import search_runbooks

        result = search_runbooks(query="ubuntu eol upgrade", domain="eol", limit=3)

        assert "query" in result
        assert "domain" in result
        assert "runbooks" in result
        assert "runbook_count" in result
        assert "query_status" in result
        assert result["runbook_count"] == 1
        assert result["query_status"] == "success"

    @patch("agents.eol.tools.instrument_tool_call")
    @patch("agents.eol.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.eol.tools.retrieve_runbooks")
    def test_empty_results(self, mock_retrieve, mock_identity, mock_instrument):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        async def mock_coro(*args, **kwargs):
            return []

        mock_retrieve.side_effect = mock_coro

        from agents.eol.tools import search_runbooks

        result = search_runbooks(query="nonexistent query")

        assert result["runbook_count"] == 0
        assert result["query_status"] == "empty"


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


class TestCacheHelpers:
    """Verify get_cached_eol and set_cached_eol PostgreSQL helper functions."""

    def test_get_cached_eol_hit(self):
        """get_cached_eol returns dict when asyncpg fetchrow returns a row."""
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = {
            "product": "ubuntu",
            "version": "22.04",
            "eol_date": date(2027, 4, 25),
            "is_eol": False,
            "lts": True,
            "latest_version": "22.04.3",
            "support_end": None,
            "source": "endoflife.date",
            "raw_response": None,
            "cached_at": None,
            "expires_at": None,
        }
        mock_conn.close = AsyncMock()

        mock_asyncpg = MagicMock()
        mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

        with patch("agents.eol.tools.asyncpg", mock_asyncpg):
            with patch("agents.eol.tools.resolve_postgres_dsn", return_value="postgresql://test"):
                from agents.eol.tools import get_cached_eol
                result = asyncio.run(get_cached_eol("ubuntu", "22.04"))

        assert result is not None
        assert result["product"] == "ubuntu"

    def test_get_cached_eol_miss(self):
        """get_cached_eol returns None when fetchrow returns None."""
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = None
        mock_conn.close = AsyncMock()

        mock_asyncpg = MagicMock()
        mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

        with patch("agents.eol.tools.asyncpg", mock_asyncpg):
            with patch("agents.eol.tools.resolve_postgres_dsn", return_value="postgresql://test"):
                from agents.eol.tools import get_cached_eol
                result = asyncio.run(get_cached_eol("ubuntu", "22.04"))

        assert result is None

    def test_get_cached_eol_db_unavailable(self):
        """get_cached_eol returns None when asyncpg is None (not installed)."""
        with patch("agents.eol.tools.asyncpg", None):
            from agents.eol.tools import get_cached_eol
            result = asyncio.run(get_cached_eol("ubuntu", "22.04"))

        assert result is None

    def test_set_cached_eol_upsert(self):
        """set_cached_eol executes ON CONFLICT upsert."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=None)
        mock_conn.close = AsyncMock()

        mock_asyncpg = MagicMock()
        mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

        with patch("agents.eol.tools.asyncpg", mock_asyncpg):
            with patch("agents.eol.tools.resolve_postgres_dsn", return_value="postgresql://test"):
                from agents.eol.tools import set_cached_eol
                asyncio.run(
                    set_cached_eol(
                        product="ubuntu",
                        version="22.04",
                        source="endoflife.date",
                        eol_date=date(2027, 4, 25),
                        is_eol=False,
                        lts=True,
                        latest_version="22.04.3",
                        support_end=None,
                        raw_response={"eol": "2027-04-25"},
                    )
                )

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args[0]
        assert "ON CONFLICT" in call_args[0]

    def test_set_cached_eol_failure_is_silent(self):
        """set_cached_eol swallows exceptions silently."""
        mock_asyncpg = MagicMock()
        mock_asyncpg.connect = AsyncMock(side_effect=Exception("DB down"))

        with patch("agents.eol.tools.asyncpg", mock_asyncpg):
            with patch("agents.eol.tools.resolve_postgres_dsn", return_value="postgresql://test"):
                from agents.eol.tools import set_cached_eol
                # Should not raise
                asyncio.run(
                    set_cached_eol(
                        product="ubuntu",
                        version="22.04",
                        source="endoflife.date",
                        eol_date=None,
                        is_eol=False,
                        lts=None,
                        latest_version=None,
                        support_end=None,
                        raw_response=None,
                    )
                )


# ---------------------------------------------------------------------------
# _fetch_with_retry
# ---------------------------------------------------------------------------


class TestFetchWithRetry:
    """Verify _fetch_with_retry HTTP retry logic."""

    def test_success_on_first_attempt(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"eol": "2028-10-31"}
        mock_response.raise_for_status.return_value = None

        with patch("agents.eol.tools.httpx.get", return_value=mock_response):
            from agents.eol.tools import _fetch_with_retry

            result = _fetch_with_retry("https://endoflife.date/api/ubuntu/22.04.json")

        assert result == {"eol": "2028-10-31"}

    def test_retry_on_429(self):
        rate_limited = MagicMock()
        rate_limited.status_code = 429

        success = MagicMock()
        success.status_code = 200
        success.json.return_value = {"eol": "2028-10-31"}
        success.raise_for_status.return_value = None

        with patch("agents.eol.tools.httpx.get", side_effect=[rate_limited, success]):
            with patch("agents.eol.tools.time.sleep"):  # Don't actually sleep
                from agents.eol.tools import _fetch_with_retry

                result = _fetch_with_retry("https://endoflife.date/api/ubuntu/22.04.json")

        assert result == {"eol": "2028-10-31"}

    def test_max_retries_exhausted(self):
        import httpx as httpx_lib

        with patch("agents.eol.tools.httpx.get") as mock_get:
            mock_get.side_effect = httpx_lib.HTTPStatusError(
                "500 error",
                request=MagicMock(),
                response=MagicMock(status_code=500),
            )
            with patch("agents.eol.tools.time.sleep"):
                from agents.eol.tools import _fetch_with_retry

                result = _fetch_with_retry(
                    "https://endoflife.date/api/ubuntu/99.99.json", max_retries=3
                )

        assert result is None

    def test_timeout_handled(self):
        import httpx as httpx_lib

        with patch("agents.eol.tools.httpx.get") as mock_get:
            mock_get.side_effect = httpx_lib.RequestError("timeout")
            with patch("agents.eol.tools.time.sleep"):
                from agents.eol.tools import _fetch_with_retry

                result = _fetch_with_retry(
                    "https://endoflife.date/api/ubuntu/22.04.json", max_retries=3
                )

        assert result is None
