from __future__ import annotations
"""Unit tests for the MSRC KB-to-CVE mapper (msrc_client.py).

All HTTP calls are mocked — no external requests during testing.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from services.api_gateway.msrc_client import (
    _CACHE_TTL_SECONDS,
    _kb_cve_cache,
    _normalise_kb_id,
    get_cves_for_kb,
    get_cves_for_kbs,
)


# ---------------------------------------------------------------------------
# _normalise_kb_id
# ---------------------------------------------------------------------------


class TestNormaliseKbId:
    """Tests for KB ID normalisation."""

    def test_strips_kb_prefix(self):
        assert _normalise_kb_id("KB5034441") == "5034441"

    def test_digits_only_input(self):
        assert _normalise_kb_id("5034441") == "5034441"

    def test_with_surrounding_text(self):
        assert _normalise_kb_id("Update KB5034441 for Windows") == "5034441"

    def test_empty_string(self):
        assert _normalise_kb_id("") == ""

    def test_no_digits(self):
        assert _normalise_kb_id("NoDigitsHere") == "NoDigitsHere"


# ---------------------------------------------------------------------------
# get_cves_for_kb
# ---------------------------------------------------------------------------


class TestGetCvesForKb:
    """Tests for async KB→CVE lookup."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """Clear the module-level cache before each test."""
        _kb_cve_cache.clear()
        yield
        _kb_cve_cache.clear()

    @pytest.mark.asyncio
    async def test_returns_cves_on_success(self):
        """Successful API response returns CVE list."""
        response_body = json.dumps({
            "value": [
                {"cveNumber": "CVE-2024-21302"},
                {"cveNumber": "CVE-2024-21303"},
            ]
        }).encode("utf-8")

        mock_response = MagicMock()
        mock_response.read.return_value = response_body
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("services.api_gateway.msrc_client.urllib.request.urlopen", return_value=mock_response):
            result = await get_cves_for_kb("KB5034441")

        assert result == ["CVE-2024-21302", "CVE-2024-21303"]

    @pytest.mark.asyncio
    async def test_returns_empty_on_http_error(self):
        """HTTP error returns empty list without raising."""
        import urllib.error
        with patch(
            "services.api_gateway.msrc_client.urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                url="", code=500, msg="Server Error", hdrs=None, fp=None  # type: ignore[arg-type]
            ),
        ):
            result = await get_cves_for_kb("KB5034441")

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_timeout(self):
        """Timeout returns empty list without raising."""
        with patch(
            "services.api_gateway.msrc_client.urllib.request.urlopen",
            side_effect=TimeoutError("Connection timed out"),
        ):
            result = await get_cves_for_kb("KB5034441")

        assert result == []

    @pytest.mark.asyncio
    async def test_deduplicates_cves(self):
        """Duplicate CVE numbers in response are deduplicated."""
        response_body = json.dumps({
            "value": [
                {"cveNumber": "CVE-2024-21302"},
                {"cveNumber": "CVE-2024-21302"},
                {"cveNumber": "CVE-2024-21303"},
            ]
        }).encode("utf-8")

        mock_response = MagicMock()
        mock_response.read.return_value = response_body
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("services.api_gateway.msrc_client.urllib.request.urlopen", return_value=mock_response):
            result = await get_cves_for_kb("KB5034441")

        assert result == ["CVE-2024-21302", "CVE-2024-21303"]

    @pytest.mark.asyncio
    async def test_uses_cache_on_second_call(self):
        """Second call uses cached result, no HTTP request."""
        response_body = json.dumps({
            "value": [{"cveNumber": "CVE-2024-21302"}]
        }).encode("utf-8")

        mock_response = MagicMock()
        mock_response.read.return_value = response_body
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("services.api_gateway.msrc_client.urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            result1 = await get_cves_for_kb("KB5034441")
            result2 = await get_cves_for_kb("KB5034441")

        assert result1 == ["CVE-2024-21302"]
        assert result2 == ["CVE-2024-21302"]
        # Only one HTTP call should have been made
        assert mock_urlopen.call_count == 1

    @pytest.mark.asyncio
    async def test_empty_kb_returns_empty(self):
        """Empty KB ID returns empty list."""
        result = await get_cves_for_kb("")
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_malformed_json(self):
        """Malformed JSON response returns empty list."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"not json"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("services.api_gateway.msrc_client.urllib.request.urlopen", return_value=mock_response):
            result = await get_cves_for_kb("KB5034441")

        assert result == []


# ---------------------------------------------------------------------------
# get_cves_for_kbs
# ---------------------------------------------------------------------------


class TestGetCvesForKbs:
    """Tests for batch KB→CVE lookup."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        _kb_cve_cache.clear()
        yield
        _kb_cve_cache.clear()

    @pytest.mark.asyncio
    async def test_returns_dict_of_cves(self):
        """Batch lookup returns dict mapping each KB to its CVEs."""
        def mock_urlopen(req, timeout=None):
            url = req.full_url if hasattr(req, 'full_url') else str(req)
            if "5034441" in url:
                body = json.dumps({"value": [{"cveNumber": "CVE-2024-21302"}]}).encode()
            elif "5034442" in url:
                body = json.dumps({"value": [{"cveNumber": "CVE-2024-99999"}]}).encode()
            else:
                body = json.dumps({"value": []}).encode()

            resp = MagicMock()
            resp.read.return_value = body
            resp.__enter__ = MagicMock(return_value=resp)
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("services.api_gateway.msrc_client.urllib.request.urlopen", side_effect=mock_urlopen):
            result = await get_cves_for_kbs(["KB5034441", "KB5034442"])

        assert result["KB5034441"] == ["CVE-2024-21302"]
        assert result["KB5034442"] == ["CVE-2024-99999"]

    @pytest.mark.asyncio
    async def test_empty_list_returns_empty_dict(self):
        """Empty input returns empty dict."""
        result = await get_cves_for_kbs([])
        assert result == {}
